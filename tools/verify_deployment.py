"""Validate actual configuration, not source-code wording. No Docker required."""

import argparse
import json

from assemble_workspace import DEPLOYMENT_ROOT, _read_components, _verify_workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-only', action='store_true')
    args = parser.parse_args()
    _read_components(DEPLOYMENT_ROOT / 'compatibility.yml')
    for path in (DEPLOYMENT_ROOT / 'data/provisioning/grafana').rglob('*.json'):
        json.loads(path.read_text(encoding='utf-8'))
    json.loads((DEPLOYMENT_ROOT / 'assembly/crawler-inventory.json').read_text())
    if not args.local_only:
        _verify_workspace(DEPLOYMENT_ROOT.parents[2])
    print('Deployment configuration valid')


if __name__ == '__main__':
    main()
