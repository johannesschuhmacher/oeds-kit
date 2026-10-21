# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = Path(
    os.getenv("OEDS_CRAWLER_CONFIG", ROOT / "CRAWLER_CONFIG.yml")
).expanduser()
CRAWLER_DATA_DIR = Path(
    os.getenv("OEDS_CRAWLER_DATA_DIR", ROOT / "crawler" / "data")
).expanduser()

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def load_crawler_config() -> dict:
    from crawler.entsoe_fms import EntsoeFMSCrawler

    with CONFIG_FILE.open(encoding="utf-8") as handle:
        raw_config = yaml.safe_load(handle)

    config = dict(raw_config["default"])
    config.update(raw_config.get("entsoe_fms", {}))
    config["schema_name"] = config.get("schema_name", "entsoe_fms")
    config["target_data_items"] = sorted(EntsoeFMSCrawler.OUTAGE_DATA_ITEMS)
    return config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill ENTSO-E unavailability extracts into entsoe_fms.",
    )
    parser.add_argument(
        "--start",
        default="2014-01-01",
        help="Start date in YYYY-MM-DD. Defaults to 2014-01-01.",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="End date in YYYY-MM-DD. Defaults to now.",
    )
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Skip refreshing derived availability map objects after the crawl.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    from crawler.entsoe_fms import EntsoeFMSCrawler

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
    )

    start_time = pd.Timestamp(args.start, tz="Europe/Berlin")
    end_time = (
        pd.Timestamp.now(tz="Europe/Berlin")
        if args.end is None
        else pd.Timestamp(args.end, tz="Europe/Berlin")
    )

    crawler = EntsoeFMSCrawler("entsoe_fms", load_crawler_config())
    local_dir = CRAWLER_DATA_DIR

    logging.info(
        "Backfilling ENTSO-E unavailability data items: %s",
        ", ".join(crawler.config["target_data_items"]),
    )
    crawler.fetch_from_entsoe_fms_to_database(
        str(local_dir),
        start_time,
        end_time,
        update_interval=pd.Timedelta(days=365),
    )

    if not args.skip_refresh:
        from scripts.refresh_entsoe_availability_map import main as refresh_availability_map

        refresh_availability_map()


if __name__ == "__main__":
    main()
