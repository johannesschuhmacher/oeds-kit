"""``oeds-crawl``: run one crawler by hand, with the config the scheduler would use.

Crawlers are found through the ``oeds.crawlers`` entry points that every crawler
package declares in its pyproject.toml. Exit codes: 0 the run succeeded, 1 it
failed, 3 it was skipped (nothing to do, e.g. missing credentials). The scheduler
starts crawlers through this command, so a run behaves the same either way.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path

from crawler.common.crawler_config import (
    crawler_sections,
    effective_crawler_config,
    job_names,
    load_config_file,
)
from crawler.common.crawler_utils import CrawlerSkipped
from crawler.common.local_env import apply_email_env_overrides

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_SKIPPED = 3
ENTRY_POINT_GROUP = "oeds.crawlers"

log = logging.getLogger("oeds-crawl")


def crawler_entry_points() -> dict[str, EntryPoint]:
    return {entry.name: entry for entry in entry_points(group=ENTRY_POINT_GROUP)}


def load_crawler_class(crawler_name: str) -> type:
    entries = crawler_entry_points()
    if crawler_name not in entries:
        known = ", ".join(sorted(entries)) or "none"
        raise LookupError(
            f"no crawler '{crawler_name}' registered under {ENTRY_POINT_GROUP} (known: {known})"
        )
    return entries[crawler_name].load()


def run_crawler(crawler) -> None:
    """Run a pack crawler (``run``) or an upstream OEDS crawler (``crawl_*``)."""
    if hasattr(crawler, "run"):
        crawler.run()
        return
    if hasattr(crawler, "crawl_structural"):
        crawler.crawl_structural()
    if hasattr(crawler, "crawl_temporal"):
        crawler.crawl_temporal()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="oeds-crawl",
        description="Run one OEDS crawler with the config the scheduler would use.",
    )
    parser.add_argument("crawler", nargs="?", help="crawler name as in CRAWLER_CONFIG.yml")
    parser.add_argument(
        "--config",
        default=os.getenv("OEDS_CRAWLER_CONFIG", "CRAWLER_CONFIG.yml"),
        help="crawler config file (default: $OEDS_CRAWLER_CONFIG or ./CRAWLER_CONFIG.yml)",
    )
    parser.add_argument("--job", help="named job of the crawler section (default: the section itself)")
    parser.add_argument("--list", action="store_true", help="list registered crawlers and exit")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.list:
        entries = crawler_entry_points()
        configured: set[str] = set()
        if Path(args.config).is_file():
            configured = set(crawler_sections(load_config_file(args.config)))
        for name in sorted(entries):
            marker = "configured" if name in configured else ""
            print(f"{name:<28} {entries[name].value:<55} {marker}")
        return EXIT_OK
    if not args.crawler:
        parser.error("crawler name is required unless --list is given")

    config_path = Path(args.config)
    raw_config = apply_email_env_overrides(load_config_file(config_path), config_path.parent)
    try:
        config = effective_crawler_config(raw_config, args.crawler, args.job)
    except KeyError as exc:
        jobs = job_names(raw_config, args.crawler)
        hint = f" (jobs: {', '.join(jobs)})" if jobs else ""
        log.error("%s%s", exc.args[0], hint)
        return EXIT_FAILED

    try:
        crawler_class = load_crawler_class(args.crawler)
        crawler = crawler_class(args.crawler, config)
        log.info("Running %s (%s)", args.crawler, config["_scheduler_job_id"])
        run_crawler(crawler)
    except CrawlerSkipped as exc:
        log.info("Skipped %s: %s", args.crawler, exc)
        return EXIT_SKIPPED
    except Exception:
        # The crawler's own logger carries the file handler and the SMTP alert
        # handler (set up in KitCrawler.__init__); a CRITICAL record there writes
        # the traceback to logs/<crawler>.log and sends the alert mail. The
        # scheduler only sees the exit code, so this must happen here.
        logging.getLogger(args.crawler).critical("Run of %s failed", args.crawler, exc_info=True)
        return EXIT_FAILED
    log.info("Finished %s", args.crawler)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
