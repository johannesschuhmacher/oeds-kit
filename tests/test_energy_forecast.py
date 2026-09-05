import pandas as pd

from crawler.energy_forecast_crawler import EnergyForecastCrawler


def test_csv_history_uses_runtime_data_directory(monkeypatch, tmp_path):
    directory = tmp_path / 'runtime-data'
    monkeypatch.setenv('OEDS_CRAWLER_DATA_DIR', str(directory))
    crawler = object.__new__(EnergyForecastCrawler)
    frame = pd.DataFrame({'price': [42.5]})

    crawler._write_to_csv(frame)
    crawler._write_to_csv(frame)

    saved = pd.read_csv(directory / 'energy_forecast_history.csv')
    assert saved.price.tolist() == [42.5, 42.5]
