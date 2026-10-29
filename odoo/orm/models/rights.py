# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Access rights checks of the records and of their fields."""

from __future__ import annotations

import functools
import logging
import re
import typing
from collections.abc import Callable

import psycopg2.extensions

from odoo.exceptions import AccessError
from odoo.tools.text.translate import LazyTranslate


from odoo.orm.core.domains import Domain
from odoo.orm.fields import Field


if typing.TYPE_CHECKING:
    from typing import Self


_lt = LazyTranslate('base')
_logger = logging.getLogger('odoo.models')
_unlink = logging.getLogger('odoo.models.unlink')

regex_order = re.compile(r'''
    ^
    (\s*
        (?P<term>((?P<field>[a-z0-9_]+)(\.(?P<property>[a-z0-9_]+))?(:(?P<func>[a-z_]+))?))
        (\s+(?P<direction>desc|asc))?
        (\s+(?P<nulls>nulls\ first|nulls\ last))?
        \s*
        (,|$)
    )+
    (?<!,)
    $
''', re.IGNORECASE | re.VERBOSE)
regex_order_part_read_group = re.compile(r"""
    \s*
    (?P<term>(?P<field>[a-z0-9_]+)(\.([\w\.]+))?(:(?P<func>[a-z_]+))?)
    (\s+(?P<direction>desc|asc))?
    (\s+(?P<nulls>nulls\ first|nulls\ last))?
    \s*
""", re.IGNORECASE | re.VERBOSE)
regex_field_agg = re.compile(r'(\w+)(?::(\w+)(?:\((\w+)\))?)?')  # For read_group
regex_read_group_spec = re.compile(r'(\w+)(\.([\w\.]+))?(?::(\w+))?$')  # For _read_group

INSERT_BATCH_SIZE = 100
UPDATE_BATCH_SIZE = 100
SQL_DEFAULT = psycopg2.extensions.AsIs("DEFAULT")

from odoo.orm.core.access import NO_ACCESS


def _has_field_access(self, field: Field, operation: typing.Literal['read', 'write']) -> bool:
    if not field.groups or self.env.su:
        return True
    if field.groups == NO_ACCESS:
        return False
    return self.env.user.has_groups(field.groups)


def _check_field_access(self, field: Field, operation: typing.Literal['read', 'write']) -> None:
    return self.check_field_access(field, operation)


def _check_access(self, operation: str) -> tuple[Self, Callable] | None:
    domain = self._access_domain(operation)
    if domain.is_false():
        return self, functools.partial(self._make_access_error_message, operation, domain)

    origin = self._origin
    if (
        origin
        and domain
        and (forbidden := origin - origin.with_context(active_test=False).sudo().filtered_domain(domain))
    ):
        return forbidden, functools.partial(forbidden._make_access_error_message, operation, domain)

    return None


def _make_access_error_message(self, operation: str, domain: Domain) -> AccessError:
    if domain.is_false():
        return self.env['ir.access']._make_model_access_error(self._name, operation)
    return self.env['ir.access']._make_record_access_error(self, operation)
