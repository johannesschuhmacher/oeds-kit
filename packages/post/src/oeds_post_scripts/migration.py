"""Helpers for migrating legacy post-run script paths to stable commands."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from oeds_post_scripts.commands import script_to_post_command


@dataclass(frozen=True)
class PostCommandReplacement:
    """One legacy post-run script replacement."""

    crawler_name: str
    job_name: str | None
    old_command: str
    new_command: str


def migrate_post_run_scripts(
    config: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[PostCommandReplacement, ...]]:
    """Replace known legacy post-run script paths with stable commands."""

    migrated = deepcopy(dict(config))
    replacements: list[PostCommandReplacement] = []

    for crawler_name, crawler_config in migrated.items():
        if crawler_name == "default" or not isinstance(crawler_config, dict):
            continue

        _replace_post_run_list(
            crawler_config,
            crawler_name=str(crawler_name),
            job_name=None,
            replacements=replacements,
        )

        jobs = crawler_config.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_name, job_config in jobs.items():
            if not isinstance(job_config, dict):
                continue
            _replace_post_run_list(
                job_config,
                crawler_name=str(crawler_name),
                job_name=str(job_name),
                replacements=replacements,
            )

    return migrated, tuple(replacements)


def _replace_post_run_list(
    config: dict[str, Any],
    *,
    crawler_name: str,
    job_name: str | None,
    replacements: list[PostCommandReplacement],
) -> None:
    post_run_scripts = config.get("post_run_scripts")
    if not isinstance(post_run_scripts, list):
        return

    migrated_scripts: list[Any] = []
    for command in post_run_scripts:
        if not isinstance(command, str):
            migrated_scripts.append(command)
            continue

        replacement = script_to_post_command(command)
        if replacement is None:
            migrated_scripts.append(command)
            continue

        migrated_scripts.append(replacement)
        replacements.append(
            PostCommandReplacement(
                crawler_name=crawler_name,
                job_name=job_name,
                old_command=command,
                new_command=replacement,
            )
        )

    config["post_run_scripts"] = migrated_scripts
