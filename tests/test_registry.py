from oeds_crawler_pack.registry import default_crawler_source_path, get_crawler_specs


def test_get_crawler_specs_discovers_fixture_crawler(tmp_path):
    crawler_dir = tmp_path / "crawler"
    crawler_dir.mkdir()
    (crawler_dir / "sample.py").write_text(
        "class SampleCrawler:\n"
        "    def run(self):\n"
        "        return None\n",
        encoding="utf-8",
    )

    specs = get_crawler_specs(tmp_path)

    assert specs == {"sample": "crawler.sample:SampleCrawler"}


def test_get_crawler_specs_contains_pilot_crawlers():
    specs = get_crawler_specs()

    assert specs["smard"] == "crawler.smard:SmardCrawler"
    assert specs["eurostat_crawler"] == "crawler.eurostat_crawler:EurostatCrawler"
    assert specs["entsoe_fms"] == "crawler.entsoe_fms:EntsoeFMSCrawler"
    assert len(specs) >= 20


def test_default_crawler_source_path_points_to_bundled_package():
    path = default_crawler_source_path()
    assert (path / "crawler").is_dir()
    assert (path / "crawler_core").is_dir()
