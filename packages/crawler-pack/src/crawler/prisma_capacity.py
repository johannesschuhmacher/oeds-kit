# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

import pandas as pd
from sqlalchemy import text

from crawler.common.kit_base import KitCrawler
from crawler.common.crawler_utils import (
    CrawlerSkipped,
    build_session,
    compact_json,
    config_or_env,
    has_credential,
    stable_hash,
    utc_now,
    write_access_status,
)
from crawler.common.local_env import load_crawler_dotenv


log = logging.getLogger("prisma_capacity")
log.setLevel(logging.INFO)

DOCS_URL = "https://help.prisma-capacity.eu/solutions/shipper-hub-prisma-api-business-information"


class PrismaCapacityCrawler(KitCrawler):
    """Generic PRISMA API collector.

    PRISMA's public documentation describes paid API packages rather than an
    anonymous transparency API. This crawler therefore records access state by
    default and can import configured JSON resources once a subscribed API base
    URL and token are provided by the operator.
    """

    def __init__(self, crawler_name: str, config: dict):
        load_crawler_dotenv()
        super().__init__(crawler_name, config)
        self.session = build_session(self.config.get("user_agent"))
        self.timeout_seconds = int(self.config.get("request_timeout_seconds", 90))

    def _prepare_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS raw_resources (
                        resource_id text NOT NULL,
                        source_url text NOT NULL,
                        fetched_at timestamp with time zone NOT NULL,
                        row_number integer NOT NULL,
                        payload_json text NOT NULL,
                        record_key text NOT NULL,
                        PRIMARY KEY (resource_id, fetched_at, row_number)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW resource_summary AS
                    SELECT
                        resource_id,
                        count(*) AS rows,
                        max(fetched_at) AS last_fetch
                    FROM raw_resources
                    GROUP BY resource_id
                    """
                )
            )

    def _credentials(self) -> tuple[str | None, str | None]:
        api_base_url = config_or_env(self.config, "api_base_url", "PRISMA_API_BASE_URL")
        api_token = config_or_env(self.config, "api_token", "PRISMA_API_TOKEN")
        return api_base_url, api_token

    def _write_missing_status(self) -> None:
        write_access_status(
            self.engine,
            source_name="PRISMA Capacity Platform API",
            status="requires_subscription",
            access_model="PRISMA API package subscription; test credentials are provided after subscription",
            credentials_required=True,
            configured_credentials=False,
            message="Set PRISMA_API_BASE_URL and PRISMA_API_TOKEN after subscribing to a PRISMA API package.",
            docs_url=DOCS_URL,
        )

    def _fetch_resource(self, api_base_url: str, api_token: str, resource: dict[str, Any]) -> pd.DataFrame:
        resource_id = resource["id"]
        path = resource.get("path", "").lstrip("/")
        params = resource.get("params", {})
        source_url = f"{api_base_url.rstrip('/')}/{path}"
        response = self.session.get(source_url, params=params, headers={"Authorization": f"Bearer {api_token}"}, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = payload.get("data") or payload.get("items") or payload.get("value") or [payload]
        else:
            records = [{"value": payload}]
        fetched_at = utc_now()
        return pd.DataFrame(
            [
                {
                    "resource_id": resource_id,
                    "source_url": response.url,
                    "fetched_at": fetched_at,
                    "row_number": index,
                    "payload_json": compact_json(record),
                    "record_key": stable_hash(resource_id, index, record),
                }
                for index, record in enumerate(records, start=1)
            ]
        )

    def run(self):
        self._prepare_schema()
        failures: list[str] = []
        api_base_url, api_token = self._credentials()
        if not has_credential(api_base_url) or not has_credential(api_token):
            self._write_missing_status()
            raise CrawlerSkipped("PRISMA API credentials missing; wrote access status only.")

        write_access_status(
            self.engine,
            source_name="PRISMA Capacity Platform API",
            status="configured",
            access_model="Bearer token against subscribed PRISMA API package",
            credentials_required=True,
            configured_credentials=True,
            message="PRISMA API base URL and token are configured. Resource paths must match the booked API package.",
            docs_url=DOCS_URL,
        )

        resources = self.config.get("resources", [])
        frames = []
        for resource in resources:
            try:
                frames.append(self._fetch_resource(str(api_base_url), str(api_token), resource))
            except Exception as exc:
                self.logger.error("PRISMA resource %s failed: %s", resource.get("id"), exc)
                failures.append(str(resource.get("id")))

        if frames:
            frame = pd.concat(frames, ignore_index=True)
            with self.engine.begin() as conn:
                frame.to_sql("raw_resources", conn, if_exists="append", index=False)
        else:
            frame = pd.DataFrame()

        self.set_metadata(
            {
                "schema_name": self.schema_name,
                "data_date": datetime.now(tz=timezone.utc).date().isoformat(),
                "data_source": str(api_base_url),
                "license": "PRISMA API package terms; subscription-specific",
                "description": "Configured PRISMA Capacity Platform API resource imports.",
                "contact": "helpdesk@prisma-capacity.eu",
            }
        )
        self.logger.info("PRISMA crawler wrote %s rows.", len(frame))
        if failures:
            raise RuntimeError(f"PRISMA resources failed: {', '.join(failures)}")


def main(schema_name: str = "prisma_capacity"):
    config = {
        "database_uri": "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path=",
        "schema_name": schema_name,
    }
    PrismaCapacityCrawler("prisma_capacity", config).run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
