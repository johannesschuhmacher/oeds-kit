"""Command line interface for OEDS post-run processing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from oeds_post_scripts.commands import (
    command_to_legacy_argv,
    list_post_commands,
    resolve_post_command,
    script_to_post_command,
)
from oeds_post_scripts.migration import migrate_post_run_scripts
from oeds_post_scripts.runner import resolve_post_repo_root, run_post_command


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="oeds-post")
    parser.add_argument(
        "--repo-root",
        default=None,
        help=(
            "repository root containing the legacy-compatible scripts directory; "
            "defaults to OEDS_POST_REPO_ROOT, the current working directory, or "
            "the installed module repo"
        ),
    )
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="print the legacy command instead of running it",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable command metadata",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list available stable post commands",
    )
    parser.add_argument(
        "--from-script",
        default=None,
        help="print the stable command replacing a legacy script path",
    )
    parser.add_argument(
        "--migrate-config",
        default=None,
        help="read a scheduler YAML config and replace known legacy post-run scripts",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="write migrated config to this path; omitted means report only",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit with code 1 when --migrate-config finds replacements",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    if args.list:
        _print_command_list(json_output=args.json)
        return

    if args.from_script:
        replacement = script_to_post_command(args.from_script)
        if replacement is None:
            raise SystemExit(f"no stable command for {args.from_script}")
        print(replacement)
        return

    if args.migrate_config:
        replacements_found = _migrate_config_file(
            Path(args.migrate_config),
            output_path=Path(args.output) if args.output else None,
            json_output=args.json,
        )
        if args.check and replacements_found:
            raise SystemExit(1)
        return

    command_args = tuple(arg for arg in args.command if arg != "--")
    try:
        resolved = resolve_post_command(command_args)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    repo_root = resolve_post_repo_root(args.repo_root)
    legacy_argv = command_to_legacy_argv(resolved, repo_root=repo_root)
    if args.print_command:
        if args.json:
            print(
                json.dumps(
                    {
                        "command": resolved.scheduler_command,
                        "legacy_argv": list(legacy_argv),
                        "repo_root": str(repo_root),
                    },
                    sort_keys=True,
                )
            )
        else:
            print(" ".join(legacy_argv))
        return

    result = run_post_command(command_args, repo_root=repo_root)
    if args.json:
        print(
            json.dumps(
                {
                    "command": result.command,
                    "execution_mode": result.execution_mode,
                    "legacy_argv": list(result.argv),
                    "repo_root": str(repo_root),
                    "returncode": result.returncode,
                    "success": result.success,
                },
                sort_keys=True,
            )
        )
    raise SystemExit(result.returncode)


def _print_command_list(*, json_output: bool) -> None:
    specs = list_post_commands()
    if json_output:
        print(
            json.dumps(
                [
                    {
                        "command": spec.scheduler_command,
                        "legacy_script": spec.legacy_script,
                        "default_args": list(spec.default_args),
                        "description": spec.description,
                    }
                    for spec in specs
                ],
                sort_keys=True,
            )
        )
        return

    for spec in specs:
        print(f"{spec.scheduler_command}\t{spec.legacy_script}")


def _migrate_config_file(
    config_path: Path,
    *,
    output_path: Path | None,
    json_output: bool,
) -> bool:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - package dependency.
        raise SystemExit("pyyaml is required for --migrate-config") from exc

    with config_path.open("r", encoding="utf-8") as file:
        raw_config = yaml.safe_load(file)
    if raw_config is None:
        raw_config = {}
    if not isinstance(raw_config, dict):
        raise SystemExit(f"config must be a YAML mapping: {config_path}")

    migrated, replacements = migrate_post_run_scripts(raw_config)

    if output_path is not None:
        with output_path.open("w", encoding="utf-8") as file:
            yaml.safe_dump(
                migrated,
                file,
                sort_keys=False,
                allow_unicode=False,
            )

    report = [
        {
            "crawler": replacement.crawler_name,
            "job": replacement.job_name,
            "old": replacement.old_command,
            "new": replacement.new_command,
        }
        for replacement in replacements
    ]
    if json_output:
        print(json.dumps(report, sort_keys=True))
    else:
        if not replacements:
            print("No legacy post-run scripts found.")
        for replacement in replacements:
            job_suffix = (
                f":{replacement.job_name}" if replacement.job_name is not None else ""
            )
            print(
                f"{replacement.crawler_name}{job_suffix}: "
                f"{replacement.old_command} -> {replacement.new_command}"
            )
        if output_path is not None:
            print(f"Wrote migrated config: {output_path}")

    return bool(replacements)


if __name__ == "__main__":
    main()
