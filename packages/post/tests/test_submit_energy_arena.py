# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from datetime import date

import pandas as pd
import pytest

from scripts.submit_energy_arena import ARENA_QUANTILES, build_payloads, submission_deadline


def _forecast(target_date: date, quantiles=(0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975)):
    start = pd.Timestamp(target_date).tz_localize("Europe/Berlin")
    slots = pd.date_range(start, start + pd.DateOffset(days=1), freq="15min", inclusive="left").tz_convert("UTC")
    point = pd.DataFrame({"delivery_start_utc": slots, "value_eur_mwh": [100.0 + i + 0.004 for i in range(len(slots))]})
    rows = [
        {"delivery_start_utc": slot, "quantile": q, "value_eur_mwh": value + 1000 * q}
        for slot, value in zip(slots, point["value_eur_mwh"])
        for q in quantiles
    ]
    # Unordered rows, as read from the database.
    return point.iloc[::-1], pd.DataFrame(rows).sample(frac=1, random_state=0)


def test_payloads_for_an_ordinary_day():
    point, quantiles = _forecast(date(2026, 11, 8))

    point_payload, quantile_payload = build_payloads(point, quantiles, date(2026, 11, 8))

    assert point_payload["challenge_id"] == "2"
    assert point_payload["target_start"] == "2026-11-08T00:00:00+01:00"
    assert len(point_payload["values"]) == 96
    assert point_payload["values"][:2] == [100.0, 101.0]
    assert quantile_payload["challenge_id"] == "8"
    assert quantile_payload["target_start"] == "2026-11-08T00:00:00+01:00"
    assert quantile_payload["values"][0] == [round(100.004 + 1000 * q, 2) for q in ARENA_QUANTILES]


def test_clock_change_days_have_100_and_92_values():
    autumn = build_payloads(*_forecast(date(2026, 10, 25)), date(2026, 10, 25))
    spring = build_payloads(*_forecast(date(2026, 3, 29)), date(2026, 3, 29))

    assert autumn[0]["target_start"] == "2026-10-25T00:00:00+02:00"
    assert len(autumn[0]["values"]) == len(autumn[1]["values"]) == 100
    assert len(spring[0]["values"]) == len(spring[1]["values"]) == 92


def test_missing_values_are_refused():
    point, quantiles = _forecast(date(2026, 11, 8))
    with pytest.raises(ValueError, match="point forecast misses 1"):
        build_payloads(point.iloc[1:], quantiles, date(2026, 11, 8))

    _, old_quantiles = _forecast(date(2026, 11, 8), quantiles=(0.1, 0.25, 0.5, 0.75, 0.9))
    with pytest.raises(ValueError, match="quantile forecast misses"):
        build_payloads(point, old_quantiles, date(2026, 11, 8))


def test_deadline_is_noon_berlin_on_the_day_before():
    assert submission_deadline(date(2026, 11, 8)).isoformat() == "2026-11-07T12:00:00+01:00"
    assert submission_deadline(date(2026, 7, 1)).isoformat() == "2026-06-30T12:00:00+02:00"
