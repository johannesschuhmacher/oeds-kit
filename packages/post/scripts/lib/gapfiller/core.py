# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later


from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats
from scipy.ndimage import uniform_filter1d
try:
    from sklearn.mixture import GaussianMixture
except ImportError:  # optional dependency for the GMM fallback path
    GaussianMixture = None

GapfillMethod = Literal["linear", "previous_period", "seasonal_linear", "donor_match", "donor_refined"]

GAPFILL_METHODS: tuple[str, ...] = (
    "linear",
    "previous_period",
    "seasonal_linear",
    "donor_match",
    "donor_refined",
)

METADATA_COLUMNS = (
    "gapfill_run_id",
    "gapfill_method",
    "gapfill_created_row",
    "gapfill_filled_columns",
    "gapfill_updated_at",
)


# ══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES  (unchanged from upstream)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SeriesFillConfig:
    table_name: str
    time_column: str
    value_columns: tuple[str, ...]
    groupby_columns: tuple[str, ...]
    method: GapfillMethod = "donor_refined"
    resolution: pd.Timedelta | None = None
    period: pd.Timedelta = pd.Timedelta(hours=24)
    candidate_periods: tuple[pd.Timedelta, ...] | None = None
    donor_context_periods: int = 6
    donor_search_radius: pd.Timedelta = pd.Timedelta(days=28)
    refinement_periods: int = 3
    max_gap_periods: int = 24
    min_points: int = 3
    # ── new parameters for the added features ────────────────────────────────
    artefact_detection: bool = False       # opt-in to preserve upstream defaults
    artefact_window: int = 7               # R² window size
    artefact_threshold: float = 0.999      # R² detection threshold
    iterative_refinement: bool = False     # opt-in to preserve upstream defaults
    refinement_max_iter: int = 50          # max refinement iterations
    refinement_target_score: float = 0.3   # stop when combined score drops below
    gmm_fallback: bool = False             # opt-in to preserve upstream defaults
    random_seed: int | None = 42           # reproducible fallback/refinement output


@dataclass(frozen=True)
class _GapRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True)
class _DonorCandidate:
    start: int
    score: float


@dataclass(frozen=True)
class GroupMetric:
    table_name: str
    value_column: str
    group_key: str
    method: str
    source_rows: int
    output_rows: int
    expected_rows: int
    created_gap_rows: int
    missing_before: int
    missing_after: int
    filled_values: int
    start_time: pd.Timestamp | None
    end_time: pd.Timestamp | None
    status: str
    error_message: str | None = None


@dataclass(frozen=True)
class TableFillResult:
    dataframe: pd.DataFrame
    metrics: list[GroupMetric]


# ══════════════════════════════════════════════════════════════════════════════
# IMPROVEMENT 1 — ARTEFACT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def _compute_r2_scores(data: np.ndarray, window_size: int = 7) -> np.ndarray:
    """
    Rolling R² of a local linear regression.
    Zero windows (< 1 % of global max) receive R² = 0 so that physically
    valid zero periods (solar night) are never flagged as artefacts.
    """
    n = len(data)
    r2 = np.zeros(n)
    half_w = window_size // 2
    global_scale = float(np.nanmax(np.abs(data))) if np.nanmax(np.abs(data)) > 0 else 1.0

    for i in range(half_w, n - half_w):
        window = data[i - half_w: i + half_w + 1]
        mask = ~np.isnan(window)
        if mask.sum() < 3:
            continue

        x = np.arange(len(window))[mask].astype(float)
        y = window[mask]
        xm, ym = x.mean(), y.mean()
        ss_xy = float(np.sum((x - xm) * (y - ym)))
        ss_xx = float(np.sum((x - xm) ** 2))
        ss_yy = float(np.sum((y - ym) ** 2))

        if ss_xx > 0 and ss_yy > 0:
            r2[i] = (ss_xy ** 2) / (ss_xx * ss_yy)
        elif ss_yy == 0:
            # Constant window — only flag if the level is clearly non-zero
            relative_level = abs(float(ym)) / global_scale
            r2[i] = 0.0 if relative_level < 0.01 else 1.0
        # else ss_xx == 0: degenerate window, leave r2 = 0

    r2[:half_w]  = r2[half_w]
    r2[-half_w:] = r2[-(half_w + 1)]
    return r2


