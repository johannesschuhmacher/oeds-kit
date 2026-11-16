import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pandas as pd
import pytest
from urllib3.connection import HTTPConnection
from urllib3.exceptions import NewConnectionError

from crawler.energyforecast import EnergyForecastCrawler


def test_csv_history_uses_runtime_data_directory(monkeypatch, tmp_path):
    directory = tmp_path / 'runtime-data'
    monkeypatch.setenv('OEDS_CRAWLER_DATA_DIR', str(directory))
    crawler = object.__new__(EnergyForecastCrawler)
    frame = pd.DataFrame({'price': [42.5]})

    crawler._write_to_csv(frame)
    crawler._write_to_csv(frame)

    saved = pd.read_csv(directory / 'energy_forecast_history.csv')
    assert saved.price.tolist() == [42.5, 42.5]


def test_download_retries_a_failed_connection(monkeypatch):
    start = (pd.Timestamp.now(tz='UTC') + pd.Timedelta(hours=1)).floor('15min')
    body = json.dumps([{'start': start.isoformat(), 'price': 0.1, 'price_origin': 'forecast'}]).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    real_new_conn = HTTPConnection._new_conn
    failures = []

    def flaky_new_conn(conn):
        if not failures:
            failures.append(1)
            raise NewConnectionError(conn, 'Network is unreachable')
        return real_new_conn(conn)

    monkeypatch.setattr(HTTPConnection, '_new_conn', flaky_new_conn)
    monkeypatch.setattr(EnergyForecastCrawler, 'BASE_URL', f'http://127.0.0.1:{server.server_port}')
    monkeypatch.setattr(EnergyForecastCrawler, 'TOKEN', 'test-token')
    crawler = object.__new__(EnergyForecastCrawler)
    crawler.logger = logging.getLogger('test-energyforecast')
    crawler.primary_key_name = 'prediction_start'
    try:
        df = crawler._download_data_df()
    finally:
        server.shutdown()

    assert failures == [1]
    assert df is not None
    assert df['p_h_00_m_00'].tolist() == [pytest.approx(0.1)]
