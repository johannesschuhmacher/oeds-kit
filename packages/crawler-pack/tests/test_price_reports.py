"""Parsers of the World Bank Pink Sheet, the EEX auction reports and the
PyPSA technology-data cost files, on small files with the sources' layout."""

from datetime import date, datetime
import io

import pandas as pd

from crawler.eex_eua_auctions import parse_auction_report
from crawler.pypsa_technology_data import parse_costs_csv
from crawler.worldbank_commodities import parse_monthly_prices


def _xlsx(sheets: dict[str, list[list]]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=name, header=False, index=False)
    return buffer.getvalue()


def test_pink_sheet_rows_per_commodity_and_month():
    content = _xlsx(
        {
            "Mismatch Details": [["x"]],
            "Monthly Prices": [
                ["World Bank Commodity Price Data (The Pink Sheet)", None, None],
                ["monthly prices in nominal US dollars, 1960 to present", None, None],
                [None, None, None],
                ["Updated on November 03, 2026", None, None],
                [None, "Crude oil, Brent", "Coal, South African **"],
                [None, "($/bbl)", "($/mt)"],
                ["1960M01", 1.6, "…"],
                ["2026M10", 125, 100],
            ],
        }
    )
    frame = parse_monthly_prices(content)
    assert frame[["commodity", "unit", "year", "month", "price"]].values.tolist() == [
        ["Crude oil, Brent", "$/bbl", 1960, 1, 1.6],
        ["Crude oil, Brent", "$/bbl", 2026, 10, 125.0],
        ["Coal, South African", "$/mt", 2026, 10, 100.0],
    ]
    assert str(frame["period_start"].iloc[1]) == "2026-10-01 00:00:00+00:00"


HEADER = [None, "Date", "Time", "Auction Name", "Contract", "Status", "Auction Price €/tCO2",
          "Auction Volume tCO2", "Cover Ratio"]


def _auction_sheet(zone_header: str, row: list) -> list[list]:
    return [[None] * 10] * 5 + [HEADER + [zone_header, "Austria\n(AT)"], row]


def test_auction_report_reads_every_sheet_and_both_zone_headers():
    content = _xlsx(
        {
            "Primary Market Auction": _auction_sheet(
                "Country",
                [None, datetime(2025, 3, 4), datetime(2025, 3, 4, 11, 0, 30), "Auction 4. Period DE", "T3PA",
                 "successful", 70.5, 3000000, 1.6, "DE", ""],
            ),
            "EU ETS1": _auction_sheet(
                "Zone",
                [None, datetime(2026, 11, 11), datetime(2026, 11, 11, 11, 0, 33), "Auction 4. Period CAP3 PL", "T3PA",
                 "successful", 88.6, 1945000, 1.58, "PL", ""],
            ),
        }
    )
    frame = parse_auction_report(content)
    assert frame[["market", "auction_date", "auction_price", "auction_volume", "zone"]].values.tolist() == [
        ["Primary Market Auction", date(2025, 3, 4), 70.5, 3000000.0, "DE"],
        ["EU ETS1", date(2026, 11, 11), 88.6, 1945000.0, "PL"],
    ]
    # Member-state revenue columns are not loaded.
    assert "Austria\n(AT)" not in frame.columns


def test_costs_file_before_currency_year_column():
    content = b"technology,parameter,value,unit,source,further description\nCCGT,efficiency,0.58,per unit,DEA,\n"
    frame = parse_costs_csv(content)
    assert frame.columns.tolist() == ["technology", "parameter", "value", "unit", "source", "further_description", "currency_year"]
    assert frame["value"].iloc[0] == 0.58
    assert pd.isna(frame["currency_year"].iloc[0])
