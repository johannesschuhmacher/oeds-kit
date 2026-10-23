from __future__ import annotations

from dataclasses import dataclass

from crawler.common.runtime_env import resolve_database_uri
from sqlalchemy import bindparam, create_engine, text

from crawler_admin.config_service import is_gapfill_command

# ``oeds_gapfill`` (oeds-post-scripts) is optional for the admin, so it is
# imported inside the functions that need it; see ``crawler_admin.POST_INSTALLED``.

GAPFILL_DASHBOARD_NAME = "OEDS Gapfilling Quality"


@dataclass(frozen=True)
class GapfillRuntimeTableItem:
    table_name: str
    value_columns_label: str
    groupby_columns_label: str
    selected: bool
    method: str
    database_status: str
    database_status_label: str


@dataclass(frozen=True)
class GapfillRuntimeView:
    crawler_name: str
    supported: bool
    source_schema: str
    target_schema: str
    script_enabled: bool
    gapfill_enabled: bool
    method: str
    candidate_periods_label: str
    donor_context_periods: int
    donor_search_radius_label: str
    refinement_periods: int
    max_gap_periods: int
    lookback_label: str
    fail_on_table_error: bool
    metadata_source_label: str
    database_status_note: str
    tables: list[GapfillRuntimeTableItem]
    post_run_scripts: list[str]
    dashboard_name: str | None

    @property
    def selected_table_count(self) -> int:
        return sum(1 for item in self.tables if item.selected)


def gapfill_method_options() -> list[str]:
    from oeds_gapfill.core import GAPFILL_METHODS

    return list(GAPFILL_METHODS)


def build_gapfill_runtime_view(
    crawler_name: str,
    raw_config: dict[str, object] | None,
    effective_config: dict[str, object] | None,
    *,
    check_database_tables: bool = False,
) -> GapfillRuntimeView:
    from oeds_gapfill.config import BUILTIN_GAPFILL_TABLES_BY_JOB, DEFAULT_POSTRUN_TABLES

    raw = raw_config if isinstance(raw_config, dict) else {}
    effective = effective_config if isinstance(effective_config, dict) else {}
    raw_gapfill = raw.get("gapfill") if isinstance(raw.get("gapfill"), dict) else {}
    effective_gapfill = (
        effective.get("gapfill") if isinstance(effective.get("gapfill"), dict) else {}
    )
    source_schema = str(effective.get("schema_name") or crawler_name)
    target_schema = str(
        effective_gapfill.get("target_schema") or f"{source_schema}_gapfilled"
    )
    scripts = (
        list(effective.get("post_run_scripts") or [])
        if isinstance(effective.get("post_run_scripts"), list)
        else []
    )
    supported_tables = BUILTIN_GAPFILL_TABLES_BY_JOB.get(crawler_name, ())
    default_method = str(effective_gapfill.get("method") or "donor_refined")
    table_methods = _extract_table_methods(effective_gapfill)
    table_names = [table.table_name for table in supported_tables]
    if check_database_tables:
        database_presence, database_status_note = _load_source_table_presence(
            effective,
            source_schema,
            table_names,
        )
    else:
        database_presence = {table_name: None for table_name in table_names}
        database_status_note = (
            "Database table status is not checked while opening Settings. "
            "Use Check DB tables to verify the current source schema."
        )

    if isinstance(raw_gapfill, dict) and "tables" in raw_gapfill:
        selected_names = {str(name) for name in (raw_gapfill.get("tables") or [])}
    elif isinstance(effective_gapfill, dict) and "tables" in effective_gapfill:
        selected_names = {str(name) for name in (effective_gapfill.get("tables") or [])}
    else:
        selected_names = set(
            DEFAULT_POSTRUN_TABLES if crawler_name == "entsoe_fms" else []
        )

    tables = [
        GapfillRuntimeTableItem(
            table_name=table.table_name,
            value_columns_label=", ".join(table.value_columns),
            groupby_columns_label=", ".join(table.groupby_columns),
            selected=table.table_name in selected_names,
            method=table_methods.get(table.table_name, default_method),
            database_status=_database_status(table.table_name, database_presence),
            database_status_label=_database_status_label(
                _database_status(table.table_name, database_presence)
            ),
        )
        for table in supported_tables
    ]

    return GapfillRuntimeView(
        crawler_name=crawler_name,
        supported=bool(supported_tables),
        source_schema=source_schema,
        target_schema=target_schema,
        script_enabled=any(is_gapfill_command(str(script)) for script in scripts),
        gapfill_enabled=bool(
            effective_gapfill.get("enable", False) if effective_gapfill else False
        ),
        method=default_method,
        candidate_periods_label=_format_period_config(
            effective_gapfill.get("candidate_periods"), fallback="24h, 7d"
        ),
        donor_context_periods=int(effective_gapfill.get("donor_context_periods", 6)),
        donor_search_radius_label=str(
            effective_gapfill.get("donor_search_radius") or "28d"
        ),
        refinement_periods=int(effective_gapfill.get("refinement_periods", 3)),
        max_gap_periods=int(effective_gapfill.get("max_gap_periods", 24)),
        lookback_label=str(effective_gapfill.get("lookback") or "7d"),
        fail_on_table_error=bool(effective_gapfill.get("fail_on_table_error", True)),
        metadata_source_label=(
            "Built-in ENTSO-E FMS table metadata"
            if crawler_name == "entsoe_fms"
            else "Built-in table metadata"
        ),
        database_status_note=database_status_note,
        tables=tables,
        post_run_scripts=scripts,
        dashboard_name=GAPFILL_DASHBOARD_NAME if supported_tables else None,
    )


