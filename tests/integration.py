"""Small deterministic DB/HTTP/crawler/scheduler test. Writes oeds_test_* schemas."""

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from zipfile import ZipFile
from urllib.parse import quote

import pandas as pd
from sqlalchemy import create_engine, text
import yaml

ROOT = Path(__file__).resolve().parent
URI = os.environ.get('OEDS_TEST_DB_URI', 'postgresql://opendata:' +
    quote(os.environ.get('OEDS_DB_PASSWORD', 'opendata'), safe='') + '@open-data:5432/opendata')


def fixture_crawler(stage):
    with tempfile.TemporaryDirectory() as directory:
        names = {'wind': 'ninja_wind_europe_v1.1_current_on-offshore.csv',
                 'solar': 'ninja_pv_europe_v1.1_merra2.csv'}
        for kind, name in names.items():
            with ZipFile(Path(directory) / f'{kind}.zip', 'w') as archive:
                archive.write(ROOT / 'data' / f'ninja_{kind}.csv', name)
        server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(
            SimpleHTTPRequestHandler, directory=directory))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        schema = f'oeds_test_{stage}'
        try:
            if stage == 'core':
                import oeds.crawler.ninja as ninja
                ninja.WIND_URL, ninja.SOLAR_URL = f'{url}/wind.zip', f'{url}/solar.zip'
                crawler = ninja.NinjaCrawler(schema, {'db_uri': URI})
                crawler.crawl_structural(recreate=True)
            else:
                from crawler.ninja import NinjaCrawler
                crawler = NinjaCrawler('ninja', {
                    'schema_name': schema, 'database_uri': URI + '?options=--search_path=',
                    'datafiles': {kind: {'download_url': f'{url}/{kind}.zip',
                                        'extract_filename': name} for kind, name in names.items()}})
                crawler.run()
            for table, expected in [('capacity_wind_on', [.1, .11, .12, .13]),
                                    ('capacity_wind_off', [.2, .21, .22, .23]),
                                    ('capacity_solar_merra2', [.05, .06, .07, .08])]:
                rows = pd.read_sql(f'SELECT * FROM {schema}.{table} ORDER BY time', crawler.engine)
                assert len(rows) == 4, (table, len(rows))
                assert all(abs(a-b) < 1e-12 for a, b in zip(rows.de, expected)), table
            print(f'PASS {stage}: HTTP ZIP/CSV -> three tables, 12 exact capacity factors', flush=True)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


def schedule_test():
    from oeds_scheduler_ui.application import SchedulerApplication
    from oeds_scheduler_ui.daemon import SchedulerDaemon
    from oeds_scheduler_ui.runtime import execute_post_command

    # Two genuine minute boundaries, no simulated clock or mocked crawler.
    results = []
    stopped = threading.Event()
    def post(command, plan):
        result = execute_post_command(command, plan)
        results.append(result)
        if len(results) == 2 or not result.success:
            stopped.set()
        return result

    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / 'schedule.yml'
        data = {'default': {'enable': False, 'database_uri': URI + '?options=--search_path=',
                            'email': {'mailhost': '', 'fromaddr': '', 'toaddrs': [],
                                      'subject': '', 'username': '', 'password': ''}},
                'ninja': {'enable': True, 'schema_name': 'oeds_test_schedule',
                          'smoke_mode': True, 'smoke_rows': 4, 'schedule': '* * * * *',
                          'run_post_scripts': True,
                          'post_run_scripts': ['oeds-post gapfill entsoe-fms --self-test']}}
        config.write_text(yaml.safe_dump(data))
        app = SchedulerApplication(config, '/app/modular_repos/docs/crawler-inventory.json',
                                   '/app/modular_repos', post_run_executor=post)
        assert app.snapshot.ready and app.snapshot.planned_job_count == 1, app.snapshot
        timer = threading.Timer(160, stopped.set)
        timer.start()
        started = time.monotonic()
        try:
            SchedulerDaemon(app, poll_seconds=1, stop_event=stopped).run_forever()
        finally:
            timer.cancel()
        assert len(results) == 2 and all(r.success for r in results), results
        assert time.monotonic() - started >= 50, 'Expected real minute-separated runs'
        data['ninja']['enable'] = False
        config.write_text(yaml.safe_dump(data))
        assert app.reload_if_changed()
        assert app.snapshot.planned_job_count == 0
        with create_engine(URI).connect() as conn:
            assert conn.execute(text('SELECT count(time) FROM oeds_test_schedule.capacity_wind_on')).scalar() == 4
        print('PASS scheduler: two minute-separated crawler/post-runs; reload disables job', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['core', 'crawlers', 'post', 'runtime'])
    stage = parser.parse_args().stage
    if stage in ('core', 'crawlers'):
        fixture_crawler(stage)
    elif stage == 'post':
        subprocess.run(['oeds-post', 'gapfill', 'entsoe-fms', '--self-test'], check=True)
        subprocess.run(['oeds-post', 'forecast', 'day-ahead-price', '--self-test'], check=True)
        print('PASS post-processing numerical self-tests', flush=True)
    else:
        schedule_test()


if __name__ == '__main__':
    main()
