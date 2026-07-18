# Crawler Preservation Strategy

The modular split must not reduce crawler functionality. The current KIT
crawler set is treated as the functional reference until each crawler is either
merged into upstream OEDS, kept as a documented extension, or explicitly
deprecated.

## Core Decision

OEDS remains the center of the architecture, but "center" means shared package,
contract, registry, and governance. It does not mean that the older upstream
implementation automatically wins when KIT has a more complete crawler.

The migration rule is:

```text
Best implementation wins, and no current KIT crawler behavior is removed without
an explicit replacement or deprecation decision.
```

## Current Inventory Snapshot

Compared repositories:

- OEDS core: `sources/oeds-core`
- OEDS-KIT current: `sources/oeds-kit-current`

### Present Only in Upstream OEDS

These crawlers exist in upstream OEDS but not in the current KIT crawler
package:

```text
chargepoint.py
dwd.py
e2watch.py
ecmwf_crawler.py
eon_grid_fees.py
fernwaerme_preisuebersicht.py
gie_crawler.py
instrat_pl.py
jao_crawler.py
jrc_idees.py
nuts_mapper.py
oep.py
opec.py
refit.py
synpro.py
```

These should remain available through OEDS core unless a replacement is
documented.

### Present Only in KIT

These crawlers exist in the current KIT crawler package but not in upstream
OEDS:

```text
axxteq.py
copernicus_cds.py
dwd_cdc.py
ecmwf.py
eia.py
energy_forecast_crawler.py
enet.py
entsoe_api.py
entsoe_fms.py
epex_spot.py
eurostat_crawler.py
gie_agsi_alsi.py
open_meteo.py
osm_power.py
power_system_data.py
prisma_capacity.py
scigrid.py
tradinghub.py
weather_forecast.py
```

These must not disappear. They should either become upstream OEDS crawlers or
be registered through an add-on crawler package.

### Present in Both

These crawler filenames exist in both trees:

```text
eex.py
entsoe_crawler.py
entsog.py
eview.py
frequency.py
iwugebaeudetypen.py
ladesaeulenregister.py
londondatastore.py
mastr.py
netztransparenz.py
ninja.py
nrw_kwp_waermedichte.py
opsd.py
regelleistung.py
smard.py
vea_industrial_load_profiles.py
windmodel.py
```

For these, the migration must compare behavior before choosing the final owner.
The KIT version often uses the newer `BaseCrawler.run()` model, while upstream
often uses `ContinuousCrawler` or `DownloadOnceCrawler`. That is an interface
difference and may also hide real behavioral differences.

## New Local Module: `oeds-crawler-pack`

To avoid losing functionality while upstream integration is still open, this
workspace includes a new local staging module:

```text
modules/oeds-crawler-pack
```

Purpose:

- preserve KIT crawler implementations during the split
- expose KIT-only crawlers through a clean registry
- optionally override older upstream crawler implementations in the deployable
  crawler set
- provide a place for tests before upstream PRs are prepared

This module can be temporary. The preferred final state is still to upstream
generally useful crawler improvements into OEDS core.

## Registry Priority

The merged registry should resolve crawlers in this order:

1. Explicit deployment override
2. `oeds-crawler-pack` enhanced crawler
3. OEDS core crawler

This prevents accidental regression when a crawler exists in both repositories.

Example:

```text
smard -> oeds-crawler-pack version until upstream OEDS has equivalent behavior
entsoe_fms -> oeds-crawler-pack because upstream OEDS has no equivalent
chargepoint -> OEDS core because KIT currently has no equivalent
```

## Promotion Paths

Each KIT crawler should be assigned one of four outcomes:

### Outcome A: Upstream Replace or Upgrade

Use when the KIT implementation is generally better and not KIT-specific.

Examples may include:

- improved `smard`
- improved `netztransparenz`
- improved `regelleistung`
- improved `entsog`

Result:

- open PR against upstream OEDS
- keep compatibility tests
- remove override from `oeds-crawler-pack` after upstream release

### Outcome B: Upstream New Crawler

Use when a KIT-only crawler is broadly useful.

Examples may include:

- `entsoe_api`
- `eurostat_crawler`
- `open_meteo`
- `dwd_cdc`

Result:

- open PR against upstream OEDS
- document source, auth, schema, and tests

### Outcome C: Add-On Crawler

Use when the crawler is useful but should not be part of upstream core because
of scope, credentials, size, or project-specific dependencies.

Examples may include:

- `entsoe_fms`
- `energy_forecast_crawler`
- `epex_spot`
- `prisma_capacity`

Result:

- keep in `oeds-crawler-pack`
- register through OEDS crawler entry points
- document it as an extension crawler

### Outcome D: Deprecated or Archived

Use only with explicit agreement.

Result:

- record why it is deprecated
- provide migration path or replacement
- keep a final archive tag if needed

## No-Loss Gates

A crawler may only move, be replaced, or be removed if these checks pass:

1. Import check:
   The crawler can be discovered through the registry.

2. Construction check:
   The crawler can be constructed from normalized config.

3. Runtime check:
   The scheduler can execute it through `run()`, `crawl_temporal()`, or
   `crawl_structural()`.

4. Config check:
   Existing `CRAWLER_CONFIG.yml` options are either still supported or have a
   documented migration.

5. Output check:
   Existing schemas and important table names remain compatible, or migrations
   are documented.

6. Credential check:
   Existing `.env` and deployment credential names still work, or replacements
   are documented.

7. Test check:
   At least one unit or smoke test covers the crawler's key behavior.

8. Documentation check:
   Source, authentication, run command, output schema, and downstream consumers
   are documented.

## Practical Next Step

The first implementation step should not be to delete or replace crawlers.
Instead:

1. Build a crawler registry that can load both OEDS core and
   `oeds-crawler-pack`.
2. Copy or move no crawler implementation until registry tests exist.
3. Add tests proving that the scheduler sees:
   - OEDS-only crawlers
   - KIT-only crawlers
   - KIT overrides for duplicate crawler names
4. Then migrate one low-risk crawler end to end.

Recommended first low-risk candidates:

- `smard` as a duplicate crawler with KIT preferred
- `eurostat_crawler` as KIT-only
- `chargepoint` as upstream-only

This three-crawler pilot proves all three paths without touching the most
complex ENTSO-E workflows first.
