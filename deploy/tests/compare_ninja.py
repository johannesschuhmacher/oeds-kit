"""Compare all real Ninja values after running both isolated live crawler tests."""

import pandas as pd
from sqlalchemy import create_engine

for table in ['capacity_wind_on', 'capacity_wind_off', 'capacity_solar_merra2']:
    frames = []
    for source in ['kit', 'core']:
        engine = create_engine(
            f'postgresql://opendata:opendata@oeds-crawler-validation-db:5432/{source}_ninja')
        with engine.connect() as conn:
            frames.append(pd.read_sql(f'SELECT * FROM ninja.{table} ORDER BY time', conn))
        engine.dispose()
    for frame in frames:
        frame['time'] = pd.to_datetime(frame['time'], utc=True)
        numeric = frame.drop(columns='time').select_dtypes(include='number')
        assert not numeric.empty and not numeric.isna().any().any(), table
        assert ((numeric >= 0) & (numeric <= 1)).all().all(), table
    pd.testing.assert_frame_equal(*frames, check_dtype=False, check_exact=True, check_like=True)
    print(f'PASS identical KIT/core Ninja: {table}; {len(frames[0])} rows')
