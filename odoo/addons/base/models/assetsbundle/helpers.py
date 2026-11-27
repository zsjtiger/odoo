"""The constants of the assets: the unique marker of the bundles and the extensions of the files."""

from __future__ import annotations

import logging

_logger = logging.getLogger('odoo.addons.base.models.assetsbundle')


ANY_UNIQUE = '_' * 7


EXTENSIONS = (".js", ".css", ".scss", ".sass", ".less", ".xml")
