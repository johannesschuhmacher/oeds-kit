#!/usr/bin/env python
# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Submit the OEDS day-ahead price forecast to the Energy Arena.

Reads the latest completed `day_ahead` run of `oeds-post forecast
day-ahead-price` for the target day from `price_forecast` and posts it to
https://api.energy-arena.org/api/v1/submissions:

- the point forecast to challenge 2 (DE_LU, point, scored by RMSE),
- the quantiles 2.5/25/50/75/97.5 % to challenge 8 (DE_LU, quantile, WIS).

Both challenges cover one calendar day in Europe/Berlin: one value per
quarter-hour (96, or 92/100 on clock-change days) in EUR/MWh with two
decimals, anchored by `target_start` (local midnight). The deadline is 12:00
Europe/Berlin on the day before; the latest submission before it counts.

The upstream LEAR model fills missing EXAA prices of the target day with the
previous day's, so nothing is submitted unless `entsoe_api.day_ahead_prices`
holds EXAA prices for the whole target day and the forecast run is newer than
them.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import create_engine, text

from oeds_post_scripts.runtime_env import load_crawler_dotenv, resolve_database_uri

BERLIN_TZ = ZoneInfo("Europe/Berlin")
DEFAULT_DATABASE_URI = "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path="
DEFAULT_API_BASE = "https://api.energy-arena.org"
POINT_CHALLENGE_ID = "2"
QUANTILE_CHALLENGE_ID = "8"
ARENA_QUANTILES = (0.025, 0.25, 0.5, 0.75, 0.975)


def target_day_bounds(target_date: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Local midnight to the next local midnight (end exclusive)."""
    start = pd.Timestamp(target_date).tz_localize(BERLIN_TZ)
    return start, start + pd.DateOffset(days=1)


def submission_deadline(target_date: date) -> pd.Timestamp:
    """12:00 Europe/Berlin on the day before the target day."""
    return pd.Timestamp(target_date).tz_localize(BERLIN_TZ) - pd.Timedelta(hours=12)


def build_payloads(point: pd.DataFrame, quantiles: pd.DataFrame, target_date: date) -> list[dict]:
    """Energy Arena payloads for the point and the quantile challenge.

    `point` has `delivery_start_utc` and `value_eur_mwh`; `quantiles` has also
    `quantile`. Every quarter-hour of the local target day must be present.
    """
    start, end = target_day_bounds(target_date)
    slots = pd.date_range(start, end, freq="15min", inclusive="left").tz_convert("UTC")

    point_values = point.set_index(pd.to_datetime(point["delivery_start_utc"], utc=True))["value_eur_mwh"]
    point_values = point_values.reindex(slots)
    if point_values.isna().any():
        raise ValueError(f"point forecast misses {int(point_values.isna().sum())} of {len(slots)} quarter-hours")

    table = quantiles.assign(
        delivery_start_utc=pd.to_datetime(quantiles["delivery_start_utc"], utc=True),
        quantile=quantiles["quantile"].round(6),
    ).pivot_table(index="delivery_start_utc", columns="quantile", values="value_eur_mwh")
    table = table.reindex(index=slots, columns=list(ARENA_QUANTILES))
    if table.isna().any().any():
        raise ValueError(
            f"quantile forecast misses {int(table.isna().sum().sum())} values; "
            f"needed are the quantiles {ARENA_QUANTILES} for {len(slots)} quarter-hours"
        )

    target_start = start.isoformat()
    return [
        {
            "challenge_id": POINT_CHALLENGE_ID,
            "target_start": target_start,
            "values": [round(float(value), 2) for value in point_values],
        },
        {
            "challenge_id": QUANTILE_CHALLENGE_ID,
            "target_start": target_start,
            "values": [[round(float(value), 2) for value in row] for row in table.itertuples(index=False)],
        },
    ]


def exaa_status(conn, market_area: str, target_date: date) -> tuple[bool, pd.Timestamp | None]:
    """Whether EXAA prices cover the whole target day, and when they were downloaded."""
    start, end = target_day_bounds(target_date)
    row = conn.execute(
        text(
            """
            SELECT
                COALESCE(SUM(EXTRACT(EPOCH FROM delivery_end_utc - delivery_start_utc)), 0) AS covered_seconds,
                MAX(download_time_utc) AS downloaded
            FROM entsoe_api.day_ahead_prices
            WHERE market_area IN (:market_area, :market_area_alt)
              AND source_market = 'EXAA'
              AND price_eur_mwh IS NOT NULL
              AND delivery_start_utc >= :start AND delivery_start_utc < :end
            """
        ),
        {
            "market_area": market_area,
            "market_area_alt": market_area.replace("_", "-"),
            "start": start.tz_convert("UTC"),
            "end": end.tz_convert("UTC"),
        },
    ).one()
    complete = float(row.covered_seconds) >= (end - start).total_seconds()
    downloaded = pd.Timestamp(row.downloaded) if row.downloaded is not None else None
    return complete, downloaded


def load_latest_run(conn, market_area: str, target_date: date):
    run = conn.execute(
        text(
            """
            SELECT run_id, created_at
            FROM price_forecast.forecast_runs
            WHERE market_area = :market_area
              AND target_date = :target_date
              AND variant = 'day_ahead'
              AND status = 'completed'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"market_area": market_area, "target_date": target_date},
    ).one_or_none()
    if run is None:
        return None, None, None
    params = {"run_id": run.run_id}
    point = pd.read_sql_query(
        text("SELECT delivery_start_utc, value_eur_mwh FROM price_forecast.point_forecasts WHERE run_id = :run_id"),
        conn,
        params=params,
    )
    quantiles = pd.read_sql_query(
        text(
            "SELECT delivery_start_utc, quantile, value_eur_mwh "
            "FROM price_forecast.quantile_forecasts WHERE run_id = :run_id"
        ),
        conn,
        params=params,
    )
    return run, point, quantiles


