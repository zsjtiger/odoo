# ruff: noqa: F401
# Exports features of the ORM to developers.
# This is a `__init__.py` file to avoid merge conflicts on `odoo/fields.py`.

from odoo.orm.fields import Field

from odoo.orm.fields.misc import Id, Json, Boolean
from odoo.orm.fields.numeric import Integer, Float, Monetary
from odoo.orm.fields.textual import Char, Text, Html
from odoo.orm.fields.selection import Selection
from odoo.orm.fields.temporal import Date, Datetime

from odoo.orm.fields.relational import Many2one, Many2many, One2many
from odoo.orm.fields.reference import Many2oneReference, Reference

from odoo.orm.fields.properties import Properties, PropertiesDefinition
from odoo.orm.fields.binary import Binary, Image

from odoo.orm.core.commands import Command
from odoo.orm.core.domains import Domain
from odoo.orm.core.access import NO_ACCESS
from odoo.orm.core.utils import parse_field_expr
