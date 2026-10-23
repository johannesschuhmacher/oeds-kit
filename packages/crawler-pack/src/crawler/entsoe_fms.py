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
import csv
import os
import re
import time
from typing import List, Dict

from dotenv import load_dotenv

import pandas as pd
import requests
from sqlalchemy import (
    text,
    Table,
    Column,
    String,
    Float,
    DateTime,
    Index,
    MetaData,
    UniqueConstraint,
)
from sqlalchemy.exc import IntegrityError
from entsoe.mappings import PSRTYPE_MAPPINGS, Area

from crawler.common.crawler_utils import build_session, copy_upsert
from crawler.common.kit_base import KitCrawler


# Data items are identified without their extract version (such as "_r3").
# At run time each one is resolved to the newest version available in the File
# Library, because ENTSO-E publishes new versions and removes the old folders.
FMS_ACTIVE_DATA_ITEMS = (
    ("AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants_16.1.D", "AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants"),
    ("ActualTotalLoad_6.1.A", "ActualTotalLoad"),
    ("DayAheadTotalLoadForecast_6.1.B", "DayAheadTotalLoadForecast"),
    ("ActualGenerationOutputPerGenerationUnit_16.1.A", "ActualGenerationOutputPerGenerationUnit"),
    ("AggregatedGenerationPerType_16.1.B_C", "AggregatedGenerationPerType"),
    ("CommercialSchedulesNetPositions_12.1.F", "CommercialSchedulesNetPositions"),
    ("DayAheadAggregatedGeneration_14.1.C", "DayAheadAggregatedGeneration"),
    ("GenerationForecastsForWindAndSolar_14.1.D", "GenerationForecastsForWindAndSolar"),
    ("EnergyPrices_12.1.D", "EnergyPrices"),
    ("ExpansionAndDismantlingProjects_9.1", "ExpansionAndDismantlingProjects"),
    ("ForecastedTransferCapacities_11.1", "ForecastedTransferCapacities"),
    ("InstalledGenerationCapacityPerProductionUnit_14.1.B", "InstalledGenerationCapacityPerProductionUnit"),
    ("InstalledGenerationCapacityAggregated_14.1.A", "InstalledGenerationCapacityAggregated"),
    ("PhysicalFlows_12.1.G", "PhysicalFlows"),
    ("ProductionAndGenerationUnits", "ProductionAndGenerationUnits"),
    ("TotalCapacityAlreadyAllocated_12.1.C", "TotalCapacityAlreadyAllocated"),
    ("TotalCapacityNominated_12.1.B", "TotalCapacityNominated"),
    ("TotalLoadForecast_6.1.C_D_E", "TotalLoadForecast"),
    ("TransmissionAssets", "TransmissionAssets"),
    ("UnavailabilityInTheTransmissionGrid_10.1.A_B", "UnavailabilityInTheTransmissionGrid"),
    ("UnavailabilityOfConsumptionUnits_7.1.A_B", "UnavailabilityOfConsumptionUnits"),
    ("UnavailabilityOfOffshoreGrid_10.1.C", "UnavailabilityOfOffshoreGrid"),
    ("UnavailabilityOfProductionAndGenerationUnits_15.1.A_B_C_D", "UnavailabilityOfProductionAndGenerationUnits"),
    ("UseOfTransferCapacity_12.1.A", "UseOfTransferCapacity"),
    ("YearAheadForecastMargin_8.1", "YearAheadForecastMargin"),
    ("ImplicitAllocationsNetPositions_12.1.E", "ImplicitAllocationsNetPositions"),
    ("CommercialSchedules_12.1.F", "CommercialSchedules"),
    ("RedispatchingInternal_13.1.A", "RedispatchingInternal"),
    ("RedispatchingCrossBorder_13.1.A", "RedispatchingCrossBorder"),
    ("Countertrading_13.1.B", "Countertrading"),
    ("CostsOfCongestionManagement_13.1.C", "CostsOfCongestionManagement"),
    ("ImbalancePrices_17.1.G", "ImbalancePrices"),
    ("TotalImbalanceVolumes_17.1.H", "TotalImbalanceVolumes"),
)

FMS_SINGLE_FILE_DATA_ITEMS = {
    "InstalledGenerationCapacityAggregated_14.1.A",
    "InstalledGenerationCapacityPerProductionUnit_14.1.B",
    "ProductionAndGenerationUnits",
    "TransmissionAssets",
    "YearAheadForecastMargin_8.1",
}

FMS_UNFILTERED_DATE_DATA_ITEMS = {
    *FMS_SINGLE_FILE_DATA_ITEMS,
    "AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants_16.1.D",
    "CostsOfCongestionManagement_13.1.C",
    "ExpansionAndDismantlingProjects_9.1",
}

FMS_ANNUAL_FILE_DATA_ITEMS = {
    "AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants_16.1.D",
    "CostsOfCongestionManagement_13.1.C",
    "ExpansionAndDismantlingProjects_9.1",
}

FMS_OUTAGE_DATA_ITEMS = {
    "UnavailabilityOfConsumptionUnits_7.1.A_B",
    "UnavailabilityOfProductionAndGenerationUnits_15.1.A_B_C_D",
}

