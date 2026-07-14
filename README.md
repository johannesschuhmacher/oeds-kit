# oeds-deployment

Deployment and operations module for the modular OEDS stack.

## Responsibility

This module should install and operate a selected set of OEDS components. It
should not patch crawler source code at deployment time.

## Contents

- Docker Compose files
- Docker build contexts
- Ansible playbooks
- host setup
- backup, restore, migration, rollback
- provisioning for Grafana, PgAdmin, and PostgREST
- operational documentation
- compatibility metadata in `compatibility.yml`

## Current Copied Implementation

This module repository now contains local copies of the current KIT deployment
assets:

```text
compose.yml
compose.modular.yml
compose.test.yml
docker/
playbooks/
data/provisioning/
oeds_ops/
modular_initdb/
tools/verify_deployment.py
tools/test_db_smoke.ps1
tools/test_real_crawler_smoke.ps1
tools/test_active_crawlers_smoke.ps1
tools/test_stack_smoke.ps1
```

These files are intentionally copied first and refactored later. That gives the
split repository a working deployment baseline while component boundaries are
stabilized.

`compose.modular.yml` is the first modular overlay. It keeps the copied KIT
baseline intact and overrides only the crawler-related build path:

- build context is the local KIT workspace root
- Dockerfile is `docker/Dockerfile.crawler-modular`
- scheduler command uses `oeds-scheduler`
- admin command uses `oeds-crawler-admin`
- admin runtime root is passed as `OEDS_ADMIN_REPO_ROOT=/app`
- post-run SQL bootstrap comes from `../oeds-post-scripts`
- the modular overlay uses `modular_initdb/09-bootstrap-roles.sh` with LF line
  endings so Docker init does not depend on the Windows checkout line endings
  of the byte-identical KIT copy
- runtime mounts default to `${OEDS_RUNTIME_DIR:-../../..}`, so local use from
  this repo picks up the current KIT workspace root unless another runtime dir
  is supplied

This means the same deployment repo can validate both:

| Mode | Command shape | Purpose |
| --- | --- | --- |
| KIT baseline | `docker compose -f compose.yml ...` | reproduce current KIT deployment |
| Modular split | `docker compose -f compose.yml -f compose.modular.yml ...` | run the local module layout |
| Isolated test | `docker compose -f compose.yml -f compose.modular.yml -f compose.test.yml ...` | run disposable local tests without touching default KIT volumes |

## Reproducibility Against KIT

The copied deployment baseline is checked byte-for-byte against the current KIT
checkout:

```powershell
python .\modular_repos\tools\verify_split_parity.py
```

If this check passes, the copied deployment files are identical to KIT. They
should provision the same stack when run with the same host, environment files,
secrets, images, and service versions.

## Local Development

Use this repo for deployment changes only. Do not patch crawler or post-script
source code here.

Recommended checks from the parent workspace:

```powershell
.\modular_repos\tools\run_full_function_test.ps1
python .\modular_repos\tools\verify_modules.py
python .\modular_repos\tools\verify_split_parity.py
python .\modular_repos\modules\oeds-deployment\tools\verify_deployment.py
```

Inside the standalone deployment repository, run the local-only verifier:

```powershell
python .\tools\verify_deployment.py --local-only
```

If Docker is available, validate the combined Compose model without starting
containers:

```powershell
cd .\modular_repos\modules\oeds-deployment
docker compose --profile crawlers -f compose.yml -f compose.modular.yml config
```

For an isolated disposable DB smoke test, add the test overlay:

```powershell
.\tools\test_db_smoke.ps1
```

The smoke script starts only `open-data`, waits for health, asserts the
`readonly` role, `postgis` extension, and `public.linear_interpolate` function,
then removes the disposable test volumes.

For a real crawler run against the disposable DB, use:

```powershell
.\tools\test_real_crawler_smoke.ps1 -RunPostScripts
```

This builds the modular crawler image, runs the SMARD crawler, executes the
legacy SMARD gapfill post-run script, asserts source and derived row counts, and
removes the disposable test volumes.

For a local setup smoke covering the service stack, use:

```powershell
.\tools\test_stack_smoke.ps1
```

This starts `open-data`, PostGREST, Grafana, and the crawler admin UI on the
isolated test ports, verifies HTTP readiness, and removes the disposable
containers and volumes.

For the active configured crawler set, use:

```powershell
.\tools\test_active_crawlers_smoke.ps1 -IncludeEntsoeFms
```

This runs ENTSO-E API, ENTSO-E FMS EnergyPrices, power-system data, and weather
forecast with reduced windows against the disposable DB. It copies only the
required static mapping files and `.env` into an ignored temporary runtime
directory, then removes that directory after the test.

## Publication Boundary

Do not publish local runtime content:

- `.env` and `.env.*`
- `runtime/`
- `.tmp/`
- `logs/`
- `crawler_admin_state/`
- Docker volumes or generated DB data

The deployment repo may publish Compose files, Dockerfiles, Ansible playbooks,
provisioning assets, smoke-test scripts, and documented examples.

## Required Interfaces

- component version pins
- database service contract
- deployment smoke tests
