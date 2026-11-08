"""Compare all real Ninja values after running both isolated live crawler tests."""

import pandas as pd
from sqlalchemy import create_engine

for table in ['capacity_wind_on', 'capacity_wind_off', 'capacity_solar_merra2']:
    frames = []
    # KIT crawler renewables_ninja and core crawler ninja, each in its own database
    for database, schema in [('kit_renewables_ninja', 'renewables_ninja'), ('core_ninja', 'ninja')]:
        engine = create_engine(
            f'postgresql://opendata:opendata@oeds-crawler-validation-db:5432/{database}')
        with engine.connect() as conn:
            frames.append(pd.read_sql(f'SELECT * FROM {schema}.{table} ORDER BY time', conn))
        engine.dispose()
    for frame in frames:
        frame['time'] = pd.to_datetime(frame['time'], utc=True)
        numeric = frame.drop(columns='time').select_dtypes(include='number')
        assert not numeric.empty and not numeric.isna().any().any(), table
        assert ((numeric >= 0) & (numeric <= 1)).all().all(), table
    pd.testing.assert_frame_equal(*frames, check_dtype=False, check_exact=True, check_like=True)
    print(f'PASS identical KIT/core Ninja: {table}; {len(frames[0])} rows')
