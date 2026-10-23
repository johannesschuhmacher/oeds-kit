"""Validate the checked-out repository: Grafana JSON and the files the
deployment copies or mounts. No Docker required."""

import json
from pathlib import Path

DEPLOYMENT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = DEPLOYMENT_ROOT.parent
REQUIRED_FILES = [
    'pyproject.toml',
    'uv.lock',
    '.dockerignore',
    'deploy/compose.yml',
    'deploy/CRAWLER_CONFIG.yml',
    'deploy/docker/Dockerfile.crawler-modular',
    'packages/crawler-pack/pyproject.toml',
    'packages/crawler-pack/src/crawler/.env.example',
    'packages/crawler-pack/src/crawler/data/mapping_eic_to_location.py',
    'packages/crawler-pack/src/crawler/data/mapping_p_to_g.json',
    'packages/crawler-pack/src/crawler/data/mapping_g_to_p.json',
    'packages/scheduler/pyproject.toml',
    'packages/post/pyproject.toml',
    'packages/post/scripts/lib/postgres_functions.sql',
]


def main():
    for path in (DEPLOYMENT_ROOT / 'data/provisioning/grafana').rglob('*.json'):
        json.loads(path.read_text(encoding='utf-8'))
    missing = [relative for relative in REQUIRED_FILES if not (REPO_ROOT / relative).exists()]
    if missing:
        raise SystemExit('repository is missing required files: ' + ', '.join(missing))
    print('Deployment configuration valid')


if __name__ == '__main__':
    main()
