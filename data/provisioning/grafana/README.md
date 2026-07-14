# Grafana Provisioning Layout

Grafana file provisioning reads all dashboards below
`data/provisioning/grafana/dashboards/` with
`foldersFromFilesStructure: true`.

## Folder rules

- Use one top-level folder per crawler, named after the crawler entry in
  `CRAWLER_CONFIG.yml`.
- Use `shared/` for cross-crawler, governance, or imported reference
  dashboards that are not owned by a single crawler.
- Keep provisioned dashboard JSON files exactly one directory below
  `dashboards/` so Grafana creates one visible folder per crawler/domain.
- Do not keep empty placeholder folders in git. Create the folder when the
  first real provisioned dashboard exists.

## Naming rules

- Each crawler should get one required signature basic dashboard at
  `dashboards/<crawler>/Signature_Basic.json`.
- Specialized dashboards should stay in the same crawler folder and use a
  descriptive topic name.
