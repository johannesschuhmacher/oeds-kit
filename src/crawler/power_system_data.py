# SPDX-FileCopyrightText: Johannes Schuhmacher, Haoshen Zhang
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
from datetime import datetime

import pandas as pd
import yaml
from sqlalchemy import Column, Float, MetaData, String, Table
from sqlalchemy.dialects.postgresql import insert

from crawler.common.base_crawler import BaseCrawler
from crawler.data.mapping_eic_to_location import etl_run


class PowerSystemDataCrawler(BaseCrawler):
    """
    Crawler to fetch power plant data from PyPSA and save it to the database.
    """

    def __init__(self, schema_name: str, config: dict):
        super().__init__(schema_name, config)
        self.schema_name = self.get("schema_name")
        self.table_name = "powersystemdata"
        self._init_table_object()

    def _init_table_object(self):
        self.metadata = MetaData(schema=self.schema_name)
        self.table = Table(
            self.table_name,
            self.metadata,
            Column("source_id", String, primary_key=True),
            Column("name", String),
            Column("fuel_type", String),
            Column("technology", String),
            Column("set_type", String),
            Column("country", String),
            Column("capacity", Float),
            Column("efficiency", Float),
            Column("date_in", Float),
            Column("date_retrofit", Float),
            Column("date_out", Float),
            Column("lat", Float),
            Column("lon", Float),
            Column("duration", Float),
            Column("volume_mm3", Float),
            Column("dam_height_m", Float),
            Column("storage_capacity_mwh", Float),
            Column("eic_code", String),
            Column("project_id", String),
        )

    def run(self):
        print("Crawler run started.")
        self.logger.info("Crawler run started.")

        # 1. Set Metadata
        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now().strftime("%Y-%m-%d"),
                "data_source": "https://github.com/PyPSA/powerplantmatching",
                "license": "MIT",
                "description": "Power plant data from PyPSA powerplantmatching",
                "contact": "PyPSA developers",
                "temporal_start": None,
                "temporal_end": None,
            }
        )

        # 2. Ensure Schema and Table
        self.metadata.create_all(self.engine, tables=[self.table])

        # 3. Download and Process
        print("Pulling power plant data")
        self.logger.info("Pulling power plant data from GitHub PyPSA")

        url = "https://raw.githubusercontent.com/PyPSA/powerplantmatching/master/powerplants.csv"

        try:
            df = pd.read_csv(url)
            self.logger.info(f"Done downloading {len(df)} records")

            column_mapping = {
                "id": "source_id",
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
                "projectID": "project_id",
            }

            df = df.rename(columns=column_mapping)
            table_columns = [column.name for column in self.table.columns]
            df = df.reindex(columns=table_columns)

            # Data Cleaning
            df = df.dropna(axis=0, subset=["lon", "lat"])
            # Ensure source_id is string and unique
            df["source_id"] = df["source_id"].astype(str)
            df = df.drop_duplicates(subset=["source_id"])

            # 4. Write to DB using Upsert pattern
            self._write_to_db(df)

            self.logger.info(f"Finish updating 'powersystemdata', {len(df)} records")
            print(f"Finish updating 'powersystemdata', {len(df)} records")

            # 5. Update geographic mapping (eic_geo_location)
            print("Updating EIC geo location mapping...")
            self.logger.info(
                f"Updating EIC geo location mapping in schema '{self.schema_name}'"
            )
            try:
                etl_run(
                    engine=self.engine,
                    source_schema=self.schema_name,
                    source_table=self.table_name,
                )
            except Exception as e:
                self.logger.error(f"Error updating EIC mapping: {e}")
                print(f"Error updating EIC mapping: {e}")

        except Exception as e:
            self.logger.exception("Error downloading power plant data")
            print(f"Error downloading powerplant data: {e}")

    def _write_to_db(self, df):
        stmt = insert(self.table)
        stmt = stmt.on_conflict_do_update(
            index_elements=["source_id"],
            set_={
                c.name: stmt.excluded[c.name]
                for c in self.table.columns
                if c.name != "source_id"
            },
        )
        # Handle large scale writes in batches
        batch_size = 5000
        data_records = df.to_dict(orient="records")

        with self.engine.begin() as conn:
            for i in range(0, len(data_records), batch_size):
                batch = data_records[i : i + batch_size]
                conn.execute(stmt, batch)

        print("Data successfully written to Database")
        self.logger.info("Data successfully written to Database")


def main(schema_name: str):
    config_file = "CRAWLER_CONFIG.yml"
    config = {}

    if os.path.exists(config_file):
        try:
            with open(config_file) as f:
                full_config = yaml.safe_load(f)

            # Load ONLY the specific section, skip 'default' to avoid initializing email logging
            config = full_config.get("power_system_data", {})

            if not config:
                print(
                    f"Warning: 'power_system_data' section not found in {config_file}"
                )
            else:
                print(
                    f"Successfully loaded 'power_system_data' configuration from {config_file}"
                )
        except Exception as e:
            print(f"Error loading {config_file}: {e}")

    if not config:
        config = {
            "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
            "schema_name": "power_system_data",
        }
        print("Using hardcoded fallback configuration.")

    print("power_system_data crawler start")
    crawler = PowerSystemDataCrawler(schema_name, config)
    print("PowerSystemDataCrawler created")
    crawler.run()


if __name__ == "__main__":
    main("power_system_data")
