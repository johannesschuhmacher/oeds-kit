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
