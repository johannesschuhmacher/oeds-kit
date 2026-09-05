# SPDX-FileCopyrightText: Florian Maurer, Johannes Schuhmacher, Andre Meyer
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from crawler.common.base_crawler import BaseCrawler

import pandas as pd
import requests

from zipfile import ZipFile
from io import BytesIO

import logging

metadata_info = {
    "schema_name": "ninja",
    "data_date": "2016-12-31",
    "data_source": "https://www.renewables.ninja/downloads",
    "license": "CC-BY-4.0",
    "description": "NINJA renewables capacity. Country specific capacities for wind and solar.",
    "contact": "",
    "temporal_start": "1980-01-01 00:00:00",
    "temporal_end": "2016-12-31 23:00:00",
}


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


class NinjaCrawler(BaseCrawler):
    def __init__(self, crawler_name, config):
        super().__init__(crawler_name, config)

    def download_and_write_to_db(self):
        datafiles_dict = self.get('datafiles')
        dataframes = {k: [] for k in datafiles_dict}
        for key in datafiles_dict:
            url = self.get(f'datafiles.{key}.download_url')
            response = requests.get(url)
            if not response.ok:
                self.logger.error(f'cannot download file {url}: status code: {response.status_code}')
                continue

            with ZipFile(BytesIO(response.content)) as archive:
                self.logger.debug(f"files in archive: {archive.namelist()}")
                extract_filename = self.get(f'datafiles.{key}.extract_filename')
                if not extract_filename in archive.namelist():
                    self.logger.error(f'file {extract_filename} not found in archive {url}')
                    continue

                with archive.open(extract_filename) as f:
                    df = pd.read_csv(f, index_col=0)
                    self.write_to_db(key, extract_filename, url, df)

        return dataframes

    def write_wind_capacity_factors(self, df):
        df.index = pd.to_datetime(df.index)
        onshore = {
            col.split("_")[0].lower(): df[col].values
            for col in df.columns
            if "ON" in col
        }
        df_on = pd.DataFrame(data=onshore, index=df.index)
        df_on.to_sql("capacity_wind_on", self.engine, if_exists="replace")
        offshore = {
            col.split("_")[0].lower(): df[col].values
            for col in df.columns
            if "OFF" in col
        }
        df_off = pd.DataFrame(data=offshore, index=df.index)
        df_off.to_sql("capacity_wind_off", self.engine, if_exists="replace")

    def write_solar_capacity_factors(self, df):
        df.index = pd.to_datetime(df.index)
        df.columns = [col.lower() for col in df.columns]
        df.to_sql("capacity_solar_merra2", self.engine, if_exists="replace")

    def write_to_db(self, energy_type, file_name, download_url, df):
        if energy_type == 'wind':
            self.write_wind_capacity_factors(df)
        elif energy_type == 'solar':
            self.write_solar_capacity_factors(df)
        else:
            self.logger.warning(f'energy_type {energy_type} is not implemented. Skipping file {file_name} downloaded from {download_url}')
            return

        self.logger.info(f'{energy_type} capacity factors written to database from {file_name} downloaded from {download_url}')

    def write_smoke_data(self):
        periods = int(self.config.get("smoke_rows", 4))
        if periods < 1:
            periods = 1
        index = pd.date_range(
            self.config.get("smoke_start", "2016-01-01 00:00:00"),
            periods=periods,
            freq="h",
            name="time",
        )
        wind = pd.DataFrame(
            {
                "DE_ON": [0.10 + i * 0.01 for i in range(periods)],
                "DE_OFF": [0.20 + i * 0.01 for i in range(periods)],
            },
            index=index,
        )
        solar = pd.DataFrame(
            {"DE": [0.05 + i * 0.01 for i in range(periods)]},
            index=index,
        )
        self.write_to_db("wind", "ninja_smoke_wind.csv", "smoke://ninja/wind", wind)
        self.write_to_db("solar", "ninja_smoke_solar.csv", "smoke://ninja/solar", solar)

    def run(self):
        self.set_metadata(metadata_info)
        if _as_bool(self.config.get("smoke_mode", False)):
            self.logger.info("writing renewables.ninja smoke dataset")
            self.write_smoke_data()
            return
        self.download_and_write_to_db()

def main():
    config = {
        'schema_name': 'ninja',
        'datafiles': {
            'wind': {
                "download_url": "https://www.renewables.ninja/downloads/ninja_europe_wind_v1.1.zip",
                "extract_filename": "ninja_wind_europe_v1.1_current_on-offshore.csv",
            },
            'solar': {
                "download_url": "https://www.renewables.ninja/downloads/ninja_europe_pv_v1.1.zip",
                "extract_filename": "ninja_pv_europe_v1.1_merra2.csv",
            },
        },
        'smoke_mode': False,
        'database_uri': "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
    }
    crawler = NinjaCrawler('ninja', config)
    crawler.run()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='[%(asctime)s]:%(name)s:%(levelname)s :: %(message)s'
    )
    main()
