# SPDX-FileCopyrightText: Haoshen Zhang, Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import sys
from dotenv import load_dotenv
from pathlib import Path
import requests
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import text, Table, MetaData, Column, DateTime, Float, String
from sqlalchemy.dialects.postgresql import insert

from crawler.common.base_crawler import BaseCrawler

class EnergyForecastCrawler(BaseCrawler):
    
    _script_dir = Path(__file__).resolve().parent
    _target_env_path = _script_dir / ".env"
    
    if _target_env_path.exists():
        load_dotenv(dotenv_path=_target_env_path)
    
    BASE_URL = "https://www.energyforecast.de"
    TOKEN = os.getenv("ENERGY_FORECAST_TOKEN")

    def __init__(self, schema_name: str, config: dict):
        super().__init__(schema_name, config)

        self.schema_name = self.get('schema_name')
        self.table_name = 'predictions_48h'
        self.primary_key_name = 'prediction_start'

        self._init_table_object()
        
    def _init_table_object(self):
        self.metadata = MetaData(schema=self.schema_name)
        
        columns = [
            Column(self.primary_key_name, DateTime(timezone=True), primary_key=True)
        ]

        for i in range(192):
            hours = i // 4
            minutes = (i % 4) * 15
            columns.append(Column(f"p_h_{hours:02d}_m_{minutes:02d}", Float))
            columns.append(Column(f"o_h_{hours:02d}_m_{minutes:02d}", String))

        self.table = Table(
            self.table_name,
            self.metadata,
            *columns
        )

    def _download_data_df(self):
        if not self.TOKEN:
            self.logger.critical("ENERGY_FORECAST_TOKEN is missing.")
            print("CRITICAL ERROR: ENERGY_FORECAST_TOKEN is missing.")
            return None
        
        endpoint = "/api/v1/predictions/next_48_hours"
        url = f"{self.BASE_URL}{endpoint}"
        
        params = {
            "token": self.TOKEN,
            "fixed_cost_cent": 0,
            "vat": 0,
            "resolution": "QUARTER_HOURLY",
            "market_zone": "DE-LU"
        }
        headers = {"Accept": "application/json"}

        try:
            self.logger.info(f"Fetching data from {url}")
            print(f"Fetching data from {url}") 
            
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                return self._process_json_to_df(response.json())
            elif response.status_code == 401:
                print("API Access Denied (401). Invalid Token.")
                return None
            else:
                print(f"API Request failed: {response.status_code}")
                return None
        except Exception as e:
            print(f"Download failed: {e}")
            self.logger.error(f"Download failed: {e}")
            return None

    def _process_json_to_df(self, data_list):
        now_utc = pd.Timestamp.now(tz='UTC')
        valid_items = []

        for item in data_list:
            try:
                start_time = pd.to_datetime(item['start'], utc=True)
                if start_time >= now_utc:
                    valid_items.append({
                        'time': start_time,
                        'price': item['price'],
                        'origin': item.get('price_origin', 'unknown')
                    })
            except Exception:
                continue
        
        if not valid_items:
            print("No valid data found after filtering.")
            return None

        required_count = 192
        current_count = len(valid_items)
        if current_count < required_count:
            valid_items += [{'price': None, 'origin': None}] * (required_count - current_count)
        else:
            valid_items = valid_items[:required_count]

        first_timestamp = valid_items[0]['time']
        row_dict = { self.primary_key_name: first_timestamp }
        
        for i, item in enumerate(valid_items):
            h, m = i // 4, (i % 4) * 15
            row_dict[f"p_h_{h:02d}_m_{m:02d}"] = item['price']
            row_dict[f"o_h_{h:02d}_m_{m:02d}"] = item['origin']

        return pd.DataFrame([row_dict])

    def _write_to_db(self, df):
        stmt = insert(self.table)
        stmt = stmt.on_conflict_do_update(
            index_elements=[self.primary_key_name],
            set_=stmt.excluded
        )
        with self.engine.begin() as conn:
            conn.execute(stmt, df.to_dict(orient='records'))
        
        print("Data successfully written to Database")
        self.logger.info('Data successfully written to Database')

    def _write_to_csv(self, df):
        try:
            data_dir = Path(os.environ.get('OEDS_CRAWLER_DATA_DIR', 'crawler/data'))
            
            if not data_dir.exists():
                data_dir.mkdir(parents=True, exist_ok=True)

            file_path = data_dir / 'energy_forecast_history.csv'
            file_exists = file_path.is_file()

            df.to_csv(file_path, mode='a', header=not file_exists, index=False)
            print(f"Data successfully appended to local file: {file_path}")
            
        except Exception as e:
            print(f"Failed to write data to local CSV file: {e}")
            self.logger.error(f"Failed to write data to local CSV file: {e}")

    def run(self):
        print("Crawler run started.")
        self.logger.info("Crawler run started.")

        self.metadata.create_all(self.engine, tables=[self.table])

        df = self._download_data_df()

        if df is None or df.empty:
            message = "Energy Forecast crawler did not receive any usable forecast data."
            self.logger.critical(message)
            raise RuntimeError(message)

        prediction_start = pd.to_datetime(df[self.primary_key_name].iloc[0], utc=True)
        self.set_metadata({
            'schema_name': self.schema_name,
            'data_date': datetime.now().strftime('%Y-%m-%d'),
            'data_source': self.BASE_URL,
            'license': 'Proprietary',
            'description': 'Energy price predictions 48h',
            'contact': 'admin@energyforecast.de',
            'temporal_start': prediction_start.isoformat(),
            'temporal_end': (prediction_start + pd.Timedelta(hours=48)).isoformat()
        })

        self._write_to_db(df)
        self._write_to_csv(df)

        print("Crawler run finished successfully.")
        self.logger.info("Crawler run finished successfully.")


def main(schema_name: str):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": "energy_forecast",
    }
    print("EnergyForecast crawler start")
    
    crawler = EnergyForecastCrawler(schema_name, config)
    print("EnergyForecastCrawler created")
    
    crawler.run()

if __name__ == '__main__':
    main("energy_forecast")
