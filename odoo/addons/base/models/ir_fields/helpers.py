# Part of Odoo. See LICENSE file for full copyright and licensing details.
from typing import NamedTuple

from odoo.tools.text.translate import LazyTranslate

_lt = LazyTranslate('odoo.addons.base.models.ir_fields')

REFERENCING_FIELDS = {None, 'id', '.id'}
def only_ref_fields(record):
    return {k: v for k, v in record.items() if k in REFERENCING_FIELDS}
def exclude_ref_fields(record):
    return {k: v for k, v in record.items() if k not in REFERENCING_FIELDS}

# these lazy translations promise translations for ['yes', 'no', 'true', 'false']
BOOLEAN_TRANSLATIONS = (
    _lt('yes'),
    _lt('no'),
    _lt('true'),
    _lt('false')
)


class FakeField(NamedTuple):
    comodel_name: str
    name: str


class ImportWarning(Warning):
    """ Used to send warnings upwards the stack during the import process """
    pass

class ConversionNotFound(ValueError):
    pass
