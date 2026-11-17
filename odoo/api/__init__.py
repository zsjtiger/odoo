# ruff: noqa: F401
# Exports features of the ORM to developers.
# This is a `__init__.py` file to avoid merge conflicts on `odoo/api.py`.
from odoo.orm.core.identifiers import NewId
from odoo.orm.models.cache import ormcache
from odoo.orm.core.decorators import (
    autovacuum,
    constrains,
    depends,
    depends_context,
    model,
    model_create_multi,
    onchange,
    ondelete,
    private,
    readonly,
)
from odoo.orm.models.environments import Environment
from odoo.orm.core.utils import SUPERUSER_ID

from odoo.orm.core.types import CommandValue, ContextType, DomainType, IdType, ValuesType
