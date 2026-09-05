"""Assemble a modular OEDS workspace from ``compatibility.yml``.

The deployment repository can be cloned by itself. This tool turns that
standalone checkout into the workspace layout expected by Docker Compose:

```
<workspace>/
  crawler/
    data/
  CRAWLER_CONFIG.yml
  modular_repos/
    docs/
    sources/oeds-core/
    modules/oeds-deployment/
    modules/oeds-crawler-pack/
    modules/oeds-scheduler-ui/
    modules/oeds-post-scripts/
```

Only Python's standard library is used so the tool can run before project
dependencies are installed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEPLOYMENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPATIBILITY = DEPLOYMENT_ROOT / "compatibility.yml"
DEFAULT_DEPLOYMENT_TARGET = Path("modular_repos/modules/oeds-deployment")
DEFAULT_MODULAR_DOCS = DEPLOYMENT_ROOT / "assembly"

IGNORED_COPY_NAMES = {
    ".git",
    ".tmp",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    "logs",
    "runtime",
    "docker_data",
    "crawler_admin_state",
    ".env",
    ".env.*",
    "*.env",
    ".bitwarden-cli-oeds",
}


@dataclass(frozen=True)
class Component:
    name: str
    path: str
    repository: str | None = None
    branch: str | None = None
    commit: str | None = None
    self_component: bool = False


def main() -> int:
    args = _parse_args()
    compatibility = args.compatibility.resolve()
    workspace = args.output.resolve()
    components = _read_components(compatibility)

    if workspace == DEPLOYMENT_ROOT or workspace in DEPLOYMENT_ROOT.parents or DEPLOYMENT_ROOT in workspace.parents:
        raise ValueError("output must be outside the deployment checkout")
    if args.dry_run:
        _print_plan(workspace, components)
        return 0

    if args.clean and workspace.exists():
        _remove_tree_safely(workspace)
    elif workspace.exists() and any(workspace.iterdir()):
        print(f"error: output directory is not empty: {workspace}", file=sys.stderr)
        print("       pass --clean to replace it", file=sys.stderr)
        return 2

    workspace.mkdir(parents=True, exist_ok=True)
    deployment_target = (workspace / DEFAULT_DEPLOYMENT_TARGET).resolve()

    for component in _ordered_components(components):
        target = _component_target(workspace, deployment_target, component)
        _assert_target_inside_workspace(workspace, target, component.name)
        if component.self_component or component.name == "oeds-deployment":
            _copy_self_checkout(target)
        else:
            _clone_component(component, target)

    _install_modular_support(workspace)
    _install_runtime_support(workspace)
    _verify_workspace(workspace)
    print(f"assembled modular OEDS workspace at {workspace}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compatibility",
        type=Path,
        default=DEFAULT_COMPATIBILITY,
        help="path to compatibility.yml",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="empty target workspace directory",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove the output directory before assembling",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the clone/copy plan without writing files",
    )
    return parser.parse_args()


def _read_components(path: Path) -> list[Component]:
    if not path.is_file():
        raise FileNotFoundError(path)

    components: list[Component] = []
    in_components = False
    current_name: str | None = None
    current: dict[str, str] = {}

    def flush() -> None:
        nonlocal current_name, current
        if current_name is None:
            return
        if "path" not in current:
            raise ValueError(f"component {current_name!r} is missing path")
        components.append(
            Component(
                name=current_name,
                path=current["path"],
                repository=current.get("repository"),
                branch=current.get("branch"),
                commit=current.get("commit"),
                self_component=_as_bool(current.get("self")),
            )
        )
        current_name = None
        current = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line:
            continue
        if not line.startswith(" "):
            if line == "components:":
                in_components = True
                continue
            if in_components:
                flush()
                break
            continue
        if not in_components:
            continue

        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            flush()
            current_name = line.strip()[:-1]
            continue

        if current_name and line.startswith("    ") and ":" in line:
            key, value = line.strip().split(":", 1)
            value = _strip_yaml_scalar(value.strip())
            if value:
                current[key] = value

    flush()
    if not components:
        raise ValueError(f"no components found in {path}")
    return components


def _strip_yaml_scalar(value: str) -> str:
    if value in {"", "[]", "{}"}:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def _as_bool(value: str | None) -> bool:
    return bool(value and value.lower() in {"true", "yes", "1"})


def _ordered_components(components: list[Component]) -> list[Component]:
    by_name = {component.name: component for component in components}
    ordered: list[Component] = []
    for name in ("oeds-core", "oeds-crawler-pack", "oeds-scheduler-ui", "oeds-post-scripts", "oeds-deployment"):
        if name in by_name:
            ordered.append(by_name.pop(name))
    ordered.extend(by_name.values())
    return ordered


def _component_target(workspace: Path, deployment_target: Path, component: Component) -> Path:
    raw_path = Path(component.path)
    if raw_path.is_absolute():
        return raw_path.resolve()
    return (deployment_target / raw_path).resolve()


def _assert_target_inside_workspace(workspace: Path, target: Path, component_name: str) -> None:
    workspace = workspace.resolve()
    if target == workspace:
        return
    if workspace not in target.parents:
        raise ValueError(f"component {component_name} target escapes workspace: {target}")


def _print_plan(workspace: Path, components: list[Component]) -> None:
    deployment_target = (workspace / DEFAULT_DEPLOYMENT_TARGET).resolve()
    for component in _ordered_components(components):
        target = _component_target(workspace, deployment_target, component)
        action = "copy-self" if component.self_component or component.name == "oeds-deployment" else "clone"
        ref = component.commit or component.branch or "HEAD"
        print(f"{component.name}: {action} {component.repository or DEPLOYMENT_ROOT} @ {ref} -> {target}")


def _clone_component(component: Component, target: Path) -> None:
    if not component.repository:
        raise ValueError(f"component {component.name} is missing repository")
    if target.exists():
        _remove_tree_safely(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    _run(["git", "clone", "--no-checkout", component.repository, str(target)])
    ref = component.commit or component.branch
    if ref:
        _run(["git", "-C", str(target), "checkout", ref])
    if component.commit:
        actual = _git_rev_parse(target, "HEAD")
        if actual != component.commit:
            raise RuntimeError(
                f"{component.name} checked out {actual}, expected {component.commit}"
            )


def _copy_self_checkout(target: Path) -> None:
    if target.exists():
        _remove_tree_safely(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        DEPLOYMENT_ROOT,
        target,
        ignore=shutil.ignore_patterns(*IGNORED_COPY_NAMES),
    )


def _install_modular_support(workspace: Path) -> None:
    modular_target = workspace / "modular_repos"
    docs_target = modular_target / "docs"
    docs_target.mkdir(parents=True, exist_ok=True)
    inventory_source = DEFAULT_MODULAR_DOCS / "crawler-inventory.json"
    if not inventory_source.is_file():
        raise FileNotFoundError(inventory_source)
    shutil.copy2(inventory_source, docs_target / "crawler-inventory.json")


def _install_runtime_support(workspace: Path) -> None:
    dockerignore = DEPLOYMENT_ROOT / ".dockerignore"
    if dockerignore.is_file():
        shutil.copy2(dockerignore, workspace / ".dockerignore")

    config_source = DEFAULT_MODULAR_DOCS / "CRAWLER_CONFIG.yml"
    if not config_source.is_file():
        raise FileNotFoundError(config_source)
    shutil.copy2(config_source, workspace / "CRAWLER_CONFIG.yml")

    crawler_package = (
        workspace
        / "modular_repos"
        / "modules"
        / "oeds-crawler-pack"
        / "src"
        / "crawler"
    )
    data_source = crawler_package / "data"
    data_target = workspace / "crawler" / "data"
    if not data_source.is_dir():
        raise FileNotFoundError(data_source)
    shutil.copytree(data_source, data_target, dirs_exist_ok=True)

    env_example = crawler_package / ".env.example"
    if env_example.is_file():
        shutil.copy2(env_example, workspace / "crawler" / ".env.example")

    (workspace / "logs").mkdir(exist_ok=True)
    (workspace / "crawler_admin_state").mkdir(exist_ok=True)


def _verify_workspace(workspace: Path) -> None:
    required = [
        ".dockerignore",
        "CRAWLER_CONFIG.yml",
        "crawler/.env.example",
        "crawler/data/mapping_eic_to_location.py",
        "crawler/data/mapping_p_to_g.json",
        "crawler/data/mapping_g_to_p.json",
        "modular_repos/docs/crawler-inventory.json",
        "modular_repos/sources/oeds-core/oeds/base_crawler.py",
        "modular_repos/modules/oeds-deployment/compose.modular.yml",
        "modular_repos/modules/oeds-crawler-pack/pyproject.toml",
        "modular_repos/modules/oeds-crawler-pack/src/crawler/common/base_crawler.py",
        "modular_repos/modules/oeds-crawler-pack/src/crawler_core/__init__.py",
        "modular_repos/modules/oeds-scheduler-ui/pyproject.toml",
        "modular_repos/modules/oeds-post-scripts/pyproject.toml",
    ]
    missing = [relative for relative in required if not (workspace / relative).exists()]
    if missing:
        raise RuntimeError("assembled workspace is missing required files: " + ", ".join(missing))


def _git_rev_parse(repo: Path, ref: str) -> str:
    return _run(["git", "-C", str(repo), "rev-parse", ref]).strip()


def _run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return completed.stdout


def _remove_tree_safely(path: Path) -> None:
    path = path.resolve()
    if not path.exists():
        return
    if path.parent == path or len(path.parts) < 3:
        raise ValueError(f"refusing to remove unsafe path: {path}")
    shutil.rmtree(path, onerror=_retry_readonly_delete)


def _retry_readonly_delete(function: object, path: str, excinfo: object) -> None:
    del excinfo
    os.chmod(path, stat.S_IWRITE)
    function(path)


if __name__ == "__main__":
    raise SystemExit(main())
