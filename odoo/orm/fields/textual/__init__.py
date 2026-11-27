# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The string fields: the base class, the character, text and HTML fields, and the translations of their values. The names are re-exported here."""

from odoo.tools.text.translate import StoredTranslations
from .base import BaseString
from .cache import LangProxyDict
from .char import Char, Text
from .html import Html
