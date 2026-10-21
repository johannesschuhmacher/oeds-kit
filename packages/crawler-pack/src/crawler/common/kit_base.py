# SPDX-FileCopyrightText: Florian Maurer, Johannes Schuhmacher, Andre Meyer
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""KIT crawler base: upstream's ``oeds.base_crawler.BaseCrawler`` plus the
per-crawler logging/alert mails, dotted config access and metadata geometry
the pack's crawlers rely on."""

from abc import ABC, abstractmethod
from datetime import date

from oeds.base_crawler import BaseCrawler
from sqlalchemy import text

from crawler.common.crawler_logging import setup_crawler_logging
from crawler.common.runtime_env import resolve_database_uri


def kit_db_uri(config: dict) -> str:
    """Database URI for upstream's ``BaseCrawler``, which does
    ``db_uri.format(DBNAME=schema_name)``.

    The pack's configs carry ``database_uri`` ending in ``?options=--search_path=``
    and expect the schema appended, so a URI without ``{DBNAME}`` gets the
    placeholder appended (literal braces escaped) and formats to exactly the
    URI the pack built before. Raises ``KeyError`` when neither ``database_uri``
    nor ``db_uri`` is configured.
    """
    uri = resolve_database_uri(config.get("database_uri") or config["db_uri"])
    if "{DBNAME}" in uri:
        return uri
    return uri.replace("{", "{{").replace("}", "}}") + "{DBNAME}"


class KitCrawler(BaseCrawler, ABC):
    # crawler_name is the section name in CRAWLER_CONFIG.yml (the basename of the
    # crawler module); config is that section's effective configuration. The
    # scheduler passes both when it constructs the crawler.
    def __init__(self, crawler_name: str, config: dict):
        self.crawler_name = crawler_name
        self.config = config
        self.schema_name = config.get("schema_name") or crawler_name
        # upstream copies the dict and formats db_uri; database_uri stays in it
        super().__init__(self.schema_name, {**config, "db_uri": self.get_db_uri()})
        self.logger = setup_crawler_logging(crawler_name, self.config)

    def get_db_uri(self) -> str:
        return kit_db_uri(self.config)

    def get(self, key: str):
        keys = key.split('.')

        conf = self.config
        for k in keys:
            if isinstance(conf, dict) and k in conf:
                conf = conf[k]
            else:
                raise KeyError(f"Key '{key}' not found in crawler configuration.")
        return conf

    # This method is the only method that will be executed by the scheduler
    # so all the setup an the code to crawl the data needs to executed in
    # in this method in order for the crawler to work
    @abstractmethod
    def run(self):
        raise NotImplementedError("Run method not implemented. Override this method in your crawler and be sure that all the setup is done in this method as well.")

    def set_metadata(self, metadata_info: dict[str, str]) -> None:
        set_metadata_with_geometry(self.engine, metadata_info)


def set_metadata_with_geometry(engine, metadata_info: dict[str, str]):
    """Upstream's ``set_metadata_only`` plus the ``concave_hull_geometry`` column."""
    for key in ["concave_hull_geometry", "temporal_start", "temporal_end", "contact"]:
        if key not in metadata_info.keys():
            metadata_info[key] = None
    if "data_date" not in metadata_info.keys():
        metadata_info["data_date"] = date.today()
    with engine.begin() as conn:
        conn.execute(
            text("""
            INSERT INTO public.metadata
            (schema_name, data_date, data_source, license, description, contact, concave_hull_geometry, temporal_start, temporal_end)
            VALUES
            (:schema_name, :data_date, :data_source, :license, :description, :contact, :concave_hull_geometry, :temporal_start, :temporal_end)
            ON CONFLICT (schema_name) DO UPDATE SET
                data_date = EXCLUDED.data_date,
                data_source = EXCLUDED.data_source,
                license = EXCLUDED.license,
                description = EXCLUDED.description,
                contact = EXCLUDED.contact,
                concave_hull_geometry = EXCLUDED.concave_hull_geometry,
                temporal_start = EXCLUDED.temporal_start,
                temporal_end = EXCLUDED.temporal_end
            """),
            metadata_info,
        )
        conn.execute(
            text("""
            UPDATE public.metadata
            SET tables = (SELECT COUNT(*) FROM pg_class JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace WHERE nspname = :schema_name AND pg_class.relkind = 'r'),
                size = (SELECT SUM(pg_total_relation_size(pg_class.oid)) FROM pg_class JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace WHERE nspname = :schema_name AND pg_class.relkind = 'r'),
                crawl_date = NOW()
            WHERE schema_name = :schema_name
            """),
            {"schema_name": metadata_info["schema_name"]},
        )
        conn.execute(
            text("""
            NOTIFY pgrst, 'reload schema';
            """)
        )
