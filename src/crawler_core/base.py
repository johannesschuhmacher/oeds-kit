# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Compatibility facade for the shared crawler base class."""

from crawler.common.base_crawler import (
    BaseCrawler,
    create_schema_only,
    set_metadata_only,
)

__all__ = ["BaseCrawler", "create_schema_only", "set_metadata_only"]
