"""The admin UI must import and serve without oeds-post-scripts.

Needs the crawler pack (``crawler.common.*``); the post packages are made
unimportable by putting ``None`` into ``sys.modules`` before a fresh import of
``crawler_admin``. The deprecated ``crawler_core`` facade is blocked the same
way so a stray import of it fails here instead of after the facade is deleted.
"""

from __future__ import annotations

import asyncio
import importlib
import sys

import pytest

BLOCKED_PACKAGES = ("oeds_gapfill", "oeds_post_scripts", "oeds_price_forecast", "crawler_core")
CONFIG = """\
default:
  enable: false
  schedule: "0 4 * * *"
  database_uri: "postgresql://user:pass@localhost:5432/opendata"
entsoe_fms:
  schema_name: "entsoe_fms"
  post_run_scripts: ["oeds-post gapfill entsoe-fms"]
entsoe_api:
  schema_name: "entsoe_api"
"""


@pytest.fixture
def admin_app(monkeypatch, tmp_path):
    (tmp_path / "CRAWLER_CONFIG.yml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("OEDS_ADMIN_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("OEDS_ADMIN_STATE_DIR", str(tmp_path / "state"))
    for name in list(sys.modules):
        if name.split(".")[0] in ("crawler_admin", "crawler_admin_server", *BLOCKED_PACKAGES):
            monkeypatch.delitem(sys.modules, name)
    for name in BLOCKED_PACKAGES:
        monkeypatch.setitem(sys.modules, name, None)  # makes ``import name`` fail
    return importlib.import_module("crawler_admin.app").app


def _request(app, method, path):
    """Minimal ASGI call; returns ``(status, body)`` without needing httpx."""

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    }
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return status, body.decode("utf-8")


def test_admin_serves_dashboard_and_crawler_page_without_post(admin_app):
    status, body = _request(admin_app, "GET", "/admin")
    assert status == 200
    assert "entsoe_fms" in body
    assert "/admin/gapfill" not in body

    # entsoe_fms has the gapfill panel and action, entsoe_api the price forecast.
    status, body = _request(admin_app, "GET", "/admin/crawlers/entsoe_fms")
    assert status == 200
    assert "gapfill-operations" not in body
    assert "Gapfill backfill" not in body

    status, body = _request(admin_app, "GET", "/admin/crawlers/entsoe_api")
    assert status == 200
    assert "price-forecast" not in body
    assert "Price forecast" not in body


def test_admin_gapfill_routes_are_absent_without_post(admin_app):
    assert _request(admin_app, "GET", "/admin/gapfill")[0] == 404
    assert _request(admin_app, "POST", "/admin/gapfill/self-tests")[0] == 404
    assert _request(admin_app, "POST", "/admin/crawlers/entsoe_fms/gapfill")[0] == 404


def test_admin_server_launcher_imports_without_crawler_core(admin_app):
    importlib.import_module("crawler_admin_server")
