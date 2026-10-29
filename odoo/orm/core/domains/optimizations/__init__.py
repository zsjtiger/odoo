# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The optimizations of the domains. Importing them registers them, in this order."""

from . import sets
from . import dates
from . import relational
from . import text
from . import merge