FMS_FULL_UPSERT_TABLES = {
    "InstalledGenerationCapacityAggregated",
    "InstalledGenerationCapacityPerProductionUnit",
    "ProductionAndGenerationUnits",
    "TransmissionAssets",
    "UnavailabilityInTheTransmissionGrid",
    "UnavailabilityOfOffshoreGrid",
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
    "StartRedispatching(UTC)",
    "EndRedispatching(UTC)",
    "TimeIntervalFrom(UTC)",
    "TimeIntervalTo(UTC)",
    "ValidityPeriodStart(UTC)",
    "ValidityPeriodEnd(UTC)",
)

FMS_UPDATE_TIME_COLUMNS = (
    "UpdateTime",
    "UpdateTime (UTC)",
    "UpdateTime(UTC)",
)

# ENTSO-E's harmonised extracts (r3.1, October 2026) renamed these columns.
# Existing tables are migrated once with ALTER TABLE ... RENAME COLUMN.
FMS_COLUMN_RENAMES = {
    "CommercialSchedulesNetPositions": {"MapCode": "AreaMapCode"},
    "EnergyPrices": {"MapCode": "AreaMapCode"},
    "ForecastedTransferCapacities": {"OutMapCode": "OutAreaMapCode", "InMapCode": "InAreaMapCode"},
    "InstalledGenerationCapacityPerProductionUnit": {
        "ValidFrom": "ValidityPeriodStart(UTC)",
        "ValidTo": "ValidityPeriodEnd(UTC)",
        "InstalledCapacity(MW)": "InstalledCapacity[MW]",
        "VoltageLevel(kV)": "VoltageLevel[kV]",
    },
    "ProductionAndGenerationUnits": {
        "ValidFrom": "ValidityPeriodStart(UTC)",
        "ValidTo": "ValidityPeriodEnd(UTC)",
        "ProductionUnitInstalledCapacity(MW)": "ProductionUnitInstalledCapacity[MW]",
        "ProductionUnitVoltage(kV)": "ProductionUnitVoltage[kV]",
        "GenerationUnitInstalledCapacity(MW)": "GenerationUnitInstalledCapacity[MW]",
    },
    "TransmissionAssets": {"ValidFrom": "ValidityPeriodStart(UTC)", "ValidTo": "ValidityPeriodEnd(UTC)"},
    "UnavailabilityInTheTransmissionGrid": {
        "AffectedAssetsCodes": "AssetsCodes",
        "AffectedAssetsNames": "AssetsNames",
        "AffectedAssetsTypes": "AssetsTypes",
        "AffectedAssetsLocations": "AssetsLocations",
    },
    "UnavailabilityOfOffshoreGrid": {"ReasonText": "Comment"},
    "UnavailabilityOfProductionAndGenerationUnits": {"ReasonText": "Comment"},
}

# Unique keys of these tables contain columns that are often empty (an open
# ValidityPeriodEnd). Without NULLS NOT DISTINCT such rows never conflict and
# every refresh would insert them again.
FMS_NULLS_NOT_DISTINCT_TABLES = {
    "InstalledGenerationCapacityPerProductionUnit",
    "ProductionAndGenerationUnits",
    "TransmissionAssets",
}

FMS_VERSION_SUFFIX = re.compile(r"_r(\d+(?:\.\d+)*)$")


def base_data_item(name: str) -> str:
    """Strip the extract version: "EnergyPrices_12.1.D_r3.1" -> "EnergyPrices_12.1.D"."""
    return FMS_VERSION_SUFFIX.sub("", name)


def data_item_version(name: str) -> tuple[int, ...]:
    """Version of a File Library folder name; a folder without suffix sorts first."""
    match = FMS_VERSION_SUFFIX.search(name)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


DEFAULT_START_DATE = "2014-01-01"


