# Testing And Reproducibility

This document defines how the local modular split is tested against the current
KIT version.

Latest recorded local test run:

```text
docs/test-run-2026-06-02.md
```

## Test Layers

| Layer | Command | What it proves |
| --- | --- | --- |
| Module wiring | `python .\modular_repos\tools\verify_modules.py` | registry priority, scheduler contracts, post-command mapping, copied artifact presence |
| Byte parity | `python .\modular_repos\tools\verify_split_parity.py` | copied post-script, deployment, and admin UI files match the current KIT checkout byte-for-byte |
| Deployment smoke | `python .\modular_repos\modules\oeds-deployment\tools\verify_deployment.py` | modular overlay references existing component paths and Dockerfile wiring |
| Compose model | `docker compose --profile crawlers -f compose.yml -f compose.modular.yml config` from `modules/oeds-deployment` | Docker can render the modular deployment model without starting containers |
| Isolated DB model | `docker compose -f compose.yml -f compose.modular.yml -f compose.test.yml config` from `modules/oeds-deployment` | disposable test ports and volumes avoid default KIT data collisions |
| Isolated DB smoke | `.\tools\test_db_smoke.ps1` from `modules/oeds-deployment` | starts `open-data`, verifies init role/extension/function, then removes test volumes |
| Real crawler smoke | `.\tools\test_real_crawler_smoke.ps1 -RunPostScripts` from `modules/oeds-deployment` | builds the modular crawler image, runs SMARD against a fresh DB, runs `gapfill_smard.py`, verifies source and derived row counts |
| Active crawler smoke | `.\tools\test_active_crawlers_smoke.ps1 -IncludeEntsoeFms` from `modules/oeds-deployment` | runs the active configured crawler set with reduced windows: ENTSO-E API, ENTSO-E FMS EnergyPrices, power-system data, and weather forecast |
| Stack smoke | `.\tools\test_stack_smoke.ps1` from `modules/oeds-deployment` | starts DB, PostGREST, Grafana, and Crawler Admin with isolated ports and verifies HTTP readiness |
| Python syntax | `python -m compileall ...` | copied Python files are importable/parseable in the current environment |

## Current Reproducibility Statement

For `oeds-post-scripts`, `oeds-deployment`, and the extracted admin UI, the
current split keeps copied KIT files byte-parity checked. These modules should
reproduce the same results as KIT when run with the same:

- Python environment and installed dependencies
- database contents and schema state
- credentials and environment variables
- external API/file availability
- Docker/Ansible host context

For `oeds-scheduler-ui`, the code is a modular rewrite rather than a direct
copy, except for the copied admin UI. Reproducibility is checked through
contract tests for:

- config merge semantics
- named job expansion
- post-run script metadata
- registry priority
- constructor compatibility
- queue locking and daemon ticks

## What Is Not Yet Proven

The local checks now execute the active crawler set with reduced windows plus
the SMARD legacy post-run path. Full equivalence across every optional crawler
family still needs broader integration tests because several disabled crawlers
depend on API credentials, SFTP access, external package subscriptions, or
large downloads.

Recommended next integration scenarios:

1. Run `smard` regularly with `.\tools\test_real_crawler_smoke.ps1 -RunPostScripts`.
2. Run the active crawler set with `.\tools\test_active_crawlers_smoke.ps1 -IncludeEntsoeFms`.
3. Run `.\tools\test_stack_smoke.ps1` after Compose/Admin changes.
4. Run broader `entsoe_fms` windows with `oeds-post gapfill entsoe-fms`
   and `oeds-post refresh entsoe-availability-map`.
5. Run `entsoe_api` with `oeds-post forecast day-ahead-price` in self-test or
   API-backed mode.
6. Compare row counts, derived schemas, and run metadata against the current KIT
   commands.

## Baseline Commands

```powershell
python .\modular_repos\tools\verify_modules.py
python .\modular_repos\tools\verify_split_parity.py
python .\modular_repos\modules\oeds-deployment\tools\verify_deployment.py
python -m compileall .\modular_repos\modules\oeds-post-scripts .\modular_repos\modules\oeds-scheduler-ui\src .\modular_repos\modules\oeds-crawler-pack\src .\modular_repos\tools
```

```powershell
cd .\modular_repos\modules\oeds-deployment
.\tools\test_db_smoke.ps1
.\tools\test_real_crawler_smoke.ps1 -RunPostScripts
.\tools\test_active_crawlers_smoke.ps1 -IncludeEntsoeFms
.\tools\test_stack_smoke.ps1
```
