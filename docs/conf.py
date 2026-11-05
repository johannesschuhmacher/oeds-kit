# Sphinx configuration for https://open-energy-data-server-kit.readthedocs.io.
#
# The source directory is the repository root, so the existing READMEs are pages
# as they are and their relative links work:
#     sphinx-build -c docs -b html . docs/_build/html

from pathlib import Path

project = "oeds-kit"
author = "Karlsruhe Institute of Technology (KIT)"
copyright = "2026, KIT and the Open Energy Data Server contributors"

extensions = ["myst_parser"]
myst_heading_anchors = 3

root_doc = "docs/index"
include_patterns = [
    "docs/**",
    "README.md",
    "CHANGELOG.md",
    "deploy/README.md",
    "deploy/playbooks/README.md",
    "deploy/docs/*.md",
    "deploy/data/provisioning/grafana/README.md",
    "packages/*/README.md",
]
exclude_patterns = ["docs/_build"]

html_theme = "sphinx_rtd_theme"
html_title = "oeds-kit"


def _write_start_page(app, exception):
    # The start page is docs/index.html; send the site root there.
    if exception is None and app.builder.format == "html":
        start = '<meta http-equiv="refresh" content="0; url=docs/index.html">'
        (Path(app.outdir) / "index.html").write_text(start, encoding="utf-8")


def setup(app):
    app.connect("build-finished", _write_start_page)
