"""Preflight checks before publishing the modular OEDS repositories."""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULES_ROOT = ROOT / "modules"

MODULES = {
    "oeds-crawler-pack": {
        "pyproject.toml",
        "src",
        "tests",
        "uv.lock",
    },
    "oeds-scheduler-ui": {
        "pyproject.toml",
        "src",
        "tests",
        "uv.lock",
    },
    "oeds-post-scripts": {
        "pyproject.toml",
        "src",
        "tests",
    },
    "oeds-deployment": {
        "compatibility.yml",
        "compose.yml",
        "compose.modular.yml",
        "compose.test.yml",
        "docker/Dockerfile.crawler-modular",
        "tools/verify_deployment.py",
        "tools/smoke_lib.sh",
        "tools/test_db_smoke.sh",
        "tools/test_real_crawler_smoke.sh",
        "tools/test_active_crawlers_smoke.sh",
        "tools/test_stack_smoke.sh",
    },
}

COMMON_MODULE_FILES = {
    "README.md",
    "CHANGELOG.md",
    ".gitignore",
    ".github/workflows/ci.yml",
    "LICENSES/AGPL-3.0-or-later.txt",
}

ROOT_FILES = {
    "README.md",
    ".gitignore",
    "docs/publication-readiness.md",
    "docs/intern-test-vm-modular-github-test-2026-09-04.md",
    "generated/CRAWLER_CONFIG.post.yml",
    "tools/check_publication_readiness.py",
    "tools/run_full_function_test.ps1",
    "tools/verify_modules.py",
}

FORBIDDEN_DIR_NAMES = {
    ".tmp",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "runtime",
    "logs",
    "crawler_admin_state",
    "docker_data",
}

FORBIDDEN_FILE_NAMES = {
    ".env",
}

FORBIDDEN_FILE_PATTERNS = (
    ".env.*",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.log",
    "*.sqlite3",
    "*.db",
)

COMPATIBILITY_TOKENS = (
    'version: "0.1.0-rc.2-github"',
    'status: "github-modular"',
    "https://github.com/johannesschuhmacher/oeds-crawler-pack.git",
    "https://github.com/johannesschuhmacher/oeds-scheduler-ui.git",
    "https://github.com/johannesschuhmacher/oeds-post-scripts.git",
    "https://github.com/johannesschuhmacher/oeds-deployment.git",
    "release_readiness:",
    "publication-readiness.md",
    "intern-test-vm-modular-github-test-2026-09-04.md",
    "test_active_crawlers_smoke.ps1 -IncludeEntsoeFms",
)


@dataclass
class GitState:
    status: str
    remotes: str


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _check_required_files(errors: list[str]) -> None:
    for relative_path in sorted(ROOT_FILES):
        path = ROOT / relative_path
        if not path.exists():
            errors.append(f"missing root artifact: {relative_path}")

    for module_name, module_files in MODULES.items():
        module_root = MODULES_ROOT / module_name
        if not module_root.is_dir():
            errors.append(f"missing module directory: modules/{module_name}")
            continue

        for relative_path in sorted(COMMON_MODULE_FILES | module_files):
            path = module_root / relative_path
            if not path.exists():
                errors.append(f"missing module artifact: modules/{module_name}/{relative_path}")


def _is_forbidden_file(name: str) -> bool:
    if name == ".env.example":
        return False
    if name in FORBIDDEN_FILE_NAMES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in FORBIDDEN_FILE_PATTERNS)


def _check_forbidden_artifacts(errors: list[str]) -> None:
    for module_name in MODULES:
        module_root = MODULES_ROOT / module_name
        if not module_root.is_dir():
            continue
        for current_root, dir_names, file_names in os.walk(module_root):
            if ".git" in dir_names:
                dir_names.remove(".git")

            for dir_name in list(dir_names):
                if dir_name in FORBIDDEN_DIR_NAMES:
                    path = Path(current_root) / dir_name
                    errors.append(f"forbidden directory: {_relative(path)}")
                    dir_names.remove(dir_name)

            for file_name in file_names:
                if _is_forbidden_file(file_name):
                    path = Path(current_root) / file_name
                    errors.append(f"forbidden file: {_relative(path)}")


def _check_compatibility_manifest(errors: list[str]) -> None:
    manifest = MODULES_ROOT / "oeds-deployment" / "compatibility.yml"
    if not manifest.is_file():
        return
    text = manifest.read_text(encoding="utf-8")
    for token in COMPATIBILITY_TOKENS:
        if token not in text:
            errors.append(f"compatibility.yml missing token: {token}")


def _git_state(module_root: Path) -> GitState | None:
    command_prefix = [
        "git",
        "-c",
        f"safe.directory={module_root.as_posix()}",
        "-C",
        str(module_root),
    ]
    try:
        status = subprocess.run(
            command_prefix + ["status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        remotes = subprocess.run(
            command_prefix + ["remote", "-v"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return GitState(status=status, remotes=remotes)


def _check_git_state(errors: list[str], warnings: list[str], strict_git: bool) -> None:
    for module_name in MODULES:
        module_root = MODULES_ROOT / module_name
        if not (module_root / ".git").is_dir():
            errors.append(f"missing git repository: modules/{module_name}")
            continue

        state = _git_state(module_root)
        if state is None:
            errors.append(f"git status failed: modules/{module_name}")
            continue

        if state.status:
            message = f"pending git changes: modules/{module_name}"
            if strict_git:
                errors.append(message)
            else:
                warnings.append(message)

        if not state.remotes:
            message = f"no git remote configured: modules/{module_name}"
            if strict_git:
                errors.append(message)
            else:
                warnings.append(message)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict-git",
        action="store_true",
        help="fail when module repositories have pending changes or no remote",
    )
    parser.add_argument(
        "--skip-git",
        action="store_true",
        help="skip nested repository checks for clean source exports without .git",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    errors: list[str] = []
    warnings: list[str] = []

    _check_required_files(errors)
    _check_forbidden_artifacts(errors)
    _check_compatibility_manifest(errors)
    if not args.skip_git:
        _check_git_state(errors, warnings, strict_git=args.strict_git)

    for warning in warnings:
        print(f"warning: {warning}")
    for error in errors:
        print(f"error: {error}")

    if errors:
        print("publication preflight failed")
        return 1

    print("publication preflight passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
