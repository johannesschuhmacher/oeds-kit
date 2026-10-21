# Changelog

## Unreleased

- Make scheduled run outcomes visible: the daemon logs every run result, a
  failed crawler run logs CRITICAL on the crawler's own logger (which sends the
  configured alert mail), and a failing tick (for example a broken config file)
  no longer terminates the daemon.
- Treat a crawler raising `CrawlerSkipped` (detected by class name) as status
  `skipped` instead of `failed` in the scheduler runtime and the admin UI.
- Apply `OEDS_EMAIL_*` environment overrides when the scheduler daemon loads
  its config, matching the admin UI.

## 0.1.0

- Discover installed crawler modules without requiring crawler sources at the
  workspace root.
- Run admin post-processing actions through the stable `oeds-post` CLI.
- Reject crawler constructors with unsupported additional required parameters
  while continuing to allow optional constructor extensions.

## 0.0.0-local

- Initial local split repository for registry-based scheduler runtime.
- Added scheduler CLI, daemon wrapper, planning, queueing, and runtime contracts.
- Extracted the current KIT crawler admin UI, templates, static assets, and
  server launcher into this module.
- Fixed legacy post-run subprocess imports by prepending the workspace CWD to
  `PYTHONPATH`.
- Fixed Admin UI repository root resolution for installed/containerized runtime
  workspaces.
- Added starter GitHub Actions CI for compile and standalone scheduler-core
  test checks.
