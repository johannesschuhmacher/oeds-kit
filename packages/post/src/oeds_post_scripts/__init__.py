"""Post-run command facade for OEDS."""

from oeds_post_scripts.commands import (
    LEGACY_SCRIPT_COMMANDS,
    POST_COMMANDS,
    PostCommandSpec,
    ResolvedPostCommand,
    command_to_legacy_argv,
    list_post_commands,
    resolve_post_command,
    script_to_post_command,
)
from oeds_post_scripts.runner import (
    PostCommandResult,
    resolve_post_repo_root,
    run_post_command,
)
from oeds_post_scripts.migration import (
    PostCommandReplacement,
    migrate_post_run_scripts,
)

__all__ = [
    "LEGACY_SCRIPT_COMMANDS",
    "POST_COMMANDS",
    "PostCommandResult",
    "PostCommandReplacement",
    "PostCommandSpec",
    "ResolvedPostCommand",
    "command_to_legacy_argv",
    "list_post_commands",
    "resolve_post_command",
    "resolve_post_repo_root",
    "run_post_command",
    "migrate_post_run_scripts",
    "script_to_post_command",
]
