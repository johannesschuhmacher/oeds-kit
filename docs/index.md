# oeds-kit

oeds-kit is the KIT extension of the
[Open Energy Data Server](https://github.com/open-energy-data-server/open-energy-data-server)
(OEDS). It collects energy-system data from public sources with scheduled
crawlers and stores them in PostgreSQL/TimescaleDB. The data can be queried with
SQL, over HTTP through PostgREST and in Grafana dashboards. The code is at
[github.com/johannesschuhmacher/oeds-kit](https://github.com/johannesschuhmacher/oeds-kit).

- New installation: [Install on a Linux VM](/deploy/README.md)
- Running server: [Operations](/deploy/playbooks/README.md) and
  [Crawler configuration](configuration.md)
- Data sources, tables and access keys: [Crawlers](crawlers/index.md)

```{toctree}
:caption: Install and operate
:maxdepth: 1

Overview </README>
Installation </deploy/README>
Operations </deploy/playbooks/README>
configuration
Grafana dashboards </deploy/data/provisioning/grafana/README>
```

```{toctree}
:caption: Data sources
:maxdepth: 1

crawlers/index
```

```{toctree}
:caption: Packages
:maxdepth: 1

Crawler pack </packages/crawler-pack/README>
Scheduler and admin UI </packages/scheduler/README>
Post-processing </packages/post/README>
```

```{toctree}
:caption: Tests and changes
:maxdepth: 1

Testing an installation </deploy/docs/testing>
Live crawler tests </deploy/docs/crawler-live-tests>
Test results </deploy/docs/test-results>
Changelog </CHANGELOG>
```
