# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The relational fields, split by kind: the many2one, the one2many and the many2many. The names are re-exported here."""

from .base import _Relational, _schema
from .many2one import Many2one
from .multi import _RelationalMulti
from .one2many import One2many
from .many2many import Many2many, TableSQLId

__all__ = [
    'Many2many',
    'Many2one',
    'One2many',
    'TableSQLId',
]
