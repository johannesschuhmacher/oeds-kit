# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text

from crawler.common.kit_base import KitCrawler
from crawler.common.crawler_utils import (
    CrawlerSkipped,
    compact_json,
    config_or_env,
    has_credential,
    stable_hash,
    utc_now,
    write_access_status,
)
from crawler.common.local_env import load_crawler_dotenv


log = logging.getLogger("copernicus_cds")
log.setLevel(logging.INFO)

DOCS_URL = "https://cds.climate.copernicus.eu/en/how-to-api"
DEFAULT_CDS_URL = "https://cds.climate.copernicus.eu/api"


class CopernicusCdsCrawler(KitCrawler):
    def __init__(self, crawler_name: str, config: dict):
        load_crawler_dotenv()
        super().__init__(crawler_name, config)

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS requests (
                        request_id text PRIMARY KEY,
                        dataset text NOT NULL,
                        request_json text NOT NULL,
                        status text NOT NULL,
                        target_path text,
                        requested_at timestamp with time zone NOT NULL,
                        completed_at timestamp with time zone,
                        error text
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS downloaded_files (
                        request_id text PRIMARY KEY,
                        dataset text NOT NULL,
                        target_path text NOT NULL,
                        file_size_bytes bigint,
                        fetched_at timestamp with time zone NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS variable_statistics (
                        request_id text NOT NULL,
                        dataset text NOT NULL,
                        variable text NOT NULL,
                        observations bigint,
                        min_value double precision,
                        mean_value double precision,
                        max_value double precision,
                        unit text,
                        fetched_at timestamp with time zone NOT NULL,
                        PRIMARY KEY (request_id, variable)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW file_summary AS
                    SELECT
                        dataset,
                        count(*) AS files,
                        sum(file_size_bytes) AS total_size_bytes,
                        max(fetched_at) AS last_fetch
                    FROM downloaded_files
                    GROUP BY dataset
                    """
                )
            )

    def _credentials(self) -> tuple[str, str | None]:
        cds_url = str(config_or_env(self.config, "cds_url", "COPERNICUS_CDS_URL", DEFAULT_CDS_URL))
        cds_key = config_or_env(self.config, "cds_key", "COPERNICUS_CDS_KEY")
        return cds_url, str(cds_key) if has_credential(cds_key) else None

    def _default_request(self) -> tuple[str, dict[str, Any]]:
        reference_date = datetime.now(tz=timezone.utc) - timedelta(days=45)
        dataset = "reanalysis-era5-single-levels"
        request = {
            "product_type": ["reanalysis"],
            "variable": [
                "2m_temperature",
                "10m_u_component_of_wind",
                "10m_v_component_of_wind",
                "surface_solar_radiation_downwards",
            ],
            "year": [str(reference_date.year)],
            "month": [f"{reference_date.month:02d}"],
            "day": ["01"],
            "time": ["00:00", "06:00", "12:00", "18:00"],
            "area": [55.2, 5.5, 47.2, 15.5],
            "data_format": "netcdf",
        }
        return dataset, request

    def _request_definition(self) -> tuple[str, dict[str, Any]]:
        if self.config.get("dataset") and self.config.get("request"):
            return str(self.config["dataset"]), dict(self.config["request"])
        return self._default_request()

    def _target_path(self, dataset: str, request: dict[str, Any], request_id: str) -> Path:
        storage_dir = Path(self.config.get("storage_dir", "crawler/data/copernicus_cds"))
        suffix = str(self.config.get("target_suffix", ".nc"))
        storage_dir.mkdir(parents=True, exist_ok=True)
        safe_dataset = dataset.replace("/", "_").replace(" ", "_")
        return storage_dir / f"{safe_dataset}_{request_id[:12]}{suffix}"

    def _write_request_status(
        self,
        request_id: str,
        dataset: str,
        request: dict[str, Any],
        status: str,
        requested_at: datetime,
        target_path: Path | None = None,
        completed_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO requests
                        (request_id, dataset, request_json, status, target_path, requested_at, completed_at, error)
                    VALUES
                        (:request_id, :dataset, :request_json, :status, :target_path, :requested_at, :completed_at, :error)
                    ON CONFLICT (request_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        target_path = EXCLUDED.target_path,
                        completed_at = EXCLUDED.completed_at,
                        error = EXCLUDED.error
                    """
                ),
                {
                    "request_id": request_id,
                    "dataset": dataset,
                    "request_json": compact_json(request),
                    "status": status,
                    "target_path": str(target_path) if target_path else None,
                    "requested_at": requested_at,
                    "completed_at": completed_at,
                    "error": error,
                },
            )

    def _summarize_netcdf(self, request_id: str, dataset: str, target_path: Path, fetched_at: datetime) -> pd.DataFrame:
        if target_path.suffix.lower() not in {".nc", ".netcdf"}:
            return pd.DataFrame()
        try:
            import xarray as xr
        except ImportError:
            self.logger.warning("xarray is not installed; skipping Copernicus file summary.")
            return pd.DataFrame()

        rows = []
        try:
            dataset_handle = xr.open_dataset(target_path)
        except Exception as exc:
            self.logger.warning("Could not summarize Copernicus file %s: %s", target_path, exc)
            return pd.DataFrame()
        with dataset_handle as ds:
            for variable_name, data_array in ds.data_vars.items():
                numeric = data_array.astype("float64")
                rows.append(
                    {
                        "request_id": request_id,
                        "dataset": dataset,
                        "variable": variable_name,
                        "observations": int(numeric.count().values),
                        "min_value": float(numeric.min(skipna=True).values),
                        "mean_value": float(numeric.mean(skipna=True).values),
                        "max_value": float(numeric.max(skipna=True).values),
                        "unit": data_array.attrs.get("units"),
                        "fetched_at": fetched_at,
                    }
                )
        return pd.DataFrame(rows)

    def run(self):
        self._prepare_schema()
        cds_url, cds_key = self._credentials()
        if not cds_key:
            write_access_status(
                self.engine,
                source_name="Copernicus Climate Data Store",
                status="missing_credentials",
                access_model="CDS account, Personal Access Token, cdsapi, and accepted dataset terms",
                credentials_required=True,
                configured_credentials=False,
                message="Set COPERNICUS_CDS_URL and COPERNICUS_CDS_KEY or provide a standard CDS API configuration.",
                docs_url=DOCS_URL,
            )
            raise CrawlerSkipped("Copernicus CDS credentials missing; wrote access status only.")

        write_access_status(
            self.engine,
            source_name="Copernicus Climate Data Store",
            status="configured",
            access_model="CDS Personal Access Token",
            credentials_required=True,
            configured_credentials=True,
            message="CDS credentials are configured. Dataset terms must be accepted in the CDS portal before retrieval.",
            docs_url=DOCS_URL,
        )
        try:
            import cdsapi
        except ImportError as exc:
            raise RuntimeError("cdsapi is required for Copernicus CDS downloads.") from exc

        dataset, request = self._request_definition()
        request_id = stable_hash(dataset, request)
        target_path = self._target_path(dataset, request, request_id)
        requested_at = utc_now()
        self._write_request_status(request_id, dataset, request, "running", requested_at, target_path)
        try:
            client = cdsapi.Client(url=cds_url, key=cds_key, quiet=True)
            client.retrieve(dataset, request, str(target_path))
            fetched_at = utc_now()
            file_size = target_path.stat().st_size if target_path.exists() else None
            stats = self._summarize_netcdf(request_id, dataset, target_path, fetched_at)
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO downloaded_files
                            (request_id, dataset, target_path, file_size_bytes, fetched_at)
                        VALUES
                            (:request_id, :dataset, :target_path, :file_size_bytes, :fetched_at)
                        ON CONFLICT (request_id) DO UPDATE SET
                            target_path = EXCLUDED.target_path,
                            file_size_bytes = EXCLUDED.file_size_bytes,
                            fetched_at = EXCLUDED.fetched_at
                        """
                    ),
                    {
                        "request_id": request_id,
                        "dataset": dataset,
                        "target_path": str(target_path),
                        "file_size_bytes": file_size,
                        "fetched_at": fetched_at,
                    },
                )
                conn.execute(text("DELETE FROM variable_statistics WHERE request_id = :request_id"), {"request_id": request_id})
                if not stats.empty:
                    stats.to_sql("variable_statistics", conn, if_exists="append", index=False)
            self._write_request_status(request_id, dataset, request, "completed", requested_at, target_path, fetched_at)
        except Exception as exc:
            self._write_request_status(request_id, dataset, request, "failed", requested_at, target_path, utc_now(), str(exc))
            raise

        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": f"{cds_url} dataset={dataset}",
                "license": "Copernicus CDS dataset-specific license and terms",
                "description": "Configured Copernicus Climate Data Store climate or reanalysis request downloads and NetCDF summaries.",
                "contact": "https://cds.climate.copernicus.eu/",
            }
        )
        self.logger.info("Copernicus CDS crawler downloaded %s.", target_path)


def main(schema_name: str = "copernicus_cds"):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": schema_name,
    }
    CopernicusCdsCrawler("copernicus_cds", config).run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
