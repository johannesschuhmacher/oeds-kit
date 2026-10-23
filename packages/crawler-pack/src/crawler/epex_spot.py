# SPDX-FileCopyrightText: Johannes Schuhmacher, Andre Meyer
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
EPEX SPOT market data crawler.

The crawler imports German EPEX SPOT intraday market data from the market-data
SFTP service into PostgreSQL:

- Intraday Continuous end-of-day statistics
- Intraday Continuous indices
- Intraday Continuous transaction ZIP files
- Pan-European intraday auction prices and volumes for IDA1, IDA2, and IDA3
"""

from __future__ import annotations

import io
import os
import re
import stat
import zipfile
from typing import Callable, Iterator

import pandas as pd
import paramiko
from dotenv import load_dotenv
from sqlalchemy import BigInteger, Column, Date, DateTime, Float, MetaData, String, Table, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import insert

from crawler.common.kit_base import KitCrawler
from crawler.common.local_env import load_crawler_dotenv


EPEX_SOURCE_URL = "sftp://sftp.marketdata.epexspot.com/germany"
DEFAULT_HOST = "sftp.marketdata.epexspot.com"
DEFAULT_PORT = 22
DEFAULT_MARKET_AREA = "DE"
DEFAULT_IDA_MARKET_AREA = "DE-LU"
BERLIN_TZ = "Europe/Berlin"

CONTINUOUS_STATISTICS_DIR = "/germany/Intraday Continuous/EOD/Results"
CONTINUOUS_INDEX_DIR = "/germany/Intraday Continuous/Indices/Intraday indices"
CONTINUOUS_TRADES_DIR = "/germany/Intraday Continuous/EOD/Transactions"

IDA_CURRENT_PRICE_VOLUME_DIRS = {
    "IDA1": "/germany/Intraday Auction/Pan-European IDA1/Current/Prices_Volumes",
    "IDA2": "/germany/Intraday Auction/Pan-European IDA2/Current/Prices_Volumes",
    "IDA3": "/germany/Intraday Auction/Pan-European IDA3/Current/Prices_Volumes",
}

DATASET_CONTINUOUS_STATISTICS = "continuous_statistics"
DATASET_CONTINUOUS_INDICES = "continuous_indices"
DATASET_CONTINUOUS_TRADES = "continuous_trades"
DATASET_INTRADAY_AUCTIONS = "intraday_auctions"
ALL_DATASETS = {
    DATASET_CONTINUOUS_STATISTICS,
    DATASET_CONTINUOUS_INDICES,
    DATASET_CONTINUOUS_TRADES,
    DATASET_INTRADAY_AUCTIONS,
}

IDA_PRODUCT_COLUMN_RE = re.compile(
    r"^Hour (?P<hour>\d{1,2})(?P<suffix>[AB]?) Q(?P<quarter>[1-4])$"
)


class EpexSpotCrawler(KitCrawler):
    """Crawler for German EPEX SPOT intraday market data."""

    def __init__(self, crawler_name: str, config: dict):
        load_crawler_dotenv()
        load_dotenv(override=False)
        super().__init__(crawler_name, config)

        self.metadata = MetaData(schema=self.schema_name)
        self.tables: dict[str, Table] = {}
        self.sftp: paramiko.SFTPClient | None = None
        self.transport: paramiko.Transport | None = None
        self._define_tables()

    def get_db_uri(self):
        # Prefer the scheduler/admin configuration. This prevents a stale local
        # EPEX_DATABASE_URI from silently redirecting scheduled writes.
        try:
            return super().get_db_uri()
        except KeyError:
            configured = os.getenv("EPEX_DATABASE_URI") or os.getenv("OEDS_EPEX_DATABASE_URI")
            if configured:
                return configured
            raise

    def _configured_start_time(self, key: str = "start_date") -> pd.Timestamp:
        configured = self.config.get(key) or self.config.get("start_date")
        if configured:
            start = pd.Timestamp(configured)
        else:
            start = pd.Timestamp(year=1970, month=1, day=1, tz=BERLIN_TZ)

        if start.tzinfo is None:
            return start.tz_localize(BERLIN_TZ).tz_convert("UTC")
        return start.tz_convert("UTC")

    def _update_interval(self) -> pd.Timedelta:
        return pd.Timedelta(days=int(self.config.get("update_interval_days", 14)))

    def _enabled_datasets(self) -> set[str]:
        configured = self.config.get("target_datasets")
        if configured:
            requested = {str(item) for item in configured}
            unknown = requested - ALL_DATASETS
            if unknown:
                raise ValueError(f"Unknown EPEX dataset(s): {', '.join(sorted(unknown))}")
            return requested

        enabled = set()
        if self.config.get("include_continuous_statistics", True):
            enabled.add(DATASET_CONTINUOUS_STATISTICS)
        if self.config.get("include_continuous_indices", True):
            enabled.add(DATASET_CONTINUOUS_INDICES)
        if self.config.get("include_intraday_auctions", True):
            enabled.add(DATASET_INTRADAY_AUCTIONS)
        if self.config.get("include_continuous_trades", True):
            enabled.add(DATASET_CONTINUOUS_TRADES)
        return enabled

    def _get_secret(self, env_name: str, config_key: str) -> str | None:
        value = os.getenv(env_name)
        if value:
            return value
        configured = self.config.get(config_key)
        return str(configured) if configured else None

    def _define_tables(self) -> None:
        self.tables["continuous_statistics"] = Table(
            "continuous_statistics",
            self.metadata,
            Column("market_area", String, nullable=False),
            Column("delivery_start_utc", DateTime(timezone=True), nullable=False),
            Column("delivery_end_utc", DateTime(timezone=True), nullable=False),
            Column("low_price", Float),
            Column("high_price", Float),
            Column("last_price", Float),
            Column("weighted_average_price", Float),
            Column("currency", String),
            Column("last_price_timestamp_utc", DateTime(timezone=True)),
            Column("volume_buy", Float),
            Column("volume_sell", Float),
            Column("volume_unit", String),
            Column("source_file", String, nullable=False),
            Column("publication_time_utc", DateTime(timezone=True)),
            Column("download_time_utc", DateTime(timezone=True), nullable=False),
            UniqueConstraint(
                "market_area",
                "delivery_start_utc",
                "delivery_end_utc",
                name="unique_epex_continuous_statistics",
            ),
        )

        self.tables["continuous_indices"] = Table(
            "continuous_indices",
            self.metadata,
            Column("market_area", String, nullable=False),
            Column("index_name", String, nullable=False),
            Column("time_resolution", String, nullable=False),
            Column("delivery_start_utc", DateTime(timezone=True), nullable=False),
            Column("delivery_end_utc", DateTime(timezone=True), nullable=False),
            Column("index_price", Float),
            Column("currency", String),
            Column("index_volume", Float),
            Column("volume_unit", String),
            Column("source_file", String, nullable=False),
            Column("publication_time_utc", DateTime(timezone=True)),
            Column("download_time_utc", DateTime(timezone=True), nullable=False),
            UniqueConstraint(
                "market_area",
                "index_name",
                "time_resolution",
                "delivery_start_utc",
                "delivery_end_utc",
                name="unique_epex_continuous_indices",
            ),
        )

        self.tables["intraday_auction_prices_volumes"] = Table(
            "intraday_auction_prices_volumes",
            self.metadata,
            Column("auction_name", String, nullable=False),
            Column("market_area", String, nullable=False),
            Column("metric", String, nullable=False),
            Column("delivery_day", Date, nullable=False),
            Column("delivery_start_utc", DateTime(timezone=True), nullable=False),
            Column("delivery_end_utc", DateTime(timezone=True), nullable=False),
            Column("time_label", String),
            Column("value", Float),
            Column("currency", String),
            Column("volume_unit", String),
            Column("source_file", String, nullable=False),
            Column("publication_time_utc", DateTime(timezone=True)),
            Column("download_time_utc", DateTime(timezone=True), nullable=False),
            UniqueConstraint(
                "auction_name",
                "market_area",
                "metric",
                "delivery_start_utc",
                "delivery_end_utc",
                name="unique_epex_intraday_auction_prices_volumes",
            ),
        )

        self.tables["continuous_trades"] = Table(
            "continuous_trades",
            self.metadata,
            Column("trade_id", String, nullable=False),
            Column("remote_trade_id", String),
            Column("side", String, nullable=False),
            Column("product", String),
            Column("delivery_start_utc", DateTime(timezone=True), nullable=False),
            Column("delivery_end_utc", DateTime(timezone=True), nullable=False),
            Column("execution_time_utc", DateTime(timezone=True), nullable=False),
            Column("delivery_area", String),
            Column("trade_phase", String),
            Column("user_defined_block", String),
            Column("self_trade", String),
            Column("price", Float),
            Column("currency", String),
            Column("volume", Float),
            Column("volume_unit", String),
            Column("order_id", String, nullable=False),
            Column("source_file", String, nullable=False),
            Column("publication_time_utc", DateTime(timezone=True)),
            Column("download_time_utc", DateTime(timezone=True), nullable=False),
            UniqueConstraint(
                "trade_id",
                "side",
                "order_id",
                name="unique_epex_continuous_trades",
            ),
        )

        # Remote files already written to the database, identified by path, size and
        # modification time. Trade archives are 1M+ rows each and never change once
        # published; without this every run re-imported the whole update window.
        self.tables["imported_files"] = Table(
            "imported_files",
            self.metadata,
            Column("remote_path", String, primary_key=True),
            Column("file_size", BigInteger, primary_key=True),
            Column("file_mtime", BigInteger, primary_key=True),
            Column("rows", BigInteger, nullable=False),
            Column("imported_at", DateTime(timezone=True), nullable=False),
        )

    def _ensure_tables(self) -> None:
        self.metadata.create_all(self.engine)
        # The trade table grows by about 1M rows a day. Without this index every run
        # (MAX(delivery_start_utc)) and every dashboard query scans the whole table.
        with self.engine.begin() as conn:
            conn.execute(text(
                f'CREATE INDEX IF NOT EXISTS idx_epex_continuous_trades_delivery_start '
                f'ON "{self.schema_name}".continuous_trades (delivery_start_utc)'
            ))

    def _upsert_dataframe(self, table_name: str, df: pd.DataFrame, constraint_name: str) -> int:
        """Upsert through COPY into a temporary table and one INSERT ... ON CONFLICT.

        Multi-row INSERT statements with 5000 x 19 bound values were the bottleneck
        (about 8 minutes per daily trade archive).
        """
        if df.empty:
            return 0

        table = self.tables[table_name]
        columns = [column.name for column in table.columns]
        constraint = next(c for c in table.constraints if c.name == constraint_name)
        key_columns = list(constraint.columns.keys())
        # ON CONFLICT DO UPDATE fails if one statement touches the same key twice.
        df = df.reindex(columns=columns).drop_duplicates(subset=key_columns, keep="last")

        buffer = io.StringIO()
        df.to_csv(buffer, index=False, header=False)
        buffer.seek(0)

        target = f'"{self.schema_name}"."{table.name}"'
        column_list = ", ".join(f'"{column}"' for column in columns)
        updates = ", ".join(
            f'"{column}" = EXCLUDED."{column}"' for column in columns if column not in key_columns
        )
        with self.engine.begin() as conn:
            cursor = conn.connection.cursor()
            cursor.execute(f"CREATE TEMP TABLE epex_stage (LIKE {target}) ON COMMIT DROP")
            cursor.copy_expert(f"COPY epex_stage ({column_list}) FROM STDIN WITH (FORMAT csv)", buffer)
            cursor.execute(
                f"INSERT INTO {target} ({column_list}) SELECT {column_list} FROM epex_stage "
                f"ON CONFLICT ON CONSTRAINT {constraint_name} DO UPDATE SET {updates}"
            )
        return len(df)

    def _imported_file_keys(self, remote_dir: str) -> set[tuple[str, int, int]]:
        prefix = remote_dir.rstrip("/") + "/"
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    f'SELECT remote_path, file_size, file_mtime FROM "{self.schema_name}".imported_files '
                    "WHERE starts_with(remote_path, :prefix)"
                ),
                {"prefix": prefix},
            )
            return {(path, int(size), int(mtime)) for path, size, mtime in rows}

    def _mark_imported(self, remote_path: str, entry: paramiko.SFTPAttributes, rows: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f'INSERT INTO "{self.schema_name}".imported_files '
                    "(remote_path, file_size, file_mtime, rows, imported_at) "
                    "VALUES (:path, :size, :mtime, :rows, now()) ON CONFLICT DO NOTHING"
                ),
                {"path": remote_path, "size": int(entry.st_size or 0),
                 "mtime": int(entry.st_mtime or 0), "rows": rows},
            )

    def _latest_delivery_start(self, table_name: str) -> pd.Timestamp | None:
        table = self.tables[table_name]
        with self.engine.connect() as conn:
            result = conn.execute(
                text(f'SELECT MAX(delivery_start_utc) FROM "{self.schema_name}"."{table.name}"')
            ).scalar()
        if result is None:
            return None
        return pd.Timestamp(result).tz_convert("UTC")

    def _effective_start_time(self, table_name: str, config_key: str = "start_date") -> pd.Timestamp:
        configured_start = self._configured_start_time(config_key)
        latest = self._latest_delivery_start(table_name)
        if latest is None:
            return configured_start
        return max(configured_start, latest - self._update_interval())

    def _connect_sftp(self) -> None:
        username_env = str(self.config.get("username_env", "EPEX_SFTP_USERNAME"))
        password_env = str(self.config.get("password_env", "EPEX_SFTP_PASSWORD"))
        host = str(os.getenv("EPEX_SFTP_HOST") or self.config.get("sftp_host") or DEFAULT_HOST)
        port = int(os.getenv("EPEX_SFTP_PORT") or self.config.get("sftp_port") or DEFAULT_PORT)
        username = self._get_secret(username_env, "sftp_username")
        password = self._get_secret(password_env, "sftp_password")

        if not username or not password:
            raise RuntimeError(
                f"EPEX SFTP credentials are missing. Set {username_env} and {password_env}."
            )

        self.transport = paramiko.Transport((host, port))
        self.transport.banner_timeout = 30
        self.transport.auth_timeout = 30
        self.transport.connect(username=username, password=password)
        self.transport.set_keepalive(30)
        self.sftp = paramiko.SFTPClient.from_transport(self.transport)
        self.logger.info("Connected to EPEX SPOT SFTP host %s:%s", host, port)

    def _disconnect_sftp(self) -> None:
        if self.sftp is not None:
            self.sftp.close()
            self.sftp = None
        if self.transport is not None:
            self.transport.close()
            self.transport = None

    def _list_remote_files(self, remote_dir: str) -> list[paramiko.SFTPAttributes]:
        if self.sftp is None:
            raise RuntimeError("SFTP connection is not open.")

        entries = self.sftp.listdir_attr(remote_dir)
        files = [entry for entry in entries if not stat.S_ISDIR(entry.st_mode)]
        return sorted(files, key=lambda entry: entry.filename)

    def _download_bytes(self, remote_path: str, attempts: int = 3) -> bytes:
        """Read one remote file; reconnect and retry when the server drops the session.

        The EPEX SFTP server closes idle or long sessions ("Socket is closed"
        in the middle of a run), which otherwise fails the whole run.
        """
        if self.sftp is None:
            raise RuntimeError("SFTP connection is not open.")

        for attempt in range(1, attempts + 1):
            try:
                with self.sftp.open(remote_path, "rb") as remote_file:
                    return remote_file.read()
            except (OSError, EOFError, paramiko.SSHException) as exc:
                if attempt == attempts:
                    raise
                self.logger.warning(
                    "SFTP read of %s failed (%s); reconnecting (attempt %s of %s)",
                    remote_path, exc, attempt + 1, attempts,
                )
                self._disconnect_sftp()
                self._connect_sftp()
        raise RuntimeError("unreachable")

    @staticmethod
    def _join_remote_path(remote_dir: str, filename: str) -> str:
        return f"{remote_dir.rstrip('/')}/{filename}"

    @staticmethod
    def _file_period(filename: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        day_match = re.search(r"(20\d{2})(\d{2})(\d{2})", filename)
        if day_match:
            year, month, day = (int(part) for part in day_match.groups())
            try:
                start = pd.Timestamp(year=year, month=month, day=day, tz=BERLIN_TZ).tz_convert("UTC")
            except ValueError:
                return None
            return start, start + pd.Timedelta(days=1)

        year_match = re.search(r"(20\d{2})", filename)
        if year_match:
            year = int(year_match.group(1))
            start = pd.Timestamp(year=year, month=1, day=1, tz=BERLIN_TZ).tz_convert("UTC")
            return start, start + pd.DateOffset(years=1)

        return None

    @staticmethod
    def _first_line(payload: bytes) -> str:
        if not payload:
            return ""
        return payload.splitlines()[0].decode("utf-8-sig", errors="replace")

    @staticmethod
    def _publication_time_from_header(header: str) -> pd.Timestamp | None:
        iso_match = re.search(
            r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)",
            header,
        )
        if iso_match:
            return pd.to_datetime(iso_match.group(1), utc=True)

        local_match = re.search(
            r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} [AP]M)",
            header,
        )
        if local_match:
            local_time = pd.to_datetime(
                local_match.group(1),
                format="%d/%m/%Y %I:%M:%S %p",
                errors="coerce",
            )
            if pd.isna(local_time):
                return None
            return local_time.tz_localize(BERLIN_TZ).tz_convert("UTC")

        return None

    @staticmethod
    def _read_csv_payload(payload: bytes) -> tuple[str, pd.DataFrame]:
        header = EpexSpotCrawler._first_line(payload)
        df = pd.read_csv(io.BytesIO(payload), comment="#")
        return header, df

    @staticmethod
    def _timestamp_utc(series: pd.Series) -> pd.Series:
        return pd.to_datetime(series, utc=True, errors="coerce")

    @staticmethod
    def _numeric(series: pd.Series) -> pd.Series:
        return pd.to_numeric(series, errors="coerce")

    @staticmethod
    def _delivery_start_from_ida_label(
        delivery_day: pd.Timestamp,
        label: str,
    ) -> pd.Timestamp | None:
        match = IDA_PRODUCT_COLUMN_RE.match(label)
        if not match:
            return None

        hour = int(match.group("hour"))
        quarter = int(match.group("quarter"))
        suffix = match.group("suffix")
        local_time = delivery_day + pd.Timedelta(
            hours=hour - 1,
            minutes=(quarter - 1) * 15,
        )
        ambiguous: bool | str = "raise"
        if suffix == "A":
            ambiguous = True
        elif suffix == "B":
            ambiguous = False

        try:
            localized = local_time.tz_localize(
                BERLIN_TZ,
                ambiguous=ambiguous,
                nonexistent="NaT",
            )
        except ValueError:
            try:
                localized = local_time.tz_localize(
                    BERLIN_TZ,
                    ambiguous=True,
                    nonexistent="NaT",
                )
            except ValueError:
                return None

        if pd.isna(localized):
            return None
        return localized.tz_convert("UTC")

    @staticmethod
    def _filter_delivery_start(df: pd.DataFrame, start_time: pd.Timestamp) -> pd.DataFrame:
        if df.empty:
            return df
        return df[df["delivery_start_utc"] >= start_time].copy()

    def _parse_continuous_statistics(self, payload: bytes, filename: str) -> pd.DataFrame:
        header, df = self._read_csv_payload(payload)
        if df.empty:
            return df

        df = df.rename(
            columns={
                "DeliveryStart": "delivery_start_utc",
                "DeliveryEnd": "delivery_end_utc",
                "LowPrice": "low_price",
                "HighPrice": "high_price",
                "LastPrice": "last_price",
                "WeightedAveragePrice": "weighted_average_price",
                "Currency": "currency",
                "LastPriceTimestamp": "last_price_timestamp_utc",
                "VolumeBuy": "volume_buy",
                "VolumeSell": "volume_sell",
                "VolumeUnit": "volume_unit",
            }
        )

        for column in ("delivery_start_utc", "delivery_end_utc", "last_price_timestamp_utc"):
            if column in df.columns:
                df[column] = self._timestamp_utc(df[column])

        for column in (
            "low_price",
            "high_price",
            "last_price",
            "weighted_average_price",
            "volume_buy",
            "volume_sell",
        ):
            if column in df.columns:
                df[column] = self._numeric(df[column])

        df["market_area"] = DEFAULT_MARKET_AREA
        df["source_file"] = filename
        df["publication_time_utc"] = self._publication_time_from_header(header)
        df["download_time_utc"] = pd.Timestamp.now(tz="UTC")
        return df

    def _parse_continuous_indices(self, payload: bytes, filename: str) -> pd.DataFrame:
        header, df = self._read_csv_payload(payload)
        if df.empty:
            return df

        df = df.rename(
            columns={
                "IndexName": "index_name",
                "TimeResolution": "time_resolution",
                "DeliveryStart": "delivery_start_utc",
                "DeliveryEnd": "delivery_end_utc",
                "IndexPrice": "index_price",
                "Currency": "currency",
                "IndexVolume": "index_volume",
                "VolumeUnit": "volume_unit",
            }
        )

        for column in ("delivery_start_utc", "delivery_end_utc"):
            if column in df.columns:
                df[column] = self._timestamp_utc(df[column])
        for column in ("index_price", "index_volume"):
            if column in df.columns:
                df[column] = self._numeric(df[column])

        df["market_area"] = DEFAULT_MARKET_AREA
        df["source_file"] = filename
        df["publication_time_utc"] = self._publication_time_from_header(header)
        df["download_time_utc"] = pd.Timestamp.now(tz="UTC")
        return df

    def _parse_continuous_trades_zip(self, payload: bytes, filename: str) -> Iterator[pd.DataFrame]:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for member in archive.namelist():
                if not member.lower().endswith(".csv"):
                    continue
                with archive.open(member) as csv_file:
                    header = csv_file.readline().decode("utf-8-sig", errors="replace")
                    csv_file.seek(0)
                    # Trade archives can expand to several GB; normalize and write one block at a time.
                    batch_size = int(self.config.get("database_batch_size", 100000))
                    for df in pd.read_csv(csv_file, comment="#", chunksize=batch_size,
                                          dtype={"TradeId": "string", "RemoteTradeId": "string", "OrderID": "string"}):
                        df = df.rename(columns={
                            "TradeId": "trade_id", "RemoteTradeId": "remote_trade_id",
                            "Side": "side", "Product": "product",
                            "DeliveryStart": "delivery_start_utc", "DeliveryEnd": "delivery_end_utc",
                            "ExecutionTime": "execution_time_utc", "DeliveryArea": "delivery_area",
                            "TradePhase": "trade_phase", "UserDefinedBlock": "user_defined_block",
                            "SelfTrade": "self_trade", "Price": "price", "Currency": "currency",
                            "Volume": "volume", "VolumeUnit": "volume_unit", "OrderID": "order_id",
                        })
                        for column in ("delivery_start_utc", "delivery_end_utc", "execution_time_utc"):
                            if column in df.columns:
                                df[column] = self._timestamp_utc(df[column])
                        for column in ("price", "volume"):
                            if column in df.columns:
                                df[column] = self._numeric(df[column])
                        for column in ("trade_id", "remote_trade_id", "order_id"):
                            if column in df.columns:
                                df[column] = df[column].astype("string")
                        df["source_file"] = filename
                        df["publication_time_utc"] = self._publication_time_from_header(header)
                        df["download_time_utc"] = pd.Timestamp.now(tz="UTC")
                        yield df

    def _parse_intraday_auction_file(
        self,
        payload: bytes,
        filename: str,
        auction_name: str,
    ) -> pd.DataFrame:
        header, wide = self._read_csv_payload(payload)
        if wide.empty or "Delivery day" not in wide.columns:
            return pd.DataFrame()

        filename_lower = filename.lower()
        metric = "price" if "price" in filename_lower else "volume"
        currency = "EUR" if metric == "price" else None
        volume_unit = "MWH" if metric == "volume" else None
        publication_time = self._publication_time_from_header(header)
        download_time = pd.Timestamp.now(tz="UTC")

        value_columns = [
            column
            for column in wide.columns
            if IDA_PRODUCT_COLUMN_RE.match(str(column))
        ]
        rows = []
        for _, source_row in wide.iterrows():
            delivery_day = pd.to_datetime(
                source_row["Delivery day"],
                format="%d/%m/%Y",
                errors="coerce",
            )
            if pd.isna(delivery_day):
                continue

            for label in value_columns:
                raw_value = source_row[label]
                if pd.isna(raw_value) or str(raw_value).strip() == "":
                    continue
                value = pd.to_numeric(raw_value, errors="coerce")
                if pd.isna(value):
                    continue
                delivery_start = self._delivery_start_from_ida_label(
                    delivery_day,
                    str(label),
                )
                if delivery_start is None:
                    continue
                rows.append(
                    {
                        "auction_name": auction_name,
                        "market_area": DEFAULT_IDA_MARKET_AREA,
                        "metric": metric,
                        "delivery_day": delivery_day.date(),
                        "delivery_start_utc": delivery_start,
                        "delivery_end_utc": delivery_start + pd.Timedelta(minutes=15),
                        "time_label": str(label),
                        "value": float(value),
                        "currency": currency,
                        "volume_unit": volume_unit,
                        "source_file": filename,
                        "publication_time_utc": publication_time,
                        "download_time_utc": download_time,
                    }
                )

        return pd.DataFrame(rows)

    def _import_remote_files(
        self,
        remote_dir: str,
        table_name: str,
        parser: Callable[[bytes, str], pd.DataFrame | Iterator[pd.DataFrame]],
        constraint_name: str,
        start_time: pd.Timestamp,
    ) -> int:
        affected = 0
        skipped = 0
        files = self._list_remote_files(remote_dir)
        imported = self._imported_file_keys(remote_dir)
        for entry in files:
            period = self._file_period(entry.filename)
            if period is not None and period[1] < start_time:
                continue

            remote_path = self._join_remote_path(remote_dir, entry.filename)
            if (remote_path, int(entry.st_size or 0), int(entry.st_mtime or 0)) in imported:
                skipped += 1
                continue
            payload = self._download_bytes(remote_path)
            parsed = parser(payload, entry.filename)
            frames = [parsed] if isinstance(parsed, pd.DataFrame) else parsed
            rows = 0
            for frame in frames:
                frame = self._filter_delivery_start(frame, start_time)
                rows += self._upsert_dataframe(table_name, frame, constraint_name)
            affected += rows
            self._mark_imported(remote_path, entry, rows)
            self.logger.info("Imported %s rows from %s", rows, remote_path)
        if skipped:
            self.logger.info("Skipped %s unchanged file(s) in %s", skipped, remote_dir)
        return affected

    def _import_continuous_statistics(self) -> int:
        start_time = self._effective_start_time("continuous_statistics")
        return self._import_remote_files(
            CONTINUOUS_STATISTICS_DIR,
            "continuous_statistics",
            self._parse_continuous_statistics,
            "unique_epex_continuous_statistics",
            start_time,
        )

    def _import_continuous_indices(self) -> int:
        start_time = self._effective_start_time("continuous_indices")
        return self._import_remote_files(
            CONTINUOUS_INDEX_DIR,
            "continuous_indices",
            self._parse_continuous_indices,
            "unique_epex_continuous_indices",
            start_time,
        )

    def _import_continuous_trades(self) -> int:
        start_time = self._effective_start_time("continuous_trades", "continuous_trades_start_date")
        return self._import_remote_files(
            CONTINUOUS_TRADES_DIR,
            "continuous_trades",
            self._parse_continuous_trades_zip,
            "unique_epex_continuous_trades",
            start_time,
        )

    def _import_intraday_auctions(self) -> int:
        start_time = self._effective_start_time(
            "intraday_auction_prices_volumes",
            "intraday_auction_start_date",
        )
        affected = 0
        for auction_name, remote_dir in IDA_CURRENT_PRICE_VOLUME_DIRS.items():
            parser = lambda payload, filename, name=auction_name: self._parse_intraday_auction_file(
                payload,
                filename,
                name,
            )
            affected += self._import_remote_files(
                remote_dir,
                "intraday_auction_prices_volumes",
                parser,
                "unique_epex_intraday_auction_prices_volumes",
                start_time,
            )
        return affected

    def run(self) -> None:
        self._ensure_tables()
        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_source": EPEX_SOURCE_URL,
                "license": "EPEX SPOT market data account",
                "description": "German EPEX SPOT intraday market data",
                "contact": "OEDS maintainers",
            }
        )

        enabled = self._enabled_datasets()
        self.logger.info("Starting EPEX SPOT import for datasets: %s", ", ".join(sorted(enabled)))
        self._connect_sftp()
        try:
            if DATASET_CONTINUOUS_STATISTICS in enabled:
                self._import_continuous_statistics()
            if DATASET_CONTINUOUS_INDICES in enabled:
                self._import_continuous_indices()
            if DATASET_INTRADAY_AUCTIONS in enabled:
                self._import_intraday_auctions()
            if DATASET_CONTINUOUS_TRADES in enabled:
                self._import_continuous_trades()
        finally:
            self._disconnect_sftp()
