"""Query every starter dashboard SQL panel through Grafana's real datasource API."""

import copy
import json
import os
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = os.environ.get('OEDS_TEST_GRAFANA_URL',
    'http://127.0.0.1:' + os.environ.get('OEDS_GRAFANA_PORT', '3006'))


def request(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = Request(BASE + path, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f'Grafana {path}: HTTP {error.code}: {error.read().decode()}') from error


def panels(items):
    for panel in items:
        yield panel
        yield from panels(panel.get('panels', []))


def main():
    assert request('/api/health')['database'] == 'ok'
    for variable, port, path in [('OEDS_POSTGREST_PORT', '3001', '/'),
                                 ('OEDS_CRAWLER_ADMIN_PORT', '3010', '/admin'),
                                 ('OEDS_PGADMIN_HTTP_PORT', '8080', '/')]:
        url = 'http://127.0.0.1:' + os.environ.get(variable, port) + path
        with urlopen(url, timeout=30) as response:
            assert response.status == 200, url
    queried = 0
    for hit in request('/api/search?type=dash-db'):
        if hit['uid'] not in ('d7e44e51-6f7f-4316-b9fb-1bb32c03fa18', 'weather-dashboard'):
            continue
        dashboard = request('/api/dashboards/uid/' + hit['uid'])['dashboard']
        rows = 0
        for panel in panels(dashboard['panels']):
            for target in panel.get('targets', []):
                if not target.get('rawSql') or target.get('hide'):
                    continue
                query = copy.deepcopy(target)
                query['datasource'] = panel.get('datasource', {'uid': 'P6EAA63344BCC9F38',
                    'type': 'grafana-postgresql-datasource'})
                query['rawSql'] = query['rawSql'].replace('$Location', 'berlin').replace('$Country_Code', 'DE')
                query.update(intervalMs=900000, maxDataPoints=1000)
                print(f'Querying {dashboard["title"]}: {panel.get("title", panel.get("id"))}', flush=True)
                historical = hit['uid'].startswith('d7e44e51')
                now = int(time.time() * 1000)
                start = '1717372800000' if historical else str(now - 86400000)
                end = '1718150400000' if historical else str(now + 172800000)
                # Grafana's frontend expands these globals before calling its SQL backend.
                query['rawSql'] = query['rawSql'].replace('$__from', start).replace('$__to', end)
                result = request('/api/ds/query', {'queries': [query],
                    'from': start, 'to': end})
                for value in result['results'].values():
                    assert not value.get('error'), (dashboard['title'], panel.get('title'), value)
                    for frame in value.get('frames', []):
                        values = frame.get('data', {}).get('values', [])
                        if values:
                            rows += len(values[0])
                queried += 1
        assert rows > 0, f'{dashboard["title"]}: no sample data returned'
        print(f'PASS Grafana {dashboard["title"]}: {rows} returned values')
    assert queried >= 2, 'Starter dashboards were not provisioned'
    print(f'PASS HTTP services and {queried} Grafana panel queries')


if __name__ == '__main__':
    main()
