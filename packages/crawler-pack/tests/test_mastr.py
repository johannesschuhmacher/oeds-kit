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


def _export_xml(tag, rows):
    body = "".join(f"<{tag}>" + "".join(f"<{k}>{v}</{k}>" for k, v in row.items()) + f"</{tag}>" for row in rows)
    return BytesIO(('<?xml version="1.0" encoding="utf-16"?><rows>' + body + "</rows>").encode("utf-16"))


def test_tables_without_unique_first_id_keep_every_row(monkeypatch):
    """Upgrades share a plant number but have unique Ids; the operator change log has
    several rows per unit across files and no key, and a rerun must not duplicate it."""
    import logging
    from types import SimpleNamespace

    from sqlalchemy import create_engine, text

    crawler = object.__new__(MastrCrawler)
    crawler.engine = create_engine("sqlite://")
    crawler.config = {"schema_name": None}
    crawler.logger = logging.getLogger("test_mastr")
    files = {
        "Ertuechtigungen.xml": [{"Id": 1, "EegMastrNummer": "EEG1"}, {"Id": 2, "EegMastrNummer": "EEG1"}],
        "EinheitenAenderungNetzbetreiberzuordnungen_1.xml": [
            {"EinheitMastrNummer": "SEE1", "Netzbetreiber": "A"}, {"EinheitMastrNummer": "SEE1", "Netzbetreiber": "B"}],
        "EinheitenAenderungNetzbetreiberzuordnungen_2.xml": [{"EinheitMastrNummer": "SEE1", "Netzbetreiber": "C"}],
    }
    monkeypatch.setattr(crawler, "get_mastr_url", lambda: "https://example.invalid/export.zip")
    monkeypatch.setattr(crawler, "get_data_from_mastr", lambda url: (
        (_export_xml("Row", rows), SimpleNamespace(filename=name)) for name, rows in files.items()))

    for _ in range(2):
        keys = crawler.create_db_from_export()

    assert keys == {"Ertuechtigungen": "Id", "EinheitenAenderungNetzbetreiberzuordnungen": None}
    with crawler.engine.connect() as conn:
        assert conn.execute(text('SELECT "Id" FROM "Ertuechtigungen" ORDER BY 1')).scalars().all() == [1, 2]
        changes = conn.execute(text('SELECT "Netzbetreiber" FROM "EinheitenAenderungNetzbetreiberzuordnungen" ORDER BY 1'))
        assert changes.scalars().all() == ["A", "B", "C"]


def test_full_xml_matches_pandas_read_xml():
    xml = '<?xml version="1.0" encoding="utf-16"?><rows>' + ''.join(
        f'<Einheit><EinheitMastrNummer>SEE{i}</EinheitMastrNummer><Ort>Georgenthal </Ort>'
        + (f'<Bruttoleistung>{i * 2.5}</Bruttoleistung>' if i % 2 else '<Strasse></Strasse>')
        + '</Einheit>' for i in range(6)) + '</rows>'
    data = xml.encode('utf-16')
    actual = MastrCrawler.read_xml(BytesIO(data))
    expected = pd.read_xml(BytesIO(data), encoding="utf-16")
    pd.testing.assert_frame_equal(actual, expected)


def test_export_download_resumes_after_a_broken_connection(tmp_path):
    """The connection drops after 3 of 10 bytes; the next request asks for the rest."""
    import logging
    from types import SimpleNamespace

    import requests

    data = b"0123456789"
    requests_seen = []

    class Response:
        def __init__(self, headers):
            start = int(headers["Range"].split("=")[1].rstrip("-")) if "Range" in headers else 0
            self.status_code = 206 if start else 200
            self.body = data[start:]
            self.broken = not requests_seen

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            if self.broken:
                yield self.body[:3]
                raise requests.ConnectionError("Connection reset by peer")
            yield self.body

    class Session:
        def head(self, url, timeout):
            return SimpleNamespace(headers={"Content-Length": str(len(data))})

        def get(self, url, headers, stream, timeout):
            response = Response(headers)
            requests_seen.append(headers.get("Range"))
            return response

    crawler = object.__new__(MastrCrawler)
    crawler.config = {}
    crawler.logger = logging.getLogger("test_mastr")
    crawler._download_session = Session
    path = tmp_path / "export.zip"

    crawler._download_export("https://example.invalid/export.zip", path, pause_seconds=0)

    assert path.read_bytes() == data
    assert requests_seen == [None, "bytes=3-"]
