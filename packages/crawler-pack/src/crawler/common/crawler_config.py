"""Build one crawler's effective config from CRAWLER_CONFIG.yml.

The file has a ``default`` section and one section per crawler; a crawler section
may hold named ``jobs`` whose keys override the section. This module applies the
same merge the scheduler uses, so ``oeds-crawl`` and scheduled runs hand the
crawler an identical config.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import yaml

# Keys that only the scheduler interprets; they never reach a crawler.
SCHEDULER_KEYS = frozenset({
    "enable",
    "enabled",
    "jobs",
    "post_run_commands",
    "post_run_scripts",
    "run_post_scripts",
    "schedule",
})


def merge_mappings(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``."""
    merged = deepcopy(dict(base))
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(value, Mapping) and isinstance(current, Mapping):
            merged[key] = merge_mappings(current, value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_config_file(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: the crawler config must be a mapping")
    return dict(raw)


def crawler_sections(raw_config: Mapping[str, Any]) -> list[str]:
    return [name for name, value in raw_config.items() if name != "default" and isinstance(value, Mapping)]


def job_names(raw_config: Mapping[str, Any], crawler_name: str) -> list[str]:
    jobs = (raw_config.get(crawler_name) or {}).get("jobs") or {}
    return [str(name) for name, value in jobs.items() if isinstance(value, Mapping)]


def effective_crawler_config(
    raw_config: Mapping[str, Any],
    crawler_name: str,
    job: str | None = None,
) -> dict[str, Any]:
    """Return the config dict a crawler constructor receives for ``crawler_name``.

    default section < crawler section < named job. ``schema_name`` defaults to the
    crawler name, ``db_uri`` and ``database_uri`` are both set, scheduler-only keys
    are removed and ``_scheduler_job_name`` / ``_scheduler_job_id`` are added.
    """
    default = raw_config.get("default") or {}
    if not isinstance(default, Mapping):
        raise ValueError("the default section must be a mapping")
    section = raw_config.get(crawler_name)
    if not isinstance(section, Mapping):
        raise KeyError(f"no section '{crawler_name}' in the crawler config")

    merged = merge_mappings(default, {key: value for key, value in section.items() if key != "jobs"})
    merged.setdefault("schema_name", crawler_name)

    if job is None:
        job_name = "default"
    else:
        jobs = section.get("jobs") or {}
        if not isinstance(jobs.get(job), Mapping):
            raise KeyError(f"crawler '{crawler_name}' has no job '{job}'")
        merged = merge_mappings(merged, jobs[job])
        job_name = str(job)
    merged["_scheduler_job_name"] = job_name
    merged["_scheduler_job_id"] = f"{crawler_name}:{job_name}"

    db_uri = merged.get("db_uri") or merged.get("database_uri")
    if not isinstance(db_uri, str) or not db_uri:
        raise ValueError(f"crawler '{crawler_name}': db_uri or database_uri is required")
    merged["db_uri"] = merged["database_uri"] = db_uri

    for key in SCHEDULER_KEYS:
        merged.pop(key, None)
    return merged