def _detect_and_remove_artefacts(
    values: np.ndarray,
    window_size: int = 7,
    threshold: float = 0.999,
    freq_minutes: int = 60,
) -> np.ndarray:
    """
    Detects linear interpolation artefacts via rolling R² and sets them to NaN.
    Returns a copy of *values* with artefact positions set to NaN.
    Physically valid zero segments (solar night) are protected.
    """
    data = values.astype("float64", copy=True)
    n = len(data)

    points_per_hour = max(1, int(60 / max(freq_minutes, 1)))
    min_length = points_per_hour + 1  # only flag segments longer than 1 h

    r2 = _compute_r2_scores(data, window_size)
    flagged = r2 > threshold
    global_scale = float(np.nanmax(np.abs(data))) if np.nanmax(np.abs(data)) > 0 else 1.0

    # Adaptive confirmation by segment length
    in_seg = False
    seg_start = 0

    for i in range(n + 1):
        is_flagged = bool(flagged[i]) if i < n else False

        if is_flagged and not in_seg:
            seg_start = i
            in_seg = True
        elif not is_flagged and in_seg:
            seg_len = i - seg_start
            in_seg = False

            if seg_len < min_length:
                continue

            seg_r2   = r2[seg_start:i]
            mean_r2  = float(np.mean(seg_r2))
            std_r2   = float(np.std(seg_r2))
            min_r2   = float(np.min(seg_r2))

            # Solar-night zero protection
            seg_data = data[seg_start:i]
            valid    = seg_data[~np.isnan(seg_data)]
            if len(valid) > 0 and np.nanmax(np.abs(valid)) / global_scale < 0.01:
                continue  # genuine zero segment — skip

            # Length-dependent thresholds
            if seg_len < 4:
                keep = mean_r2 > 0.9990 and std_r2 < 0.003 and min_r2 > 0.993
            elif seg_len < 12:
                keep = mean_r2 > 0.9985 and std_r2 < 0.003 and min_r2 > 0.993
            elif seg_len < 48:
                keep = mean_r2 > 0.9980 and std_r2 < 0.005
            else:
                keep = mean_r2 > 0.9950

            if keep:
                data[seg_start:i] = np.nan

    # Handle trailing open segment
    if in_seg:
        seg_len  = n - seg_start
        seg_data = data[seg_start:]
        valid    = seg_data[~np.isnan(seg_data)]
        if seg_len >= min_length and len(valid) > 0:
            if np.nanmax(np.abs(valid)) / global_scale >= 0.01:
                if float(np.mean(r2[seg_start:])) > 0.9950:
                    data[seg_start:] = np.nan

    return data


# ══════════════════════════════════════════════════════════════════════════════
# IMPROVEMENT 2 — GMM FALLBACK
# ══════════════════════════════════════════════════════════════════════════════

