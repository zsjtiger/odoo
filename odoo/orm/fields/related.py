"""Related fields: the setup of a related field, and the reading, writing and searching through the related path."""

from __future__ import annotations

import logging
import typing
from odoo.exceptions import AccessError
from odoo.tools import SQL
from odoo.orm.core.domains import Domain
from odoo.orm.core.utils import COLLECTION_TYPES

if typing.TYPE_CHECKING:
    from odoo.orm.models.environments import Environment
    from odoo.orm.database.query import TableSQL
    from odoo.orm.core.types import BaseModel, DomainType


_logger = logging.getLogger('odoo.fields')


def setup_related(self, model: BaseModel) -> None:
    """ Setup the attributes of a related field. """
    assert isinstance(self.related, str), self.related

    # determine the chain of fields, and make sure they are all set up
    field_seq = []
    model_name = self.model_name
    for name in self.related.split('.'):
        if not model_name:
            raise ValueError(
                f"Field {name} in related field {self} is not reachable."
            )
        field = model.pool[model_name]._fields.get(name)
        if field is None:
            raise KeyError(
                f"Field {name} referenced in related field definition {self} does not exist."
            )
        if not field._setup_done:
            field.setup(model.env[model_name])
        field_seq.append(field)
        model_name = field.comodel_name if field.relational else None

    # check type consistency
    if self.type != field.type:
        raise TypeError("Type of related field %s is inconsistent with %s" % (self, field))

    self.related_field = field

    # if field's setup is invalidated, then self's setup must be invalidated, too
    model.pool.field_setup_dependents.add(field, self)

    # determine dependencies, compute, inverse, and search
    self.compute = self._compute_related
    if self.inherited or not (self.readonly or field.readonly):
        self.inverse = self._inverse_related
    if (
        not self.store
        and all(
            # representable in SQL
            f.column_type
            # and we know how to represent it
            and (f.store or f.compute_sql)
            # but we don't traverse a model with heavy permission checks (such as ir.attachment)
            and (f is field_seq[-1] or not getattr(model.pool[f.model_name], '_access_domain_heavy', False))
            for f in field_seq
        )
    ):
        self.compute_sql = self._compute_sql_related
    if not self.store and all(f._description_searchable for f in field_seq):
        # allow searching on self only if the related field is searchable
        self.search = self._search_related

    # A readonly related field without an inverse method should not have a
    # default value, as it does not make sense.
    if self.default and self.readonly and not self.inverse:
        _logger.warning("Redundant default on %s", self)

    # copy attributes from field to self (string, help, etc.)
    for attr, prop in self.related_attrs:
        # check whether 'attr' is explicitly set on self (from its field
        # definition), and ignore its class-level value (only a default)
        if attr not in self.__dict__ and prop.startswith('_related_'):
            setattr(self, attr, getattr(field, prop))

    for attr in field._extra_keys__:
        if not hasattr(self, attr) and model._valid_field_parameter(self, attr):
            setattr(self, attr, getattr(field, attr))

    # special cases of inherited fields
    if self.inherited:
        self.inherited_field = field
        if field.required:
            self.required = True
        # add modules from delegate and target fields; the first one ensures
        # that inherited fields introduced via an abstract model (_inherits
        # being on the abstract model) are assigned an XML id
        delegate_field = model._fields[self.related.split('.')[0]]
        self._modules = tuple({*self._modules, *delegate_field._modules, *field._modules})

    if (
        not self.init_storage
        and self.related.count('.') == 1
        and self.related_field.store
        and not self.related_field.compute
        and self.related_field.column_type
    ):
        # optimization for computing simple related fields like 'foo_id.bar'
        self.init_storage = self._init_column_related


def _compute_related(self, records: BaseModel) -> None:
    """ Compute the related field ``self`` on ``records``. """
    #
    # Traverse fields one by one for all records, in order to take advantage
    # of prefetching for each field access. In order to clarify the impact
    # of the algorithm, consider traversing 'foo.bar' for records a1 and a2,
    # where 'foo' is already present in cache for a1, a2. Initially, both a1
    # and a2 are marked for prefetching. As the commented code below shows,
    # traversing all fields one record at a time will fetch 'bar' one record
    # at a time.
    #
    #       b1 = a1.foo         # mark b1 for prefetching
    #       v1 = b1.bar         # fetch/compute bar for b1
    #       b2 = a2.foo         # mark b2 for prefetching
    #       v2 = b2.bar         # fetch/compute bar for b2
    #
    # On the other hand, traversing all records one field at a time ensures
    # maximal prefetching for each field access.
    #
    #       b1 = a1.foo         # mark b1 for prefetching
    #       b2 = a2.foo         # mark b2 for prefetching
    #       v1 = b1.bar         # fetch/compute bar for b1, b2
    #       v2 = b2.bar         # value already in cache
    #
    # This difference has a major impact on performance, in particular in
    # the case where 'bar' is a computed field that takes advantage of batch
    # computation.
    #
    values = list(records)
    for name in self.related.split('.')[:-1]:
        try:
            values = [value[name][:1] for value in values]
        except AccessError as e:
            description = records.env['ir.model']._get(records._name).name
            env = records.env
            raise AccessError(env._(
                "%(previous_message)s\n\nImplicitly accessed through '%(document_kind)s' (%(document_model)s).",
                previous_message=e.args[0],
                document_kind=description,
                document_model=records._name,
            ))
    # assign final values to records
    for record, value in zip(records, values):
        record[self.name] = self._process_related(value[self.related_field.name], record.env)


