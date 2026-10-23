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
