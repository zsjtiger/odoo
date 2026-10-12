# ruff: noqa: E402, F401
import typing
from collections.abc import Collection, Mapping

from odoo.orm.core.commands import Command
from odoo.orm.core.domains import Domain
from odoo.orm.models.environments import Environment
from odoo.orm.fields import Field
from odoo.orm.core.identifiers import IdType, NewId
from odoo.orm.models import BaseModel
from odoo.orm.models.registry import Registry

DomainType = Domain | list[str | tuple[str, str, typing.Any]]
ContextType = Mapping[str, typing.Any]
ValuesType = dict[str, typing.Any]
ModelType = typing.TypeVar("ModelType", bound=BaseModel)
CommandValue = tuple[Command, int, typing.Literal[0] | ValuesType | Collection[int]]
