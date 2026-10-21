from unittest.mock import Mock

from crawler.epex_spot import EpexSpotCrawler


def test_download_reconnects_after_a_dropped_session():
    crawler = object.__new__(EpexSpotCrawler)
    crawler.logger = Mock()
    good = Mock()
    good.__enter__ = Mock(return_value=Mock(read=Mock(return_value=b"ok")))
    good.__exit__ = Mock(return_value=False)
    first = Mock(side_effect=OSError("Socket is closed"))
    sftp_broken = Mock(open=first)
    sftp_fresh = Mock(open=Mock(return_value=good))
    crawler.sftp = sftp_broken

    def reconnect():
        crawler.sftp = sftp_fresh

    crawler._disconnect_sftp = Mock()
    crawler._connect_sftp = Mock(side_effect=reconnect)

    assert crawler._download_bytes("/germany/x.csv") == b"ok"
    crawler._connect_sftp.assert_called_once()
