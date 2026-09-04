# SPDX-FileCopyrightText: Johannes Schuhmacher, Andre Meyer
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import hashlib
import logging
import re
import sys

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import insert

from crawler.common.base_crawler import BaseCrawler

try:
    import eurostat
except ModuleNotFoundError:  # pragma: no cover - exercised in dependency-light tests
    eurostat = None


DEFAULT_TABLE_NAME = "eurostat"
LEGACY_DATASET_ID = "nrg_inf_epcrw"
MAX_IDENTIFIER_LENGTH = 63


class EurostatCrawler(BaseCrawler):
    def __init__(self, crawler_name, config):
        super().__init__(crawler_name, config)
        self.schema_name = self.get("schema_name")
        self.dataset_id = self.get("dataset_id")
        self.table_name = self._resolve_table_name()
        self.unique_constraint_name = self._build_unique_constraint_name()

        self._init_table_object()

    @staticmethod
    def _sanitize_identifier(value: str) -> str:
        sanitized = re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_").lower()
        if not sanitized:
            return "dataset"
        if sanitized[0].isdigit():
            return f"dataset_{sanitized}"
        return sanitized

    @classmethod
    def _truncate_identifier(cls, identifier: str) -> str:
        if len(identifier) <= MAX_IDENTIFIER_LENGTH:
            return identifier
        digest = hashlib.sha1(identifier.encode("utf-8")).hexdigest()[:8]
        prefix = identifier[: MAX_IDENTIFIER_LENGTH - len(digest) - 1]
        return f"{prefix}_{digest}"

    def _resolve_table_name(self) -> str:
        configured_table_name = self.config.get("table_name")
        if configured_table_name:
            return self._truncate_identifier(
                self._sanitize_identifier(str(configured_table_name))
            )

        if self.dataset_id == LEGACY_DATASET_ID:
            return DEFAULT_TABLE_NAME

        dataset_suffix = self._sanitize_identifier(str(self.dataset_id))
        return self._truncate_identifier(f"{DEFAULT_TABLE_NAME}_{dataset_suffix}")

    def _build_unique_constraint_name(self) -> str:
        return self._truncate_identifier(
            f"uq_{self.table_name}_year_geo_siec_plant_tec"
        )

    def _init_table_object(self):
        self.metadata = MetaData(schema=self.schema_name)
        self.table = Table(
            self.table_name,
            self.metadata,
            Column("year", Integer),
            Column("geo\\TIME_PERIOD", String),
            Column("siec", String),
            Column("plant_tec", String),
            Column("freq", String),
            Column("unit", String),
            Column("capacity", Float),
            UniqueConstraint(
                "year",
                "geo\\TIME_PERIOD",
                "siec",
                "plant_tec",
                name=self.unique_constraint_name,
            ),
        )

    def _create_table(self):
        self.metadata.create_all(self.engine, tables=[self.table])
        self.logger.info(f"Table {self.table_name} created succsessfully")

        with self.engine.begin() as conn:
            query_create_hypertable = (
                "SELECT public.create_hypertable("
                ":table_name, 'year', if_not_exists => TRUE, migrate_data => TRUE);"
            )
            conn.execute(
                text(query_create_hypertable),
                {"table_name": f"{self.schema_name}.{self.table_name}"},
            )
            self.logger.info("Hypertable created")

    # 1990 - 2023 is the whole dataset
    def _download_data_df(self):
        if eurostat is None:
            raise RuntimeError(
                "The 'eurostat' package is required to run eurostat_crawler."
            )

        start_year = self.get("start_year")
        end_year = self.get("end_year")
        df = eurostat.get_data_df(
            self.dataset_id,
            filter_pars={"startPeriod": start_year, "endPeriod": end_year},
        )

        if df is None:
            self.logger.error(f"No data downloaded for years {start_year} - {end_year}")
            return

        available_year_columns = [
            str(year)
            for year in range(start_year, end_year + 1)
            if str(year) in df.columns
        ]

        if not available_year_columns:
            self.logger.error(
                f"No requested year columns are available for dataset {self.dataset_id} "
                f"in range {start_year} - {end_year}"
            )
            return None

        # reshape the dataframe so that year can be used as a column in order
        # for the hypertable to work
        df = df.melt(
            id_vars=["freq", "siec", "plant_tec", "unit", "geo\\TIME_PERIOD"],
            value_vars=available_year_columns,
            var_name="year",
            value_name="capacity",
        )
        df["year"] = df["year"].astype(int)
        df = df.dropna(subset=["capacity"])

        return df

    def _write_to_db(self, df):
        stmt = insert(self.table)
        stmt = stmt.on_conflict_do_update(
            constraint=self.unique_constraint_name,
            set_=stmt.excluded,
        )
        stmt = stmt.values(df.to_dict(orient="records"))

        with self.engine.begin() as conn:
            conn.execute(stmt)
        self.logger.info("Data written to Database")

    def run(self):
        self.set_metadata(
            {
                "schema_name": self.get("schema_name"),
                "data_date": "2024-06-12",
                "data_source": "https://www.eurostat.europa.eu/",
                "license": "",
                "description": "",
                "contact": "",
                "temporal_start": "1990-01-01 00:00:00",
                "temporal_end": "2023-12-31 23:59:59",
                "concave_hull_geometry": None,
            }
        )
        self._create_table()
        df = self._download_data_df()

        if df is None:
            self.logger.error("No data to write to Database")
            return

        self._write_to_db(df)


def main(schema_name):
    ec = EurostatCrawler(
        "eurostat_crawler",
        {
            "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
            "schema_name": schema_name,
            "dataset_id": LEGACY_DATASET_ID,
            "start_year": 2022,
            "end_year": 2023,
        },
    )
    ec.run()


if __name__ == "__main__":
    logging.basicConfig(
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("eurostat.log"),
        ],
        encoding="utf-8",
        level=logging.INFO,
    )
    main("eurostat")
