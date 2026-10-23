import pandas as pd
from sqlalchemy import create_engine, text

from crawler.common.crawler_utils import copy_insert


def test_copy_insert_falls_back_to_plain_insert_outside_postgres():
    engine = create_engine("sqlite://")
    frame = pd.DataFrame({"name": ["a", None], "value": [1.5, float("nan")]})

    with engine.begin() as conn:
        frame.to_sql("t", conn, index=False, method=copy_insert)
        rows = conn.execute(text("SELECT name, value FROM t")).fetchall()

    assert rows == [("a", 1.5), (None, None)]


def test_copy_insert_writes_whole_floats_as_integers():
    from types import SimpleNamespace

    copied = {}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def copy_expert(self, sql, buffer):
            copied["sql"], copied["data"] = sql, buffer.read()

    conn = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"),
                           connection=SimpleNamespace(cursor=Cursor))
    table = SimpleNamespace(schema="entsog", name="physical_flow")

    copy_insert(table, conn, ["idpointtype", "value", "unit"], iter([(0.0, 1.5, ""), (None, 2.0, None)]))

    assert copied["sql"].startswith('COPY "entsog"."physical_flow" ("idpointtype", "value", "unit")')
    # None stays an unquoted empty field (NULL), "" a quoted one (empty string).
    assert copied["data"].splitlines() == ['"0","1.5",""', ',"2",']


class _RecordingCursor:
    def __init__(self):
        self.sql, self.data = [], None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        self.sql.append(sql)

    def copy_expert(self, sql, buffer):
        self.sql.append(sql)
        self.data = buffer.read()


def recording_engine():
    """Engine stand-in whose begin() yields a connection with a recording raw cursor."""
    from contextlib import contextmanager
    from types import SimpleNamespace

    cursor = _RecordingCursor()
    conn = SimpleNamespace(connection=SimpleNamespace(cursor=lambda: cursor))
    return SimpleNamespace(begin=contextmanager(lambda: iter([conn]))), cursor


def test_copy_upsert_stages_rows_and_updates_non_key_columns():
    from sqlalchemy import BigInteger, Column, Float, MetaData, String, Table, UniqueConstraint

    from crawler.common.crawler_utils import copy_upsert

    table = Table(
        "t", MetaData(schema="s"),
        Column("key", String), Column("n", BigInteger), Column("label", String), Column("note", String),
        UniqueConstraint("key", name="uq_t"),
    )
    frame = pd.DataFrame({
        "key": ["a", "a", "b"],
        "n": [1.0, 2.0, float("nan")],
        "label": [9.0, 1.0, 1.5],  # float into a text column
    })
    engine, cursor = recording_engine()

    assert copy_upsert(engine, table, frame, "uq_t", ["key"], where='"s"."t"."n" < EXCLUDED."n"') == 2

    assert cursor.sql == [
        'CREATE TEMP TABLE upsert_stage (LIKE "s"."t") ON COMMIT DROP',
        'COPY upsert_stage ("key", "n", "label", "note") FROM STDIN WITH (FORMAT csv)',
        'INSERT INTO "s"."t" ("key", "n", "label", "note") SELECT "key", "n", "label", "note" FROM upsert_stage '
        'ON CONFLICT ON CONSTRAINT "uq_t" DO UPDATE SET "n" = EXCLUDED."n", "label" = EXCLUDED."label", '
        '"note" = EXCLUDED."note" WHERE "s"."t"."n" < EXCLUDED."n"',
    ]
    # Last row per key wins; a whole float is an integer only in the integer column;
    # NaN and the missing column are NULL (unquoted empty field).
    assert cursor.data.splitlines() == ['"a","2","1.0",', '"b",,"1.5",']
