# SPDX-FileCopyrightText: Johannes Schuhmacher, Haoshen Zhang
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
ENTSO-E Transparency Platform File Library crawler.

The crawler pulls the selected FMS CSV extracts via OAuth2/HTTPS and writes
them into PostgreSQL. Active file-library items and their target tables are
defined in one place so that new extracts can be added without touching the
download loop in multiple spots.
"""
import os
import logging
import re
from typing import List, Dict

import gc
from dotenv import load_dotenv

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import (
    text,
    Table,
    Column,
    String,
    Float,
    DateTime,
    MetaData,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from entsoe.mappings import PSRTYPE_MAPPINGS, Area
from urllib3.util.retry import Retry

from crawler.common.base_crawler import BaseCrawler

from datetime import datetime


FMS_ACTIVE_DATA_ITEMS = (
    ("AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants_16.1.D_r3", "AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants"),
    ("ActualTotalLoad_6.1.A_r3", "ActualTotalLoad"),
    ("DayAheadTotalLoadForecast_6.1.B_r3", "DayAheadTotalLoadForecast"),
    ("ActualGenerationOutputPerGenerationUnit_16.1.A_r3", "ActualGenerationOutputPerGenerationUnit"),
    ("AggregatedGenerationPerType_16.1.B_C_r3", "AggregatedGenerationPerType"),
    ("CommercialSchedulesNetPositions_12.1.F_r3", "CommercialSchedulesNetPositions"),
    ("DayAheadAggregatedGeneration_14.1.C_r3", "DayAheadAggregatedGeneration"),
    ("GenerationForecastsForWindAndSolar_14.1.D_r3", "GenerationForecastsForWindAndSolar"),
    ("EnergyPrices_12.1.D_r3", "EnergyPrices"),
    ("ExpansionAndDismantlingProjects_9.1_r3", "ExpansionAndDismantlingProjects"),
    ("ForecastedTransferCapacities_11.1_r3", "ForecastedTransferCapacities"),
    ("InstalledGenerationCapacityPerProductionUnit_14.1.B_r3", "InstalledGenerationCapacityPerProductionUnit"),
    ("InstalledGenerationCapacityAggregated_14.1.A_r3", "InstalledGenerationCapacityAggregated"),
    ("PhysicalFlows_12.1.G_r3", "PhysicalFlows"),
    ("ProductionAndGenerationUnits_r3", "ProductionAndGenerationUnits"),
    ("TotalCapacityAlreadyAllocated_12.1.C_r3", "TotalCapacityAlreadyAllocated"),
    ("TotalCapacityNominated_12.1.B_r3", "TotalCapacityNominated"),
    ("TotalLoadForecast_6.1.C_D_E_r3", "TotalLoadForecast"),
    ("TransmissionAssets_r3", "TransmissionAssets"),
    ("UnavailabilityInTheTransmissionGrid_10.1.A_B_r3", "UnavailabilityInTheTransmissionGrid"),
    ("UnavailabilityOfConsumptionUnits_7.1.A_B_r3", "UnavailabilityOfConsumptionUnits"),
    ("UnavailabilityOfOffshoreGrid_10.1.C_r3", "UnavailabilityOfOffshoreGrid"),
    ("UnavailabilityOfProductionAndGenerationUnits_15.1.A_B_C_D_r3", "UnavailabilityOfProductionAndGenerationUnits"),
    ("UseOfTransferCapacity_12.1.A_r3", "UseOfTransferCapacity"),
    ("YearAheadForecastMargin_8.1_r3", "YearAheadForecastMargin"),
)

FMS_SINGLE_FILE_DATA_ITEMS = {
    "InstalledGenerationCapacityAggregated_14.1.A_r3",
    "InstalledGenerationCapacityPerProductionUnit_14.1.B_r3",
    "ProductionAndGenerationUnits_r3",
    "TransmissionAssets_r3",
    "YearAheadForecastMargin_8.1_r3",
}

FMS_UNFILTERED_DATE_DATA_ITEMS = {
    *FMS_SINGLE_FILE_DATA_ITEMS,
    "AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants_16.1.D_r3",
    "ExpansionAndDismantlingProjects_9.1_r3",
}

FMS_ANNUAL_FILE_DATA_ITEMS = {
    "AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants_16.1.D_r3",
    "ExpansionAndDismantlingProjects_9.1_r3",
}

FMS_OUTAGE_DATA_ITEMS = {
    "UnavailabilityOfConsumptionUnits_7.1.A_B_r3",
    "UnavailabilityOfProductionAndGenerationUnits_15.1.A_B_C_D_r3",
}

FMS_FULL_UPSERT_TABLES = {
    "InstalledGenerationCapacityAggregated",
    "InstalledGenerationCapacityPerProductionUnit",
    "ProductionAndGenerationUnits",
    "TransmissionAssets",
    "UnavailabilityInTheTransmissionGrid",
    "UnavailabilityOfGenerationUnits",
    "UnavailabilityOfGenerationUnitsReasons",
    "UnavailabilityOfOffshoreGrid",
    "UnavailabilityOfProductionUnits",
    "UnavailabilityOfProductionUnitsReasons",
    "UnavailabilityOfProductionAndGenerationUnits",
}

FMS_DATETIME_COLUMNS = (
    "DateTime",
    "DateTime (UTC)",
    "DateTime(UTC)",
    "EndOutage",
    "StartOutage",
    "StartTS",
    "EndTS",
    "StartOutage(UTC)",
    "EndOutage(UTC)",
    "StartTimeSeries(UTC)",
    "EndTimeSeries(UTC)",
    "VersionPublicationTimestamp(UTC)",
)

FMS_UPDATE_TIME_COLUMNS = (
    "UpdateTime",
    "UpdateTime (UTC)",
    "UpdateTime(UTC)",
)

DEFAULT_START_DATE = "2014-01-01"


class EntsoeFMSCrawler(BaseCrawler):
    """Crawler for the selected ENTSO-E FMS extracts."""

    DATA_ITEM_TABLE_MAP = dict(FMS_ACTIVE_DATA_ITEMS)
    TARGET_FILES_DIR = [f"/TP_export/{data_item}/" for data_item, _ in FMS_ACTIVE_DATA_ITEMS]
    ANNUAL_FILE_DATA_ITEMS = FMS_ANNUAL_FILE_DATA_ITEMS
    SINGLE_FILE_DATA_ITEMS = FMS_SINGLE_FILE_DATA_ITEMS
    UNFILTERED_DATE_DATA_ITEMS = FMS_UNFILTERED_DATE_DATA_ITEMS
    OUTAGE_DATA_ITEMS = FMS_OUTAGE_DATA_ITEMS
    FULL_UPSERT_TABLES = FMS_FULL_UPSERT_TABLES

    UNIQUE_KEY_DICT = {
        "AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants": "unique_agg_fill_rate_hydro",
        "ActualGenerationOutputPerGenerationUnit": "unique_generation_output",
        "ActualTotalLoad": "unique_actual_total_load",
        "AggregatedGenerationPerType": "unique_agreegated_generation_type",
        "CommercialSchedulesNetPositions": "unique_comm_sched_net_pos",
        "DayAheadAggregatedGeneration": "unique_day_ahead_agg_gen",
        "DayAheadTotalLoadForecast": "unique_day_ahead_total_load_fore",
        "GenerationForecastsForWindAndSolar": "unique_gen_forecast_wind_solar",
        "EnergyPrices": "unique_energy_price",
        "ExpansionAndDismantlingProjects": "unique_expansion_dismantling_projects",
        "ForecastedTransferCapacities": "unique_forecasted_transfer_capa",
        "InstalledGenerationCapacityPerProductionUnit": "unique_insta_capa_prod_unit",
        "InstalledCapacityProductionUnit": "unique_insta_capa_prod_unit",
        "InstalledGenerationCapacityAggregated": "unique_insta_gen_capa_aggr",
        "PhysicalFlows": "unique_physical_flows",
        "ProductionAndGenerationUnits": "unique_prod_gen_units",
        "TotalCapacityAlreadyAllocated": "unique_total_capa_allocated",
        "TotalCapacityNominated": "unique_total_capa_nominated",
        "TotalLoadForecast": "unique_total_load_forecast",
        "TransmissionAssets": "unique_transmission_assets",
        "UnavailabilityInTheTransmissionGrid": "unique_unava_trans_grid",
        "UnavailabilityOfConsumptionUnits": "unique_plam_unava_cons_units",
        "UnavailabilityOfOffshoreGrid": "unique_unava_offshore_grid",
        "PlannedUnavailabilityOfConsumptionUnits": "unique_plam_unava_cons_units",
        "UseOfTransferCapacity": "unique_use_of_transfer_capacity",
        "UnavailabilityOfGenerationUnits": "unique_unava_gen_units",
        "UnavailabilityOfGenerationUnitsReasons": "unique_unava_gen_reason",
        "UnavailabilityOfProductionUnits": "unique_unava_pro_units",
        "UnavailabilityOfProductionUnitsReasons": "unique_unava_pro_reasons",
        "UnavailabilityOfProductionAndGenerationUnits": "unique_unava_prod_gen_units",
        "YearAheadForecastMargin": "unique_year_ahead_forecast_margin",
    }

    UNIQUE_KEY_COLUMNS = {
        "AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants": [
            "Year", "Month", "Week", "ResolutionCode", "AreaDisplayName", "AreaTypeCode"
        ],
        "ActualGenerationOutputPerGenerationUnit": [
            "DateTime(UTC)", "ResolutionCode", "AreaCode", "AreaDisplayName",
            "AreaTypeCode", "AreaMapCode", "GenerationUnitCode", "GenerationUnitName", "GenerationUnitType"
        ],
        "ActualTotalLoad": [
            "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "AreaTypeCode"
        ],
        "AggregatedGenerationPerType": [
            "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "ProductionType", "AreaTypeCode"
        ],
        "CommercialSchedulesNetPositions": [
            "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "AreaTypeCode"
        ],
        "DayAheadAggregatedGeneration": [
            "DateTime(UTC)", "AreaDisplayName", "AreaTypeCode"
        ],
        "DayAheadTotalLoadForecast": [
            "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "AreaTypeCode"
        ],
        "EnergyPrices": [
            "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "ContractType", "Sequence"
        ],
        "ExpansionAndDismantlingProjects": [
            "DateTime(UTC)", "OutAreaDisplayName", "InAreaDisplayName", "ProjectType", "AssetCode", "EstimatedCompletionDate"
        ],
        "InstalledCapacityProductionUnit": [
            "EICCode",
            "Name",
            "ValidFrom",
            "ValidTo",
            "Status",
            "Type",
            "Location",
        ],
        "InstalledGenerationCapacityAggregated": [
            "Year", "ResolutionCode", "AreaDisplayName", "AreaTypeCode", "ProductionType"
        ],
        "ForecastedTransferCapacities": [
            "DateTime(UTC)", "ResolutionCode", "OutAreaDisplayName",
            "InAreaDisplayName", "ContractType"
        ],
        "InstalledGenerationCapacityPerProductionUnit": [
            "ProductionUnitCode", "ValidFrom", "ValidTo", "ProductionType",
            "AreaCode", "AreaDisplayName", "AreaTypeCode"
        ],
        "PhysicalFlows": [
            "DateTime(UTC)", "ResolutionCode", "OutAreaDisplayName", "InAreaDisplayName"
        ],
        "ProductionAndGenerationUnits": [
            "ProductionUnitCode", "GenerationUnitCode", "ValidFrom", "ValidTo", "AreaCode", "AreaDisplayName", "AreaTypeCode"
        ],
        "TotalCapacityAlreadyAllocated": [
            "InstanceCode", "DateTime(UTC)", "ResolutionCode", "ContractType", "Category", "OutAreaDisplayName", "InAreaDisplayName"
        ],
        "TotalCapacityNominated": [
            "DateTime(UTC)", "ResolutionCode", "OutAreaDisplayName", "InAreaDisplayName", "ContractType"
        ],
        "TotalLoadForecast": [
            "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "AreaTypeCode", "ContractType"
        ],
        "TransmissionAssets": [
            "AssetCode", "ValidFrom", "ValidTo", "AreaCode", "AreaDisplayName", "AreaTypeCode"
        ],
        "UseOfTransferCapacity": [
            "InstanceCode", "DateTime(UTC)", "ResolutionCode", "ContractType", "Category", "Sequence", "OutAreaDisplayName", "InAreaDisplayName"
        ],
        "GenerationForecastsForWindAndSolar": [
            "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "AreaTypeCode", "ProductionType"
        ],
        "PlannedUnavailabilityOfConsumptionUnits": [
            "DateTime",
            "ResolutionCode",
            "AreaCode",
            "AreaTypeCode",
            "AreaName",
            "MapCode",
        ],

        "UnavailabilityOfConsumptionUnits": [
            "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "AreaTypeCode"
        ],
        "UnavailabilityInTheTransmissionGrid": [
            "InstanceCode", "Version", "StartOutage(UTC)", "EndOutage(UTC)",
            "StartTimeSeries(UTC)", "EndTimeSeries(UTC)", "OutAreaCode", "InAreaCode", "Status", "Type"
        ],
        "UnavailabilityOfOffshoreGrid": [
            "InstanceCode", "Version", "StartOutage(UTC)", "EndOutage(UTC)",
            "StartTimeSeries(UTC)", "EndTimeSeries(UTC)", "AssetCode", "Status"
        ],
        "UnavailabilityOfGenerationUnits": [
            "StartOutage",
            "EndOutage",
            "StartTS",
            "EndTS",
            "TimeZone",
            "MRID",
            "Status",
            "Type",
            "AreaCode",
            "AreaTypeCode",
            "AreaName",
            "MapCode",
            "PowerResourceEIC",
            "UnitName",
            "ProductionType",
            "Version",
            "OldVersion",
        ],
        "UnavailabilityOfProductionAndGenerationUnits": [
            "InstanceCode", "Version", "StartOutage(UTC)", "EndOutage(UTC)",
            "StartTimeSeries(UTC)", "EndTimeSeries(UTC)",
            "AssetCode", "Status", "Type"
        ],
        "UnavailabilityOfGenerationUnitsReasons": [
            "StartTS",
            "EndTS",
            "MRID",
            "Version",
            "OldVersion",
            "ReasonCode",
        ],
        "UnavailabilityOfProductionUnits": [
            "StartOutage",
            "EndOutage",
            "StartTS",
            "EndTS",
            "TimeZone",
            "MRID",
            "Status",
            "Type",
            "AreaCode",
            "AreaTypeCode",
            "AreaName",
            "MapCode",
            "PowerResourceEIC",
            "UnitName",
            "ProductionType",
            "Version",
            "OldVersion",
        ],
        "UnavailabilityOfProductionUnitsReasons": [
            "StartTS",
            "EndTS",
            "MRID",
            "Version",
            "OldVersion",
            "ReasonCode",
        ],
        "YearAheadForecastMargin": [
            "Year", "ResolutionCode", "AreaDisplayName", "AreaTypeCode"
        ],
    }

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------
    def __init__(self, schema_name: str, config: dict):
        super().__init__(schema_name, config)
        self._access_token: str | None = None
        self.session: requests.Session | None = None
        configured_start = self.config.get("default_start_date", DEFAULT_START_DATE)
        self.default_start_time = pd.Timestamp(configured_start)
        if self.default_start_time.tzinfo is None:
            self.default_start_time = self.default_start_time.tz_localize("Europe/Berlin")
        else:
            self.default_start_time = self.default_start_time.tz_convert("Europe/Berlin")

    def init_base_sql(self):
        """Write the static PSRTYPE and area lookup tables."""
        psrtype = pd.DataFrame.from_dict(PSRTYPE_MAPPINGS, orient="index", columns=["prod_type"])
        areas = pd.DataFrame(
            [[e.name, e.value, e.tz, e.meaning] for e in Area],
            columns=["name", "value", "tz", "meaning"],
        )
        with self.engine.begin() as conn:
            areas.columns = [x.lower() for x in areas.columns]
            psrtype.columns = [x.lower() for x in psrtype.columns]
            areas.to_sql("areas", conn, if_exists="replace")
            psrtype.to_sql("psrtype", conn, if_exists="replace")

    # ---------------------------
    # Authentication and session setup
    # ---------------------------
    # Read credentials from environment variables or a local dotenv file.
    load_dotenv()
    KETCLOAK_URL = "https://keycloak.tp.entsoe.eu/realms/tp/protocol/openid-connect/token"
    FMS_URL = "https://fms.tp.entsoe.eu/downloadFileContent"
    USERNAME = os.getenv("ENTSOE_USERNAME")
    PASSWORD = os.getenv("ENTSOE_PASSWORD")
    CLIENT_ID = "tp-fms-public"

    # ---------------------------
    # Constant endpoints and paths
    # ---------------------------
    TOKEN_URL = "https://keycloak.tp.entsoe.eu/realms/tp/protocol/openid-connect/token"
    CLIENT_ID = "tp-fms-public"
    FMS_BASEURL = "https://fms.tp.entsoe.eu"

    def _authenticate(self) -> None:
        """Fetch an OAuth2 access token and initialize the retry-enabled session."""

        if not self.USERNAME or not self.PASSWORD:
            print("Error: ENTSOE_USERNAME or ENTSOE_PASSWORD is not set in .env")

        payload = (
            f"client_id={self.CLIENT_ID}"
            f"&grant_type=password"
            f"&username={self.USERNAME}"
            f"&password={self.PASSWORD}"
        )

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        response = requests.post(self.TOKEN_URL, headers=headers, data=payload, timeout=120)
        response.raise_for_status()

        self._access_token = response.json().get("access_token")

        retries = Retry(
            total=5,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retries)

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }
        )
        self.session.mount("https://", adapter)
        self.logger.info("FMS Token received and session established.")

    # ---------------------------
    # File‑Library Helpers
    # ---------------------------
    def _list_metadata(self, data_item: str, start: pd.Timestamp, end: pd.Timestamp) -> List[Dict]:
        payload = {
            "topLevelFolder": "TP_export",
            "path": f"/TP_export/{data_item}/",
            "pageInfo": {
                "pageIndex": 0,
                "pageSize": 100
            }
        }
        all_metas = []
        while True:
            try:
                r = self.session.post(f"{self.FMS_BASEURL}/listFolder", json=payload, timeout=120)
                r.raise_for_status()
            except requests.HTTPError as exc:
                if exc.response.status_code == 401:
                    self.logger.warning(f"Access Token expired during listFolder for {data_item}. Re-authenticating...")
                    self._authenticate()
                    self.logger.info("Re-authentication successful. Retrying listFolder...")
                    r = self.session.post(f"{self.FMS_BASEURL}/listFolder", json=payload, timeout=120)
                    r.raise_for_status()
                else:
                    self.logger.error(f"HTTP error in listFolder for {data_item}: {exc}")
                    raise exc
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Network error (e.g., Timeout) in listFolder for {data_item}: {e}")
                raise e

            data = r.json()
            metas = data.get("contentItemList", [])
            if not metas:
                break
            all_metas.extend(metas)
            payload["pageInfo"]["pageIndex"] += 1

        return all_metas

    def _download_file(self, fileid: str, target: str) -> None:
        payload = {
            "fileIdList": [
                f"{fileid}"
            ],
            "topLevelFolder": "TP_export",
            "downloadAsZip": False,
        }
        try:
            r = self.session.post(f"{self.FMS_BASEURL}/downloadFileContent", json=payload, timeout=120)
            r.raise_for_status()
        except requests.HTTPError as exc:
            # Re-authenticate when the current access token has expired.
            if exc.response.status_code == 401:
                self.logger.warning("Access Token expired. Re-authenticating")

                self.logger.warning("Re-authenticating")

                # Refresh the access token and retry the download.
                self._authenticate()
                self.logger.info("Re-authentication successful. Retrying download for %s...", target)

                r = self.session.post(f"{self.FMS_BASEURL}/downloadFileContent", json=payload, timeout=120)
                r.raise_for_status()
            else:
                raise exc

        with open(target, "wb") as f:
            f.write(r.content)

    def _get_target_data_items(self) -> List[str]:
        target_data_items = self.config.get("target_data_items")
        if not target_data_items:
            return list(self.DATA_ITEM_TABLE_MAP)

        requested = set(target_data_items)
        selected = [
            data_item
            for data_item in self.DATA_ITEM_TABLE_MAP
            if data_item in requested
        ]

        missing = sorted(requested - set(selected))
        if missing:
            self.logger.warning("Unknown FMS target_data_items requested: %s", ", ".join(missing))

        return selected

    def _get_table_name_for_data_item(self, data_item: str) -> str:
        return self.DATA_ITEM_TABLE_MAP[data_item]

    @staticmethod
    def _should_process_metadata_entry(meta: Dict) -> bool:
        name = meta.get("name", "")
        return isinstance(name, str) and name.lower().endswith(".csv")

    @classmethod
    def _should_skip_date_filter(cls, data_item: str) -> bool:
        return data_item in cls.UNFILTERED_DATE_DATA_ITEMS

    @staticmethod
    def _extract_file_period_start(filename: str) -> pd.Timestamp | None:
        match = re.match(r"^(?P<year>\d{4})(?:_(?P<month>\d{2}))?", filename)
        if not match:
            return None

        year = int(match.group("year"))
        month = int(match.group("month") or 1)
        try:
            return pd.Timestamp(year=year, month=month, day=1, tz="Europe/Berlin")
        except ValueError:
            return None

    @classmethod
    def _file_period_overlaps(
        cls,
        filename: str,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
    ) -> bool | None:
        file_start = cls._extract_file_period_start(filename)
        if file_start is None:
            return None
        file_end = file_start + pd.DateOffset(months=1)
        return file_start < end_time and file_end > start_time

    def _get_table_state(self, table_name: str) -> dict:
        state = {
            "table_exists": False,
            "update_time_column": None,
            "datetime_column_name": None,
            "last_update_time": None,
            "last_date_time": None,
        }

        with self.engine.connect() as conn:
            result = conn.execute(
                text(
                    f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'entsoe_fms' AND table_name = '{table_name}'
                    ) AS table_exists;
                    """
                )
            ).fetchone()
            state["table_exists"] = result[0] if result else False

            if not state["table_exists"]:
                return state

            result = conn.execute(
                text(
                    f"""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'entsoe_fms'
                      AND table_name = '{table_name}'
                      AND column_name ~* 'UpdateTime';
                    """
                )
            ).fetchone()
            state["update_time_column"] = result[0] if result else None

            result = conn.execute(
                text(
                    f"""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'entsoe_fms'
                      AND table_name = '{table_name}'
                      AND column_name ~* 'DateTime';
                    """
                )
            ).fetchone()
            state["datetime_column_name"] = result[0] if result else None

            if state["update_time_column"]:
                state["last_update_time"] = conn.execute(
                    text(f'SELECT MAX("{state["update_time_column"]}") FROM "entsoe_fms"."{table_name}"')
                ).scalar()

            if state["datetime_column_name"]:
                state["last_date_time"] = conn.execute(
                    text(f'SELECT MAX("{state["datetime_column_name"]}") FROM "entsoe_fms"."{table_name}"')
                ).scalar()

        if state["last_update_time"]:
            state["last_update_time"] = state["last_update_time"].replace(tzinfo=None)
        if state["last_date_time"]:
            state["last_date_time"] = state["last_date_time"].replace(tzinfo=None)

        return state

    def _ensure_current_table_schema(self, table_name: str) -> None:
        if table_name != "UnavailabilityOfConsumptionUnits":
            return

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    'ALTER TABLE "entsoe_fms"."UnavailabilityOfConsumptionUnits" '
                    'ADD COLUMN IF NOT EXISTS "ActualUnavailableCapacity[MW]" DOUBLE PRECISION'
                )
            )
            conn.execute(
                text(
                    'ALTER TABLE "entsoe_fms"."UnavailabilityOfConsumptionUnits" '
                    'ADD COLUMN IF NOT EXISTS "TotalUnavailableCapacity[MW]" DOUBLE PRECISION'
                )
            )

    @staticmethod
    def _normalize_timestamp_columns(df: pd.DataFrame) -> pd.DataFrame:
        for col_name in FMS_DATETIME_COLUMNS + FMS_UPDATE_TIME_COLUMNS:
            if col_name in df.columns:
                df[col_name] = pd.to_datetime(df[col_name], format="mixed")
                if df[col_name].dt.tz is None:
                    df[col_name] = df[col_name].dt.tz_localize("UTC")
                else:
                    df[col_name] = df[col_name].dt.tz_convert("UTC")
        return df

    def _deduplicate_on_unique_keys(self, table_name: str, df: pd.DataFrame) -> pd.DataFrame:
        """Keep only the latest row per unique-key tuple inside the current dataframe."""
        if df.empty:
            return df

        df = df.copy()
        update_time_column = next((col for col in FMS_UPDATE_TIME_COLUMNS if col in df.columns), None)
        if update_time_column:
            df = df.sort_values(update_time_column, kind="stable")

        return df.drop_duplicates(
            subset=self.UNIQUE_KEY_COLUMNS[table_name],
            keep="last",
        )

    def _upsert_dataframe(self, table_name: str, df: pd.DataFrame) -> None:
        """Upsert a dataframe into the target table in conflict-safe batches."""
        if df.empty:
            return

        df = self._deduplicate_on_unique_keys(table_name, df)
        if df.empty:
            return

        data = df.to_dict(orient="records")
        metadata = MetaData()
        table_obj = Table(table_name, metadata, autoload_with=self.engine, schema="entsoe_fms")
        batch_size = 5000

        for i in range(0, len(data), batch_size):
            batch = data[i : i + batch_size]
            stmt = insert(table_obj).values(batch)
            update_dict = {c.name: stmt.excluded[c.name] for c in table_obj.columns}
            stmt = stmt.on_conflict_do_update(
                constraint=self.UNIQUE_KEY_DICT[table_name],
                set_=update_dict,
            )
            with self.engine.begin() as conn:
                conn.execute(stmt)

    def _insert_dataframe(self, table_name: str, df: pd.DataFrame) -> None:
        """Insert new rows in batches and fall back to upsert if a conflict appears."""
        if df.empty:
            return

        df = self._deduplicate_on_unique_keys(table_name, df)
        if df.empty:
            return

        batch_size = 5000
        for i in range(0, len(df), batch_size):
            batch_df = df.iloc[i : i + batch_size]
            try:
                batch_df.to_sql(table_name, con=self.engine, if_exists="append", index=False)
            except (IntegrityError, pd.errors.DatabaseError) as exc:
                if not self._is_integrity_error(exc):
                    raise
                self.logger.warning(
                    "Insert conflict detected for table '%s' in rows %s-%s. Falling back to upsert for this batch.",
                    table_name,
                    i,
                    i + len(batch_df) - 1,
                )
                self._upsert_dataframe(table_name, batch_df)

    @staticmethod
    def _is_integrity_error(exc: BaseException) -> bool:
        current: BaseException | None = exc
        while current is not None:
            if isinstance(current, IntegrityError):
                return True
            current = current.__cause__ or current.__context__
        return False

    def _split_incremental_chunk(
        self,
        table_name: str,
        df: pd.DataFrame,
        update_time_column: str | None,
        last_update_time,
        datetime_column_name: str | None,
        last_date_time,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        if update_time_column and update_time_column in df.columns and last_update_time:
            temp_update = df[update_time_column].dt.tz_localize(None)
            df = df[temp_update > last_update_time].copy()
        else:
            df = df.copy()

        if df.empty:
            return pd.DataFrame(), pd.DataFrame()

        if table_name == "InstalledGenerationCapacityAggregated":
            df["Year"] = pd.to_numeric(df["Year"])
            return pd.DataFrame(), df

        if table_name in self.FULL_UPSERT_TABLES:
            return pd.DataFrame(), df.copy()

        if datetime_column_name and datetime_column_name in df.columns and last_date_time:
            temp_date = df[datetime_column_name].dt.tz_localize(None)
            df_update = df[temp_date <= last_date_time].copy()
            df_insert = df[temp_date > last_date_time].copy()
            return df_insert, df_update

        return pd.DataFrame(), df.copy()

    @staticmethod
    def calculate_package_window_start(end_time: pd.Timestamp, window_months: int) -> pd.Timestamp:
        if window_months < 1:
            raise ValueError("fms_package_window_months must be at least 1.")

        if end_time.tzinfo is None:
            end_time = end_time.tz_localize("Europe/Berlin")
        else:
            end_time = end_time.tz_convert("Europe/Berlin")

        current_month_start = end_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return current_month_start - pd.DateOffset(months=window_months - 1)

    def _get_run_start_time(self, end_time: pd.Timestamp) -> pd.Timestamp:
        window_months = self.config.get("fms_package_window_months")
        if window_months is None:
            return self.default_start_time

        try:
            parsed_window_months = int(window_months)
        except (TypeError, ValueError) as exc:
            raise ValueError("fms_package_window_months must be an integer.") from exc

        return self.calculate_package_window_start(end_time, parsed_window_months)

    def _uses_full_package_upsert(self) -> bool:
        return self.config.get("fms_package_write_mode") == "full_upsert"

    def _split_package_refresh_chunk(self, table_name: str, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        return pd.DataFrame(), self._deduplicate_on_unique_keys(table_name, df.copy())

    # ---------------------------
    # Main download routine
    # ---------------------------
    def _download_files_and_write_into_database(
        self,
        local_dir: str,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        update_interval: pd.Timedelta = pd.Timedelta(days=90),
    ) -> None:
        if not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)

        # Authenticate with ENTSO-E
        self._authenticate()

        # Kept as a safe fallback if a future change re-introduces buffered writes.
        df_insert_full = pd.DataFrame()
        df_update_full = pd.DataFrame()
        failures: list[str] = []

        target_data_items = self._get_target_data_items()
        if not target_data_items:
            self.logger.warning("No FMS data items selected. Nothing to download.")
            return

        full_package_upsert = self._uses_full_package_upsert()
        if full_package_upsert:
            self.logger.info("Full package upsert mode is enabled for this ENTSO-E FMS run.")

        for data_item in target_data_items:
            create = False
            do_not_create_again = False
            schema_checked = False
            table_name = self._get_table_name_for_data_item(data_item)

            print(f"\n--- Processing data item: {data_item} ---")
            self.logger.info("Starting processing for data item %s -> table %s", data_item, table_name)

            try:
                metas = self._list_metadata(data_item, start_time, end_time)
            except Exception as exc:
                self.logger.error(f"Failed metadata request for {data_item}: {exc}", exc_info=True)
                failures.append(f"{data_item}: metadata request")
                continue

            metas = sorted(
                [meta for meta in metas if self._should_process_metadata_entry(meta)],
                key=lambda meta: meta.get("name", ""),
            )

            # -------------------------------------------------------------------------
            # Pre-check logic: Determine effective start time for this specific table
            # -------------------------------------------------------------------------
            effective_start_time = start_time
            try:
                table_state = self._get_table_state(table_name)
                if full_package_upsert:
                    self.logger.info(
                        "Table '%s' uses package-refresh mode. Processing package files from %s.",
                        table_name,
                        effective_start_time,
                    )
                elif table_state["table_exists"] and table_state["last_update_time"]:
                    effective_start_time = max(start_time, end_time - update_interval)
                    self.logger.info(
                        "Table '%s' exists. Incremental mode starts at %s.",
                        table_name,
                        effective_start_time,
                    )
            except Exception as e:
                self.logger.warning(f"Pre-check failed: {e}")

            for meta in metas:
                fname: str = meta["name"]

                skip_date_filter = self._should_skip_date_filter(data_item)
                if not skip_date_filter:
                    overlaps = self._file_period_overlaps(
                        fname,
                        effective_start_time,
                        end_time,
                    )
                    if overlaps is None:
                        self.logger.warning(
                            "Could not infer period from FMS file '%s' in '%s'. Processing without date filter.",
                            fname,
                            data_item,
                        )
                    elif not overlaps:
                        continue

                local_path = os.path.join(local_dir, fname)
                print(f"  > Downloading: {fname}")
                self.logger.info(f"Downloading file: {fname} (ID: {meta.get('fileId', 'N/A')})")
                try:
                    self._download_file(meta["fileId"], local_path)
                except requests.HTTPError as exc:
                    self.logger.error(f"Download failed for {fname}: {exc}", exc_info=True)
                    failures.append(f"{fname}: download")
                    continue

                # ---------------- CSV Parsing & DB Logic (Stream-Processing) ----------------
                try:
                    table_state = self._get_table_state(table_name)
                    if not table_state["table_exists"]:
                        create = True
                        if not do_not_create_again:
                            self.logger.info("Table '%s' not found, creating it.", table_name)
                            self._create_table_with_unique_constraint(table_name)
                            do_not_create_again = True
                        table_state = self._get_table_state(table_name)
                    if not schema_checked:
                        self._ensure_current_table_schema(table_name)
                        schema_checked = True

                    chunk_size = 50000
                    total_file_inserts = 0
                    total_file_updates = 0

                    with pd.read_csv(local_path, sep=r"\t", engine="python", chunksize=chunk_size) as reader:
                        for chunk_idx, df in enumerate(reader):
                            df = self._normalize_timestamp_columns(df)

                            if create:
                                df = self._deduplicate_on_unique_keys(table_name, df)
                                total_rows = len(df)
                                print(f"    Processing chunk {chunk_idx+1}: Inserting {total_rows} rows...")
                                total_file_inserts += total_rows
                                self._insert_dataframe(table_name, df)

                            elif full_package_upsert:
                                df_insert_chunk, df_update_chunk = self._split_package_refresh_chunk(table_name, df)

                                if df_insert_chunk.empty and df_update_chunk.empty:
                                    continue

                                print(
                                    f"    Processing chunk {chunk_idx+1}: "
                                    f"0 new inserts, {len(df_update_chunk)} package upserts."
                                )
                                self._flush_to_database(table_name, df_insert_chunk, df_update_chunk)
                                total_file_updates += len(df_update_chunk)

                            elif table_state["last_update_time"]:
                                df_insert_chunk, df_update_chunk = self._split_incremental_chunk(
                                    table_name=table_name,
                                    df=df,
                                    update_time_column=table_state["update_time_column"],
                                    last_update_time=table_state["last_update_time"],
                                    datetime_column_name=table_state["datetime_column_name"],
                                    last_date_time=table_state["last_date_time"],
                                )

                                if df_insert_chunk.empty and df_update_chunk.empty:
                                    continue

                                print(
                                    f"    Processing chunk {chunk_idx+1}: "
                                    f"{len(df_insert_chunk)} new inserts, {len(df_update_chunk)} updates."
                                )
                                self._flush_to_database(table_name, df_insert_chunk, df_update_chunk)
                                total_file_inserts += len(df_insert_chunk)
                                total_file_updates += len(df_update_chunk)

                            else:
                                df_update_chunk = df.drop_duplicates(
                                    subset=self.UNIQUE_KEY_COLUMNS[table_name],
                                    keep="first",
                                )
                                self._flush_to_database(table_name, pd.DataFrame(), df_update_chunk)
                                total_file_updates += len(df_update_chunk)

                            del df
                            if 'df_update_chunk' in locals():
                                del df_update_chunk
                            if 'df_insert_chunk' in locals():
                                del df_insert_chunk
                            if chunk_idx % 5 == 0:
                                gc.collect()

                    self.logger.info(f"File {fname} processed successfully. Total rows inserted: {total_file_inserts}, Total rows updated: {total_file_updates}.")
                    print(f"    -> Finished processing {fname}: {total_file_inserts} rows inserted, {total_file_updates} rows updated.")

                except Exception as e:
                    self.logger.error(f"Error processing file {meta['name']}: {e}", exc_info=True)
                    failures.append(f"{fname}: processing")

                finally:
                    print(f"Data processing complete for file {meta['name']}")
                    print(f"Deleted local file: {local_path}")
                    if os.path.exists(local_path):
                        try:
                            os.remove(local_path)
                        except Exception:
                            pass

                    if 'df' in locals():
                        del df
                    gc.collect()

            # Flush accumulated data (safe fallback)
            if not df_insert_full.empty or not df_update_full.empty:
                print(f"--- Flushing data for {table_name} ({len(df_insert_full)} new, {len(df_update_full)} updates) ---")
                self._flush_to_database(table_name, df_insert_full, df_update_full)

            df_insert_full = pd.DataFrame()
            df_update_full = pd.DataFrame()

        if failures:
            raise RuntimeError(
                "ENTSO-E FMS completed with failed files: " + ", ".join(failures)
            )

    # ------------------------------------------------------------------
    # Database flush helper extracted from the legacy SFTP crawler
    # ------------------------------------------------------------------
    def _flush_to_database(self, table_name: str, df_insert: pd.DataFrame, df_update: pd.DataFrame):
        """Write batched inserts and upserts into PostgreSQL."""
        if df_insert.empty and df_update.empty:
            return

        self.logger.info(f"Flushing data for table {table_name} ({len(df_insert)} new, {len(df_update)} updates)...")

        # ---------------- Updates ----------------
        if not df_update.empty:
            self._upsert_dataframe(table_name, df_update)

        # ---------------- Inserts ----------------
        if not df_insert.empty:
            self._insert_dataframe(table_name, df_insert)

    # ------------------------------------------------------------------
    # Public Interface
    # ------------------------------------------------------------------
    def fetch_from_entsoe_fms_to_database(
        self,
        local_dir: str,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        update_interval: pd.Timedelta = pd.Timedelta(days=90),
    ):
        try:
            self._download_files_and_write_into_database(local_dir, start_time, end_time, update_interval)
        finally:
            self.logger.info("Fetching process completed.")

    def save_power_system_data(self):
        print("Pulling power plant data")
        self.logger.info("Pulling power plant data from GitHub PyPSA")

        url = "https://raw.githubusercontent.com/PyPSA/powerplantmatching/master/powerplants.csv"

        try:
            df = pd.read_csv(url)
            self.logger.info(f"Done downloading {len(df)} records")

            column_mapping = {
                "id": "source_id",             # rename id to make sure no conflicts
                "Name": "name",
                "Fueltype": "fuel_type",
                "Technology": "technology",
                "Set": "set_type",
                "Country": "country",
                "Capacity": "capacity",
                "Efficiency": "efficiency",
                "DateIn": "date_in",
                "DateRetrofit": "date_retrofit",
                "DateOut": "date_out",
                "lat": "lat",
                "lon": "lon",
                "Duration": "duration",
                "Volume_Mm3": "volume_mm3",
                "DamHeight_m": "dam_height_m",
                "StorageCapacity_MWh": "storage_capacity_mwh",
                "EIC": "eic_code",
                "projectID": "project_id"
            }

            df = df.rename(columns=column_mapping)

            original_count = len(df)
            df = df.dropna(axis=0, subset=["lon", "lat"])  # Drop rows that cannot be shown on a map.
            dropped_count = original_count - len(df)

            with self.engine.begin() as conn:
                df.to_sql("powersystemdata", conn, if_exists="replace", index=False)  # Replace the snapshot on refresh.

            self.logger.info(f"Finish updating 'powersystemdata',  {len(df)} records")
            print(f"Finish updating 'powersystemdata',  {len(df)} records")

        except Exception as e:
            self.logger.error(f"error: {e}", exc_info=True)
            print("Error downloading powerplant data")

    # ------------------------------------------------------------------
    # Table definitions are currently kept compatible with the legacy SFTP crawler.
    # _create_table_with_unique_constraint()
    #   -> Refactor this into declarative schema metadata in a later cleanup pass.
    # ------------------------------------------------------------------
    def _create_table_with_unique_constraint(self, table_name):
        """
        Create new table using the table_name and create the unique constraint
        """
        metadata = MetaData(schema="entsoe_fms")
        table = None

        match table_name:
            case 'AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants':
                table = Table(
                    'AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants', metadata,
                    Column("Year", Float),
                    Column("Month", Float),
                    Column("Week", Float),
                    Column("TimeZone", String),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("StoredEnergy[MWh]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "Year", "Month", "Week", "ResolutionCode", "AreaDisplayName", "AreaTypeCode",
                        name="unique_agg_fill_rate_hydro"
                    )
                )
            case 'ActualGenerationOutputPerGenerationUnit':
                table = Table(
                    'ActualGenerationOutputPerGenerationUnit', metadata,
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("GenerationUnitCode", String),
                    Column("GenerationUnitName", String),
                    Column("GenerationUnitType", String),
                    Column("ActualGenerationOutput[MW]", Float),
                    Column("ActualConsumption[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "ResolutionCode", "AreaCode", "AreaDisplayName",
                        "AreaTypeCode", "AreaMapCode", "GenerationUnitCode", "GenerationUnitName", "GenerationUnitType",
                        name="unique_generation_output"
                    )
                )
            case 'ActualTotalLoad':
                table = Table(
                    'ActualTotalLoad', metadata,
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("TotalLoad[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "AreaTypeCode",
                        name="unique_actual_total_load"
                    )
                )
            case 'AggregatedGenerationPerType':
                table = Table(
                    'AggregatedGenerationPerType', metadata,
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("ProductionType", String),
                    Column("ActualGenerationOutput[MW]", Float),
                    Column("ActualConsumption[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "ProductionType", "AreaTypeCode",
                        name="unique_agreegated_generation_type"
                    )
                )
            case 'CommercialSchedulesNetPositions':
                table = Table(
                    'CommercialSchedulesNetPositions', metadata,
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("MapCode", String),
                    Column("DayAheadCapacity[MW]", Float),
                    Column("DayAheadSchedulesDirection", String),
                    Column("TotalCapacity[MW]", Float),
                    Column("TotalSchedulesDirection", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "AreaTypeCode",
                        name="unique_comm_sched_net_pos"
                    )
                )
            case 'DayAheadAggregatedGeneration':
                table = Table(
                    'DayAheadAggregatedGeneration', metadata,
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaTypeCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaMapCode", String),
                    Column("GenerationForecast[MW]", Float),
                    Column("ScheduledConsumption[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "AreaDisplayName", "AreaTypeCode",
                        name="unique_day_ahead_agg_gen"
                    )
                )
            case 'GenerationForecastsForWindAndSolar':
                table = Table(
                    'GenerationForecastsForWindAndSolar', metadata,
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("ProductionType", String),
                    Column("DayAheadGenerationForecast[MW]", Float),
                    Column("IntradayGenerationForecast[MW]", Float),
                    Column("CurrentGenerationForecast[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "ProductionType", "AreaTypeCode",
                        name="unique_gen_forecast_wind_solar"
                    )
                )
            case 'DayAheadTotalLoadForecast':
                table = Table(
                    'DayAheadTotalLoadForecast', metadata,
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaTypeCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaMapCode", String),
                    Column("TotalLoad[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "AreaTypeCode",
                        name="unique_day_ahead_total_load_fore"
                    )
                )
            case 'EnergyPrices':
                table = Table(
                    'EnergyPrices', metadata,
                    Column("InstanceCode", String),
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("MapCode", String),
                    Column("ContractType", String),
                    Column("Sequence", String),
                    Column("Price[Currency/MWh]", Float),
                    Column("Currency", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "ResolutionCode", "AreaDisplayName",
                        "ContractType", "Sequence",
                        name="unique_energy_price"
                    )
                )
            case 'ExpansionAndDismantlingProjects':
                table = Table(
                    'ExpansionAndDismantlingProjects', metadata,
                    Column("InstanceCode", String),
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("OutAreaCode", String),
                    Column("OutAreaDisplayName", String),
                    Column("OutAreaTypeCode", String),
                    Column("OutAreaMapCode", String),
                    Column("InAreaCode", String),
                    Column("InAreaDisplayName", String),
                    Column("InAreaTypeCode", String),
                    Column("InAreaMapCode", String),
                    Column("ProjectType", String),
                    Column("AssetCode", String),
                    Column("AssetName", String),
                    Column("AssetLocation", String),
                    Column("AssetType", String),
                    Column("NewNTC[MW]", Float),
                    Column("EstimatedCompletionDate", String),
                    Column("Status", String),
                    Column("Comment", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "OutAreaDisplayName", "InAreaDisplayName", "ProjectType", "AssetCode", "EstimatedCompletionDate",
                        name="unique_expansion_dismantling_projects"
                    )
                )
            case 'ForecastedTransferCapacities':
                table = Table(
                    'ForecastedTransferCapacities', metadata,
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("OutAreaCode", String),
                    Column("OutAreaDisplayName", String),
                    Column("OutAreaTypeCode", String),
                    Column("OutMapCode", String),
                    Column("InAreaCode", String),
                    Column("InAreaDisplayName", String),
                    Column("InAreaTypeCode", String),
                    Column("InMapCode", String),
                    Column("ContractType", String),
                    Column("ForecastTransferCapacity[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "ResolutionCode", "OutAreaDisplayName",
                        "InAreaDisplayName", "ContractType",
                        name="unique_forecasted_transfer_capa"
                    )
                )
            case 'InstalledCapacityProductionUnit':
                table = Table(
                    'InstalledCapacityProductionUnit', metadata,
                    Column("EICCode", String),
                    Column("Name", String),
                    Column("ValidFrom", String),
                    Column("ValidTo", String),
                    Column("Status", String),
                    Column("Type", String),
                    Column("Location", String),
                    Column("InstalledCapacity", Float),
                    Column("ControlArea", String),
                    Column("BiddingZone", String),
                    Column("Voltage", Float),
                    UniqueConstraint(
                        "EICCode", "Name", "ValidFrom", "ValidTo", "Status", "Type", "Location",
                        name="unique_insta_capa_prod_unit"
                    )
                )

            case 'InstalledGenerationCapacityPerProductionUnit':
                table = Table(
                    'InstalledGenerationCapacityPerProductionUnit', metadata,
                    Column("ProductionUnitCode", String),
                    Column("ProductionUnitName", String),
                    Column("ValidFrom", DateTime(timezone=True)),
                    Column("ValidTo", DateTime(timezone=True)),
                    Column("Status", String),
                    Column("ProductionType", String),
                    Column("ProductionUnitLocation", String),
                    Column("InstalledCapacity(MW)", Float),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("VoltageLevel(kV)", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "ProductionUnitCode", "ValidFrom", "ValidTo", "ProductionType", "AreaCode", "AreaDisplayName", "AreaTypeCode",
                        name="unique_insta_capa_prod_unit"
                    )
                )
            case 'InstalledGenerationCapacityAggregated':
                table = Table(
                    'InstalledGenerationCapacityAggregated', metadata,
                    Column("Year", Float),
                    Column("TimeZone", String),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("ProductionType", String),
                    Column("AggregatedInstalledCapacity[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "Year", "ResolutionCode", "AreaDisplayName", "AreaTypeCode", "ProductionType",
                        name="unique_insta_gen_capa_aggr"
                    )
                )
            case 'PhysicalFlows':
                table = Table(
                    'PhysicalFlows', metadata,
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("OutAreaCode", String),
                    Column("OutAreaDisplayName", String),
                    Column("OutAreaTypeCode", String),
                    Column("OutAreaMapCode", String),
                    Column("InAreaCode", String),
                    Column("InAreaDisplayName", String),
                    Column("InAreaTypeCode", String),
                    Column("InAreaMapCode", String),
                    Column("Flow[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "ResolutionCode", "OutAreaDisplayName", "InAreaDisplayName",
                        name="unique_physical_flows"
                    )
                )
            case 'ProductionAndGenerationUnits':
                table = Table(
                    'ProductionAndGenerationUnits', metadata,
                    Column("ValidFrom", DateTime(timezone=True)),
                    Column("ValidTo", DateTime(timezone=True)),
                    Column("ProductionUnitCode", String),
                    Column("ProductionUnitName", String),
                    Column("ProductionUnitStatus", String),
                    Column("ProductionUnitType", String),
                    Column("ProductionUnitLocation", String),
                    Column("ProductionUnitInstalledCapacity(MW)", Float),
                    Column("ProductionUnitVoltage(kV)", Float),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("GenerationUnitCode", String),
                    Column("GenerationUnitName", String),
                    Column("GenerationUnitStatus", String),
                    Column("GenerationUnitType", String),
                    Column("GenerationUnitLocation", String),
                    Column("GenerationUnitInstalledCapacity(MW)", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "ProductionUnitCode", "GenerationUnitCode", "ValidFrom", "ValidTo", "AreaCode", "AreaDisplayName", "AreaTypeCode",
                        name="unique_prod_gen_units"
                    )
                )
            case 'PlannedUnavailabilityOfConsumptionUnits':
                table = Table(
                    'PlannedUnavailabilityOfConsumptionUnits', metadata,
                    Column("DateTime", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaTypeCode", String),
                    Column("AreaName", String),
                    Column("MapCode", String),
                    Column("UnavailableCapacity", Float),
                    Column("UpdateTime", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime", "ResolutionCode", "AreaCode", "AreaTypeCode", "AreaName", "MapCode",
                        name="unique_plam_unava_cons_units"
                    )
                )
            case 'TotalCapacityAlreadyAllocated':
                table = Table(
                    'TotalCapacityAlreadyAllocated', metadata,
                    Column("InstanceCode", String),
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("ContractType", String),
                    Column("Category", String),
                    Column("OutAreaCode", String),
                    Column("OutAreaDisplayName", String),
                    Column("OutAreaTypeCode", String),
                    Column("OutAreaMapCode", String),
                    Column("InAreaCode", String),
                    Column("InAreaDisplayName", String),
                    Column("InAreaTypeCode", String),
                    Column("InAreaMapCode", String),
                    Column("Capacity[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "InstanceCode", "DateTime(UTC)", "ResolutionCode", "ContractType", "Category", "OutAreaDisplayName", "InAreaDisplayName",
                        name="unique_total_capa_allocated"
                    )
                )
            case 'TotalCapacityNominated':
                table = Table(
                    'TotalCapacityNominated', metadata,
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("OutAreaCode", String),
                    Column("OutAreaDisplayName", String),
                    Column("OutAreaTypeCode", String),
                    Column("OutAreaMapCode", String),
                    Column("InAreaCode", String),
                    Column("InAreaDisplayName", String),
                    Column("InAreaTypeCode", String),
                    Column("InAreaMapCode", String),
                    Column("ContractType", String),
                    Column("Capacity[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "ResolutionCode", "OutAreaDisplayName", "InAreaDisplayName", "ContractType",
                        name="unique_total_capa_nominated"
                    )
                )
            case 'TotalLoadForecast':
                table = Table(
                    'TotalLoadForecast', metadata,
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("ContractType", String),
                    Column("MinimumLoadForecast[MW]", Float),
                    Column("MaximumLoadForecast[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "AreaTypeCode", "ContractType",
                        name="unique_total_load_forecast"
                    )
                )
            case 'TransmissionAssets':
                table = Table(
                    'TransmissionAssets', metadata,
                    Column("ValidFrom", DateTime(timezone=True)),
                    Column("ValidTo", DateTime(timezone=True)),
                    Column("AssetCode", String),
                    Column("AssetName", String),
                    Column("AssetStatus", String),
                    Column("AssetType", String),
                    Column("AssetLocation", String),
                    Column("LossFactor", Float),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("OrganizationCode", String),
                    Column("OrganizationName", String),
                    Column("MarketInformationDataProviderCodes", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "AssetCode", "ValidFrom", "ValidTo", "AreaCode", "AreaDisplayName", "AreaTypeCode",
                        name="unique_transmission_assets"
                    )
                )
            case 'UseOfTransferCapacity':
                table = Table(
                    'UseOfTransferCapacity', metadata,
                    Column("InstanceCode", String),
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("ContractType", String),
                    Column("Category", String),
                    Column("Sequence", String),
                    Column("OutAreaCode", String),
                    Column("OutAreaDisplayName", String),
                    Column("OutAreaTypeCode", String),
                    Column("OutAreaMapCode", String),
                    Column("InAreaCode", String),
                    Column("InAreaDisplayName", String),
                    Column("InAreaTypeCode", String),
                    Column("InAreaMapCode", String),
                    Column("AllocatedCapacity[MW]", Float),
                    Column("RequestedCapacity[MW]", Float),
                    Column("CapacityPrice[Currency/MWh]", Float),
                    Column("Currency", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "InstanceCode", "DateTime(UTC)", "ResolutionCode", "ContractType", "Category", "Sequence", "OutAreaDisplayName", "InAreaDisplayName",
                        name="unique_use_of_transfer_capacity"
                    )
                )
            case 'UnavailabilityInTheTransmissionGrid':
                table = Table(
                    'UnavailabilityInTheTransmissionGrid', metadata,
                    Column("InstanceCode", String),
                    Column("Version", Float),
                    Column("OldVersion", String),
                    Column("StartOutage(UTC)", DateTime(timezone=True)),
                    Column("EndOutage(UTC)", DateTime(timezone=True)),
                    Column("StartTimeSeries(UTC)", DateTime(timezone=True)),
                    Column("EndTimeSeries(UTC)", DateTime(timezone=True)),
                    Column("Status", String),
                    Column("Type", String),
                    Column("OutAreaCode", String),
                    Column("OutAreaDisplayName", String),
                    Column("OutAreaTypeCode", String),
                    Column("OutAreaMapCode", String),
                    Column("InAreaCode", String),
                    Column("InAreaDisplayName", String),
                    Column("InAreaTypeCode", String),
                    Column("InAreaMapCode", String),
                    Column("AffectedAssetsCodes", String),
                    Column("AffectedAssetsNames", String),
                    Column("AffectedAssetsTypes", String),
                    Column("AffectedAssetsLocations", String),
                    Column("NewNTC[MW]", Float),
                    Column("Reason", String),
                    Column("Comment", String),
                    Column("VersionPublicationTimestamp(UTC)", DateTime(timezone=True)),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "InstanceCode", "Version", "StartOutage(UTC)", "EndOutage(UTC)", "StartTimeSeries(UTC)", "EndTimeSeries(UTC)", "OutAreaCode", "InAreaCode", "Status", "Type",
                        name="unique_unava_trans_grid"
                    )
                )
            case 'UnavailabilityOfProductionAndGenerationUnits':
                table = Table(
                    'UnavailabilityOfProductionAndGenerationUnits', metadata,
                    Column("InstanceCode", String),
                    Column("Version", Float),
                    Column("OldVersion", String),  # Keep String for compatibility with the existing table.
                    Column("StartOutage(UTC)", DateTime(timezone=True)),
                    Column("EndOutage(UTC)", DateTime(timezone=True)),
                    Column("StartTimeSeries(UTC)", DateTime(timezone=True)),
                    Column("EndTimeSeries(UTC)", DateTime(timezone=True)),
                    Column("Status", String),
                    Column("Type", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("AssetCode", String),
                    Column("AssetName", String),
                    Column("AssetType", String),
                    Column("ProductionType", String),
                    Column("AvailableCapacity[MW]", Float),
                    Column("Reason", String),
                    Column("ReasonText", String),
                    Column("VersionPublicationTimestamp(UTC)", DateTime(timezone=True)),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "InstanceCode", "Version", "StartOutage(UTC)", "EndOutage(UTC)",
                        "StartTimeSeries(UTC)", "EndTimeSeries(UTC)",
                        "AssetCode", "Status", "Type",
                        name="unique_unava_prod_gen_units"
                    )
                )
            case 'UnavailabilityOfConsumptionUnits':
                table = Table(
                    'UnavailabilityOfConsumptionUnits', metadata,
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("PlannedUnavailableCapacity[MW]", Float),
                    Column("ActualUnavailableCapacity[MW]", Float),
                    Column("TotalUnavailableCapacity[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "AreaTypeCode",
                        name="unique_plam_unava_cons_units"
                    )
                )
            case 'UnavailabilityOfOffshoreGrid':
                table = Table(
                    'UnavailabilityOfOffshoreGrid', metadata,
                    Column("InstanceCode", String),
                    Column("Version", Float),
                    Column("OldVersion", String),
                    Column("StartOutage(UTC)", DateTime(timezone=True)),
                    Column("EndOutage(UTC)", DateTime(timezone=True)),
                    Column("StartTimeSeries(UTC)", DateTime(timezone=True)),
                    Column("EndTimeSeries(UTC)", DateTime(timezone=True)),
                    Column("Status", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("AssetCode", String),
                    Column("AssetName", String),
                    Column("AssetType", String),
                    Column("WindPowerFedIn[MW]", Float),
                    Column("InstalledWindPowerGenerationCapacity[MW]", Float),
                    Column("Reason", String),
                    Column("ReasonText", String),
                    Column("VersionPublicationTimestamp(UTC)", DateTime(timezone=True)),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "InstanceCode", "Version", "StartOutage(UTC)", "EndOutage(UTC)", "StartTimeSeries(UTC)", "EndTimeSeries(UTC)", "AssetCode", "Status",
                        name="unique_unava_offshore_grid"
                    )
                )
            case 'UnavailabilityOfGenerationUnits':
                table = Table(
                    'UnavailabilityOfGenerationUnits', metadata,
                    Column("StartOutage", DateTime(timezone=True)),
                    Column("EndOutage", DateTime(timezone=True)),
                    Column("StartTS", DateTime(timezone=True)),
                    Column("EndTS", DateTime(timezone=True)),
                    Column("TimeZone", String),
                    Column("MRID", String),
                    Column("Status", String),
                    Column("Type", String),
                    Column("AreaCode", String),
                    Column("AreaTypeCode", String),
                    Column("AreaName", String),
                    Column("MapCode", String),
                    Column("PowerResourceEIC", String),
                    Column("UnitName", String),
                    Column("ProductionType", String),
                    Column("InstalledCapacity", Float),
                    Column("AvailableCapacity", Float),
                    Column("Version", Float),
                    Column("OldVersion", String),
                    Column("Reason", String),
                    Column("UpdateTime", DateTime(timezone=True)),
                    UniqueConstraint(
                        "StartOutage", "EndOutage", "StartTS", "EndTS", "TimeZone", "MRID", "Status", "Type", "AreaCode",
                        "AreaTypeCode", "AreaName", "MapCode", "PowerResourceEIC", "UnitName", "ProductionType", "Version", "OldVersion",
                        name="unique_unava_gen_units"
                    )
                )
            case 'UnavailabilityOfGenerationUnitsReasons':
                table = Table(
                    'UnavailabilityOfGenerationUnitsReasons', metadata,
                    Column("StartTS", DateTime(timezone=True)),
                    Column("EndTS", DateTime(timezone=True)),
                    Column("MRID", String),
                    Column("Version", Float),
                    Column("OldVersion", String),
                    Column("ReasonCode", String),
                    Column("Reason", String),
                    Column("ReasonText", String),
                    Column("UpdateTime", DateTime(timezone=True)),
                    UniqueConstraint(
                        "StartTS", "EndTS", "MRID", "Version", "OldVersion", "ReasonCode",
                        name="unique_unava_gen_reason"
                    )
                )
            case 'UnavailabilityOfProductionUnits':
                table = Table(
                    'UnavailabilityOfProductionUnits', metadata,
                    Column("StartOutage", DateTime(timezone=True)),
                    Column("EndOutage", DateTime(timezone=True)),
                    Column("StartTS", DateTime(timezone=True)),
                    Column("EndTS", DateTime(timezone=True)),
                    Column("TimeZone", String),
                    Column("MRID", String),
                    Column("Status", String),
                    Column("Type", String),
                    Column("AreaCode", String),
                    Column("AreaTypeCode", String),
                    Column("AreaName", String),
                    Column("MapCode", String),
                    Column("PowerResourceEIC", String),
                    Column("UnitName", String),
                    Column("ProductionType", String),
                    Column("Version", Float),
                    Column("OldVersion", String),
                    Column("VoltageConnectionLevel", Float),
                    Column("InstalledCapacity", Float),
                    Column("AvailableCapacity", Float),
                    Column("Reason", String),
                    Column("UpdateTime", DateTime(timezone=True)),
                    UniqueConstraint(
                        "StartOutage", "EndOutage", "StartTS", "EndTS", "TimeZone", "MRID", "Status", "Type", "AreaCode",
                        "AreaTypeCode", "AreaName", "MapCode", "PowerResourceEIC", "UnitName", "ProductionType", "Version", "OldVersion",
                        name="unique_unava_pro_units"
                    )
                )
            case 'UnavailabilityOfProductionUnitsReasons':
                table = Table(
                    'UnavailabilityOfProductionUnitsReasons', metadata,
                    Column("StartTS", DateTime(timezone=True)),
                    Column("EndTS", DateTime(timezone=True)),
                    Column("MRID", String),
                    Column("Version", Float),
                    Column("OldVersion", String),
                    Column("ReasonCode", String),
                    Column("Reason", String),
                    Column("ReasonText", String),
                    Column("UpdateTime", DateTime(timezone=True)),
                    UniqueConstraint(
                        "StartTS", "EndTS", "MRID", "Version", "OldVersion", "ReasonCode",
                        name="unique_unava_pro_reasons"
                    )
                )
            case 'YearAheadForecastMargin':
                table = Table(
                    'YearAheadForecastMargin', metadata,
                    Column("Year", Float),
                    Column("TimeZone", String),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("ForecastMargin[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                    UniqueConstraint(
                        "Year", "ResolutionCode", "AreaDisplayName", "AreaTypeCode",
                        name="unique_year_ahead_forecast_margin"
                    )
                )

        if table is not None:
            try:
                metadata.create_all(self.engine, tables=[table])
                self.logger.info(f"Table '{table_name}' created successfully.")
                print(f"Table '{table_name}' created successfully.")
            except Exception as e:
                self.logger.error(f"Error creating table '{table_name}': {e}", exc_info=True)
        else:
            self.logger.error(f"No table definition found for '{table_name}'.")


    def run(self):
        """
        Main entry point invoked by the scheduler.
        It executes the complete crawling workflow.
        """

        local_dir = os.path.join("crawler", "data")
        end_time = pd.Timestamp.now(tz="Europe/Berlin")
        start_time = self._get_run_start_time(end_time)

        self.logger.info("Crawler run started.")
        if self.config.get("_scheduler_job_id"):
            self.logger.info("Scheduler job: %s", self.config["_scheduler_job_id"])
        if self.config.get("target_data_items"):
            self.logger.info(
                "Targeted FMS run enabled for: %s",
                ", ".join(self.config["target_data_items"]),
            )
        if self.config.get("fms_package_window_months") is not None:
            self.logger.info(
                "ENTSO-E FMS package refresh window starts at %s for %s month(s).",
                start_time,
                self.config.get("fms_package_window_months"),
            )
        else:
            self.logger.info("ENTSO-E FMS initial/default start date: %s", start_time)

        try:
            self.logger.info("Saving power system data...")
            self.save_power_system_data()

            self.logger.info("Starting ENTSO-E FMS fetch...")
            self.fetch_from_entsoe_fms_to_database(local_dir, start_time, end_time)

            self.logger.info("Crawler run finished successfully.")

        except Exception as e:
            self.logger.critical(f"Crawler run FAILED: {e}", exc_info=True)

    # ----------------------------------------------------------------------
    # Backward update: refresh a specific historical file period
    # ----------------------------------------------------------------------
    def backwards_update(self, start, end, local_dir, TARGET_FILES_DIR_index):
        """
        Batch update data for a specific type within a given monthly/yearly date range.
        """

        try:
            dir_path = self.TARGET_FILES_DIR[TARGET_FILES_DIR_index]
            data_item = dir_path.strip("/").split("/")[-1]
        except IndexError:
            self.logger.error(f"Backward update failed: Invalid TARGET_FILES_DIR_index: {TARGET_FILES_DIR_index}")
            return

        self.logger.info(f"Starting backward update for: {data_item} (Period: {start} to {end})")

        if data_item in self.SINGLE_FILE_DATA_ITEMS:
            self.logger.warning(f"Backward update is not supported for SINGLE-FILE table '{data_item}'.")
            self.logger.info(f"Processing the single file '{data_item}.csv' one time...")
            metadata_entries = self._load_backfill_metadata(data_item)
            if metadata_entries is None:
                return
            self._update_data_file(
                data_item,
                local_dir,
                file_identifier=None,
                logic_type="single",
                metadata_entries=metadata_entries,
            )
            return
        elif data_item in self.ANNUAL_FILE_DATA_ITEMS:
            loop_format = "%Y"
            date_offset = pd.DateOffset(years=1)
            self.logger.info("Detected ANNUAL file logic for backward update.")
        else:
            # The default case uses monthly files.
            loop_format = "%Y_%m"
            date_offset = pd.DateOffset(months=1)
            self.logger.info("Detected MONTHLY file logic for backward update.")

        try:
            backfill_periods = self._build_backfill_periods(start, end, loop_format, date_offset)
        except ValueError:
            self.logger.error(f"Invalid start/end format. Expected format '{loop_format}' for {data_item}, but got start='{start}' and end='{end}'.", exc_info=True)
            return

        if not backfill_periods:
            self.logger.warning(f"Backward update range is empty for {data_item}: {start} to {end}.")
            return

        metadata_entries = self._load_backfill_metadata(data_item)
        if metadata_entries is None:
            return

        for period_string in backfill_periods:
            self._update_data_file(
                data_item,
                local_dir,
                file_identifier=period_string,
                logic_type=loop_format,
                metadata_entries=metadata_entries,
            )

        self.logger.info(f"Backward update finished for {data_item}.")

    @staticmethod
    def _build_backfill_periods(start: str, end: str, loop_format: str, date_offset: pd.DateOffset) -> list[str]:
        start_dt = pd.to_datetime(start, format=loop_format)
        end_dt = pd.to_datetime(end, format=loop_format)

        periods = []
        dt = start_dt
        while dt <= end_dt:
            periods.append(dt.strftime(loop_format))
            dt += date_offset
        return periods

    def _load_backfill_metadata(self, data_item: str) -> list[Dict] | None:
        try:
            return self._list_metadata(data_item, pd.Timestamp("2000-01-01"), pd.Timestamp.now())
        except Exception as exc:
            self.logger.error(f"Backward update failed while listing metadata for {data_item}: {exc}", exc_info=True)
            return None

    def _update_data_file(
        self,
        data_item: str,
        local_dir: str,
        file_identifier: str | None,
        logic_type: str,
        metadata_entries: list[Dict] | None = None,
    ):
        """
        Helper for backwards_update. Downloads a specific file using the robust
        _list_metadata and _download_file methods, processes it, and flushes *only* old data.

        Args:
            data_item (str): The data item string (e.g., "ActualTotalLoad_6.1.A_r3").
            local_dir (str): Local directory to save temp file.
            file_identifier (str | None): The period string (e.g., "2024_01" or "2022") or None for "single" logic.
            logic_type (str): "%Y_%m", "%Y", or "single".
        """

        table_name = self._get_table_name_for_data_item(data_item)
        local_path = None

        try:
            self.logger.debug(f"[_update_data_file] Listing metadata for {data_item} to find file for period '{file_identifier}'...")

            all_metas = metadata_entries
            if all_metas is None:
                all_metas = self._list_metadata(data_item, pd.Timestamp("2000-01-01"), pd.Timestamp.now())

            target_meta = None
            if logic_type == "single":
                target_fname = f"{data_item}.csv"
                target_meta = next((m for m in all_metas if m["name"] == target_fname), None)
            else:
                target_meta = next((m for m in all_metas if m["name"].startswith(str(file_identifier))), None)

            if target_meta is None:
                self.logger.warning(f"[_update_data_file] No file found for {data_item} matching identifier '{file_identifier}'. Skipping period.")
                return

            fname = target_meta["name"]
            file_id = target_meta["fileId"]
            local_path = os.path.join(local_dir, fname)

            self.logger.info(f"Downloading (Backward Update): {fname}")
            self._download_file(file_id, local_path)
            df = pd.read_csv(local_path, encoding="utf-8-sig", sep="\t")

            if table_name == "InstalledCapacityProductionUnit":
                self.logger.info(f"[_update_data_file] Flushing (special case) {len(df)} rows for {table_name}")
                self._flush_to_database(table_name, pd.DataFrame(), df)
                return

            with self.engine.connect() as conn:
                table_exists_query = text(f"""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'entsoe_fms' AND table_name = '{table_name}'
                ) AS table_exists;
                """)
                result = conn.execute(table_exists_query).fetchone()
                if not (result and result[0]):
                    self.logger.error(f"[_update_data_file] Table '{table_name}' does not exist. Cannot run backward update.")
                    return

                column_query = text(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'entsoe_fms'
                AND table_name = '{table_name}' AND column_name ~* 'UpdateTime';
                """)
                result = conn.execute(column_query).fetchone()
                update_time_column = result[0] if result else None

                if not update_time_column:
                    self.logger.error(f"[_update_data_file] Could not find 'UpdateTime' column for '{table_name}'.")
                    return

                query = text(f"""
                SELECT MAX("{update_time_column}") AS last_update_time
                FROM "entsoe_fms"."{table_name}"
                """)
                result = conn.execute(query).fetchone()
                last_update_time = result[0] if result else None

            if last_update_time is None:
                self.logger.warning(f"[_update_data_file] Table '{table_name}' is empty (no last_update_time). Flushing all {len(df)} rows as update.")
                self._flush_to_database(table_name, pd.DataFrame(), df)
                return

            last_update_time = last_update_time.replace(tzinfo=None)
            df.loc[:, update_time_column] = pd.to_datetime(df[update_time_column])
            # Preserve the table's UpdateTime semantics so regular incremental runs keep working.
            df_update = df[df[update_time_column] <= last_update_time].copy()

            if not df_update.empty:
                self.logger.info(f"[_update_data_file] Flushing {len(df_update)} old records for {table_name} from file {fname}.")
                self._flush_to_database(table_name, pd.DataFrame(), df_update)
            else:
                self.logger.info(f"[_update_data_file] File {fname} contained no new backward-update data (older than {last_update_time}).")

        except Exception as e:
            self.logger.error(f"[_update_data_file] Failed during processing for identifier '{file_identifier}': {e}", exc_info=True)
        finally:
            if local_path and os.path.exists(local_path):
                os.remove(local_path)


    # ----------------------------------------------------------------------
    # Outlier Detection Method
    # ----------------------------------------------------------------------
    '''
    TABLE_CONFIG = {
        "ActualGenerationOutputPerGenerationUnit": {"identifiers": ["GenerationUnitName"], "value_columns": ["ActualGenerationOutput(MW)", "ActualConsumption(MW)", "GenerationUnitInstalledCapacity(MW)"], "time_column": "DateTime (UTC)"},
        "ActualTotalLoad": {"identifiers": ["AreaName"], "value_columns": ["TotalLoadValue"], "time_column": "DateTime"},
        "AggregatedGenerationPerType": {"identifiers": ["AreaName", "ProductionType"], "value_columns": ["ActualGenerationOutput", "ActualConsumption"], "time_column": "DateTime"},
        "DayAheadAggregatedGeneration": {"identifiers": ["AreaName"], "value_columns": ["ScheduledGeneration", "ScheduledConsumption"], "time_column": "DateTime"},
        "DayAheadGenerationForecastForWindAndSolar": {"identifiers": ["AreaName", "ProductionType"], "value_columns": ["AggregatedGenerationForecast"], "time_column": "DateTime"},
        "DayAheadTotalLoadForecast": {"identifiers": ["AreaName"], "value_columns": ["TotalLoadValue"], "time_column": "DateTime"},
        "IntradayGenerationForecastForWindAndSolar": {"identifiers": ["AreaName", "ProductionType"], "value_columns": ["AggregatedGenerationForecast"], "time_column": "DateTime"}
    }

    def detect_outliers_in_table(self, table_name: str, start_date: datetime, end_date: datetime, warmup_days: int = 7):
        """
        Detects outliers in a specified database table for a given time period.
        Automatically handles naive datetime inputs by assuming UTC.

        Args:
            table_name (str): The name of the database table to check.
            start_date (datetime): The start time of the detection period.
            end_date (datetime): The end time of the detection period.
            warmup_days (int): A warm-up period in days to provide context for the filter.
                            Data from this period will be fetched additionally.

        Returns:
            dict: A dictionary reporting the detection results.
                Keys are the group identifiers (e.g., 'Germany' or ('Germany', 'Wind')).
                Values are a list of column names where outliers were found for that group.
                Example: {'Germany': ['TotalLoadValue'], ('France', 'Solar'): []}
        """
        # --- Added Section ---
        # 1. Define the UTC timezone object
        utc_tz = pytz.utc

        # 2. Check start_date and localize to UTC if it's naive
        if start_date.tzinfo is None:
            print(f"  [INFO] start_date is timezone-naive. Localizing to UTC.")
            start_date = utc_tz.localize(start_date)

        # 3. Check end_date and localize to UTC if it's naive
        if end_date.tzinfo is None:
            print(f"  [INFO] end_date is timezone-naive. Localizing to UTC.")
            end_date = utc_tz.localize(end_date)
        # --- End of Added Section ---

        # --- Subsequent logic remains unchanged ---
        if table_name not in self.TABLE_CONFIG:
            print(f"ERROR: Configuration for table '{table_name}' not found in TABLE_CONFIG.")
            return {}

        config = self.TABLE_CONFIG[table_name]
        identifiers = config["identifiers"]
        value_columns = config["value_columns"]
        time_column = config["time_column"]

        query_start_date = start_date - timedelta(days=warmup_days)

        print(f"Fetching data from table '{table_name}' from {query_start_date} to {end_date}...")

        query = text(f'SELECT * FROM "{table_name}" WHERE "{time_column}" >= :start AND "{time_column}" < :end')

        try:
            df = pd.read_sql(query, self.engine, params={"start": query_start_date, "end": end_date})
        except Exception as e:
            print(f"Database query failed: {e}")
            return {}

        if df.empty:
            print(f"No data found for table '{table_name}' in the specified time period.")
            return {}

        df[time_column] = pd.to_datetime(df[time_column])

        results = {}
        grouped = df.groupby(identifiers)
        print(f"Data has been split into {len(grouped)} groups by {identifiers}. Starting detection...")

        for group_name, group_df in grouped:
            results[group_name] = []
            for value_col in value_columns:
                ts_data = group_df.set_index(time_column)[value_col].sort_index()
                ts_data = ts_data[~ts_data.index.duplicated(keep='first')]

                if ts_data.empty:
                    continue

                transformer = HampelFilter(window_length=24, return_bool=True)
                outlier_labels = transformer.fit_transform(ts_data)

                target_period_outliers = outlier_labels.loc[start_date:end_date]

                if target_period_outliers.any():
                    print(f"  -> Outlier found in group '{group_name}' for column '{value_col}'!")
                    results[group_name].append(value_col)

        print("Detection complete.")
        return results
    '''

def main(schema_name: str):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": "entsoe_fms",
    }
    print("Entsoe_fms crawler start")
    crawler = EntsoeFMSCrawler(schema_name, config)
    print("EntsoeFMSCrawler created")
    crawler.run()

    # backward update test
    # start = "2010-03"
    # end = "2025_07"
    # print("Start backwards updating")
    # crawler.backwards_update(start=start, end=end, local_dir=local_dir, TARGET_FILES_DIR_index=0)

    # outlier detector test
    # table_to_check = "ActualTotalLoad"
    # outlier_report = crawler.detect_outliers_in_table(table_to_check, start_time, end_time)
    # print(len(outlier_report))

if __name__ == "__main__":
    main("entsoe_fms")
