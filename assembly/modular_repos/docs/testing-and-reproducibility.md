# Testing And Reproducibility

The release boundary is the set of commits pinned by
`oeds-deployment/compatibility.yml`. Reproducibility no longer depends on a KIT
monorepository checkout or byte-for-byte comparison with that repository.

## Test Layers

| Layer | Command | Evidence |
| --- | --- | --- |
| Module contracts | `python modular_repos/tools/verify_modules.py` | registry priority, constructor compatibility, scheduler contracts, post commands |
| Deployment structure | `python modular_repos/modules/oeds-deployment/tools/verify_deployment.py` | component paths, manifest, Compose, Dockerfile, Ansible, smoke tools |
| Package tests | module-local `uv run --with pytest python -m pytest -q` | standalone crawler-pack, scheduler/UI, and post-script behavior |
| Image build | `docker compose --profile crawlers -f compose.yml build scheduler` | official core and all add-ons install together |
| Database smoke | `tools/test_db_smoke.sh` or `.ps1` | PostgreSQL initialization, roles, extensions, SQL functions |
| Real crawler smoke | `tools/test_real_crawler_smoke.sh --run-post-scripts` | SMARD source rows and gapfilled output |
| Active crawler smoke | `tools/test_active_crawlers_smoke.sh --include-entsoe-fms` | bounded active crawler runs and expected tables |
| Stack smoke | `tools/test_stack_smoke.sh` | database, PostgREST, Grafana, and Admin UI readiness |
| Fresh install | `tools/oeds_clean_install_from_git.sh --reset ...` | clone, assembly, Ansible, Compose, live data, and cleanup on Linux |

## Source Revisions

The assembler checks out every component at the exact commit recorded in
`compatibility.yml` and verifies the resulting `HEAD`. The official OEDS core
is one of these components and remains unmodified. The Crawler Pack contains
the current KIT crawler implementations and temporary adapter explicitly,
rather than obtaining them from an implicit workspace path.

The same result still depends on the same runtime inputs:

- crawler configuration
- Python and container versions
- database state
- credentials and source permissions
- upstream API or download availability

## Baseline Commands

From an assembled workspace on Windows:

```powershell
python .\modular_repos\tools\verify_modules.py
python .\modular_repos\modules\oeds-deployment\tools\verify_deployment.py

cd .\modular_repos\modules\oeds-deployment
docker compose --profile crawlers -f compose.yml config --quiet
.\tools\test_db_smoke.ps1
.\tools\test_real_crawler_smoke.ps1 -RunPostScripts
.\tools\test_active_crawlers_smoke.ps1 -IncludeEntsoeFms
.\tools\test_stack_smoke.ps1
```

Equivalent `.sh` smoke scripts are provided for Linux. Credential-dependent or
large crawlers must be tested separately with their required environment and
bounded time windows.
