# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import os

import pytest

from oeds_post_scripts import runtime_env
from oeds_post_scripts.runtime_env import load_crawler_dotenv, resolve_database_uri

URI = "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path="


@pytest.fixture
def no_db_overrides(monkeypatch):
    for name in ("OEDS_DB_HOST", "OEDS_DB_PORT", "OEDS_DB_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fresh_dotenv_state(monkeypatch):
    monkeypatch.setattr(runtime_env, "_LOADED_DOTENV_PATHS", set())
    monkeypatch.delenv("OEDS_CRAWLER_ENV", raising=False)
    yield
    # load_dotenv writes to os.environ behind monkeypatch's back.
    for name in ("OEDS_TEST_FROM_FILE", "OEDS_TEST_FROM_NAMED_FILE", "OEDS_TEST_ADDED_LATER"):
        os.environ.pop(name, None)


def test_resolve_database_uri_passes_through_without_overrides(no_db_overrides):
    assert resolve_database_uri(URI) == URI
    assert resolve_database_uri("") == ""


def test_resolve_database_uri_applies_host_port_and_quoted_password(no_db_overrides, monkeypatch):
    monkeypatch.setenv("OEDS_DB_HOST", "db.internal")
    monkeypatch.setenv("OEDS_DB_PORT", "5432")
    monkeypatch.setenv("OEDS_DB_PASSWORD", "p@ss:word/1")

    assert resolve_database_uri(URI) == (
        "postgresql://opendata:p%40ss%3Aword%2F1@db.internal:5432/opendata?options=--search_path="
    )


def test_resolve_database_uri_brackets_ipv6_host(no_db_overrides, monkeypatch):
    monkeypatch.setenv("OEDS_DB_HOST", "::1")

    assert resolve_database_uri(URI) == "postgresql://opendata:opendata@[::1]:6432/opendata?options=--search_path="


def test_resolve_database_uri_ignores_blank_overrides(no_db_overrides, monkeypatch):
    monkeypatch.setenv("OEDS_DB_HOST", "  ")
    monkeypatch.setenv("OEDS_DB_PASSWORD", "")

    assert resolve_database_uri(URI) == URI


def test_load_crawler_dotenv_defaults_to_cwd_and_keeps_existing_values(fresh_dotenv_state, monkeypatch, tmp_path):
    env_file = tmp_path / "crawler" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("OEDS_TEST_FROM_FILE=loaded\nOEDS_TEST_PRESET=from-file\n", encoding="utf-8")
    monkeypatch.setenv("OEDS_TEST_PRESET", "from-environment")
    monkeypatch.chdir(tmp_path)

    assert load_crawler_dotenv() == env_file.resolve()
    assert os.environ["OEDS_TEST_FROM_FILE"] == "loaded"
    assert os.environ["OEDS_TEST_PRESET"] == "from-environment"


def test_load_crawler_dotenv_prefers_oeds_crawler_env_over_given_path(fresh_dotenv_state, monkeypatch, tmp_path):
    named_file = tmp_path / "named.env"
    named_file.write_text("OEDS_TEST_FROM_NAMED_FILE=named\n", encoding="utf-8")
    other_file = tmp_path / "other.env"
    other_file.write_text("OEDS_TEST_FROM_FILE=other\n", encoding="utf-8")
    monkeypatch.setenv("OEDS_CRAWLER_ENV", str(named_file))

    assert load_crawler_dotenv(other_file) == named_file.resolve()
    assert os.environ["OEDS_TEST_FROM_NAMED_FILE"] == "named"
    assert "OEDS_TEST_FROM_FILE" not in os.environ


def test_load_crawler_dotenv_returns_none_for_missing_file(fresh_dotenv_state, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    assert load_crawler_dotenv() is None
    assert load_crawler_dotenv(tmp_path / "missing.env") is None


def test_load_crawler_dotenv_loads_each_file_only_once(fresh_dotenv_state, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OEDS_TEST_FROM_FILE=loaded\n", encoding="utf-8")

    assert load_crawler_dotenv(env_file) == env_file.resolve()
    env_file.write_text("OEDS_TEST_ADDED_LATER=late\n", encoding="utf-8")
    assert load_crawler_dotenv(env_file) == env_file.resolve()
    assert "OEDS_TEST_ADDED_LATER" not in os.environ
