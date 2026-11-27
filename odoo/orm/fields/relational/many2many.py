"""The many2many fields: the relation table, its reads and its writes, and the SQL of its joins."""

from __future__ import annotations

import typing
from collections import defaultdict
from odoo.exceptions import AccessError
from odoo.tools import SQL, OrderedSet, sql
from odoo.tools.misc import SENTINEL, Sentinel
from odoo.orm.core.commands import Command
from odoo.orm.fields import _logger, determine
from odoo.orm.core.identifiers import NewId
from odoo.orm.models import BaseModel
from odoo.orm.database.query import Query, TableSQL
from odoo.orm.core.utils import check_pg_name

if typing.TYPE_CHECKING:
    OnDelete = typing.Literal['cascade', 'set null', 'restrict']

from .base import _schema
from .multi import _RelationalMulti


class Many2many(_RelationalMulti):
    """ Many2many field; the value of such a field is the recordset.

    :param str comodel_name: name of the target model (string)
        mandatory except in the case of related or extended fields

    :param str relation: optional name of the table that stores the relation in
        the database

    :param str column1: optional name of the column referring to "these" records
        in the table ``relation``

    :param str column2: optional name of the column referring to "those" records
        in the table ``relation``

    The attributes ``relation``, ``column1`` and ``column2`` are optional.
    If not given, names are automatically generated from model names,
    provided ``model_name`` and ``comodel_name`` are different!

    Note that having several fields with implicit relation parameters on a
    given model with the same comodel is not accepted by the ORM, since
    those field would use the same table. The ORM prevents two many2many
    fields to use the same relation parameters, except if

    - both fields use the same model, comodel, and relation parameters are
      explicit; or

    - at least one field belongs to a model with ``_auto = False``.

    :param domain: an optional domain to set on candidate values on the
        client side (domain or a python expression that will be evaluated
        to provide domain)

    :param dict context: an optional context to use on the client side when
        handling that field

    :param bool check_company: Mark the field to be verified in
        :meth:`~odoo.models.Model._check_company`. Add a default company
        domain depending on the field attributes.

    """
    type = 'many2many'

    _explicit: bool = True              # whether schema is explicitly given
    relation: str | None = None         # name of table
    column1: str | None = None          # column of table referring to model
    column2: str | None = None          # column of table referring to comodel
    ondelete: OnDelete | None = 'cascade'  # optional ondelete for the column2 fkey

    def __init__(self, comodel_name: str | Sentinel = SENTINEL, relation: str | Sentinel = SENTINEL,
                 column1: str | Sentinel = SENTINEL, column2: str | Sentinel = SENTINEL,
                 string: str | Sentinel = SENTINEL, **kwargs):
        super().__init__(
            comodel_name=comodel_name,
            relation=relation,
            column1=column1,
            column2=column2,
            string=string,
            **kwargs
        )

    def setup_related(self, model):
        super().setup_related(model)
        self._setup_relation(model)

    def setup_nonrelated(self, model):
        super().setup_nonrelated(model)
        self._setup_relation(model)

    def _setup_relation(self, model: BaseModel):
        # 2 cases:
        # 1) The ondelete attribute is defined and its definition makes sense
        # 2) The ondelete attribute is explicitly defined as 'set null' for a m2m,
        #    this is considered a programming error.
        if self.ondelete not in ('cascade', 'restrict'):
            raise ValueError(
                "The m2m field %s of model %s declares its ondelete policy "
                "as being %r. Only 'restrict' and 'cascade' make sense."
                % (self.name, model._name, self.ondelete)
            )
        if self.store:
            if not (self.relation and self.column1 and self.column2):
                if not self.relation:
                    self._explicit = False
                # table name is based on the stable alphabetical order of tables
                comodel = model.env[self.comodel_name]
                if not self.relation:
                    tables = sorted([model._table, comodel._table])
                    assert tables[0] != tables[1], \
                        "%s: Implicit/canonical naming of many2many relationship " \
                        "table is not possible when source and destination models " \
                        "are the same" % self
                    self.relation = '%s_%s_rel' % tuple(tables)
                # Safe to update shared fields' attributes
                # because _check_model_extension guarantees model_cls._table is not overridable.
                if not self.column1:
                    self.column1 = '%s_id' % model._table
                if not self.column2:
                    self.column2 = '%s_id' % comodel._table
            # check validity of table name
            check_pg_name(self.relation)
        else:
            self.relation = self.column1 = self.column2 = None

        if self.relation:
            # check whether other fields use the same schema
            fields = model.pool.many2many_relations[self.relation, self.column1, self.column2]
            for mname, fname in fields:
                field = model.pool[mname]._fields[fname]
                if (
                    field is self
                ) or (    # same model: relation parameters must be explicit
                    self.model_name == field.model_name and
                    self.comodel_name == field.comodel_name and
                    self._explicit and field._explicit
                ) or (  # different models: one model must be _auto=False
                    self.model_name != field.model_name and
                    not (model._auto and model.env[field.model_name]._auto)
                ):
                    continue
                msg = "Many2many fields %s and %s use the same table and columns"
                raise TypeError(msg % (self, field))
            fields.add((self.model_name, self.name))

    def setup_inverses(self, registry, inverses):
        if self.relation:
            # retrieve inverse fields, and link them in field_inverses
            for mname, fname in registry.many2many_relations[self.relation, self.column2, self.column1]:
                field = registry[mname]._fields[fname]
                inverses.add(self, field)
                inverses.add(field, self)

    def update_db(self, model, columns):
        cr = model.env.cr
        # Do not reflect relations for custom fields, as they do not belong to a
        # module. They are automatically removed when dropping the corresponding
        # 'ir.model.field'.
        if not self.manual:
            model.pool.post_init(model.env['ir.model.relation']._reflect_relation,
                                 model, self.relation, self._module)
        comodel = model.env[self.comodel_name]
        if not sql.table_exists(cr, self.relation):
            cr.execute(SQL(
                """ CREATE TABLE %(rel)s (%(id1)s INTEGER NOT NULL,
                                          %(id2)s INTEGER NOT NULL,
                                          PRIMARY KEY(%(id1)s, %(id2)s));
                    COMMENT ON TABLE %(rel)s IS %(comment)s;
                    CREATE INDEX ON %(rel)s (%(id2)s, %(id1)s); """,
                rel=SQL.identifier(self.relation),
                id1=SQL.identifier(self.column1),
                id2=SQL.identifier(self.column2),
                comment=f"RELATION BETWEEN {model._table} AND {comodel._table}",
            ))
            _schema.debug("Create table %r: m2m relation between %r and %r", self.relation, model._table, comodel._table)
            model.pool.post_init(self.update_db_foreign_keys, model)

            # Check if we have a custom init function
            if self.init_storage:
                _logger.debug("Table '%s': call %s for column %s", model._table, self.init_storage, self.name)
                to_compute = determine(self.init_storage, model)
            else:
                to_compute = True
            # Mark computed fields to recompute
            if to_compute and self.compute:
                _logger.info("Prepare computation of %s", self)
                cr.execute(SQL(
                    "SELECT id FROM %(table)s WHERE id NOT IN (SELECT %(id1)s FROM %(rel)s)",
                    table=SQL.identifier(model._table),
                    rel=SQL.identifier(self.relation),
                    id1=SQL.identifier(self.column1),
                ))
                records = model.browse(row[0] for row in cr.fetchall())
                model.env.add_to_compute(self, records)

        model.pool.post_init(self.update_db_foreign_keys, model)

    def update_db_foreign_keys(self, model):
        """ Add the foreign keys corresponding to the field's relation table. """
        comodel = model.env[self.comodel_name]
        if model._is_an_ordinary_table():
            model.pool.add_foreign_key(
                self.relation, self.column1, model._table, 'id', 'cascade',
                model, self._module, force=False,
            )
        if comodel._is_an_ordinary_table():
            model.pool.add_foreign_key(
                self.relation, self.column2, comodel._table, 'id', self.ondelete,
                model, self._module,
            )

    def read(self, records):
        context = {'active_test': False}
        context.update(self.context)
        comodel = records.env[self.comodel_name].with_context(**context)

        # make the query for the lines
        domain = self.get_comodel_domain(records)
        # bypass_access set because of context management in ir.attachment
        query = comodel.sudo()._search(domain, order=comodel._order, bypass_access=True)

        # join with many2many relation table
        sql_id1 = SQL.identifier(self.relation, self.column1)
        sql_id2 = SQL.identifier(self.relation, self.column2)
        query.add_join('JOIN', self.relation, None, SQL(
            "%s = %s", sql_id2, SQL.identifier(comodel._table, 'id'),
        ))
        query.add_where(SQL("%s IN %s", sql_id1, tuple(records.ids)))

        # retrieve pairs (record, line) and group by record
        group = defaultdict(list)
        corecord_ids = OrderedSet()
        for id1, id2 in records.env.execute_query(query.select(sql_id1, sql_id2)):
            group[id1].append(id2)
            corecord_ids.add(id2)

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
        cr = model.env.cr

        if is_real and self.store:
            # Using `record[self.name]` generates 2 SQL queries when the value
            # is not in cache: one that actually checks access rules for
            # records, and the other one fetching the actual data. We use
            # `self.read` instead to shortcut the first query.
            missing_ids = tuple(self._cache_missing_ids(records))
            if missing_ids:
                self.read(records.browse(missing_ids))

        # determine old and new relation {x: ys}
        #
        # sudo() is only needed to see the full DB relation for a *stored*
        # field. For a non-stored, context-dependent field (e.g.
        # depends_context('uid')), it reads/caches a different bucket than
        # the one being written, which can poison it with a stale empty
        # value.
        relation_records = records.sudo() if self.store else records
        old_relation = {record.id: OrderedSet(record[self.name]._ids) for record in relation_records}
        if records.env.context.get('active_test', True):
            old_inactive_relation = {
                record.id: OrderedSet(record[self.name]._ids) - old_relation[record.id]
                for record in relation_records.with_context(active_test=False)
            }
        else:
            old_inactive_relation = None
        new_relation = {x: OrderedSet(ys) for x, ys in old_relation.items()}
        inaccessible_coids = (
            OrderedSet()
            if not self.store or model.env.su
            else OrderedSet(records.sudo()[self.name]._ids) - OrderedSet(records[self.name]._ids)
        )
        added_ids = OrderedSet()

        # operations on new relation
        def relation_add(xs, y):
            added_ids.add(y)
            for x in xs:
                new_relation[x].add(y)

        def relation_remove(xs, y):
            if y in inaccessible_coids:
                return
            for x in xs:
                new_relation[x].discard(y)

        def relation_set(xs, ys):
            added_ids.update(ys)
            if inaccessible_coids:
                for x in xs:
                    new_relation[x] = OrderedSet(ys) | (new_relation[x] & inaccessible_coids)
            else:
                for x in xs:
                    new_relation[x] = OrderedSet(ys)

        def relation_delete(ys):
            ys = OrderedSet(ys) - inaccessible_coids
            # the pairs (x, y) have been cascade-deleted from relation
            for ys1 in old_relation.values():
                ys1.difference_update(ys)
            for ys1 in new_relation.values():
                ys1.difference_update(ys)

        for recs, commands in records_commands_list:
            to_create = []  # line vals to create
            to_delete = []  # line ids to delete
            for command in commands:
                if command[0] == Command.CREATE:
                    if is_real:
                        to_create.append((recs._ids, command[2]))
                    else:
                        line_id = comodel.new(command[2], ref=command[1]).id
                        relation_add(recs._ids, line_id)
                elif command[0] == Command.UPDATE:
                    line_id = command[1]
                    if is_real and line_id:
                        prefetch_ids = recs[self.name]._prefetch_ids
                        comodel.browse((line_id,)).with_prefetch(prefetch_ids).write(command[2])
                    else:
                        if line_id:
                            line_id = NewId(line_id)
                        comodel.browse((line_id,)).update(command[2])
                elif command[0] == Command.DELETE:
                    line_id = command[1]
                    if is_real and line_id:
                        to_delete.append(line_id)
                    else:
                        if line_id:
                            line_id = NewId(line_id)
                        relation_delete((line_id,))
                elif command[0] == Command.UNLINK:
                    line_id = command[1]
                    if not is_real and line_id:
                        line_id = NewId(line_id)
                    relation_remove(recs._ids, line_id)
                elif command[0] == Command.LINK:
                    line_id = command[1]
                    if not is_real and line_id:
                        line_id = NewId(line_id)
                    relation_add(recs._ids, line_id)
                elif command[0] in (Command.CLEAR, Command.SET):
                    # new lines must no longer be linked to records
                    to_create = [(OrderedSet(ids) - OrderedSet(recs._ids), vals) for (ids, vals) in to_create]
                    line_ids = command[2] if command[0] == Command.SET else ()
                    if not is_real:
                        line_ids = OrderedSet(line_id and NewId(line_id) for line_id in line_ids)
                    relation_set(recs._ids, line_ids)

            if to_create:
                # create lines in batch, and link them
                lines = comodel.create([vals for ids, vals in to_create])
                for line, (ids, _vals) in zip(lines, to_create):
                    relation_add(ids, line.id)

            if to_delete:
                # delete lines in batch
                comodel.browse(to_delete).unlink()
                relation_delete(to_delete)

        # check comodel access of added records
        # we check the su flag of the environment of records, because su may be
        # disabled on the comodel
        lines = comodel.browse(added_ids)
        if not model.env.su:
            try:
                lines.check_access('read')
            except AccessError as e:
                raise AccessError(model.env._("Failed to write field %s", self) + "\n" + str(e))
        if is_real and len(lines.filtered_domain(comodel_domain := self.get_comodel_domain(model))) < len(lines):
            raise ValueError(f"Cannot link inaccessible records in {self} ({comodel_domain})")

        if new_relation == old_relation:
            return

        # update the cache of self
        for record in records:
            new_ids = tuple(new_relation[record.id])
            if old_inactive_relation is not None:
                new_ids += tuple(old_inactive_relation[record.id])
            self._update_cache(record, new_ids)

        # determine pairs to add and to remove in the relation
        add_pairs = [(x, y) for x, ys in new_relation.items() for y in ys - old_relation[x]]
        remove_pairs = [(x, y) for x, ys in old_relation.items() for y in ys - new_relation[x]]

        if is_real and self.store:
            if add_pairs:
                cr.execute(SQL(
                    "INSERT INTO %s (%s, %s) SELECT * FROM UNNEST(%s, %s) ON CONFLICT DO NOTHING",
                    SQL.identifier(self.relation),
                    SQL.identifier(self.column1),
                    SQL.identifier(self.column2),
                    [x for x, y in add_pairs],
                    [y for x, y in add_pairs],
                ))
            if remove_pairs:
                cr.execute(SQL(
                    "DELETE FROM %s WHERE (%s, %s) IN (SELECT * FROM UNNEST(%s, %s))",
                    SQL.identifier(self.relation),
                    SQL.identifier(self.column1),
                    SQL.identifier(self.column2),
                    [x for x, y in remove_pairs],
                    [y for x, y in remove_pairs],
                ))

        # update the cache of all the other fields that use the same relation
        registry = model.pool

        # collect impacted records {model_name: (ids, field_names)} (see below)
        modified = {}

        if sibling_fields := [
            field
            for model_name, field_name in registry.many2many_relations[self.relation, self.column1, self.column2]
            if (field := registry[model_name]._fields[field_name]) is not self
        ]:
            # group coids to add/remove by id
            more, less = defaultdict(OrderedSet), defaultdict(OrderedSet)
            for x, y in add_pairs:
                more[x].add(y)
            for x, y in remove_pairs:
                less[x].add(y)
            ids = OrderedSet([*more, *less])

            for field in sibling_fields:
                modified.setdefault(field.model_name, (ids, []))[1].append(field.name)
                if field.model_name != self.model_name or field.comodel_name != self.comodel_name:
                    # this may happen when the relation is reused with an SQL view
                    field._invalidate_cache(model.env, ids)
                    continue
                field_cache = field._get_cache(model.env)
                if not field_cache:
                    continue
                domain = field.get_comodel_domain(model).optimize_dynamic(comodel)
                for id_ in ids:
                    if id_ in field_cache:
                        value = OrderedSet(field_cache[id_])
                        if ys := more.get(id_):
                            value.update(comodel.browse(ys).filtered(domain)._ids)
                        if ys := less.get(id_):
                            value.difference_update(ys)
                        field._update_cache(model.browse((id_,)), tuple(value))

        if inverse_fields := registry.field_inverses[self]:
            # group ids to add/remove by coid
            more, less = defaultdict(OrderedSet), defaultdict(OrderedSet)
            for x, y in add_pairs:
                more[y].add(x)
            for x, y in remove_pairs:
                less[y].add(x)
            ids = OrderedSet([*more, *less])

            for field in inverse_fields:
                modified.setdefault(field.model_name, (ids, []))[1].append(field.name)
                if field.model_name != self.comodel_name or field.comodel_name != self.model_name:
                    # this may happen when the relation is reused with an SQL view
                    field._invalidate_cache(comodel.env, ids)
                    continue
                field_cache = field._get_cache(comodel.env)
                if not field_cache:
                    continue
                domain = field.get_comodel_domain(comodel).optimize_dynamic(model)
                valid_ids = set(records.filtered_domain(domain)._ids)
                if not valid_ids:
                    continue
                for coid in ids:
                    if coid in field_cache:
                        value = OrderedSet(field_cache[coid])
                        if xs := more.get(coid):
                            value.update(xs & valid_ids)
                        if xs := less.get(coid):
                            value.difference_update(xs)
                        field._update_cache(comodel.browse((coid,)), tuple(value))

        # trigger the recomputation of fields that depend on the inverse
        # fields of self on the modified corecords and on sibling fields
        for model_name, (ids, field_names) in modified.items():
            model.env[model_name].browse(ids).modified(field_names)

    def join(self, table: TableSQL, kind='LEFT JOIN', *, only_ids: bool = False) -> TableSQL:
        """ Add a LEFT JOIN to ``query`` by following field ``self``,
        and return the joined table's corresponding model and alias.
        """
        if not self.store:
            # traverse_related, skip last one if not stored
            if self.related:
                traverse = table
                if self.compute_sudo:
                    env = table._model.env
                    traverse = traverse._sudo()
                for fname in self.related.split('.')[:-1]:
                    traverse = traverse[fname]
                table = traverse.id._table
                if self.compute_sudo:
                    table = table._with_model(table._model.with_env(env))
                return self.related_field.join(table, kind=kind, only_ids=only_ids)
            raise ValueError(f"Cannot join a non-stored many2many field: {self!r}")

        model = table._model
        comodel = model.env[self.comodel_name].with_context(**self.context)
        rel_table, rel_id1, rel_id2 = self.relation, self.column1, self.column2
        codomain = self.get_comodel_domain(model)
        coquery = comodel._search(codomain, bypass_access=self.bypass_search_access)

        rel_alias = table._make_alias(f'{self.name}__rel')
        condition = SQL(
            "%s = %s",
            table.id,
            rel_alias[rel_id1],
        )
        if only_ids:
            result_id = TableSQLId(rel_alias._alias, rel_id2, table._query)
            if coquery.where_clause:
                condition = SQL(
                    "%s AND %s IN %s",
                    condition,
                    result_id.id,
                    coquery.subselect(),
                )
            table._query.add_join(kind, rel_alias, rel_table, condition)
            return result_id

        table._query.add_join(kind, rel_alias, rel_table, condition)
        coalias = table._make_alias(self.name, comodel)
        condition = SQL(
            "%s = %s",
            rel_alias[rel_id2],
            coalias.id,
        )
        if coquery.where_clause:
            # note that the number of rows in the result depends on the
            # rel_table, but usually the resulting query will group by or
            # exclude null values from the comodel
            cotable_sql = coquery.subselect(SQL('%s.*', coquery.table))
        else:
            cotable_sql = None
        table._query.add_join(kind, coalias, cotable_sql, condition)
        return coalias

    def _condition_to_sql_relational(self, table: TableSQL, exists: bool, coquery: Query) -> SQL:
        assert not coquery.is_empty()
        rel_table, rel_id1, rel_id2 = self.relation, self.column1, self.column2
        rel_alias = table._make_alias(self.name)
        if not coquery.where_clause:
            # case: no constraints on table and we have foreign keys
            # so we can inverse the operator and check existence
            exists = not exists
            return SQL(
                "%sEXISTS (SELECT 1 FROM %s AS %s WHERE %s = %s)",
                SQL("NOT ") if exists else SQL(),
                SQL.identifier(rel_table),
                rel_alias,
                rel_alias[rel_id1],
                table.id,
            )
        return SQL(
            "%sEXISTS (SELECT 1 FROM %s AS %s WHERE %s = %s AND %s IN %s)",
            SQL("NOT ") if not exists else SQL(),
            SQL.identifier(rel_table),
            rel_alias,
            rel_alias[rel_id1],
            table.id,
            rel_alias[rel_id2],
            coquery.subselect(),
        )


class TableSQLId(TableSQL):
    def __init__(self, alias, field_name, query):
        super().__init__(alias, None, query)
        self._sql_field = SQL.identifier(alias, field_name)

    def __getitem__(self, name):
        if name == 'id':
            return self._sql_field
        raise KeyError(f"Only 'id' is supported in {self!r}")

    __getattr__ = __getitem__
