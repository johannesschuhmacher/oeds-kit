# Changelog

## Unreleased

- Normalize current ALSI LNG values with explicit units and compatible schema upgrades.
- Derive SMARD metadata coverage from stored timestamps.
- Stream MaStR ZIP members and support small, repeatable table samples.

## 0.1.0

- Bundled all current KIT crawler implementations and required data mappings.
- Bundled the temporary BaseCrawler and `crawler_core` compatibility layer.
- Removed runtime discovery from the KIT monorepository.

## 0.0.0-local

- Initial local split repository for KIT-preferred crawler registry metadata.
- Registry facade discovers KIT crawler specs from the local source tree.
- Upstream OEDS crawler specs remain available through the merged registry
  inventory.
- Added starter GitHub Actions CI and fixture-based registry tests that can run
  without a checked-out KIT workspace.
