from io import BytesIO

import pandas as pd

from crawler.mastr import MastrCrawler


def test_bounded_xml_preserves_complete_records_and_numeric_values():
    xml = '<?xml version="1.0" encoding="utf-16"?><rows>' + ''.join(
        f'<Einheit><EinheitMastrNummer>SEE{i}</EinheitMastrNummer>'
        f'<Nettonennleistung>{i + 0.5}</Nettonennleistung></Einheit>' for i in range(5)) + '</rows>'
    data = xml.encode('utf-16')
    actual = MastrCrawler.read_xml(BytesIO(data), 2)
    expected = pd.read_xml(BytesIO(data), encoding="utf-16").head(2)
    pd.testing.assert_frame_equal(actual, expected)


def test_later_export_file_with_new_column_is_appended():
    from sqlalchemy import create_engine, text

    engine = create_engine("sqlite://")
    first = pd.DataFrame({"EinheitMastrNummer": ["SEE1"], "Nettonennleistung": [1.5]})
    later = pd.DataFrame({"EinheitMastrNummer": ["SEE2"], "Nettonennleistung": [2.5], "Weic": ["x"]})
    with engine.begin() as conn:
        first.to_sql("EinheitenSolar", conn, index=False)
        MastrCrawler._align_table(conn, "EinheitenSolar", later)
        later.to_sql("EinheitenSolar", conn, if_exists="append", index=False)
        rows = conn.execute(text('SELECT "EinheitMastrNummer", "Weic" FROM "EinheitenSolar" ORDER BY 1')).fetchall()
    assert rows == [("SEE1", None), ("SEE2", "x")]
