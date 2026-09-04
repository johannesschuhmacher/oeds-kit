# Changelog

## 0.1.0

- Packaged post-processing scripts, helper packages, and SQL resources.
- Declared runtime and optional price-forecast dependencies.
- Removed the installed CLI's dependency on a KIT monorepository checkout.

## 0.0.0-local

- Initial local split repository for stable `oeds-post` commands.
- Copied current KIT gapfill, forecast, refresh, and derived-data scripts.
- Added config migration from legacy `post_run_scripts` to stable commands.
- Added repo-root resolution and first direct-call support for scripts with
  safe `main()` entry points.
- Added starter GitHub Actions CI for compile and unit test checks.