class _GMMFallback:
    """
    Per-(hour, weekday) Gaussian Mixture Model.
    Fitted on the observed data; used to fill gaps when no donor is found.
    """

    def __init__(self, max_components: int = 3, random_seed: int | None = 42):
        self._max_k = max_components
        self._random_seed = random_seed
        self._rng = np.random.default_rng(random_seed)
        self._models: dict[tuple[int, int], dict] = {}
        self._global_mean = 0.0
        self._global_std  = 1.0

    def fit(self, index: pd.DatetimeIndex, values: np.ndarray) -> None:
        clean = values[~np.isnan(values)]
        if len(clean) == 0:
            return
        self._global_mean = float(np.mean(clean))
        self._global_std  = max(float(np.std(clean)), 1e-6)

        series = pd.Series(values, index=index)
        for hour in range(24):
            for weekday in range(7):
                mask = (series.index.hour == hour) & (series.index.weekday == weekday)
                vals = series[mask].dropna().values
                if len(vals) < 5:
                    continue
                key = (hour, weekday)
                mean_v = float(np.mean(vals))
                std_v  = max(float(np.std(vals)), 1e-6)
                gmm    = None
                if GaussianMixture is not None and len(vals) >= 10:
                    best_bic = float("inf")
                    for k in range(1, min(self._max_k + 1, len(vals) // 5 + 1)):
                        try:
                            g = GaussianMixture(
                                n_components=k,
                                random_state=self._random_seed,
                                max_iter=200,
                            )
                            g.fit(vals.reshape(-1, 1))
                            bic = g.bic(vals.reshape(-1, 1))
                            if bic < best_bic:
                                best_bic = bic
                                gmm = g
                        except Exception:
                            pass
                self._models[key] = {"mean": mean_v, "std": std_v, "gmm": gmm}

    def sample(self, hour: int, weekday: int) -> float:
        key = (hour, weekday)
        if key not in self._models:
            return float(self._global_mean)
        m = self._models[key]
        if m["gmm"] is not None:
            weights = np.asarray(m["gmm"].weights_, dtype="float64")
            means = np.asarray(m["gmm"].means_, dtype="float64").reshape(-1)
            xi = float(np.dot(weights, means))
        else:
            xi = float(m["mean"])
        return 0.6 * m["mean"] + 0.4 * xi

    def fill_series(self, series: pd.Series) -> pd.Series:
        """Fill all NaN positions in *series* using GMM samples."""
        filled = series.copy()
        for idx in series.index[series.isna()]:
            filled[idx] = self.sample(idx.hour, idx.weekday())
        return filled


# ══════════════════════════════════════════════════════════════════════════════
# IMPROVEMENT 3 — ITERATIVE STATISTICAL REFINEMENT
# ══════════════════════════════════════════════════════════════════════════════

def _refinement_score(
    data: np.ndarray,
    start: int,
    end: int,
    context_size: int = 48,
) -> tuple[float, dict[str, float]]:
    """
    Combined score (0–1) measuring how detectable a segment is as an imputation.
    Higher = more detectable = needs more refinement.
    """
    segment = data[start: end + 1]
    ctx_l   = data[max(0, start - context_size): start]
    ctx_r   = data[end + 1: min(len(data), end + 1 + context_size)]
    ctx     = np.concatenate([ctx_l, ctx_r])
    ctx     = ctx[~np.isnan(ctx)]

    scores: dict[str, float] = {}

    # 1. Edge detection
    edge_scores = []
    if start > 0 and not np.isnan(data[start - 1]):
        left_jump   = abs(float(data[start]) - float(data[start - 1]))
        local_diffs = np.abs(np.diff(data[max(0, start - 24): start]))
        local_diffs = local_diffs[~np.isnan(local_diffs)]
        if len(local_diffs) > 0 and np.std(local_diffs) > 0:
            s = (left_jump - np.mean(local_diffs)) / (3 * (np.std(local_diffs) + 1e-10))
            edge_scores.append(float(np.clip(s, 0, 1)))
    if end < len(data) - 1 and not np.isnan(data[end + 1]):
        right_jump  = abs(float(data[end]) - float(data[end + 1]))
        local_diffs = np.abs(np.diff(data[end + 1: min(len(data), end + 25)]))
        local_diffs = local_diffs[~np.isnan(local_diffs)]
        if len(local_diffs) > 0 and np.std(local_diffs) > 0:
            s = (right_jump - np.mean(local_diffs)) / (3 * (np.std(local_diffs) + 1e-10))
            edge_scores.append(float(np.clip(s, 0, 1)))
    scores["edge"] = float(np.mean(edge_scores)) if edge_scores else 0.0

    # 2. Variance
    if len(segment) >= 3 and len(ctx) >= 3:
        seg_var = float(np.var(segment))
        ctx_var = float(np.var(ctx))
        scores["variance"] = float(np.clip(abs(np.log((seg_var + 1e-10) / (ctx_var + 1e-10))) / 2, 0, 1))
    else:
        scores["variance"] = 0.0

    # 3. Autocorrelation (lag-1)
    def _ac1(arr: np.ndarray) -> float:
        if len(arr) < 2:
            return 0.0
        c = float(np.corrcoef(arr[:-1], arr[1:])[0, 1])
        return c if np.isfinite(c) else 0.0

    if len(segment) >= 10 and len(ctx) >= 10:
        scores["autocorr"] = float(abs(_ac1(segment) - _ac1(ctx)))
    else:
        scores["autocorr"] = 0.0

    # 4. Kolmogorov–Smirnov
    if len(segment) >= 5 and len(ctx) >= 5:
        _, p = stats.ks_2samp(segment[~np.isnan(segment)], ctx)
        scores["ks"] = float(np.clip(1 - p, 0, 1))
    else:
        scores["ks"] = 0.0

    combined = (
        0.35 * scores["edge"]
        + 0.25 * scores["variance"]
        + 0.20 * scores["autocorr"]
        + 0.20 * scores["ks"]
    )
    return float(combined), scores


def _iterative_refine(
    data: np.ndarray,
    start: int,
    end: int,
    *,
    max_iter: int = 50,
    target_score: float = 0.3,
    context_size: int = 48,
    learning_rate: float = 0.1,
    noise_scale: float = 0.02,
    rng: np.random.Generator | None = None,
) -> None:
    """
    Iteratively refines the segment data[start:end+1] in-place until its
    combined detection score drops below *target_score* or *max_iter* is reached.
    """
    score, sub = _refinement_score(data, start, end, context_size)
    if score <= target_score:
        return

    ctx_l = data[max(0, start - context_size): start]
    ctx_r = data[end + 1: min(len(data), end + 1 + context_size)]
    ctx   = np.concatenate([ctx_l, ctx_r])
    ctx   = ctx[~np.isnan(ctx)]

    rng = rng or np.random.default_rng(42)
    prev_score = score
    for iteration in range(max_iter):
        # Edge blending
        if sub["edge"] > 0.3:
            blend = min(6, (end - start + 1) // 4)
            if blend >= 2:
                if start > 0 and not np.isnan(data[start - 1]):
                    lv = float(data[start - 1])
                    for k in range(blend):
                        w = 0.3 * (1 - k / blend)
                        data[start + k] = (1 - w) * data[start + k] + w * lv
                if end < len(data) - 1 and not np.isnan(data[end + 1]):
                    rv = float(data[end + 1])
                    for k in range(blend):
                        idx = end - k
                        w   = 0.3 * (1 - k / blend)
                        data[idx] = (1 - w) * data[idx] + w * rv

        # Variance matching
        if sub["variance"] > 0.4 and len(ctx) >= 3:
            seg = data[start: end + 1]
            seg_mean = float(np.mean(seg))
            seg_std  = max(float(np.std(seg)), 1e-10)
            ctx_std  = max(float(np.std(ctx)), 1e-10)
            scale    = 1 + learning_rate * (ctx_std / seg_std - 1)
            data[start: end + 1] = seg_mean + (seg - seg_mean) * scale

        # Realistic noise
        if len(ctx) >= 10:
            noise_std = float(np.std(np.diff(ctx, n=2))) * 0.5 if len(ctx) > 2 else float(np.std(ctx)) * 0.1
            noise = rng.normal(0, noise_std * noise_scale, end - start + 1)
            data[start: end + 1] += noise

        # Local smoothing
        seg_len = end - start + 1
        if seg_len >= 5:
            seg      = data[start: end + 1].copy()
            smoothed = uniform_filter1d(seg, size=min(3, seg_len // 3), mode="nearest")
            data[start: end + 1] = 0.9 * seg + 0.1 * smoothed

        score, sub = _refinement_score(data, start, end, context_size)
        if score <= target_score:
            return
        if iteration > 10 and abs(score - prev_score) < 0.01:
            return  # converged
        prev_score = score


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS  (unchanged from upstream)
# ══════════════════════════════════════════════════════════════════════════════

def slugify_column(name: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").lower()
    return slug or "value"


def group_key_from_values(groupby_columns: tuple[str, ...], values: dict[str, object]) -> str:
    if not groupby_columns:
        return "__all__"
    tokens = []
    for column in groupby_columns:
        value = values.get(column)
        if pd.isna(value):
            value = "<null>"
        tokens.append(f"{column}={value}")
    return "|".join(tokens)


def infer_frequency(index: pd.DatetimeIndex) -> pd.Timedelta | None:
    clean_index = pd.DatetimeIndex(pd.Series(index).dropna().sort_values().unique())
    if len(clean_index) < 2:
        return None
    diffs = clean_index.to_series().diff().dropna()
    diffs = diffs[diffs > pd.Timedelta(0)]
    if diffs.empty:
        return None
    median = diffs.median()
    if median <= pd.Timedelta(0) or pd.isna(median):
        return None
    seconds = max(1, int(round(median.total_seconds())))
    return pd.Timedelta(seconds=seconds)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE ENTRY POINTS  (fill_table / fill_group — enhanced)
# ══════════════════════════════════════════════════════════════════════════════

def fill_table(
    dataframe: pd.DataFrame,
    config: SeriesFillConfig,
    run_id: str,
    run_timestamp: pd.Timestamp | None = None,
) -> TableFillResult:
    if dataframe.empty:
        return TableFillResult(dataframe=_empty_output(dataframe), metrics=[])

    _validate_columns(dataframe, config)
    run_timestamp = run_timestamp or pd.Timestamp.now(tz="UTC")

    prepared = dataframe.copy()
    prepared[config.time_column] = pd.to_datetime(prepared[config.time_column], utc=True, errors="coerce")
    prepared = prepared.dropna(subset=[config.time_column])

    if prepared.empty:
        return TableFillResult(dataframe=_empty_output(dataframe), metrics=[])

    if config.groupby_columns:
        grouped     = prepared.groupby(list(config.groupby_columns), dropna=False, sort=False)
        group_items = grouped
    else:
        group_items = [((), prepared)]

    outputs: list[pd.DataFrame] = []
    metrics: list[GroupMetric]  = []

    for group_values_raw, group_df in group_items:
        group_values = _normalise_group_values(config.groupby_columns, group_values_raw, group_df)
        group_result = fill_group(group_df, config, run_id, run_timestamp, group_values)
        outputs.append(group_result.dataframe)
        metrics.extend(group_result.metrics)

    if not outputs:
        return TableFillResult(dataframe=_empty_output(dataframe), metrics=metrics)

    output = pd.concat(outputs, ignore_index=True)
    output = output.sort_values([*config.groupby_columns, config.time_column], kind="stable").reset_index(drop=True)
    return TableFillResult(dataframe=output, metrics=metrics)


def fill_group(
    dataframe: pd.DataFrame,
    config: SeriesFillConfig,
    run_id: str,
    run_timestamp: pd.Timestamp,
    group_values: dict[str, object],
) -> TableFillResult:
    group_key = group_key_from_values(config.groupby_columns, group_values)
    group_df  = dataframe.copy()
    group_df  = group_df.sort_values(config.time_column, kind="stable")
    group_df  = group_df.drop_duplicates(subset=[config.time_column], keep="last")

    source_rows = len(group_df)
    if source_rows < config.min_points:
        output  = _with_metadata(group_df, config, run_id, run_timestamp, False, [])
        metrics = [
            _metric(config=config, value_column=vc, group_key=group_key, method=config.method,
                    source_rows=source_rows, output_rows=len(output), expected_rows=len(output),
                    created_gap_rows=0,
                    missing_before=int(group_df[vc].isna().sum()),
                    missing_after=int(group_df[vc].isna().sum()),
                    filled_values=0,
                    start_time=_timestamp_or_none(group_df[config.time_column].min()),
                    end_time=_timestamp_or_none(group_df[config.time_column].max()),
                    status="skipped_insufficient_points")
            for vc in config.value_columns
        ]
        return TableFillResult(dataframe=output, metrics=metrics)

    indexed   = group_df.set_index(config.time_column).sort_index()
    frequency = config.resolution or infer_frequency(pd.DatetimeIndex(indexed.index))
    if frequency is None:
        output  = _with_metadata(group_df, config, run_id, run_timestamp, False, [])
        metrics = [
            _metric(config=config, value_column=vc, group_key=group_key, method=config.method,
                    source_rows=source_rows, output_rows=len(output), expected_rows=len(output),
                    created_gap_rows=0,
                    missing_before=int(group_df[vc].isna().sum()),
                    missing_after=int(group_df[vc].isna().sum()),
                    filled_values=0,
                    start_time=_timestamp_or_none(group_df[config.time_column].min()),
                    end_time=_timestamp_or_none(group_df[config.time_column].max()),
                    status="skipped_no_frequency")
            for vc in config.value_columns
        ]
        return TableFillResult(dataframe=output, metrics=metrics)

    full_index   = pd.date_range(indexed.index.min(), indexed.index.max(), freq=frequency)
    expanded     = indexed.reindex(full_index)
    created_mask = ~expanded.index.isin(indexed.index)

    for column, value in group_values.items():
        expanded[column] = value

    for column in expanded.columns:
        if column in config.value_columns or column in config.groupby_columns:
            continue
        if column.startswith("gapfill_"):
            continue
        if pd.api.types.is_datetime64_any_dtype(expanded[column]):
            continue
        expanded[column] = expanded[column].ffill().bfill()

    filled_columns_by_row: dict[pd.Timestamp, list[str]] = {ts: [] for ts in expanded.index}
    metrics: list[GroupMetric] = []

    freq_minutes = int(round(frequency.total_seconds() / 60))

    for value_column in config.value_columns:
        series = pd.to_numeric(expanded[value_column], errors="coerce")
        original_missing_before = int(series.isna().sum())

        # ── IMPROVEMENT 1: artefact detection ────────────────────────────────
        if config.artefact_detection and config.method in ("donor_match", "donor_refined"):
            raw_values = series.to_numpy(dtype="float64")
            cleaned    = _detect_and_remove_artefacts(
                raw_values,
                window_size=config.artefact_window,
                threshold=config.artefact_threshold,
                freq_minutes=freq_minutes,
            )
            n_artefacts = int(np.sum(np.isnan(cleaned) & ~np.isnan(raw_values)))
            if n_artefacts > 0:
                series = pd.Series(cleaned, index=series.index)

        missing_before_mask = series.isna()
        missing_before      = int(missing_before_mask.sum())

        # ── Build fill candidate (donor / linear / previous_period / etc.) ───
        candidate    = _build_fill_candidate(series, config)
        eligible_mask = _eligible_missing_mask(missing_before_mask, config.max_gap_periods)
        filled_mask   = missing_before_mask & eligible_mask & candidate.notna()

        expanded.loc[filled_mask, value_column] = candidate.loc[filled_mask]

        # ── IMPROVEMENT 2: GMM fallback for remaining NaN ────────────────────
        if config.gmm_fallback and config.method in ("donor_match", "donor_refined"):
            still_missing = pd.to_numeric(expanded[value_column], errors="coerce").isna()
            still_eligible = still_missing & eligible_mask
            if still_eligible.any():
                gmm = _GMMFallback(random_seed=config.random_seed)
                gmm.fit(pd.DatetimeIndex(expanded.index), series.to_numpy(dtype="float64"))
                for ts in expanded.index[still_eligible]:
                    expanded.loc[ts, value_column] = gmm.sample(ts.hour, ts.weekday())
                filled_mask = filled_mask | still_eligible

        # ── IMPROVEMENT 3: iterative statistical refinement ──────────────────
        if (
            config.iterative_refinement
            and config.method in ("donor_refined",)
            and filled_mask.any()
        ):
            work_array = pd.to_numeric(expanded[value_column], errors="coerce").to_numpy(dtype="float64").copy()
            rng = np.random.default_rng(config.random_seed)
            for gap in _missing_ranges(missing_before_mask & eligible_mask):
                _iterative_refine(
                    work_array,
                    gap.start,
                    gap.end,
                    max_iter=config.refinement_max_iter,
                    target_score=config.refinement_target_score,
                    rng=rng,
                )
            expanded[value_column] = work_array

        for ts in expanded.index[filled_mask]:
            filled_columns_by_row[ts].append(value_column)

        missing_after = int(pd.to_numeric(expanded[value_column], errors="coerce").isna().sum())
        metrics.append(
            _metric(config=config, value_column=value_column, group_key=group_key,
                    method=config.method, source_rows=source_rows, output_rows=len(expanded),
                    expected_rows=len(full_index), created_gap_rows=int(created_mask.sum()),
                    missing_before=original_missing_before, missing_after=missing_after,
                    filled_values=int(filled_mask.sum()),
                    start_time=_timestamp_or_none(full_index.min()),
                    end_time=_timestamp_or_none(full_index.max()),
                    status="ok")
        )

    output = expanded.reset_index(names=config.time_column)
    output["gapfill_run_id"]       = run_id
    output["gapfill_method"]       = config.method
    output["gapfill_created_row"]  = created_mask
    output["gapfill_filled_columns"] = [
        ",".join(filled_columns_by_row.get(ts, [])) for ts in expanded.index
    ]
    output["gapfill_updated_at"] = run_timestamp
    return TableFillResult(dataframe=output, metrics=metrics)


# ══════════════════════════════════════════════════════════════════════════════
# DONOR MATCHING  (unchanged from upstream)
# ══════════════════════════════════════════════════════════════════════════════

def _build_fill_candidate(series: pd.Series, config: SeriesFillConfig) -> pd.Series:
    linear = series.interpolate(method="time", limit_area="inside")
    if config.method == "linear":
        return linear

    previous_period = _previous_period_candidate(series, config.period)
    if config.method == "previous_period":
        return previous_period.combine_first(linear)

    if config.method == "seasonal_linear":
        both      = previous_period.notna() & linear.notna()
        candidate = previous_period.combine_first(linear)
        candidate.loc[both] = 0.7 * previous_period.loc[both] + 0.3 * linear.loc[both]
        return candidate

    if config.method == "donor_match":
        return _donor_match_candidate(series, config, refine=False)

    if config.method == "donor_refined":
        return _donor_match_candidate(series, config, refine=True)

    raise ValueError(f"Unsupported gapfill method: {config.method}")


def _previous_period_candidate(series: pd.Series, period: pd.Timedelta) -> pd.Series:
    candidate     = pd.Series(np.nan, index=series.index, dtype="float64")
    missing_index = series.index[series.isna()]
    values        = series.dropna()
    if values.empty:
        return candidate
    for timestamp in missing_index:
        donor_ts = timestamp - period
        if donor_ts in values.index:
            candidate.loc[timestamp] = values.loc[donor_ts]
    return candidate


def _donor_match_candidate(
    series: pd.Series,
    config: SeriesFillConfig,
    *,
    refine: bool,
) -> pd.Series:
    candidate     = pd.Series(np.nan, index=series.index, dtype="float64")
    missing_mask  = series.isna()
    eligible_mask = _eligible_missing_mask(missing_mask, config.max_gap_periods)
    fillable_mask = missing_mask & eligible_mask
    if not bool(fillable_mask.any()):
        return candidate

    frequency = config.resolution or infer_frequency(pd.DatetimeIndex(series.index))
    if frequency is None:
        return candidate

    values            = series.to_numpy(dtype="float64")
    index             = pd.DatetimeIndex(series.index)
    candidate_periods = _candidate_periods(config, frequency)
    context_points    = max(1, int(config.donor_context_periods))
    refinement_periods = max(0, int(config.refinement_periods))

    for gap in _missing_ranges(fillable_mask):
        donor = _best_donor_candidate(
            values=values, index=index, gap=gap, frequency=frequency,
            candidate_periods=candidate_periods, context_points=context_points,
            search_radius=config.donor_search_radius,
        )
        if donor is None:
            continue

        donor_end = donor.start + gap.length
        segment   = values[donor.start:donor_end].astype("float64", copy=True)
        if refine:
            segment = _refine_donor_segment(
                values=values, gap=gap, segment=segment,
                context_points=context_points,
                refinement_periods=refinement_periods,
            )
        candidate.iloc[gap.start: gap.end + 1] = segment

    return candidate


def _candidate_periods(config: SeriesFillConfig, frequency: pd.Timedelta) -> tuple[pd.Timedelta, ...]:
    raw_periods = config.candidate_periods or (
        config.period, pd.Timedelta(days=1), pd.Timedelta(days=7),
    )
    periods: list[pd.Timedelta] = []
    for period in raw_periods:
        if period <= pd.Timedelta(0):
            continue
        steps = _timedelta_to_steps(period, frequency)
        if steps is None:
            continue
        normalised = steps * frequency
        if normalised not in periods:
            periods.append(normalised)
    return tuple(periods or (frequency,))


def _best_donor_candidate(
    *,
    values: np.ndarray,
    index: pd.DatetimeIndex,
    gap: _GapRange,
    frequency: pd.Timedelta,
    candidate_periods: tuple[pd.Timedelta, ...],
    context_points: int,
    search_radius: pd.Timedelta,
) -> _DonorCandidate | None:
    best: _DonorCandidate | None = None
    best_distance: int | None    = None
    starts = _donor_start_candidates(
        index=index, gap=gap, frequency=frequency,
        candidate_periods=candidate_periods, search_radius=search_radius,
    )

    for start in starts:
        if not _is_valid_donor_start(values, gap, start, context_points):
            continue
        score    = _score_donor_candidate(
            values=values, index=index, gap=gap, donor_start=start,
            candidate_periods=candidate_periods, context_points=context_points,
        )
        distance = abs(gap.start - start)
        if best is None or score > best.score + 1e-12:
            best          = _DonorCandidate(start=start, score=score)
            best_distance = distance
        elif best_distance is not None and abs(score - best.score) <= 1e-12:
            if distance < best_distance:
                best          = _DonorCandidate(start=start, score=score)
                best_distance = distance

    return best


def _donor_start_candidates(
    *,
    index: pd.DatetimeIndex,
    gap: _GapRange,
    frequency: pd.Timedelta,
    candidate_periods: tuple[pd.Timedelta, ...],
    search_radius: pd.Timedelta,
) -> list[int]:
    last_start = len(index) - gap.length
    if last_start < 0:
        return []

    starts:       set[int] = set()
    radius_steps = _timedelta_to_steps(search_radius, frequency)
    if radius_steps is None:
        radius_steps = len(index)

    start_min = max(0, gap.start - radius_steps)
    start_max = min(last_start, gap.start + radius_steps)
    starts.update(range(start_min, start_max + 1))

    for period in candidate_periods:
        period_steps = _timedelta_to_steps(period, frequency)
        if period_steps is None:
            continue
        multiples = max(1, radius_steps // period_steps)
        for multiple in range(1, multiples + 1):
            offset = multiple * period_steps
            starts.add(gap.start - offset)
            starts.add(gap.start + offset)

    return sorted(s for s in starts if 0 <= s <= last_start)


def _is_valid_donor_start(
    values: np.ndarray, gap: _GapRange, start: int, context_points: int,
) -> bool:
    end = start + gap.length - 1
    if end >= len(values):
        return False
    if start <= gap.end and end >= gap.start:
        return False
    ctx_start = max(0, gap.start - context_points)
    ctx_end   = min(len(values) - 1, gap.end + context_points)
    if start <= ctx_end and end >= ctx_start:
        return False
    return not bool(np.isnan(values[start: end + 1]).any())


def _score_donor_candidate(
    *,
    values: np.ndarray,
    index: pd.DatetimeIndex,
    gap: _GapRange,
    donor_start: int,
    candidate_periods: tuple[pd.Timedelta, ...],
    context_points: int,
) -> float:
    donor_end = donor_start + gap.length - 1

    context_scores = []
    before_gap   = values[max(0, gap.start - context_points): gap.start]
    before_donor = values[max(0, donor_start - context_points): donor_start]
    bs = _array_similarity(before_gap, before_donor, align="right")
    if bs is not None:
        context_scores.append(bs)

    after_gap   = values[gap.end + 1: min(len(values), gap.end + 1 + context_points)]
    after_donor = values[donor_end + 1: min(len(values), donor_end + 1 + context_points)]
    as_ = _array_similarity(after_gap, after_donor, align="left")
    if as_ is not None:
        context_scores.append(as_)

    context_score  = float(np.mean(context_scores)) if context_scores else 0.5
    boundary_score = _boundary_similarity(values, gap, donor_start, donor_end)
    seasonal_score = _seasonality_similarity(index, gap.start, donor_start, candidate_periods)
    return 0.5 * context_score + 0.3 * boundary_score + 0.2 * seasonal_score


def _array_similarity(
    left: np.ndarray, right: np.ndarray, *, align: Literal["left", "right"],
) -> float | None:
    length = min(len(left), len(right))
    if length == 0:
        return None
    left  = left[-length:] if align == "right" else left[:length]
    right = right[-length:] if align == "right" else right[:length]

    clean = ~(np.isnan(left) | np.isnan(right))
    left  = left[clean]
    right = right[clean]
    if len(left) == 0:
        return None
    if len(left) == 1:
        return _level_similarity(float(left[0]), float(right[0]))

    left_std = float(np.std(left))
    right_std = float(np.std(right))
    if left_std > 1e-12 and right_std > 1e-12:
        corr       = float(np.corrcoef(left, right)[0, 1])
        corr_score = (max(-1.0, min(1.0, corr if np.isfinite(corr) else 0.0)) + 1.0) / 2.0
    else:
        corr_score = _level_similarity(left_std, right_std)

    mean_score = _level_similarity(float(np.mean(left)), float(np.mean(right)))
    std_score  = _level_similarity(left_std, right_std)
    rmse       = float(np.sqrt(np.mean((left - right) ** 2)))
    scale      = max(float(np.nanmean(np.abs(left))), float(np.nanmean(np.abs(right))), 1.0)
    rmse_score = max(0.0, 1.0 - rmse / scale)
    return 0.35 * corr_score + 0.30 * mean_score + 0.20 * std_score + 0.15 * rmse_score


def _boundary_similarity(
    values: np.ndarray, gap: _GapRange, donor_start: int, donor_end: int,
) -> float:
    scores = []
    if gap.start > 0 and not np.isnan(values[gap.start - 1]):
        scores.append(_level_similarity(float(values[gap.start - 1]), float(values[donor_start])))
    if gap.end + 1 < len(values) and not np.isnan(values[gap.end + 1]):
        scores.append(_level_similarity(float(values[gap.end + 1]), float(values[donor_end])))
    return float(np.mean(scores)) if scores else 0.5


def _seasonality_similarity(
    index: pd.DatetimeIndex,
    gap_start: int,
    donor_start: int,
    candidate_periods: tuple[pd.Timedelta, ...],
) -> float:
    gap_ts    = pd.Timestamp(index[gap_start])
    donor_ts  = pd.Timestamp(index[donor_start])
    spd       = 24 * 60 * 60
    sec_delta = abs(
        gap_ts.hour * 3600 + gap_ts.minute * 60 + gap_ts.second
        - donor_ts.hour * 3600 - donor_ts.minute * 60 - donor_ts.second
    )
    clock_delta = min(sec_delta, spd - sec_delta)
    clock_score   = max(0.0, 1.0 - clock_delta / (spd / 2))
    weekday_score = 1.0 if gap_ts.weekday() == donor_ts.weekday() else 0.5

    distance = abs(gap_ts - donor_ts)
    period_scores = [_period_alignment_score(distance, p) for p in candidate_periods]
    period_score  = max(period_scores) if period_scores else 0.5
    return 0.45 * clock_score + 0.25 * weekday_score + 0.30 * period_score


def _period_alignment_score(distance: pd.Timedelta, period: pd.Timedelta) -> float:
    if distance <= pd.Timedelta(0) or period <= pd.Timedelta(0):
        return 0.0
    ratio   = distance / period
    nearest = max(1, int(round(ratio)))
    return max(0.0, 1.0 - 4.0 * abs(ratio - nearest) / nearest)


def _level_similarity(left: float, right: float) -> float:
    if not (np.isfinite(left) and np.isfinite(right)):
        return 0.0
    scale = max(abs(left), abs(right), 1.0)
    return max(0.0, 1.0 - abs(left - right) / scale)


def _refine_donor_segment(
    *,
    values: np.ndarray,
    gap: _GapRange,
    segment: np.ndarray,
    context_points: int,
    refinement_periods: int,
) -> np.ndarray:
    if len(segment) == 0:
        return segment

    refined      = segment.astype("float64", copy=True)
    left_anchor  = _known_value(values, gap.start - 1)
    right_anchor = _known_value(values, gap.end + 1)

    if left_anchor is not None and right_anchor is not None and len(refined) > 1:
        target_baseline = np.linspace(left_anchor, right_anchor, len(refined) + 2)[1:-1]
        donor_baseline  = np.linspace(refined[0], refined[-1], len(refined))
        shaped          = target_baseline + (refined - donor_baseline)
        refined         = 0.6 * refined + 0.4 * shaped
    elif left_anchor is not None:
        refined = refined + 0.35 * (left_anchor - refined[0])
    elif right_anchor is not None:
        refined = refined + 0.35 * (right_anchor - refined[-1])

    refined = _match_context_scale(values, gap, refined, context_points)
    return _blend_segment_edges(refined, left_anchor, right_anchor, refinement_periods)


def _match_context_scale(
    values: np.ndarray, gap: _GapRange, segment: np.ndarray, context_points: int,
) -> np.ndarray:
    before  = values[max(0, gap.start - context_points): gap.start]
    after   = values[gap.end + 1: min(len(values), gap.end + 1 + context_points)]
    context = np.concatenate([before, after])
    context = context[~np.isnan(context)]
    if len(context) < 2 or len(segment) < 2:
        return segment

    seg_std     = float(np.std(segment))
    ctx_std     = float(np.std(context))
    ctx_mean    = float(np.mean(context))
    seg_mean    = float(np.mean(segment))

    if not np.isfinite(seg_std) or seg_std <= 1e-12:
        adjusted = np.full_like(segment, ctx_mean)
    else:
        adjusted = ctx_mean + (segment - seg_mean) * (ctx_std / seg_std)
    return 0.85 * segment + 0.15 * adjusted


def _blend_segment_edges(
    segment: np.ndarray,
    left_anchor: float | None,
    right_anchor: float | None,
    refinement_periods: int,
) -> np.ndarray:
    if refinement_periods <= 0:
        return segment

    refined      = segment.astype("float64", copy=True)
    blend_periods = min(refinement_periods, len(refined))
    if left_anchor is not None:
        for offset in range(blend_periods):
            weight          = (blend_periods - offset) / (blend_periods + 1)
            refined[offset] = weight * left_anchor + (1.0 - weight) * refined[offset]
    if right_anchor is not None:
        for offset in range(blend_periods):
            position           = len(refined) - offset - 1
            weight             = (blend_periods - offset) / (blend_periods + 1)
            refined[position]  = weight * right_anchor + (1.0 - weight) * refined[position]
    return refined


def _known_value(values: np.ndarray, position: int) -> float | None:
    if position < 0 or position >= len(values):
        return None
    value = float(values[position])
    return None if np.isnan(value) else value


def _timedelta_to_steps(delta: pd.Timedelta, frequency: pd.Timedelta) -> int | None:
    if delta <= pd.Timedelta(0) or frequency <= pd.Timedelta(0):
        return None
    steps = int(round(delta / frequency))
    return steps if steps > 0 else None


def _missing_ranges(missing_mask: pd.Series) -> list[_GapRange]:
    positions = np.flatnonzero(missing_mask.to_numpy())
    if len(positions) == 0:
        return []

    ranges: list[_GapRange] = []
    start    = positions[0]
    previous = positions[0]
    for position in positions[1:]:
        if position != previous + 1:
            ranges.append(_GapRange(start=int(start), end=int(previous)))
            start = position
        previous = position
    ranges.append(_GapRange(start=int(start), end=int(previous)))
    return ranges


def _eligible_missing_mask(missing_mask: pd.Series, max_gap_periods: int) -> pd.Series:
    if max_gap_periods <= 0:
        return pd.Series(False, index=missing_mask.index)

    eligible  = pd.Series(False, index=missing_mask.index)
    positions = np.flatnonzero(missing_mask.to_numpy())
    if len(positions) == 0:
        return eligible

    start    = positions[0]
    previous = positions[0]
    for position in positions[1:]:
        if position != previous + 1:
            _mark_gap_if_eligible(eligible, start, previous, max_gap_periods)
            start = position
        previous = position
    _mark_gap_if_eligible(eligible, start, previous, max_gap_periods)
    return eligible


def _mark_gap_if_eligible(eligible: pd.Series, start: int, end: int, max_gap_periods: int) -> None:
    if end - start + 1 <= max_gap_periods:
        eligible.iloc[start: end + 1] = True


# ══════════════════════════════════════════════════════════════════════════════
# METADATA HELPERS  (unchanged from upstream)
# ══════════════════════════════════════════════════════════════════════════════

def _validate_columns(dataframe: pd.DataFrame, config: SeriesFillConfig) -> None:
    required = {config.time_column, *config.value_columns, *config.groupby_columns}
    missing  = sorted(required - set(dataframe.columns))
    if missing:
        raise ValueError(f"Missing columns for {config.table_name}: {missing}")


def _normalise_group_values(
    groupby_columns: tuple[str, ...],
    raw_values: object,
    group_df: pd.DataFrame,
) -> dict[str, object]:
    if not groupby_columns:
        return {}
    if len(groupby_columns) == 1:
        values = raw_values if isinstance(raw_values, tuple) else (raw_values,)
    elif isinstance(raw_values, tuple):
        values = raw_values
    else:
        values = tuple(group_df.iloc[0][column] for column in groupby_columns)
    return dict(zip(groupby_columns, values, strict=True))


def _with_metadata(
    dataframe: pd.DataFrame, config: SeriesFillConfig, run_id: str,
    run_timestamp: pd.Timestamp, created_row: bool, filled_columns: list[str],
) -> pd.DataFrame:
    output                           = dataframe.copy()
    output["gapfill_run_id"]         = run_id
    output["gapfill_method"]         = config.method
    output["gapfill_created_row"]    = created_row
    output["gapfill_filled_columns"] = ",".join(filled_columns)
    output["gapfill_updated_at"]     = run_timestamp
    return output


def _metric(
    *, config: SeriesFillConfig, value_column: str, group_key: str, method: str,
    source_rows: int, output_rows: int, expected_rows: int, created_gap_rows: int,
    missing_before: int, missing_after: int, filled_values: int,
    start_time: pd.Timestamp | None, end_time: pd.Timestamp | None,
    status: str, error_message: str | None = None,
) -> GroupMetric:
    return GroupMetric(
        table_name=config.table_name, value_column=value_column, group_key=group_key,
        method=method, source_rows=int(source_rows), output_rows=int(output_rows),
        expected_rows=int(expected_rows), created_gap_rows=int(created_gap_rows),
        missing_before=int(missing_before), missing_after=int(missing_after),
        filled_values=int(filled_values), start_time=start_time, end_time=end_time,
        status=status, error_message=error_message,
    )


def _timestamp_or_none(value: object) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _empty_output(dataframe: pd.DataFrame) -> pd.DataFrame:
    output = dataframe.copy()
    for column in METADATA_COLUMNS:
        if column not in output.columns:
            output[column] = None
    return output


def serialise_metric(metric: GroupMetric) -> dict[str, object]:
    row = metric.__dict__.copy()
    for key in ("start_time", "end_time"):
        value = row[key]
        if value is not None and not (isinstance(value, float) and math.isnan(value)):
            row[key] = pd.Timestamp(value).isoformat()
    return row
