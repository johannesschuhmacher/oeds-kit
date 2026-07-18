# Repository Naming Options

This document collects local naming options for the planned modular OEDS
repositories. No remote repository has been created from this list.

## Recommended Set

| Local module | Recommended repo name | Reason |
| --- | --- | --- |
| OEDS core | `open-energy-data-server` | Keep the original project as the center. |
| Scheduler and admin UI | `oeds-scheduler-ui` | Clear responsibility, short enough for CLI/docs. |
| Post-processing scripts | `oeds-post-scripts` | Matches the `oeds-post` command facade. |
| Deployment, operations, and compatibility | `oeds-deployment` | Covers Compose, Docker, Ansible, ops tooling, and the compatibility manifest. |
| Optional crawler registry | `oeds-crawler-pack` | Only needed while KIT crawler preference is external to core. |

## Alternative Names

| Module | Option A | Option B | Notes |
| --- | --- | --- | --- |
| Scheduler and admin UI | `oeds-scheduler-admin` | `oeds-operator-ui` | `oeds-scheduler-ui` is more explicit and neutral. |
| Post-processing scripts | `oeds-postprocessing` | `oeds-derived-data` | `oeds-post-scripts` maps directly to `oeds-post`. |
| Deployment | `oeds-ops` | `oeds-infra` | `oeds-deployment` is clearer for public users. |
| Crawler registry | `oeds-crawler-extensions` | `oeds-kit-crawlers` | Keep only if improved crawlers are not yet merged into core. |

## Naming Rules

- Prefer `oeds-*` for add-on modules so they group naturally in GitHub/GitLab.
- Keep the original `open-energy-data-server` name for the core.
- Avoid putting `KIT` into generic module names unless the module is truly
  KIT-specific and should not become a general OEDS component.
- Do not name a module as if it owns crawler base logic unless it actually owns
  that code. Shared crawler runtime logic belongs in OEDS core.

## Current Recommendation

Use:

```text
open-energy-data-server
oeds-scheduler-ui
oeds-post-scripts
oeds-deployment
```

Keep `oeds-crawler-pack` local for now as a transition aid. If all improved
KIT crawlers and the shared `crawler_core` contract move into OEDS core, this
repo can stay unpublished or become a small optional registry package.

Do not create a separate distribution repository for now. The final system is
intended to stay compatible across modules, so the version and compatibility
matrix belongs in `oeds-deployment/compatibility.yml`.