def _compute_sql_related(self, model, table: TableSQL) -> SQL:
    # traverse_related
    assert self.related and not self.store
    assert model is table._model

    env = table._model.env
    if self.compute_sudo and not env.su:
        table = table._sudo()
    else:
        env = None  # env not changed
    sql = table
    for fname in self.related.split('.'):
        sql = sql[fname]
    if env is not None:
        # rebind the table to the original environment
        table = sql._table
        sql._table = table._with_model(table._model.with_env(env))
    return sql


def _process_related(self, value, env: Environment):
    """No transformation by default, but allows override."""
    return value


def _inverse_related(self, records: BaseModel) -> None:
    """ Inverse the related field ``self`` on ``records``. """
    # store record values, otherwise they may be lost by cache invalidation!
    record_value = {record: record[self.name] for record in records}
    path = self.related.split('.')[:-1]
    field = self.related_field
    for record in records:
        target = record
        for name in path:
            # take the first record when traversing
            target = target[name][:1]
        # update 'target' only if 'record' and 'target' are both real or
        # both new (see `test_base_objects.py`, `test_basic`)
        if target and bool(target.id) == bool(record.id):
            target[field.name] = record_value[record]


def _search_related(self, records: BaseModel, operator: str, value) -> DomainType:
    """ Determine the domain to search on field ``self``. """

    # Compute the new domain for ('x.y.z', op, value)
    # as ('x', 'any', [('y', 'any', [('z', op, value)])])
    # If the followed relation is a nullable many2one, we accept null
    # for that path as well.

    # determine whether the related field can be null
    falsy_value = self.falsy_value
    if isinstance(value, COLLECTION_TYPES):
        value_is_null = any(val is False or val is None or val == falsy_value for val in value)
    else:
        value_is_null = value is False or value is None or value == falsy_value
    can_be_null = (  # (..., '=', False) or (..., 'not in', [truthy vals])
        (operator not in Domain.NEGATIVE_OPERATORS) == value_is_null
    )
    if operator in Domain.NEGATIVE_OPERATORS and not value_is_null:
        # we have a condition like 'not in' ['a']
        # let's call back with a positive operator
        return NotImplemented

    # parse the path
    field_seq = []
    model_name = self.model_name
    for fname in self.related.split('.'):
        field = records.env[model_name]._fields[fname]
        field_seq.append(field)
        model_name = field.comodel_name if field.relational else None

    # build the domain backwards with the any operator
    domain = Domain(field_seq[-1].name, operator, value)
    for field in reversed(field_seq[:-1]):
        domain = Domain(field.name, 'any!' if self.compute_sudo else 'any', domain)
        if can_be_null and field.type == 'many2one' and not field.required:
            domain |= Domain(field.name, '=', False)
    return domain


def _init_column_related(self, model: BaseModel) -> bool:
    join_field = model._fields[self.related.split('.')[0]]
    if (
        join_field.type == 'many2one'
        and join_field.store and not join_field.compute
    ):
        model.pool.post_init(self._init_column_related_update, model)
        # discard the "classical" computation
        return False
    return True


def _init_column_related_update(self, model: BaseModel) -> None:
    """ Compute a stored related field directly in SQL. """
    comodel = model.env[self.related_field.model_name]
    join_field, comodel_field = self.related.split('.')
    model.env.cr.execute(SQL(
        """ UPDATE %(model_table)s AS x
            SET %(model_field)s = y.%(comodel_field)s
            FROM %(comodel_table)s AS y
            WHERE x.%(join_field)s = y.id
            AND x.%(model_field)s IS NULL
        """,
        model_table=SQL.identifier(model._table),
        model_field=SQL.identifier(self.name),
        comodel_table=SQL.identifier(comodel._table),
        comodel_field=SQL.identifier(comodel_field),
        join_field=SQL.identifier(join_field),
    ))
