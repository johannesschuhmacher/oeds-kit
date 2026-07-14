# Changelog

## 0.0.0-local

- Initial local split repository for stable `oeds-post` commands.
- Copied current KIT gapfill, forecast, refresh, and derived-data scripts.
- Added config migration from legacy `post_run_scripts` to stable commands.
- Added repo-root resolution and first direct-call support for scripts with
  safe `main()` entry points.
- Added starter GitHub Actions CI for compile and unit test checks.