def post_submission(payload: dict, api_key: str, api_base: str) -> dict:
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}/api/v1/submissions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": api_key, "User-Agent": "oeds-kit"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"HTTP {exc.code}: {detail[:500]}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit the OEDS day-ahead price forecast to the Energy Arena.")
    parser.add_argument(
        "--database-uri",
        default=os.getenv("OEDS_PRICE_FORECAST_DATABASE_URI") or DEFAULT_DATABASE_URI,
    )
    parser.add_argument("--market-area", default="DE_LU", choices=["DE_LU"], help="the challenges cover DE_LU only")
    parser.add_argument("--target-date", help="delivery day (default: tomorrow in Europe/Berlin)")
    parser.add_argument("--api-base", default=os.getenv("ENERGY_ARENA_API_BASE_URL") or DEFAULT_API_BASE)
    parser.add_argument("--dry-run", action="store_true", help="print the payloads instead of submitting them")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_crawler_dotenv()
    if args.target_date:
        target_date = pd.Timestamp(args.target_date).date()
    else:
        target_date = (pd.Timestamp.now(tz=BERLIN_TZ).normalize() + pd.DateOffset(days=1)).date()

    deadline = submission_deadline(target_date)
    if pd.Timestamp.now(tz=BERLIN_TZ) >= deadline and not args.dry_run:
        print(f"Energy Arena: deadline {deadline.isoformat()} for {target_date} has passed; nothing submitted.")
        return 0

    api_key = os.getenv("ENERGY_ARENA_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        print("Energy Arena: ENERGY_ARENA_API_KEY is not set.", file=sys.stderr)
        return 1

    engine = create_engine(resolve_database_uri(args.database_uri))
    with engine.connect() as conn:
        exaa_complete, exaa_downloaded = exaa_status(conn, args.market_area, target_date)
        run, point, quantiles = load_latest_run(conn, args.market_area, target_date)

    if not exaa_complete:
        print(f"Energy Arena: EXAA prices for {target_date} are not complete yet; nothing submitted.")
        return 0
    if run is None or pd.Timestamp(run.created_at) <= exaa_downloaded:
        print(
            f"Energy Arena: no completed forecast for {target_date} made after the EXAA prices "
            f"(downloaded {exaa_downloaded.isoformat()}); nothing submitted.",
            file=sys.stderr,
        )
        return 1

    payloads = build_payloads(point, quantiles, target_date)
    print(f"Energy Arena: forecast run {run.run_id} ({run.created_at}) for {target_date}, deadline {deadline.isoformat()}")
    for payload in payloads:
        if args.dry_run:
            print(json.dumps(payload))
            continue
        result = post_submission(payload, api_key, args.api_base)
        print(
            f"Energy Arena: challenge {payload['challenge_id']} submitted, "
            f"{len(payload['values'])} values, submission_id={result.get('submission_id')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
