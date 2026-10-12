"""The implementation of the ORM.

The subpackages are:

- ``models``: the base class of models, the registry of the models of a
  database, the environments and the caches of records;
- ``fields``: the base class of fields and the field types;
- ``database``: the SQL cursors, the queries and the table objects;
- ``core``: the access rights, the domains, the commands and the helpers.

We export the needed features in various packages and developers should not
import directly from here.
"""
# import first for core setup
import odoo.core.bootstrap  # noqa: F401

# shortcuts exposed at the `odoo` namespace level
import odoo
from odoo.orm.core.commands import Command
from odoo.orm.core.utils import SUPERUSER_ID
from odoo.tools.translate import _, _lt

odoo.SUPERUSER_ID = SUPERUSER_ID
odoo._ = _
odoo._lt = _lt
odoo.Command = Command
