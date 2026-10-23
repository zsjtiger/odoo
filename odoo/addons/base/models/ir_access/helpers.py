# Part of Odoo. See LICENSE file for full copyright and licensing details.

import typing
from odoo.fields import Domain
from odoo.tools.text.translate import _lt

CRUD_SELECTION = {
    'crud': 'Create, Read, Update, Delete',
    'cru': 'Create, Read, Update',
    'crd': 'Create, Read, Delete',
    'cud': 'Create, Update, Delete',
    'rud': 'Read, Update, Delete',
    'cr': 'Create, Read',
    'cu': 'Create, Update',
    'cd': 'Create, Delete',
    'ru': 'Read, Update',
    'rd': 'Read, Delete',
    'ud': 'Update, Delete',
    'c': 'Create',
    'r': 'Read',
    'u': 'Update',
    'd': 'Delete',
}

IN_SELECTION = {
    'read': frozenset(key for key in CRUD_SELECTION if 'r' in key),
    'write': frozenset(key for key in CRUD_SELECTION if 'u' in key),
    'create': frozenset(key for key in CRUD_SELECTION if 'c' in key),
    'unlink': frozenset(key for key in CRUD_SELECTION if 'd' in key),
}

OPERATION_NAME = {
    'read': _lt("read"),
    'write': _lt("write"),
    'create': _lt("create"),
    'unlink': _lt("delete"),
}

ACCESS_ERROR_MESSAGE = {
    'read': _lt("You are not allowed to access '%(document_kind)s' (%(document_model)s) records."),
    'write': _lt("You are not allowed to modify '%(document_kind)s' (%(document_model)s) records."),
    'create': _lt("You are not allowed to create '%(document_kind)s' (%(document_model)s) records."),
    'unlink': _lt("You are not allowed to delete '%(document_kind)s' (%(document_model)s) records."),
}


class AccessInfo(typing.NamedTuple):
    """ The data of an ir.access record for a given model, for caching purpose. """
    id: int
    group_id: int  # may be False
    operation: str
    domain: Domain | str
