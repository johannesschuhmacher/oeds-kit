"""Cross-process crawler lock: a PostgreSQL session advisory lock.

The scheduler daemon and the admin UI run in separate containers, so an
in-process lock cannot keep them from starting the same crawler at once. Both
take ``pg_try_advisory_lock(hashtext('oeds-crawler:<name>'))`` on a dedicated
connection before a run and hold it until the run ends.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

try:
    from crawler.common.runtime_env import resolve_database_uri
except ImportError:  # pragma: no cover - crawler pack is optional for the core.

    def resolve_database_uri(database_uri: str) -> str:
        return database_uri


logger = logging.getLogger(__name__)

LOCK_KEY_PREFIX = "oeds-crawler:"


def lock_engine(database_uri: str) -> Any:
    """Engine for advisory locks.

    ``NullPool`` so that closing a connection really closes it and a lock can
    never linger on a pooled connection; autocommit so the connection does not
    sit idle in a transaction for the whole run.
    """

    return create_engine(
        resolve_database_uri(database_uri),
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )


class CrawlerLock:
    """One acquired advisory lock. ``release`` unlocks and closes the connection."""

    def __init__(self, connection: Any, key: str) -> None:
        self._connection = connection
        self.key = key

    @classmethod
    def try_acquire(cls, engine: Any, crawler_name: str) -> CrawlerLock | None:
        """Return the lock, or ``None`` when another process holds it."""

        key = LOCK_KEY_PREFIX + crawler_name
        connection = engine.connect()
        try:
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": key}
            ).scalar()
        except Exception:
            connection.close()
            raise
        if not acquired:
            connection.close()
            return None
        return cls(connection, key)

    def release(self) -> None:
        try:
            self._connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": self.key}
            )
        except Exception as exc:
            # Closing the session releases the lock anyway.
            logger.warning("Could not unlock %s explicitly: %s", self.key, exc)
        finally:
            self._connection.close()
