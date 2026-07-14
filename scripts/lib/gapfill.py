# SPDX-FileCopyrightText: Johannes Schuhmacher, Andre Meyer
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from datetime import datetime, timedelta
import logging
from pathlib import Path
import sys

from pandas import Timedelta, Timestamp
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler_core.runtime_env import resolve_database_uri

# this function fills gaps for a given table
# by coping the original data into a new table named <table_name>_gapfilled
def fill_gaps(
    schema_name: str,
    table_name: str,
    start_datetime: datetime,
    end_datetime: datetime,
    interval: timedelta, # The time interval for the time series
    timestamp_column_name: str, # The name of the timestamp column in the table
    value_column_names: list[str], # The names of the value columns to fill gaps for
    copy_column_names: list[str], # The names of the columns where the original data should simply be copied
    unique_column_names: list[str], # The names of the unique columns to identify different time series
    imputation_method: str = "linear_interpolate", # The imputation method to use, default is linear interpolation
):
    assert imputation_method in ["linear_interpolate"], "Unsupported imputation method"

    base_uri = resolve_database_uri("postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=")
    engine = create_engine(f"{base_uri}{schema_name}")
    with engine.begin() as conn:
        # create table with the same columns but with an additional column for imputation method
        conn.execute(text(
            f"CREATE TABLE IF NOT EXISTS {table_name}_gapfilled( "
            f"LIKE {table_name} INCLUDING ALL, "
            "imputation_method TEXT);"
        ))
        logging.debug(f"Created table {table_name}_gapfilled")

        unique_combinations = conn.execute(text(
            f"SELECT DISTINCT {', '.join(unique_column_names)} FROM {table_name};"
        )).all()

        logging.debug(f"Found {len(unique_combinations)} unique combinations: {unique_combinations}")

        for unique_combination in unique_combinations:
            # generate a time series for each unique combination with no gaps
            # an copy the original data into the new table
            stmnt = text(
                f"INSERT INTO {table_name}_gapfilled ( "
                f"{timestamp_column_name}, {', '.join(unique_column_names)}) "
                f"SELECT g.{timestamp_column_name}, {', '.join([f'\'{uv}\' AS {cn}' if type(uv) == str else f'{uv} AS {cn}' for cn, uv in zip(unique_column_names, unique_combination)])} "
                "FROM generate_series( "
                f"  '{Timestamp(start_datetime)}'::TIMESTAMP, "
                f"  '{Timestamp(end_datetime)}'::TIMESTAMP, "
                f"  '{Timedelta(interval)}'::INTERVAL) "
                "AS g(timestamp) "
                "ON CONFLICT DO NOTHING;"
            )

            # logging.debug(stmnt)
            conn.execute(stmnt)

        # copy original data into the new table
        stmnt = text(
            f"UPDATE {table_name}_gapfilled g "
            f"SET {', '.join([f"{cn} = t.{cn}" for cn in value_column_names+copy_column_names])} "
            f"FROM {table_name} AS t "
            f"WHERE g.{timestamp_column_name} = t.{timestamp_column_name} "
            f"{'  '.join([f"AND g.{cn} = t.{cn}" for cn in unique_column_names])};"
        )

        # logging.debug(stmnt)
        conn.execute(stmnt)


    for unique_combination in unique_combinations:
        # find gaps in the time original data
        # by comparing the previous timestamp and value with the current timestamp and value
        # and check if the difference is greater than the specified interval
        for value_column_name in value_column_names:
            with engine.begin() as conn:
                stmnt = text(
                    "WITH gaps AS ( "
                    f"  SELECT *, "
                    f"  LAG({timestamp_column_name}, 1) OVER (ORDER BY {timestamp_column_name} ASC) AS previous_timestamp, "
                    f"  LAG({value_column_name}, 1) OVER (ORDER BY {timestamp_column_name} ASC) AS previous_value "
                    f"  FROM {table_name} "
                    f"  WHERE {timestamp_column_name} >= '{Timestamp(start_datetime)}' "
                    f"    AND {timestamp_column_name} <= '{Timestamp(end_datetime)}' "
                    f"{'  '.join(f'AND {cn} = \'{value}\'' if type(value) == str else f'AND {cn} = {value}' for cn, value in zip(unique_column_names, unique_combination))} "
                    f") SELECT previous_timestamp, previous_value, {timestamp_column_name}, {value_column_name} "
                    "FROM gaps "
                    "WHERE previous_timestamp IS NOT NULL "
                    f"  AND {timestamp_column_name} - previous_timestamp > '{Timedelta(interval)}'::INTERVAL;"
                )

                # logging.debug(stmnt)
                gaps = conn.execute(stmnt).all()

                if not gaps:
                    logging.info(f"No gaps found for unique combination: {unique_combination}, value column: {value_column_name}")
                    continue

                logging.info(f"Found {len(gaps)} gaps for unique combination: {unique_combination}, value column: {value_column_name}")
                # fill gaps using the specified imputation method
                for gap in gaps:
                    if imputation_method == "linear_interpolate":
                        stmnt = text(
                            "WITH li AS ( "
                            "  SELECT * FROM linear_interpolate ( "
                            f"    '{gap._mapping['previous_timestamp']}'::TIMESTAMP, "
                            f"    {gap._mapping['previous_value']}::NUMERIC, "
                            f"    '{gap._mapping[timestamp_column_name]}'::TIMESTAMP, "
                            f"    {gap._mapping[value_column_name]}::NUMERIC, "
                            f"    '{Timedelta(interval)}'::INTERVAL "
                            f"  ) "
                            f") UPDATE {table_name}_gapfilled g "
                            f"SET {value_column_name} = ROUND(li.interpolated_value, 2), imputation_method = '{imputation_method}' "
                            "FROM li "
                            f"WHERE g.{timestamp_column_name} = li.timestmp "
                            f"  {'  '.join([f'AND g.{cn} = \'{val}\'' if type(val) == str else f'AND {cn} = {val}' for cn, val in zip(unique_column_names, unique_combination)])};"
                        )

                        # logging.debug(stmnt)
                        logging.debug(gap)
                        conn.execute(stmnt)
