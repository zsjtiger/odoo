# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The languages: the language data, the digit grouping of the numbers and the model. The names are re-exported here."""

# the data and the grouping first, then the model that uses them
from .lang_data import LangData, LangDataDict
from .grouping import intersperse, intersperse_pat, split
from .lang import ResLang
