# SPDX-FileCopyrightText: Johannes Schuhmacher, Andre Meyer
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from lib.gapfill import fill_gaps
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.DEBUG)

fill_gaps(
    schema_name="smard",
    table_name="smard.smard",
    timestamp_column_name="timestamp",
    start_datetime=datetime(2024, 6, 2, 22, 0, 0),
    end_datetime= datetime(2024, 6, 9, 21, 45, 0),
    interval=timedelta(minutes=15),
    unique_column_names=["commodity_id", "commodity_name"],
    value_column_names=["mwh"],
    copy_column_names=["download_timestamp"],
    imputation_method="linear_interpolate"
)
