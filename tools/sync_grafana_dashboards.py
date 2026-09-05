"""Read-only export of the two starter dashboards from the public OEDS Grafana."""

import copy
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1] / 'data/provisioning/grafana/dashboards'
DASHBOARDS = {
    'd7e44e51-6f7f-4316-b9fb-1bb32c03fa18': 'smard/smard.json',
    'weather-dashboard': 'weather_forecast/weather.json',
}


def main():
    for uid, relative in DASHBOARDS.items():
        with urlopen(f'https://oeds.iip.kit.edu/api/dashboards/uid/{uid}', timeout=30) as response:
            dashboard = json.load(response)['dashboard']
        dashboard['id'] = None
        dashboard['version'] = 1
        if uid.startswith('d7e44e51'):
            # Preserve the production comparison; it requires a separate ENTSO-E schema.
            original = copy.deepcopy(dashboard)
            original['uid'] = 'smard-entsoe-comparison'
            original['title'] = 'SMARD and ENTSO-E comparison'
            archive = ROOT.parent / 'optional-dashboards/smard/SMARD_ENTSOE_Comparison.json'
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_text(json.dumps(original, ensure_ascii=True, indent=2) + '\n')
            dashboard['title'] = 'SMARD'
            generation, price = dashboard['panels']
            generation['title'] = 'Electricity generation and load (MW)'
            generation['fieldConfig']['defaults']['unit'] = 'suffix:MW'
            labels = {'410': 'Total load', '4066': 'Biomass', '1226': 'Hydropower',
                      '1225': 'Wind offshore', '4067': 'Wind onshore', '4068': 'Solar',
                      '1228': 'Other renewables', '1223': 'Lignite', '4071': 'Natural gas',
                      '4070': 'Pumped storage', '1227': 'Other conventional', '4069': 'Hard coal'}
            metric = 'CASE commodity_id ' + ' '.join(
                f"WHEN '{key}' THEN '{label}'" for key, label in labels.items()) + ' END'
            generation['targets'][0]['rawSql'] = (
                'SELECT $__timeGroupAlias(timestamp,$__interval), ' + metric + ' AS metric, '
                'avg(mwh*4) AS power_mw FROM smard.smard WHERE $__timeFilter(timestamp) '
                'GROUP BY 1,2 ORDER BY 1,2')
            price['title'] = 'Day-ahead electricity price (EUR/MWh)'
            price['targets'] = [{'refId': 'A', 'editorMode': 'code', 'format': 'time_series',
                'rawQuery': True, 'rawSql': 'SELECT timestamp AS time, price FROM smard.prices '
                'WHERE $__timeFilter(timestamp) AND commodity_id = \'4169\' ORDER BY 1'}]
            price['fieldConfig']['defaults']['unit'] = 'suffix:EUR/MWh'
            for panel in (generation, price):
                # Production exports may contain a temporary "show only this series" selection.
                panel['fieldConfig']['overrides'] = []
                panel['fieldConfig']['defaults']['custom']['stacking']['mode'] = 'none'
        target = ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(dashboard, ensure_ascii=True, indent=2) + '\n')
        print(f'Exported {dashboard["title"]} -> {relative}')


if __name__ == '__main__':
    main()
