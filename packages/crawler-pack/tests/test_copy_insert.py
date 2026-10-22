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
