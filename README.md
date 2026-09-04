# oeds-crawler-pack

Installable repository for the KIT crawler extensions while upstream OEDS
remains the base project.

This repository is part of the modular OEDS stack. The shared crawler and
database core remains in
[open-energy-data-server](https://github.com/open-energy-data-server/open-energy-data-server),
while deployment, scheduling/UI, and post-processing live in
[oeds-deployment](https://github.com/johannesschuhmacher/oeds-deployment),
[oeds-scheduler-ui](https://github.com/johannesschuhmacher/oeds-scheduler-ui),
and [oeds-post-scripts](https://github.com/johannesschuhmacher/oeds-post-scripts).

## Responsibility

This module contains the KIT-enhanced crawler implementations, their registry,
and the current compatibility implementation of `crawler.common.BaseCrawler`.
It does not contain the scheduler, post-run scripts, or deployment.

The generic parts of `crawler_core`, `BaseCrawler`, database URI handling, and
the crawler contract are intended for an upstream contribution to OEDS. Until
that contribution is accepted, the compatibility code is kept here so the
published modules work without the KIT monorepository.

This package exists to prevent functionality loss while improved KIT crawlers
are prepared for upstream OEDS or kept as extension crawlers.

## Current Behavior

- ships all current KIT crawler implementations as importable `crawler.*`
- ships the temporary `crawler_core` and BaseCrawler compatibility API
- discovers crawlers from its own installed package
- exposes stable crawler specs such as `crawler.smard:SmardCrawler`
- gives KIT crawler specs priority over upstream OEDS when the deployment stack
  merges registries
- keeps upstream-only crawlers available through `oeds-core`

The registry priority is:

```text
oeds-crawler-pack before oeds-core
```

## Local Development

Install and test this repository directly:

```powershell
uv sync
uv run pytest
uv run python -c "from oeds_crawler_pack import get_crawler_specs; print(get_crawler_specs())"
```

No checkout of `open-energy-data-server-KIT` is required.

## Policy

No crawler should be removed from the deployable crawler set until it has one of
these documented outcomes:

- merged into upstream OEDS
- kept here as an extension crawler
- replaced by a verified equivalent
- explicitly deprecated

## Out Of Scope

- scheduler UI
- deployment playbooks
- post-run gapfill or forecast pipelines
