import math

import pytest

from crawler.tyndp_pecd import HOURS, array_literal, climate_year_label, parse_member_name, parse_series


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "PECD/2030/PECD_Wind_Onshore_2030_DE00_edition 2023.2.csv",
            (2030, "DE00", "wind_onshore", "Wind_Onshore"),
        ),
        (
            "PECD/2040/PECD_CSP_withStorage_7h_preDispatch_2040_GR03_edition 2023.2.csv",
            (2040, "GR03", "csp_storage_7h_predispatch", "CSP_withStorage_7h_preDispatch"),
        ),
        (
            "PECD/2050/DKN6_OFF_CapacityFactors_Wind_Offshore_2050.csv",
            (2050, "DKN6_OFF", "wind_offshore", "Wind_Offshore"),
        ),
        # TYNDP 2026 solar files have no year in their name; it is the folder.
        ("PECD/2035/Solar PV Utility LUG1.csv", (2035, "LUG1", "solar_pv_utility", "Solar PV Utility")),
    ],
)
def test_member_name_gives_target_year_zone_and_technology(name, expected):
    member = parse_member_name(name)
    assert (member["target_year"], member["zone"], member["technology"], member["source_technology"]) == expected


@pytest.mark.parametrize(
    "name",
    [
        "__MACOSX/PECD/2030/._PECD_Wind_Onshore_2030_DE00_edition 2023.2.csv",
        "PECD/2040/PECD_LFSolarPVUtility_2040_ITCS_edition 2023.2.xlsx",
        "PECD/.DS_Store",
        "PECD/2030/",
    ],
)
def test_other_members_are_skipped(name):
    assert parse_member_name(name) is None


def _pecd_csv(columns: list[str], hours: int = HOURS) -> bytes:
    width = 2 + len(columns)
    blank = "," * (width - 1)
    lines = [blank, blank, "Country,DE" + "," * (width - 2), "PECD Zone,DE00" + "," * (width - 2), blank]
    lines.append(",".join(["Date", "Hour", *columns]))
    for hour in range(hours):
        lines.append(",".join(["01.01.", str(hour % 24 + 1), *[f"{0.5 + i / 10}" for i in range(len(columns))]]))
    return "\n".join(lines).encode()


def test_series_table_starts_at_the_date_row():
    frame = parse_series(_pecd_csv(["1982.0", "1983.0"]))
    assert list(frame.columns) == ["Date", "Hour", "1982.0", "1983.0"]
    assert len(frame) == HOURS
    assert frame["1983.0"].iloc[0] == "0.6"


def test_series_with_missing_hours_is_rejected():
    with pytest.raises(ValueError, match="8760"):
        parse_series(_pecd_csv(["WS061"], hours=8736))


def test_climate_year_labels_and_array_literal():
    assert [climate_year_label(c) for c in ["1982.0", "WS061"]] == ["1982", "WS061"]
    # 6.95e-48 occurs in the source files and is below the range of real.
    assert array_literal([0.1234567, math.nan, 0.0, 6.95334e-48, 1.0]) == "{0.123457,NULL,0,0,1}"
