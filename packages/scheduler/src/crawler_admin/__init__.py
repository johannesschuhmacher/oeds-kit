# SPDX-FileCopyrightText: Johannes Schuhmacher
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""OEDS crawler admin UI package."""

from importlib.util import find_spec

# oeds-post-scripts is optional. Without it the gapfill and price-forecast
# pages, panels and actions are absent; everything else works as usual.
POST_INSTALLED = find_spec("oeds_gapfill") is not None
