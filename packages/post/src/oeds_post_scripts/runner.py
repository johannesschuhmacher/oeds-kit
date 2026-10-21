"""Execution helpers for stable post-run commands."""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Sequence

from oeds_post_scripts.commands import command_to_legacy_argv, resolve_post_command


@dataclass(frozen=True)
class PostCommandResult:
    """Result of a stable post command execution."""

    command: str
    argv: tuple[str, ...]
    returncode: int
    success: bool
    execution_mode: str = "subprocess"


_DIRECT_MAIN_SCRIPTS: dict[str, tuple[str, str, bool]] = {
    "scripts/gapfill_timeseries.py": ("scripts.gapfill_timeseries", "main", False),
    "scripts/refresh_entsoe_availability_map.py": (
        "scripts.refresh_entsoe_availability_map",
        "main",
        False,
    ),
    "scripts/run_price_forecast.py": ("scripts.run_price_forecast", "main", True),
    "scripts/backfill_entsoe_unavailability.py": (
        "scripts.backfill_entsoe_unavailability",
        "main",
        False,
    ),
}


def run_post_command(
    args: Sequence[str],
    *,
    repo_root: str | Path | None = None,
    prefer_direct: bool = True,
) -> PostCommandResult:
    """Run a stable post command through its current legacy script."""

    resolved_repo_root = resolve_post_repo_root(repo_root)
    resolved = resolve_post_command(args)
    legacy_argv = command_to_legacy_argv(resolved, repo_root=resolved_repo_root)
    if prefer_direct:
        direct_returncode = _run_direct_main_if_available(
            resolved.spec.legacy_script,
            resolved_repo_root,
            (
                *resolved.spec.default_args,
                *resolved.extra_args,
            ),
        )
        if direct_returncode is not None:
            return PostCommandResult(
                command=resolved.scheduler_command,
                argv=legacy_argv,
                returncode=direct_returncode,
                success=direct_returncode == 0,
                execution_mode="direct",
            )

    completed = subprocess.run(
        [sys.executable, *legacy_argv],
        cwd=resolved_repo_root,
        check=False,
    )
    return PostCommandResult(
        command=resolved.scheduler_command,
        argv=legacy_argv,
        returncode=completed.returncode,
        success=completed.returncode == 0,
        execution_mode="subprocess",
    )


def resolve_post_repo_root(repo_root: str | Path | None = None) -> Path:
    """Resolve the root containing legacy-compatible post-script paths."""

    if repo_root is not None:
        return Path(repo_root).resolve()

    env_root = os.getenv("OEDS_POST_REPO_ROOT")
    if env_root:
        return Path(env_root).resolve()

    cwd = Path.cwd().resolve()
    if (cwd / "scripts").is_dir():
        return cwd

    for candidate in Path(__file__).resolve().parents:
        if (candidate / "scripts").is_dir():
            return candidate

    return cwd


def _run_direct_main_if_available(
    legacy_script: str,
    repo_root: Path,
    forwarded_args: Sequence[str],
) -> int | None:
    direct_target = _DIRECT_MAIN_SCRIPTS.get(legacy_script.replace("\\", "/"))
    if direct_target is None:
        return None

    module_name, function_name, accepts_argv = direct_target
    old_argv = sys.argv[:]
    added_sys_paths: list[str] = []
    try:
        for path in (repo_root, repo_root / "scripts"):
            path_text = str(path)
            if path_text not in sys.path:
                sys.path.insert(0, path_text)
                added_sys_paths.append(path_text)
        module = import_module(module_name)
        main_func = getattr(module, function_name)
        if accepts_argv:
            result = main_func(list(forwarded_args))
        else:
            sys.argv = [str(repo_root / legacy_script), *forwarded_args]
            result = main_func()
    except ModuleNotFoundError:
        return None
    except SystemExit as exc:
        return _system_exit_code(exc)
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        sys.argv = old_argv
        for path_text in added_sys_paths:
            try:
                sys.path.remove(path_text)
            except ValueError:
                pass

    if result is None:
        return 0
    return int(result)


def _system_exit_code(exc: SystemExit) -> int:
    if exc.code is None:
        return 0
    if isinstance(exc.code, int):
        return exc.code
    print(exc.code, file=sys.stderr)
    return 1
