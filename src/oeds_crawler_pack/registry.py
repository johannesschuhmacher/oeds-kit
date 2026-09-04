"""Registry metadata for KIT-derived crawler implementations."""

from __future__ import annotations

import ast
from pathlib import Path

CRAWLER_BASE_NAMES = {"BaseCrawler", "ContinuousCrawler", "DownloadOnceCrawler"}
CRAWLER_RUN_METHODS = {"run", "crawl_temporal", "crawl_structural"}


def default_crawler_source_path() -> Path:
    """Return the source root containing this package's bundled crawlers."""

    return Path(__file__).resolve().parents[1]


def default_kit_source_path() -> Path:
    """Return the bundled crawler source root for backwards compatibility."""

    return default_crawler_source_path()


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return ast.unparse(base)


def _class_methods(class_node: ast.ClassDef) -> set[str]:
    return {
        node.name for node in class_node.body if isinstance(node, ast.FunctionDef)
    }


def _is_crawler_candidate(class_node: ast.ClassDef) -> bool:
    bases = {_base_name(base) for base in class_node.bases}
    if bases & CRAWLER_BASE_NAMES:
        return True

    methods = _class_methods(class_node)
    return bool(methods & CRAWLER_RUN_METHODS) and class_node.name.endswith(
        ("Crawler", "Downloader")
    )


def _candidate_score(class_node: ast.ClassDef) -> tuple[int, int, str]:
    bases = {_base_name(base) for base in class_node.bases}
    methods = _class_methods(class_node)
    return (
        1 if bases & CRAWLER_BASE_NAMES else 0,
        len(methods & CRAWLER_RUN_METHODS),
        class_node.name,
    )


def _find_crawler_class(module_file: Path) -> str | None:
    tree = ast.parse(module_file.read_text(encoding="utf-8"))
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _is_crawler_candidate(node)
    ]
    if not candidates:
        return None
    return max(candidates, key=_candidate_score).name


def get_crawler_specs(source_path: str | Path | None = None) -> dict[str, str]:
    """Return crawler spec strings for the bundled crawler implementations."""

    root = (
        Path(source_path).expanduser().resolve()
        if source_path
        else default_crawler_source_path()
    )
    crawler_dir = root / "crawler"
    specs: dict[str, str] = {}

    if not crawler_dir.is_dir():
        return specs

    for module_file in sorted(crawler_dir.glob("*.py")):
        if module_file.name.startswith("__"):
            continue
        try:
            class_name = _find_crawler_class(module_file)
        except (OSError, SyntaxError):
            continue
        if class_name is None:
            continue
        module_name = f"crawler.{module_file.stem}"
        specs[module_file.stem] = f"{module_name}:{class_name}"

    return specs
