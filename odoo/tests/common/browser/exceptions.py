# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Errors raised while driving the headless Chrome browser."""

from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    pass


class ChromeBrowserException(Exception):
    pass
