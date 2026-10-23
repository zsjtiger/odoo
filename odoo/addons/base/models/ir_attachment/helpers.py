# Part of Odoo. See LICENSE file for full copyright and licensing details.
from __future__ import annotations

import logging
import typing

from odoo.fields import Domain
from odoo.tools.constants import IN_MAX

if typing.TYPE_CHECKING:
    pass


_logger = logging.getLogger('odoo.addons.base.models.ir_attachment')


SECURITY_FIELDS = ('res_model', 'res_id', 'create_uid', 'public', 'res_field')
MAX_COMODELS_FOR_DOMAIN = 5
MAX_SEARCH_LIMIT = IN_MAX * 10
CREATE_FROM_STREAM_FLAG = object()  # sentinel that cannot be given over RPC
DIRECTORY_MODE = 0o751
GC_FILE_SUFFIX = '.__gc'
GC_GRACE_PERIOD = 1800  # 30 minutes
GC_GRACE_PERIOD_MAX = 604800  # 1 week


def condition_values(model, field_name, domain):
    """Get the values in the domain for a specific field name.

    Returns the values appearing in the `in` conditions that would be restricted
    to by the domain.
    """
    domain = domain.optimize(model)
    for condition in domain.map_conditions(
        lambda cond: cond
        if cond.field_expr == field_name and cond.operator == 'in'
        else Domain.TRUE
    ).optimize(model).iter_conditions():
        return condition.value
    return None
