"""The one2many fields: the inverse of a many2one, its reads and its writes."""

from __future__ import annotations

import typing
from collections import defaultdict
from operator import attrgetter
from odoo.exceptions import UserError
from odoo.tools import SQL, OrderedSet, unique
from odoo.tools.misc import SENTINEL, Sentinel
from odoo.orm.core.commands import Command
from odoo.orm.core.domains import Domain
from odoo.orm.fields import _logger
from odoo.orm.fields.reference import Many2oneReference
from odoo.orm.core.identifiers import NewId
from odoo.orm.models import BaseModel
from odoo.orm.database.query import Query, TableSQL
from odoo.orm.core.utils import SQL_OPERATORS

if typing.TYPE_CHECKING:
    OnDelete = typing.Literal['cascade', 'set null', 'restrict']

from .many2one import Many2one
from .multi import _RelationalMulti


class One2many(_RelationalMulti):
    """One2many field; the value of such a field is the recordset of all the
    records in ``comodel_name`` such that the field ``inverse_name`` is equal to
    the current record.

    :param str comodel_name: name of the target model

    :param str inverse_name: name of the inverse ``Many2one`` field in
        ``comodel_name``

    :param domain: an optional domain to set on candidate values on the
        client side (domain or a python expression that will be evaluated
        to provide domain)

    :param dict context: an optional context to use on the client side when
        handling that field

    :param bool bypass_search_access: whether access rights are bypassed on the
        comodel (default: ``False``)

    The attributes ``comodel_name`` and ``inverse_name`` are mandatory except in
    the case of related fields or field extensions.
    """
    type = 'one2many'

    inverse_name: str | None = None     # name of the inverse field
    copy: bool = False                  # o2m are not copied by default

    def __init__(self, comodel_name: str | Sentinel = SENTINEL, inverse_name: str | Sentinel = SENTINEL,
                 string: str | Sentinel = SENTINEL, **kwargs):
        super().__init__(
            comodel_name=comodel_name,
            inverse_name=inverse_name,
            string=string,
            **kwargs
        )

    def setup_nonrelated(self, model):
        super().setup_nonrelated(model)
        if self.inverse_name:
            # link self to its inverse field and vice-versa
            comodel = model.env[self.comodel_name]
            try:
                field = comodel._fields[self.inverse_name]
                field.setup(comodel)
            except KeyError:
                raise ValueError(f"{self.inverse_name!r} declared in {self!r} does not exist on {comodel._name!r}.")

    def setup_inverses(self, registry, inverses):
        if self.inverse_name:
            # link self to its inverse field and vice-versa
            if self.manual and self.inverse_name not in registry[self.comodel_name]._fields:
                # ignore manual fields (e.g. from Studio) that may reference a
                # non-existent inverse field in the registry to avoid crashing
                _logger.warning("%s: ignoring manual field with invalid inverse name %r", self, self.inverse_name)
                return
            invf = registry[self.comodel_name]._fields[self.inverse_name]
            if isinstance(invf, (Many2one, Many2oneReference)):
                # setting one2many fields only invalidates many2one inverses;
                # integer inverses (res_model/res_id pairs) are not supported
                inverses.add(self, invf)
            inverses.add(invf, self)

    _description_relation_field = property(attrgetter('inverse_name'))

    def update_db(self, model, columns):
        if self.comodel_name in model.env:
            comodel = model.env[self.comodel_name]
            if self.inverse_name not in comodel._fields:
                raise UserError(model.env._(
                    'No inverse field "%(inverse_field)s" found for "%(comodel)s"',
                    inverse_field=self.inverse_name,
                    comodel=self.comodel_name
                ))
        assert not self.init_storage, "One2many.init_storage not supported"

    def _additional_domain(self, env) -> Domain:
        if self.comodel_name and self.inverse_name:
            comodel = env.registry[self.comodel_name]
            inverse_field = comodel._fields[self.inverse_name]
            if inverse_field.type == 'many2one_reference':
                return Domain(inverse_field.model_field, '=', self.model_name)
        return Domain.TRUE

    def get_comodel_domain(self, model: BaseModel) -> Domain:
        return super().get_comodel_domain(model) & self._additional_domain(model.env)

    def _internal_description_domain_raw(self, env) -> str | list:
        domain = super()._internal_description_domain_raw(env)
        additional_domain = self._additional_domain(env)
        if additional_domain.is_true():
            return domain
        return f"({domain}) + ({additional_domain})"

    def __get__(self, records, owner=None):
        if records is not None and self.inverse_name is not None:
            # force the computation of the inverse field to ensure that the
            # cache value of self is consistent
            inverse_field = records.pool[self.comodel_name]._fields[self.inverse_name]
            if inverse_field.compute:
                records.env[self.comodel_name]._recompute_model([self.inverse_name])
        return super().__get__(records, owner)

    def read(self, records):
        # retrieve the lines in the comodel
        context = {'active_test': False}
        context.update(self.context)
        comodel = records.env[self.comodel_name].with_context(**context)
        inverse = self.inverse_name
        inverse_field = comodel._fields[inverse]

        # optimization: fetch the inverse and active fields with search()
        domain = self.get_comodel_domain(records) & Domain(inverse, 'in', records.ids)
        field_names = OrderedSet((inverse,))
        if comodel._active_name:
            # add the active field
            field_names.add(comodel._active_name)
        if not comodel.env.su:
            # add fields for security rules
            sec_domain = comodel._access_domain('read')
            field_names.update(c.field_expr for c in sec_domain.optimize(comodel.sudo()).iter_conditions())
        lines = comodel.sudo().search_fetch(domain, field_names)

        # group lines by inverse field (without prefetching other fields)
        get_id = (lambda rec: rec.id) if inverse_field.type == 'many2one' else int
        group = defaultdict(list)
        for line in lines:
            # line[inverse] may be a record or an integer
            group[get_id(line[inverse])].append(line.id)

        # store result in cache
        values = [tuple(group[id_]) for id_ in records._ids]
        self._insert_cache(records, values)

    def write_batch(self, records_commands_list, create=False):
        records, records_commands_list = self._parse_write_commands(records_commands_list)
        if not records:
            return

        is_real = any(records._ids)
        model = records.browse()
        comodel = model.env[self.comodel_name].with_context(**self.context)
        comodel = self._check_sudo_commands(comodel)

        if is_real:
            browse = comodel.browse
        else:
            def browse(ids):
                return comodel.browse(id_ and NewId(id_) for id_ in ids)

            # make sure self is in cache
            records[self.name]

        if self.store and is_real:
            inverse = self.inverse_name
            to_create = []                      # line vals to create
            to_delete = []                      # line ids to delete
            to_link = defaultdict(OrderedSet)   # {record: line_ids}
            allow_full_delete = not create
            comodel_domain = self.get_comodel_domain(model).optimize_dynamic(comodel)

            def unlink(lines):
                if getattr(comodel._fields[inverse], 'ondelete', False) == 'cascade':
                    to_delete.extend(lines._ids)
                else:
                    lines[inverse] = False

            def flush():
                if to_link:
                    before = {record: record[self.name] for record in to_link}
                if to_delete:
                    # unlink() will remove the lines from the cache
                    browse(to_delete).unlink()
                    to_delete.clear()
                if to_create:
                    # create() will add the new lines to the cache of records
                    lines = comodel.create(to_create)
                    if len(lines.filtered_domain(comodel_domain)) < len(lines):
                        raise ValueError(f"Cannot link inaccessible records in {self} ({comodel_domain})")
                    to_create.clear()
                if to_link:
                    for record, line_ids in to_link.items():
                        lines = browse(line_ids) - before[record]
                        # linking missing lines should fail
                        lines.mapped(inverse)
                        if len(lines.filtered_domain(comodel_domain)) < len(lines):
                            raise ValueError(f"Cannot link inaccessible records in {self} ({comodel_domain})")
                        lines[inverse] = record
                    to_link.clear()

            for recs, commands in records_commands_list:
                for command in (commands or ()):
                    if command[0] == Command.CREATE:
                        to_create.extend(dict(command[2], **{inverse: record.id}) for record in recs)
                        allow_full_delete = False
                    elif command[0] == Command.UPDATE:
                        prefetch_ids = recs[self.name]._prefetch_ids
                        browse((command[1],)).with_prefetch(prefetch_ids).write(command[2])
                    elif command[0] == Command.DELETE:
                        to_delete.append(command[1])
                    elif command[0] == Command.UNLINK:
                        unlink(browse((command[1],)))
                    elif command[0] == Command.LINK:
                        to_link[recs[-1]].add(command[1])
                        allow_full_delete = False
                    elif command[0] in (Command.CLEAR, Command.SET):
                        line_ids = command[2] if command[0] == Command.SET else []
                        if not allow_full_delete:
                            # do not try to delete anything in creation mode if nothing has been created before
                            if line_ids:
                                # equivalent to Command.LINK
                                if line_ids.__class__ is int:
                                    line_ids = [line_ids]
                                to_link[recs[-1]].update(line_ids)
                                allow_full_delete = False
                            continue
                        flush()
                        # assign the given lines to the last record only
                        lines = browse(line_ids)
                        domain = self.get_comodel_domain(model) & Domain(inverse, 'in', recs.ids) & Domain('id', 'not in', lines.ids)
                        unlink(comodel.search(domain))
                        lines[inverse] = recs[-1]

            flush()

        elif self.store:  # stored and new
            inverse = self.inverse_name

            # make sure self's inverse is in cache
            inverse_field = comodel._fields[inverse]
            for record in records:
                inverse_field._update_cache(record[self.name], record.id)

            for recs, commands in records_commands_list:
                for command in commands:
                    if command[0] == Command.CREATE:
                        for record in recs:
                            line = comodel.new(command[2], ref=command[1])
                            line[inverse] = record
                    elif command[0] == Command.UPDATE:
                        browse((command[1],)).update(command[2])
                    elif command[0] in (Command.DELETE, Command.UNLINK):
                        browse((command[1],))[inverse] = False
                    elif command[0] == Command.LINK:
                        browse((command[1],))[inverse] = recs[-1]
                    elif command[0] == Command.CLEAR:
                        self._update_cache(recs, ())
                    elif command[0] == Command.SET:
                        # assign the given lines to the last record only
                        self._update_cache(recs, ())
                        last, lines = recs[-1], browse(command[2])
                        self._update_cache(last, lines._ids)
                        inverse_field._update_cache(lines, last.id)

        else:  # not stored
            def link(record, lines):
                ids = record[self.name]._ids
                self._update_cache(record, tuple(unique(ids + lines._ids)))

            def unlink(lines):
                for record in records:
                    self._update_cache(record, (record[self.name] - lines)._ids)

            for recs, commands in records_commands_list:
                for command in commands:
                    if command[0] == Command.SET:
                        # assign the given lines to the last record only
                        self._update_cache(recs, ())
                        lines = browse(command[2])
                        self._update_cache(recs[-1], lines._ids)
                    elif command[0] == Command.CLEAR:
                        self._update_cache(recs, ())
                    elif command[0] == Command.LINK:
                        link(recs[-1], browse((command[1],)))
                    elif command[0] == Command.CREATE:
                        for record in recs:
                            link(record, comodel.new(command[2], ref=command[1]))
                    elif command[0] == Command.UPDATE:
                        lines = browse(command[1])
                        if is_real:
                            lines.write(command[2])
                        else:
                            lines.update(command[2])
                    elif command[0] in (Command.DELETE, Command.UNLINK):
                        unlink(browse((command[1],)))
                    else:
                        assert False, command

    def join(self, table: TableSQL, kind='LEFT JOIN') -> TableSQL:
        """ Add a LEFT JOIN to ``query`` by following field ``self``,
        and return the joined table's corresponding model and alias.
        """
        model = table._model
        comodel = model.env[self.comodel_name].with_context(**self.context)
        codomain = self.get_comodel_domain(model)
        coquery = comodel._search(codomain, bypass_access=self.bypass_search_access)

        coalias = table._make_alias(self.name, comodel)
        condition = SQL(
            "%s = %s",
            table.id,
            coalias[self.inverse_name],
        )
        if coquery.where_clause:
            cotable_sql = coquery.subselect(SQL('%s.*', coquery.table))
        else:
            cotable_sql = None
        table._query.add_join(kind, coalias, cotable_sql, condition)
        return coalias

    def _condition_to_sql_relational(self, table: TableSQL, exists: bool, coquery: Query) -> SQL:
        assert not coquery.is_empty()
        model = table._model
        comodel = model.env[self.comodel_name].sudo()
        inverse_field = comodel._fields[self.inverse_name]
        if not (inverse_field.store or inverse_field.compute_sql):
            # determine ids1 in model related to ids2
            # TODO should we support this in the future?
            recs = comodel.browse(coquery).with_context(prefetch_fields=False)
            if inverse_field.relational:
                inverses = inverse_field.__get__(recs)
            else:
                # int values, map them
                inverses = model.browse(inverse_field.__get__(rec) for rec in recs)
            subselect = inverses._as_query(ordered=False).subselect()
            return SQL(
                "%s%s%s",
                table.id,
                SQL_OPERATORS['in' if exists else 'not in'],
                subselect,
            )

        subselect = coquery.subselect(
            SQL("%s AS __inverse", coquery.table[inverse_field.name]),
        )
        return SQL(
            "%sEXISTS(SELECT FROM %s AS __sub WHERE __inverse = %s)",
            SQL() if exists else SQL("NOT "),
            subselect,
            table.id,
        )
