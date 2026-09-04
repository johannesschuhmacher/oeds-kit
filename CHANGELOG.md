# Changelog

## 0.0.0-local

- Initial local split repository for KIT deployment assets.
- Copied current Compose, Docker, Ansible, provisioning, and ops files.
- Added `compose.modular.yml`, `Dockerfile.crawler-modular`, and a local
  deployment smoke verifier for the repository split.
- Added isolated DB, real SMARD crawler, SMARD post-run, and stack smoke tests.
- Added active configured crawler smoke coverage for ENTSO-E API, ENTSO-E FMS
  EnergyPrices, power-system data, and weather forecast.
- Set modular image `PYTHONPATH=/app` and passed `OEDS_ADMIN_REPO_ROOT=/app`
  for runtime-mounted Admin UI operation.
- Added starter GitHub Actions CI and a `--local-only` deployment repository
  verification mode.
- Install the complete official OEDS crawler requirements on Python 3.13 and
  pass the runtime crawler-config path to post-processing commands.
- Bound ENTSO-E FMS backfills to the requested file period and migrate the
  consumption-unavailability table for current source columns.
- Pin the scheduler constructor audit that rejects unsupported additional
  required parameters in legacy crawler modules.
- Keep the generated Ansible inventory inside a custom `--work-dir` unless an
  explicit `OEDS_ANSIBLE_INVENTORY_FILE` is configured.
