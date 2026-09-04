# SPDX-FileCopyrightText: Florian Maurer, Jonathan Sejdija, Johannes Schuhmacher, Andre Meyer
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
This crawler downloads all the generation data of germany from the smard portal of the Bundesnetzagentur at smard.de.
It contains mostly data for Germany which is also availble in the ENTSO-E transparency platform but under a CC open license.
"""

import json
import logging
from datetime import timedelta

import pandas as pd
import requests
from sqlalchemy import MetaData, Table, text
from sqlalchemy.dialects.postgresql import insert

from crawler.common.base_crawler import BaseCrawler

log = logging.getLogger("smard")
DEFAULT_START_DATE = "2024-06-02 22:00:00"  # "2023-11-26 22:45:00"


metadata_info = {
    "schema_name": "smard",
    "data_date": "2024-06-12",
    "data_source": "https://www.smard.de/",
    "license": "CC-BY-4.0",
    "description": "Open access ENTSOE  Germany. Production of energy by good and timestamp",
    "contact": "",
    "temporal_start": "2023-01-01 23:00:00",
    "temporal_end": "2024-06-09 21:45:00",
    "concave_hull_geometry": None,
}


class SmardCrawler(BaseCrawler):
    def __init__(self, crawler_name, config):
        super().__init__(crawler_name, config)
        self.schema_name = self.get("schema_name")
        self._table_cache: dict[str, Table] = {}
        configured_start = self.config.get("default_start_date", DEFAULT_START_DATE)
        self.default_start_date = pd.Timestamp(configured_start)
        if self.default_start_date.tzinfo is None:
            self.default_start_date = self.default_start_date.tz_localize("UTC")
        else:
            self.default_start_date = self.default_start_date.tz_convert("UTC")

    def create_table(self):
        try:
            query_create_hypertable = "SELECT public.create_hypertable('smard', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);"
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS smard( "
                        "timestamp timestamp without time zone NOT NULL, "
                        "commodity_id text, "
                        "commodity_name text, "
                        "mwh double precision, "
                        "download_timestamp timestamp without time zone DEFAULT now(), "
                        "PRIMARY KEY (timestamp , commodity_id));"
                    )
                )
                conn.execute(text(query_create_hypertable))
            log.info("created hypertable smard")
        except Exception as e:
            log.error(f"could not create hypertable: {e}")
        try:
            query_create_hypertable_prices = "SELECT public.create_hypertable('prices', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);"
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS prices( "
                        "timestamp timestamp without time zone NOT NULL, "
                        "commodity_id text, "
                        "price double precision, "
                        "PRIMARY KEY (timestamp , commodity_id));"
                    )
                )
                conn.execute(text(query_create_hypertable_prices))
            log.info("created hypertable prices")
        except Exception as e:
            log.error(f"could not create hypertable: {e}")

    def _get_table(self, table_name: str) -> Table:
        if table_name not in self._table_cache:
            self._table_cache[table_name] = Table(
                table_name,
                MetaData(),
                schema=self.schema_name,
                autoload_with=self.engine,
            )
        return self._table_cache[table_name]

    @staticmethod
    def _build_upsert_statement(
        table: Table,
        rows: list[dict],
        update_columns: tuple[str, ...],
    ):
        statement = insert(table).values(rows)
        return statement.on_conflict_do_update(
            index_elements=["timestamp", "commodity_id"],
            set_={
                column_name: statement.excluded[column_name]
                for column_name in update_columns
            },
        )

    def _write_rows(
        self,
        table_name: str,
        data_to_write: pd.DataFrame,
        update_columns: tuple[str, ...],
    ) -> None:
        rows = data_to_write.to_dict(orient="records")
        if not rows:
            return

        statement = self._build_upsert_statement(
            self._get_table(table_name),
            rows,
            update_columns,
        )
        with self.engine.begin() as conn:
            conn.execute(statement)

    def get_data_per_commodity(self):
        keys = {
            # 411: 'Prognostizierter Stromverbrauch',
            4169: "Preis",
            410: "Realisierter Stromverbrauch",
            4066: "Biomasse",
            1226: "Wasserkraft",
            1225: "Wind Offshore",
            4067: "Wind Onshore",
            4068: "Photovoltaik",
            1228: "Sonstige Erneuerbare",
            1223: "Braunkohle",
            4071: "Erdgas",
            4070: "Pumpspeicher",
            1227: "Sonstige Konventionelle",
            4069: "Steinkohle",
            # 5097: 'Prognostizierte Erzeugung PV und Wind Day-Ahead'
        }

        for commodity_id, commodity_name in keys.items():
            start_date, latest = self.select_latest(commodity_id)
            # start_date_tz to unix time
            start_date_unix = int(start_date.timestamp() * 1000)
            url = f"https://www.smard.de/app/chart_data/{commodity_id}/DE/{commodity_id}_DE_quarterhour_{start_date_unix}.json"
            log.info(url)
            response = requests.get(url, timeout=30)
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                log.error(f"Could not get data for commodity: {commodity_id} {e}")
                continue
            data = json.loads(response.text)
            timeseries = pd.DataFrame.from_dict(data["series"])
            if timeseries.empty:
                log.info(f"Received empty data for commodity: {commodity_id}")
                continue
            timeseries[0] = pd.to_datetime(timeseries[0], unit="ms", utc=True)
            if commodity_id == 4169:
                timeseries.columns = ["timestamp", "price"]
                timeseries = timeseries.dropna(subset="price")
            else:
                timeseries.columns = ["timestamp", "mwh"]
                timeseries = timeseries.dropna(subset="mwh")
                timeseries["commodity_name"] = commodity_name
            timeseries["commodity_id"] = commodity_id
            if latest is not None:
                timeseries = timeseries[timeseries["timestamp"] > latest]

            yield timeseries

    def select_latest(
        self, commodity_id, delete=False, prev_latest=None
    ) -> tuple[pd.Timestamp, pd.Timestamp | None]:
        # day = default_start_date
        # today = date.today().strftime('%d.%m.%Y')
        # sql = f"select timestamp from smard where timestamp > '{day}' and timestamp < '{today}' order by timestamp desc limit 1"
        if commodity_id != 4169:
            sql = f"select timestamp from smard where commodity_id='{commodity_id}' order by timestamp desc limit 1"
        else:
            sql = f"select timestamp from prices where commodity_id='{commodity_id}' order by timestamp desc limit 1"
        try:
            with self.engine.begin() as conn:
                latest = pd.read_sql(sql, conn, parse_dates=["timestamp"]).values[0][0]
            latest = pd.to_datetime(latest, unit="ns", utc=True)
            log.info(f"The latest date in the database is {latest}")
            if latest.weekday() != 6 or (latest.hour < 21 and latest.minute == 45):
                last_sunday = latest - timedelta(days=latest.weekday() + 1)
                last_sunday_22 = last_sunday.replace(
                    hour=22, minute=0, second=0, microsecond=0
                )
                log.info(
                    f"the latest date in the database is not a sunday after 22:00, taking last week sunday 22:00 as start date to fill the missing data: {latest} -> {last_sunday_22}"
                )
                start_date = last_sunday_22
            else:
                log.info(
                    "the latest date in the database is a sunday 21:45, taking this sunday 22:00 as start date"
                )
                start_date = latest.replace(hour=22, minute=0, second=0, microsecond=0)
            return start_date, latest
        except Exception as e:
            log.info(f"Using the default start date {e}")
            return self.default_start_date, None

    def feed(self):
        for data_for_commodity in self.get_data_per_commodity():
            if data_for_commodity.empty:
                log.debug(f"No data for commodity {data_for_commodity}")
                continue
            df_for_commodity = data_for_commodity.set_index(
                ["timestamp", "commodity_id"]
            )
            # delete timezone duplicate
            # https://stackoverflow.com/a/34297689
            df_for_commodity = df_for_commodity[
                ~df_for_commodity.index.duplicated(keep="first")
            ]
            data_to_write = df_for_commodity.reset_index()
            data_to_write["timestamp"] = (
                pd.to_datetime(data_to_write["timestamp"], utc=True)
                .dt.tz_convert("UTC")
                .dt.tz_localize(None)
            )

            # log.debug(df_for_commodity)
            # check if commodity_id is == 4169 then it isprice data
            if df_for_commodity.index.get_level_values("commodity_id")[0] == 4169:
                self._write_rows("prices", data_to_write, ("price",))
            else:
                self._write_rows("smard", data_to_write, ("commodity_name", "mwh"))

    def run(self):
        self.logger.info("SMARD crawler started.")
        self.create_table()
        self.feed()
        self.set_metadata(metadata_info)
        self.logger.info("SMARD crawler finished successfully.")


def main(schema_name):
    ec = SmardCrawler(
        "smard",
        {
            "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
            "schema_name": schema_name,
        },
    )
    ec.run()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="[%(asctime)s] %(levelname)-8s [%(filename)s:%(lineno)d] :: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    # db_uri = 'sqlite:///./data/smard.db'
    main("smard")
