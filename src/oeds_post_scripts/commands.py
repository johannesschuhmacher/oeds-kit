"""Stable post-run command registry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class PostCommandSpec:
    """Mapping from stable post command to current legacy script."""

    group: str
    action: str
    legacy_script: str
    default_args: tuple[str, ...] = ()
    description: str = ""
    aliases: tuple[tuple[str, str], ...] = ()

    @property
    def command_name(self) -> str:
        return f"{self.group} {self.action}"

    @property
    def scheduler_command(self) -> str:
        return f"oeds-post {self.command_name}"


@dataclass(frozen=True)
class ResolvedPostCommand:
    """Resolved stable post command plus forwarded args."""

    spec: PostCommandSpec
    extra_args: tuple[str, ...] = ()

    @property
    def scheduler_command(self) -> str:
        parts = [self.spec.scheduler_command, *self.extra_args]
        return " ".join(parts)


POST_COMMANDS: tuple[PostCommandSpec, ...] = (
    PostCommandSpec(
        group="gapfill",
        action="smard",
        legacy_script="scripts/gapfill_smard.py",
        description="Run the legacy SMARD gapfill helper.",
    ),
    PostCommandSpec(
        group="gapfill",
        action="entsoe-fms",
        legacy_script="scripts/gapfill_timeseries.py",
        default_args=("--job", "entsoe_fms"),
        description="Run generic time-series gapfilling for ENTSO-E FMS.",
        aliases=(("gapfill", "entsoe_fms"),),
    ),
    PostCommandSpec(
        group="refresh",
        action="entsoe-availability-map",
        legacy_script="scripts/refresh_entsoe_availability_map.py",
        description="Refresh derived ENTSO-E availability map SQL objects.",
        aliases=(("refresh", "availability-map"),),
    ),
    PostCommandSpec(
        group="forecast",
        action="day-ahead-price",
        legacy_script="scripts/run_price_forecast.py",
        description="Run the derived day-ahead price forecast pipeline.",
        aliases=(("forecast", "price"),),
    ),
    PostCommandSpec(
        group="backfill",
        action="entsoe-unavailability",
        legacy_script="scripts/backfill_entsoe_unavailability.py",
        description="Backfill ENTSO-E unavailability data and refresh availability map.",
        aliases=(("backfill", "entsoe-fms-unavailability"),),
    ),
)

_COMMAND_INDEX: dict[tuple[str, str], PostCommandSpec] = {}
for _spec in POST_COMMANDS:
    _COMMAND_INDEX[(_spec.group, _spec.action)] = _spec
    for _alias in _spec.aliases:
        _COMMAND_INDEX[_alias] = _spec

LEGACY_SCRIPT_COMMANDS: dict[str, str] = {
    spec.legacy_script.replace("\\", "/"): spec.scheduler_command
    for spec in POST_COMMANDS
}


def list_post_commands() -> tuple[PostCommandSpec, ...]:
    """Return all canonical stable post commands."""

    return POST_COMMANDS


def resolve_post_command(args: Sequence[str]) -> ResolvedPostCommand:
    """Resolve CLI args like ``gapfill entsoe-fms`` to a legacy script."""

    if len(args) < 2:
        raise ValueError("post command requires a group and action")

    group = _normalize_token(args[0])
    action = _normalize_token(args[1])
    try:
        spec = _COMMAND_INDEX[(group, action)]
    except KeyError as exc:
        raise ValueError(f"unknown post command: {group} {action}") from exc
    return ResolvedPostCommand(spec=spec, extra_args=tuple(args[2:]))


def command_to_legacy_argv(
    command: ResolvedPostCommand,
    *,
    repo_root: str | Path = ".",
) -> tuple[str, ...]:
    """Convert a stable post command to a legacy script argv."""

    root = Path(repo_root)
    script_path = root / command.spec.legacy_script
    return (
        str(script_path),
        *command.spec.default_args,
        *command.extra_args,
    )


def script_to_post_command(script_path: str | Path) -> str | None:
    """Return the stable command that replaces a legacy script path."""

    normalized = str(script_path).replace("\\", "/")
    return LEGACY_SCRIPT_COMMANDS.get(normalized)


def _normalize_token(value: str) -> str:
    return value.strip().lower().replace("_", "-")
