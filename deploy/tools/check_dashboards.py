"""Query dashboard SQL panels through Grafana's real datasource API.

Without arguments: the two starter dashboards must return data (installation test).
With --all: every provisioned dashboard is queried with the default value of each
variable; SQL errors fail the check, panels without rows are listed.
"""

import argparse
import copy
import json
import os
import re
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


DATASOURCE = {'uid': 'P6EAA63344BCC9F38', 'type': 'grafana-postgresql-datasource'}


def parse_time(value, now_ms):
    """Grafana time range value ('now-7d', 'now+1d', ISO date) in epoch milliseconds."""
    match = re.fullmatch(r'now(?:([+-])(\d+)([smhdwMy]))?(?:/\w)?', value)
    if match:
        if not match.group(1):
            return now_ms
        seconds = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800, 'M': 2592000, 'y': 31536000}
        delta = int(match.group(2)) * seconds[match.group(3)] * 1000
        return now_ms + delta if match.group(1) == '+' else now_ms - delta
    return int(time.mktime(time.strptime(value[:19], '%Y-%m-%dT%H:%M:%S')) * 1000)


def format_value(values, quoted_by_default, fmt):
    """Interpolate like Grafana's SQL datasources: multi-value and All variables are
    single-quoted lists unless a format such as :raw or :csv is given."""
    quote = fmt in ('sqlstring', 'singlequote') or (fmt is None and quoted_by_default)
    if quote:
        return ','.join("'" + str(value).replace("'", "''") + "'" for value in values)
    return ','.join(str(value) for value in values)


def substitute(sql, values, start, end):
    """Expand the variables the Grafana frontend expands before calling the SQL backend."""
    sql = sql.replace('$__from', str(start)).replace('$__to', str(end))
    sql = re.sub(r'\$\{__interval\}|\$__interval\b', '1h', sql.replace('$__interval_ms', '3600000'))
    for name, (current, quoted_by_default) in values.items():
        pattern = r'\$\{%s(?::(\w+))?\}|\[\[%s\]\]|\$%s\b' % (name, name, name)
        sql = re.sub(pattern, lambda match: format_value(current, quoted_by_default, match.group(1)), sql)
    return sql


def query(sql, fmt, start, end):
    body = {'queries': [{'refId': 'A', 'datasource': DATASOURCE, 'rawSql': sql, 'format': fmt,
                         'rawQuery': True, 'intervalMs': 900000, 'maxDataPoints': 1000}],
            'from': str(start), 'to': str(end)}
    try:
        result = request('/api/ds/query', body)
    except RuntimeError as error:
        return None, str(error)[:300]
    frames = []
    for value in result['results'].values():
        if value.get('error'):
            return None, value['error'][:300]
        frames.extend(value.get('frames', []))
    return frames, None


def variable_options(variable, values, start, end):
    if variable.get('type') != 'query':
        return [option['value'] for option in variable.get('options', []) if option.get('value') != '$__all']
    sql = variable.get('query')
    sql = sql.get('query', '') if isinstance(sql, dict) else sql
    frames, _ = query(substitute(sql, values, start, end), 'table', start, end)
    for frame in frames or []:
        names = [field['name'] for field in frame['schema']['fields']]
        column = names.index('__value') if '__value' in names else 0
        rows = frame.get('data', {}).get('values', [])
        if rows and rows[column]:
            return list(rows[column])
    return []


def variable_values(dashboard, start, end):
    """Each variable's saved value, or its first option; 'All' becomes every option."""
    values = {}
    for variable in dashboard.get('templating', {}).get('list', []):
        current = (variable.get('current') or {}).get('value')
        current = current if isinstance(current, list) else [current]
        current = [value for value in current if value not in (None, '')]
        if not current or current == ['$__all']:
            options = variable_options(variable, values, start, end)
            current = options if current == ['$__all'] else options[:1]
        quoted = bool(variable.get('multi') or variable.get('includeAll'))
        values[variable['name']] = (current or [''], quoted)
    return values


def check_all():
    failures = 0
    for hit in request('/api/search?type=dash-db'):
        dashboard = request('/api/dashboards/uid/' + hit['uid'])['dashboard']
        now = int(time.time() * 1000)
        start = parse_time(dashboard.get('time', {}).get('from', 'now-7d'), now)
        end = parse_time(dashboard.get('time', {}).get('to', 'now'), now)
        values = variable_values(dashboard, start, end)
        errors, empty, checked = [], [], 0
        for panel in panels(dashboard.get('panels', [])):
            for target in panel.get('targets', []):
                if not target.get('rawSql') or target.get('hide'):
                    continue
                checked += 1
                frames, error = query(substitute(target['rawSql'], values, start, end),
                                      target.get('format', 'time_series'), start, end)
                title = panel.get('title') or panel.get('id')
                if error:
                    errors.append(f'{title}: {error}')
                elif not any(frame.get('data', {}).get('values') and frame['data']['values'][0] for frame in frames):
                    empty.append(str(title))
        status = 'FAIL' if errors else ('WARN' if empty else 'PASS')
        failures += bool(errors)
        print(f'{status} {hit.get("folderTitle", "General")} / {dashboard["title"]}: {checked} queries, '
              f'{len(empty)} empty, {len(errors)} errors')
        for line in errors:
            print('    error  ' + line)
        for line in empty:
            print('    empty  ' + line)
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--all', action='store_true', help='query every provisioned dashboard')
    if parser.parse_args().all:
        raise SystemExit(check_all())
    assert request('/api/health')['database'] == 'ok'
    for variable, port, path in [('OEDS_POSTGREST_PORT', '3001', '/'),
                                 ('OEDS_CRAWLER_ADMIN_PORT', '3010', '/admin'),
                                 ('OEDS_PGADMIN_HTTP_PORT', '8080', '/')]:
        url = 'http://127.0.0.1:' + os.environ.get(variable, port) + path
        with urlopen(url, timeout=30) as response:
            assert response.status == 200, url
    queried = 0
    expected = {'d7e44e51-6f7f-4316-b9fb-1bb32c03fa18', 'weather-dashboard'}
    seen = set()
    for hit in request('/api/search?type=dash-db'):
        if hit['uid'] not in expected:
            continue
        seen.add(hit['uid'])
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
                smard = hit['uid'].startswith('d7e44e51')
                now = int(time.time() * 1000)
                start = str(now - (30 * 86400000 if smard else 12 * 3600000))
                end = str(now if smard else now + 72 * 3600000)
                # Grafana's frontend expands these globals before calling its SQL backend.
                query['rawSql'] = query['rawSql'].replace('$__from', start).replace('$__to', end)
                result = request('/api/ds/query', {'queries': [query],
                    'from': start, 'to': end})
                target_rows = 0
                for value in result['results'].values():
                    assert not value.get('error'), (dashboard['title'], panel.get('title'), value)
                    for frame in value.get('frames', []):
                        values = frame.get('data', {}).get('values', [])
                        if values:
                            rows += len(values[0])
                            target_rows += len(values[0])
                assert target_rows > 0, f'{dashboard["title"]}: {panel.get("title")}: no data in the default window'
                queried += 1
        assert rows > 0, f'{dashboard["title"]}: no sample data returned'
        print(f'PASS Grafana {dashboard["title"]}: {rows} returned values')
    assert seen == expected, f'Missing starter dashboards: {expected - seen}'
    print(f'PASS HTTP services and {queried} Grafana panel queries')


if __name__ == '__main__':
    main()