def _extract_table_methods(gapfill_config: object) -> dict[str, str]:
    if not isinstance(gapfill_config, dict):
        return {}
    raw_methods = gapfill_config.get("table_methods")
    if not isinstance(raw_methods, dict):
        return {}
    return {
        str(table_name): str(method)
        for table_name, method in raw_methods.items()
        if str(table_name).strip() and str(method).strip()
    }


def _load_source_table_presence(
    effective_config: dict[str, object],
    source_schema: str,
    table_names: list[str],
) -> tuple[dict[str, bool | None], str]:
    if not table_names:
        return {}, "No built-in gapfill tables are configured for this crawler."

    database_uri = str(effective_config.get("database_uri") or "").strip()
    if not database_uri:
        return (
            {table_name: None for table_name in table_names},
            "Database table status unavailable because no database URI is configured.",
        )

    try:
        resolved_uri = resolve_database_uri(database_uri)
        engine = create_engine(
            resolved_uri,
            connect_args=_connect_args_for_database_uri(resolved_uri),
        )
        statement = text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = :schema
              AND table_name IN :table_names
            """
        ).bindparams(bindparam("table_names", expanding=True))
        with engine.connect() as connection:
            present = {
                str(row[0])
                for row in connection.execute(
                    statement,
                    {"schema": source_schema, "table_names": table_names},
                )
            }
    except Exception:
        return (
            {table_name: None for table_name in table_names},
            "Database table status could not be checked. The list below is still the supported gapfill metadata list.",
        )

    return (
        {table_name: table_name in present for table_name in table_names},
        "Database table status was checked against the configured source schema.",
    )


def _connect_args_for_database_uri(database_uri: str) -> dict[str, int]:
    if database_uri.startswith(("postgresql://", "postgresql+psycopg2://")):
        return {"connect_timeout": 1}
    return {}


def _database_status(
    table_name: str,
    database_presence: dict[str, bool | None],
) -> str:
    present = database_presence.get(table_name)
    if present is True:
        return "present"
    if present is False:
        return "missing"
    return "unknown"


def _database_status_label(status: str) -> str:
    if status == "present":
        return "DB table present"
    if status == "missing":
        return "Not in source DB"
    return "DB not checked"


def _format_period_config(value: object, *, fallback: str = "-") -> str:
    if value is None:
        return fallback
    if isinstance(value, str | int | float):
        return str(value)
    if isinstance(value, tuple | list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(parts) if parts else fallback
    return str(value)
