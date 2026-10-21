#!/usr/bin/env bash
# Regenerate docker/requirements.lock: every dependency of the four modules,
# pinned for the image (Linux, Python 3.13) under docker/constraints.txt.
# Run it inside an assembled workspace after bumping compatibility.yml pins or
# changing a module's dependencies, then copy the result into your checkout:
#   python3 tools/assemble_workspace.py --output "$HOME/oeds-assembled" --clean
#   bash "$HOME/oeds-assembled/modular_repos/modules/oeds-deployment/tools/update_requirements_lock.sh"
#   cp "$HOME/oeds-assembled/modular_repos/modules/oeds-deployment/docker/requirements.lock" docker/
# Needs uv (https://docs.astral.sh/uv/) and Git access to the pinned sources.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
for module in ../../sources/oeds-core ../oeds-crawler-pack ../oeds-post-scripts ../oeds-scheduler-ui; do
  if [[ ! -f "$module/pyproject.toml" ]]; then
    echo "missing module checkout: $module (run this script inside an assembled workspace)" >&2
    exit 1
  fi
done
uv pip compile --python-version 3.13 --python-platform linux \
  --custom-compile-command 'bash tools/update_requirements_lock.sh' \
  -c docker/constraints.txt \
  ../../sources/oeds-core/requirements.txt \
  ../../sources/oeds-core/pyproject.toml \
  ../oeds-crawler-pack/pyproject.toml \
  ../oeds-post-scripts/pyproject.toml --extra price-forecast \
  ../oeds-scheduler-ui/pyproject.toml \
  -o docker/requirements.lock