class EntsoeFMSCrawler(KitCrawler):
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
        "UseOfTransferCapacity": "unique_use_of_transfer_capacity",
        "UnavailabilityOfProductionAndGenerationUnits": "unique_unava_prod_gen_units",
        "YearAheadForecastMargin": "unique_year_ahead_forecast_margin",
        "ImplicitAllocationsNetPositions": "unique_implicit_alloc_net_pos",
        "CommercialSchedules": "unique_comm_schedules",
        "RedispatchingInternal": "unique_redispatching_internal",
        "RedispatchingCrossBorder": "unique_redispatching_cross_border",
        "Countertrading": "unique_countertrading",
        "CostsOfCongestionManagement": "unique_costs_congestion_mgmt",
        "ImbalancePrices": "unique_imbalance_prices",
        "TotalImbalanceVolumes": "unique_total_imbalance_volumes",
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
        "InstalledGenerationCapacityAggregated": [
            "Year", "ResolutionCode", "AreaDisplayName", "AreaTypeCode", "ProductionType"
        ],
        "ForecastedTransferCapacities": [
            "DateTime(UTC)", "ResolutionCode", "OutAreaDisplayName",
            "InAreaDisplayName", "ContractType"
        ],
        "InstalledGenerationCapacityPerProductionUnit": [
            "ProductionUnitCode", "ValidityPeriodStart(UTC)", "ValidityPeriodEnd(UTC)", "ProductionType",
            "AreaCode", "AreaDisplayName", "AreaTypeCode"
        ],
        "PhysicalFlows": [
            "DateTime(UTC)", "ResolutionCode", "OutAreaDisplayName", "InAreaDisplayName"
        ],
        "ProductionAndGenerationUnits": [
            "ProductionUnitCode", "GenerationUnitCode", "ValidityPeriodStart(UTC)", "ValidityPeriodEnd(UTC)", "AreaCode", "AreaDisplayName", "AreaTypeCode"
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
            "AssetCode", "ValidityPeriodStart(UTC)", "ValidityPeriodEnd(UTC)", "AreaCode", "AreaDisplayName", "AreaTypeCode"
        ],
        "UseOfTransferCapacity": [
            "InstanceCode", "DateTime(UTC)", "ResolutionCode", "ContractType", "Category", "Sequence", "OutAreaDisplayName", "InAreaDisplayName"
        ],
        "GenerationForecastsForWindAndSolar": [
            "DateTime(UTC)", "ResolutionCode", "AreaDisplayName", "ProductionType", "AreaTypeCode"
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
        "UnavailabilityOfProductionAndGenerationUnits": [
            "InstanceCode", "Version", "StartOutage(UTC)", "EndOutage(UTC)",
            "StartTimeSeries(UTC)", "EndTimeSeries(UTC)",
            "AssetCode", "Status", "Type"
        ],
        "YearAheadForecastMargin": [
            "Year", "ResolutionCode", "AreaDisplayName", "AreaTypeCode"
        ],
        "ImplicitAllocationsNetPositions": [
            "DateTime(UTC)", "ResolutionCode", "AreaCode", "AreaTypeCode", "ContractType"
        ],
        "CommercialSchedules": [
            "DateTime(UTC)", "ResolutionCode", "OutAreaCode", "InAreaCode"
        ],
        "RedispatchingInternal": [
            "InstanceCode", "StartTimeSeries(UTC)", "EndTimeSeries(UTC)", "AssetCode", "ActionType", "ActionDirection"
        ],
        "RedispatchingCrossBorder": [
            "InstanceCode", "StartTimeSeries(UTC)", "EndTimeSeries(UTC)", "AssetCode",
            "OutAreaCode", "InAreaCode", "ActionType", "ActionDirection"
        ],
        "Countertrading": [
            "InstanceCode", "StartTimeSeries(UTC)", "EndTimeSeries(UTC)", "OutAreaCode", "InAreaCode"
        ],
        "CostsOfCongestionManagement": [
            "Year", "Month", "AreaCode", "AreaTypeCode"
        ],
        "ImbalancePrices": [
            "DateTime(UTC)", "ResolutionCode", "AreaCode", "AreaTypeCode"
        ],
        "TotalImbalanceVolumes": [
            "DateTime(UTC)", "ResolutionCode", "AreaCode", "AreaTypeCode"
        ],
    }

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------
    def __init__(self, crawler_name: str, config: dict):
        super().__init__(crawler_name, config)
        self._access_token: str | None = None
        self.session: requests.Session | None = None
        self._available_folders: list[str] | None = None
        # Per-run caches: reflected tables for the upsert statement, the column set
        # of the table currently being loaded (reset per file) and the tables whose
        # UpdateTime index has been checked.
        self._reflected_tables: dict[str, Table] = {}
        self._known_columns: dict[str, set[str]] = {}
        self._update_time_index_checked: set[str] = set()
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
    # Constant endpoints and paths
    # ---------------------------
    TOKEN_URL = "https://keycloak.tp.entsoe.eu/realms/tp/protocol/openid-connect/token"
    CLIENT_ID = "tp-fms-public"
    FMS_BASEURL = "https://fms.tp.entsoe.eu"

    def _authenticate(self) -> None:
        """Fetch an OAuth2 access token and initialize the retry-enabled session."""

        # Credentials come from the environment or a local dotenv file.
        load_dotenv()
        username = os.getenv("ENTSOE_USERNAME")
        password = os.getenv("ENTSOE_PASSWORD")
        if not username or not password:
            print("Error: ENTSOE_USERNAME or ENTSOE_PASSWORD is not set in .env")

        payload = (
            f"client_id={self.CLIENT_ID}"
            f"&grant_type=password"
            f"&username={username}"
            f"&password={password}"
        )

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        response = requests.post(self.TOKEN_URL, headers=headers, data=payload, timeout=120)
        response.raise_for_status()

        self._access_token = response.json().get("access_token")

        self.session = build_session(retries=5, backoff_factor=2)
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }
        )
        self.logger.info("FMS Token received and session established.")

    # ---------------------------
    # File‑Library Helpers
    # ---------------------------
    def _list_folder(self, path: str) -> List[Dict]:
        payload = {
            "topLevelFolder": "TP_export",
            "path": path,
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
                    self.logger.warning(f"Access Token expired during listFolder for {path}. Re-authenticating...")
                    self._authenticate()
                    self.logger.info("Re-authentication successful. Retrying listFolder...")
                    r = self.session.post(f"{self.FMS_BASEURL}/listFolder", json=payload, timeout=120)
                    r.raise_for_status()
                else:
                    self.logger.error(f"HTTP error in listFolder for {path}: {exc}")
                    raise exc
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Network error (e.g., Timeout) in listFolder for {path}: {e}")
                raise e

            data = r.json()
            metas = data.get("contentItemList", [])
            if not metas:
                break
            all_metas.extend(metas)
            payload["pageInfo"]["pageIndex"] += 1

        return all_metas

    def _resolve_folder(self, data_item: str) -> str:
        """Return the newest File Library folder of a data item, e.g. "_r3.2" before "_r3.1"."""
        if getattr(self, "_available_folders", None) is None:
            self._available_folders = [
                meta["name"] for meta in self._list_folder("/TP_export/") if meta.get("name")
            ]
        base = base_data_item(data_item)
        candidates = [name for name in self._available_folders if base_data_item(name) == base]
        if not candidates:
            raise LookupError(f"No File Library folder found for data item '{base}'.")
        folder = max(candidates, key=data_item_version)
        self.logger.info("Data item %s uses File Library folder %s.", base, folder)
        return folder

    def _list_metadata(self, data_item: str, start: pd.Timestamp, end: pd.Timestamp) -> List[Dict]:
        return self._list_folder(f"/TP_export/{self._resolve_folder(data_item)}/")

    def _download_file(self, fileid: str, target: str) -> None:
        payload = {
            "fileIdList": [
                f"{fileid}"
            ],
            "topLevelFolder": "TP_export",
            "downloadAsZip": False,
        }
        # Stream the body to disk; monthly extracts reach hundreds of MB.
        try:
            r = self.session.post(f"{self.FMS_BASEURL}/downloadFileContent", json=payload, timeout=120, stream=True)
            r.raise_for_status()
        except requests.HTTPError as exc:
            # Re-authenticate when the current access token has expired.
            if exc.response.status_code == 401:
                self.logger.warning("Access Token expired. Re-authenticating")

                self.logger.warning("Re-authenticating")

                # Refresh the access token and retry the download.
                self._authenticate()
                self.logger.info("Re-authentication successful. Retrying download for %s...", target)

                r = self.session.post(f"{self.FMS_BASEURL}/downloadFileContent", json=payload, timeout=120, stream=True)
                r.raise_for_status()
            else:
                raise exc

        with r, open(target, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)

    def _get_target_data_items(self) -> List[str]:
        target_data_items = self.config.get("target_data_items")
        if not target_data_items:
            return list(self.DATA_ITEM_TABLE_MAP)

        # Older configurations name versioned folders such as "EnergyPrices_12.1.D_r3".
        requested = {base_data_item(item) for item in target_data_items}
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
        return self.DATA_ITEM_TABLE_MAP[base_data_item(data_item)]

    @staticmethod
    def _should_process_metadata_entry(meta: Dict) -> bool:
        name = meta.get("name", "")
        return isinstance(name, str) and name.lower().endswith(".csv")

    @classmethod
    def _should_skip_date_filter(cls, data_item: str) -> bool:
        return base_data_item(data_item) in cls.UNFILTERED_DATE_DATA_ITEMS

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

    def _get_table_state(self, table_name: str, include_watermarks: bool = True) -> dict:
        """Table existence and column names; with include_watermarks also MAX(UpdateTime)/MAX(DateTime).

        The MAX queries scan the whole table, so callers that only need to know whether
        the table exists (package-refresh mode, right after creating it) skip them.
        """
        state = {
            "table_exists": False,
            "update_time_column": None,
            "datetime_column_name": None,
            "last_update_time": None,
            "last_date_time": None,
        }

        columns = self._table_columns(table_name)
        if not columns:
            return state
        state["table_exists"] = True
        # First match in column order, case-insensitive like the former "~*" queries.
        # "DateTime" also matches "UpdateTime(UTC)" in tables without a DateTime column.
        state["update_time_column"] = next((c for c in columns if "updatetime" in c.lower()), None)
        state["datetime_column_name"] = next((c for c in columns if "datetime" in c.lower()), None)

        if not include_watermarks:
            return state
        with self.engine.connect() as conn:
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

    def _table_columns(self, table_name: str) -> list[str]:
        with self.engine.connect() as conn:
            return [
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'entsoe_fms' AND table_name = :table_name "
                        "ORDER BY ordinal_position"
                    ),
                    {"table_name": table_name},
                )
            ]

    def _migrate_renamed_columns(self, table_name: str) -> None:
        """Rename columns of an existing table to ENTSO-E's current names, keeping the data."""
        renames = FMS_COLUMN_RENAMES.get(table_name)
        if not renames:
            return
        columns = set(self._table_columns(table_name))
        with self.engine.begin() as conn:
            for old, new in renames.items():
                if old in columns and new not in columns:
                    conn.execute(text(f'ALTER TABLE "entsoe_fms"."{table_name}" RENAME COLUMN "{old}" TO "{new}"'))
                    self.logger.info("Renamed column %s.%s to %s.", table_name, old, new)
                    self._known_columns.pop(table_name, None)
                    self._reflected_tables.pop(table_name, None)

    @staticmethod
    def _update_time_index_name(table_name: str) -> str:
        # PostgreSQL truncates identifiers to 63 bytes; truncate here so the
        # name matches on repeated IF NOT EXISTS checks.
        return f"ix_{table_name}_updatetime"[:63]

    def _ensure_update_time_index(self, table_name: str) -> None:
        """Index "UpdateTime(UTC)" of an existing table once per run.

        MAX("UpdateTime(UTC)") (incremental watermark) and the gapfill change
        detection otherwise scan the whole table.
        """
        if table_name in self._update_time_index_checked:
            return
        self._update_time_index_checked.add(table_name)
        if "UpdateTime(UTC)" not in self._table_columns(table_name):
            return
        index_name = self._update_time_index_name(table_name)
        with self.engine.begin() as conn:
            exists = conn.execute(
                text("SELECT to_regclass(:name)"), {"name": f'"entsoe_fms"."{index_name}"'}
            ).scalar()
            if exists:
                return
            self.logger.info("Creating index %s on %s; this takes a while on large tables.", index_name, table_name)
            started = time.monotonic()
            conn.execute(
                text(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "entsoe_fms"."{table_name}" ("UpdateTime(UTC)")')
            )
        self.logger.info("Index %s created in %.0f s.", index_name, time.monotonic() - started)

    def _ensure_nulls_not_distinct(self, table_name: str) -> None:
        """Recreate the unique constraint of an existing table with NULLS NOT DISTINCT."""
        if table_name not in FMS_NULLS_NOT_DISTINCT_TABLES:
            return
        constraint = self.UNIQUE_KEY_DICT[table_name]
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT i.indnullsnotdistinct FROM pg_constraint c "
                    "JOIN pg_index i ON i.indexrelid = c.conindid "
                    "WHERE c.conrelid = to_regclass(:table) AND c.conname = :constraint"
                ),
                {"table": f'"entsoe_fms"."{table_name}"', "constraint": constraint},
            ).fetchone()
            if row is None or row[0]:
                return
            columns = ", ".join(f'"{col}"' for col in self.UNIQUE_KEY_COLUMNS[table_name])
            conn.execute(
                text(
                    f'ALTER TABLE "entsoe_fms"."{table_name}" DROP CONSTRAINT "{constraint}", '
                    f'ADD CONSTRAINT "{constraint}" UNIQUE NULLS NOT DISTINCT ({columns})'
                )
            )
        self.logger.info("Unique constraint %s of %s now treats NULLs as equal.", constraint, table_name)

    def _add_missing_columns(self, table_name: str, df: pd.DataFrame) -> None:
        """Add columns that ENTSO-E introduced after the table was created.

        The column set is cached in self._known_columns (callers reset it per file),
        so information_schema is not queried for every chunk.
        """
        existing = self._known_columns.get(table_name)
        if existing is None:
            existing = set(self._table_columns(table_name))
            self._known_columns[table_name] = existing
        missing = [col for col in df.columns if col not in existing]
        if not missing:
            return
        with self.engine.begin() as conn:
            for col in missing:
                if pd.api.types.is_datetime64_any_dtype(df[col]):
                    sql_type = "TIMESTAMP WITH TIME ZONE"
                elif pd.api.types.is_numeric_dtype(df[col]):
                    sql_type = "DOUBLE PRECISION"
                else:
                    sql_type = "TEXT"
                conn.execute(text(f'ALTER TABLE "entsoe_fms"."{table_name}" ADD COLUMN IF NOT EXISTS "{col}" {sql_type}'))
                self.logger.info("Added column %s.%s (%s).", table_name, col, sql_type)
                existing.add(col)
        self._reflected_tables.pop(table_name, None)

    @staticmethod
    def _normalize_timestamp_columns(df: pd.DataFrame) -> pd.DataFrame:
        for col_name in FMS_DATETIME_COLUMNS + FMS_UPDATE_TIME_COLUMNS:
            if col_name in df.columns:
                try:
                    # ENTSO-E writes "YYYY-MM-DD HH:MM:SS[.fff]"; the vectorised ISO
                    # parser is much faster than per-value "mixed" parsing.
                    df[col_name] = pd.to_datetime(df[col_name], format="ISO8601")
                except (ValueError, TypeError):
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

        update_time_column = next((col for col in FMS_UPDATE_TIME_COLUMNS if col in df.columns), None)
        if update_time_column:
            df = df.sort_values(update_time_column, kind="stable")

        return df.drop_duplicates(
            subset=self.UNIQUE_KEY_COLUMNS[table_name],
            keep="last",
        )

    def _upsert_dataframe(self, table_name: str, df: pd.DataFrame) -> None:
        """Upsert a dataframe into the target table with COPY (see copy_upsert)."""
        if df.empty:
            return

        df = self._deduplicate_on_unique_keys(table_name, df)
        table_obj = self._reflected_table(table_name)

        # Only rewrite a row when the file carries a newer UpdateTime; the hourly
        # package refresh re-upserts the whole month and would otherwise rewrite
        # every unchanged row (WAL and bloat). Rows whose stored UpdateTime is NULL
        # are always updated.
        update_time_column = next(
            (col for col in FMS_UPDATE_TIME_COLUMNS if col in table_obj.c and col in df.columns), None
        )
        where = None
        if update_time_column:
            stored = f'"entsoe_fms"."{table_name}"."{update_time_column}"'
            where = f'{stored} IS NULL OR {stored} < EXCLUDED."{update_time_column}"'
        copy_upsert(
            self.engine, table_obj, df, self.UNIQUE_KEY_DICT[table_name], self.UNIQUE_KEY_COLUMNS[table_name], where
        )

    def _reflected_table(self, table_name: str) -> Table:
        """Reflect the table once per run; _add_missing_columns and renames invalidate it."""
        table_obj = self._reflected_tables.get(table_name)
        if table_obj is None:
            table_obj = Table(table_name, MetaData(), autoload_with=self.engine, schema="entsoe_fms")
            self._reflected_tables[table_name] = table_obj
        return table_obj

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
            df = df[temp_update > last_update_time]

        if df.empty:
            return pd.DataFrame(), pd.DataFrame()

        if table_name == "InstalledGenerationCapacityAggregated":
            df["Year"] = pd.to_numeric(df["Year"])
            return pd.DataFrame(), df

        if table_name in self.FULL_UPSERT_TABLES:
            return pd.DataFrame(), df

        if datetime_column_name and datetime_column_name in df.columns and last_date_time:
            temp_date = df[datetime_column_name].dt.tz_localize(None)
            df_update = df[temp_date <= last_date_time]
            df_insert = df[temp_date > last_date_time]
            return df_insert, df_update

        return pd.DataFrame(), df

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

        # Authenticate with ENTSO-E and list the current folder versions once per run.
        self._authenticate()
        self._available_folders = None

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
            table_name = self._get_table_name_for_data_item(data_item)

            print(f"\n--- Processing data item: {data_item} ---")
            self.logger.info("Starting processing for data item %s -> table %s", data_item, table_name)

            try:
                self._migrate_renamed_columns(table_name)
                self._ensure_nulls_not_distinct(table_name)
                self._ensure_update_time_index(table_name)
            except Exception as exc:
                self.logger.error(f"Column migration failed for {table_name}: {exc}", exc_info=True)
                failures.append(f"{data_item}: column migration")
                continue

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
            # The watermark is read once per data item. Re-reading it after every file
            # would drop rows of the next file whose UpdateTime lies below the new maximum.
            effective_start_time = start_time
            try:
                table_state = self._get_table_state(table_name, include_watermarks=not full_package_upsert)
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
                self.logger.error(f"Pre-check failed for {table_name}: {e}", exc_info=True)
                failures.append(f"{data_item}: pre-check")
                continue

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
                    if not table_state["table_exists"]:
                        create = True
                        if not do_not_create_again:
                            self.logger.info("Table '%s' not found, creating it.", table_name)
                            self._create_table_with_unique_constraint(table_name)
                            do_not_create_again = True
                            table_state = self._get_table_state(table_name, include_watermarks=False)

                    chunk_size = 50000
                    total_file_inserts = 0
                    total_file_updates = 0
                    # Column set is re-read once per file (see _add_missing_columns).
                    self._known_columns.pop(table_name, None)

                    # Plain "\t" keeps the fast C parser; the previous regex separator
                    # forced the Python engine. QUOTE_NONE: ENTSO-E's TSV is unquoted.
                    with pd.read_csv(local_path, sep="\t", quoting=csv.QUOTE_NONE, chunksize=chunk_size) as reader:
                        for chunk_idx, df in enumerate(reader):
                            df.columns = df.columns.str.strip()
                            df = self._normalize_timestamp_columns(df)
                            self._add_missing_columns(table_name, df)

                            # _insert_dataframe and _upsert_dataframe drop duplicate keys themselves.
                            if create:
                                print(f"    Processing chunk {chunk_idx+1}: Inserting {len(df)} rows...")
                                total_file_inserts += len(df)
                                self._insert_dataframe(table_name, df)

                            elif full_package_upsert:
                                print(f"    Processing chunk {chunk_idx+1}: 0 new inserts, {len(df)} package upserts.")
                                self._flush_to_database(table_name, pd.DataFrame(), df)
                                total_file_updates += len(df)

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

    def _create_table_with_unique_constraint(self, table_name):
        """Create the table with its unique constraint (UNIQUE_KEY_DICT/UNIQUE_KEY_COLUMNS)."""
        match table_name:
            case 'AggregatedFillingRateOfWaterReservoirsAndHydroStoragePlants':
                columns = [
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
                ]
            case 'ActualGenerationOutputPerGenerationUnit':
                columns = [
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
                ]
            case 'ActualTotalLoad':
                columns = [
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("TotalLoad[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'AggregatedGenerationPerType':
                columns = [
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
                ]
            case 'CommercialSchedulesNetPositions':
                columns = [
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("DayAheadCapacity[MW]", Float),
                    Column("DayAheadSchedulesDirection", String),
                    Column("TotalCapacity[MW]", Float),
                    Column("TotalSchedulesDirection", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'DayAheadAggregatedGeneration':
                columns = [
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaTypeCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaMapCode", String),
                    Column("GenerationForecast[MW]", Float),
                    Column("ScheduledConsumption[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'GenerationForecastsForWindAndSolar':
                columns = [
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
                ]
            case 'DayAheadTotalLoadForecast':
                columns = [
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaTypeCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaMapCode", String),
                    Column("TotalLoad[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'EnergyPrices':
                columns = [
                    Column("InstanceCode", String),
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("ContractType", String),
                    Column("Sequence", String),
                    Column("Price[Currency/MWh]", Float),
                    Column("Currency", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'ExpansionAndDismantlingProjects':
                columns = [
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
                ]
            case 'ForecastedTransferCapacities':
                columns = [
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
                    Column("ForecastTransferCapacity[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'InstalledGenerationCapacityPerProductionUnit':
                columns = [
                    Column("ProductionUnitCode", String),
                    Column("ProductionUnitName", String),
                    Column("ValidityPeriodStart(UTC)", DateTime(timezone=True)),
                    Column("ValidityPeriodEnd(UTC)", DateTime(timezone=True)),
                    Column("Status", String),
                    Column("ProductionType", String),
                    Column("ProductionUnitLocation", String),
                    Column("InstalledCapacity[MW]", Float),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("VoltageLevel[kV]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'InstalledGenerationCapacityAggregated':
                columns = [
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
                ]
            case 'PhysicalFlows':
                columns = [
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
                ]
            case 'ProductionAndGenerationUnits':
                columns = [
                    Column("ValidityPeriodStart(UTC)", DateTime(timezone=True)),
                    Column("ValidityPeriodEnd(UTC)", DateTime(timezone=True)),
                    Column("ProductionUnitCode", String),
                    Column("ProductionUnitName", String),
                    Column("ProductionUnitStatus", String),
                    Column("ProductionUnitType", String),
                    Column("ProductionUnitLocation", String),
                    Column("ProductionUnitInstalledCapacity[MW]", Float),
                    Column("ProductionUnitVoltage[kV]", Float),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("GenerationUnitCode", String),
                    Column("GenerationUnitName", String),
                    Column("GenerationUnitStatus", String),
                    Column("GenerationUnitType", String),
                    Column("GenerationUnitLocation", String),
                    Column("GenerationUnitInstalledCapacity[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'TotalCapacityAlreadyAllocated':
                columns = [
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
                ]
            case 'TotalCapacityNominated':
                columns = [
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
                ]
            case 'TotalLoadForecast':
                columns = [
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
                ]
            case 'TransmissionAssets':
                columns = [
                    Column("ValidityPeriodStart(UTC)", DateTime(timezone=True)),
                    Column("ValidityPeriodEnd(UTC)", DateTime(timezone=True)),
                    Column("AssetCode", String),
                    Column("AssetName", String),
                    Column("AssetStatus", String),
                    Column("AssetType", String),
                    Column("AssetLocation", String),
                    Column("InstalledCapacity[MW]", Float),
                    Column("LossFactor", Float),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("OrganizationCode", String),
                    Column("OrganizationName", String),
                    Column("MarketInformationDataProviderCodes", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'UseOfTransferCapacity':
                columns = [
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
                ]
            case 'UnavailabilityInTheTransmissionGrid':
                columns = [
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
                    Column("AssetsCodes", String),
                    Column("AssetsNames", String),
                    Column("AssetsTypes", String),
                    Column("AssetsLocations", String),
                    Column("NewNTC[MW]", Float),
                    Column("Reason", String),
                    Column("Comment", String),
                    Column("VersionPublicationTimestamp(UTC)", DateTime(timezone=True)),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'UnavailabilityOfProductionAndGenerationUnits':
                columns = [
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
                    Column("Comment", String),
                    Column("VersionPublicationTimestamp(UTC)", DateTime(timezone=True)),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'UnavailabilityOfConsumptionUnits':
                columns = [
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
                ]
            case 'UnavailabilityOfOffshoreGrid':
                columns = [
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
                    Column("Comment", String),
                    Column("VersionPublicationTimestamp(UTC)", DateTime(timezone=True)),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'YearAheadForecastMargin':
                columns = [
                    Column("Year", Float),
                    Column("TimeZone", String),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("ForecastMargin[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'ImplicitAllocationsNetPositions':
                columns = [
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("ContractType", String),
                    Column("NetPosition[MW]", Float),
                    Column("Direction", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'CommercialSchedules':
                columns = [
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
                    Column("DayAheadCapacity[MW]", Float),
                    Column("TotalCapacity[MW]", Float),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'RedispatchingInternal':
                columns = [
                    Column("InstanceCode", String),
                    Column("StartRedispatching(UTC)", DateTime(timezone=True)),
                    Column("EndRedispatching(UTC)", DateTime(timezone=True)),
                    Column("StartTimeSeries(UTC)", DateTime(timezone=True)),
                    Column("EndTimeSeries(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("AssetCode", String),
                    Column("AssetName", String),
                    Column("AssetType", String),
                    Column("AssetLocation", String),
                    Column("ConnectingMarketParticipantCode", String),
                    Column("ConnectingMarketParticipantName", String),
                    Column("CapacityImpact[MWh/MTU]", Float),
                    Column("ActionType", String),
                    Column("ActionDirection", String),
                    Column("Reason", String),
                    Column("Comment", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'RedispatchingCrossBorder':
                columns = [
                    Column("InstanceCode", String),
                    Column("StartRedispatching(UTC)", DateTime(timezone=True)),
                    Column("EndRedispatching(UTC)", DateTime(timezone=True)),
                    Column("StartTimeSeries(UTC)", DateTime(timezone=True)),
                    Column("EndTimeSeries(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("OutAreaCode", String),
                    Column("OutAreaDisplayName", String),
                    Column("OutAreaTypeCode", String),
                    Column("OutAreaMapCode", String),
                    Column("InAreaCode", String),
                    Column("InAreaDisplayName", String),
                    Column("InAreaTypeCode", String),
                    Column("InAreaMapCode", String),
                    Column("AssetCode", String),
                    Column("AssetName", String),
                    Column("AssetType", String),
                    Column("AssetLocation", String),
                    Column("ConnectingMarketParticipantCode", String),
                    Column("ConnectingMarketParticipantName", String),
                    Column("CapacityImpact[MWh/MTU]", Float),
                    Column("ActionType", String),
                    Column("ActionDirection", String),
                    Column("Reason", String),
                    Column("Comment", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'Countertrading':
                columns = [
                    Column("InstanceCode", String),
                    Column("TimeIntervalFrom(UTC)", DateTime(timezone=True)),
                    Column("TimeIntervalTo(UTC)", DateTime(timezone=True)),
                    Column("StartTimeSeries(UTC)", DateTime(timezone=True)),
                    Column("EndTimeSeries(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("OutAreaCode", String),
                    Column("OutAreaDisplayName", String),
                    Column("OutAreaTypeCode", String),
                    Column("OutAreaMapCode", String),
                    Column("InAreaCode", String),
                    Column("InAreaDisplayName", String),
                    Column("InAreaTypeCode", String),
                    Column("InAreaMapCode", String),
                    Column("ConnectingMarketParticipantCode", String),
                    Column("ConnectingMarketParticipantName", String),
                    Column("Action", String),
                    Column("ChangeInCrossBorderExchange[MW]", Float),
                    Column("Reason", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'CostsOfCongestionManagement':
                columns = [
                    Column("Year", Float),
                    Column("Month", Float),
                    Column("TimeZone", String),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("RedispatchingCosts", Float),
                    Column("CountertradingCosts", Float),
                    Column("OtherCosts", Float),
                    Column("TotalCosts", Float),
                    Column("Currency", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'ImbalancePrices':
                columns = [
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("PositiveImbalancePrice[Currency/MWh]", Float),
                    Column("PositiveScarcity[Currency/MWh]", Float),
                    Column("PositiveIncentive[Currency/MWh]", Float),
                    Column("PositiveFinancialNeutrality[Currency/MWh]", Float),
                    Column("NegativeImbalancePrice[Currency/MWh]", Float),
                    Column("NegativeScarcity[Currency/MWh]", Float),
                    Column("NegativeIncentive[Currency/MWh]", Float),
                    Column("NegativeFinancialNeutrality[Currency/MWh]", Float),
                    Column("Currency", String),
                    Column("Status", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case 'TotalImbalanceVolumes':
                columns = [
                    Column("DateTime(UTC)", DateTime(timezone=True)),
                    Column("ResolutionCode", String),
                    Column("AreaCode", String),
                    Column("AreaDisplayName", String),
                    Column("AreaTypeCode", String),
                    Column("AreaMapCode", String),
                    Column("TotalImbalanceVolume[MWh]", Float),
                    Column("Difference[MWh]", Float),
                    Column("Situation", String),
                    Column("Status", String),
                    Column("UpdateTime(UTC)", DateTime(timezone=True)),
                ]
            case _:
                self.logger.error(f"No table definition found for '{table_name}'.")
                return

        metadata = MetaData(schema="entsoe_fms")
        table = Table(
            table_name, metadata, *columns,
            UniqueConstraint(
                *self.UNIQUE_KEY_COLUMNS[table_name],
                name=self.UNIQUE_KEY_DICT[table_name],
                # None leaves the clause out; False would write NULLS DISTINCT.
                postgresql_nulls_not_distinct=(table_name in FMS_NULLS_NOT_DISTINCT_TABLES) or None,
            ),
        )
        if "UpdateTime(UTC)" in table.c:
            Index(self._update_time_index_name(table_name), table.c["UpdateTime(UTC)"])
        try:
            metadata.create_all(self.engine, tables=[table])
            self.logger.info(f"Table '{table_name}' created successfully.")
            print(f"Table '{table_name}' created successfully.")
        except Exception as e:
            self.logger.error(f"Error creating table '{table_name}': {e}", exc_info=True)


    def run(self):
        """
        Main entry point invoked by the scheduler.
        It executes the complete crawling workflow.
        """

        local_dir = os.getenv("OEDS_CRAWLER_DATA_DIR", os.path.join("crawler", "data"))
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
            self.logger.info("Starting ENTSO-E FMS fetch...")
            self.fetch_from_entsoe_fms_to_database(local_dir, start_time, end_time)

            self.logger.info("Crawler run finished successfully.")

        except Exception as e:
            self.logger.critical(f"Crawler run FAILED: {e}", exc_info=True)
            raise
