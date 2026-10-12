"""Schema of the registry: the tables, the constraints, the indexes and the hooks run after the initialization of the models."""

from __future__ import annotations

import typing
import warnings
from collections import deque
from functools import partial
import psycopg2.sql
from odoo.tools import sql
from odoo.orm.core.utils import SUPERUSER_ID

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from odoo.models import BaseModel
    from odoo.orm.database.sql_db import BaseCursor, Cursor

from .base import _logger, _schema

def post_init(self, func: Callable, *args, **kwargs) -> None:
    """ Register a function to call at the end of :meth:`~.init_models`. """
    self._post_init_queue.append(partial(func, *args, **kwargs))


def post_constraint(self, cr: BaseCursor, func: Callable[[BaseCursor], None], key) -> None:
    """ Call the given function, and delay it if it fails during an upgrade. """
    try:
        if key not in self._constraint_queue:
            # Module A may try to apply a constraint and fail but another module B inheriting
            # from Module A may try to reapply the same constraint and succeed, however the
            # constraint would already be in the _constraint_queue and would be executed again
            # at the end of the registry cycle, this would fail (already-existing constraint)
            # and generate an error, therefore a constraint should only be applied if it's
            # not already marked as "to be applied".
            with cr.savepoint(flush=False):
                func(cr)
        else:
            self._constraint_queue[key] = func
    except Exception as e:  # noqa: BLE001
        if self._is_install:
            _schema.error("Constraint not added: %s", e)
        else:
            _schema.info("Constraint not added: %s", e)
            self._constraint_queue[key] = func


def finalize_constraints(self, cr: Cursor) -> None:
    """ Call the delayed functions from above. """
    for func in self._constraint_queue.values():
        try:
            with cr.savepoint(flush=False):
                func(cr)
        except Exception as e:  # noqa: BLE001
            # warn only, this is not a deployment showstopper, and
            # can sometimes be a transient error
            _schema.warning("Constraint not added during finalize: %s", e)
    self._constraint_queue.clear()


def init_models(self, cr: Cursor, model_names: Iterable[str], context: dict[str, typing.Any], install: bool = True):
    """ Initialize a list of models (given by their name). Call methods
        ``_auto_init`` and ``init`` on each model to create or update the
        database tables supporting the models.

        The ``context`` may contain the following items:
         - ``module``: the name of the module being installed/updated, if any;
         - ``update_custom_fields``: whether custom fields should be updated.
    """
    if not model_names:
        return

    if 'module' in context:
        _logger.info('module %s: creating or updating database tables', context['module'])
    elif context.get('models_to_check', False):
        _logger.info("verifying fields for every extended model")

    from odoo.orm.models.environments import Environment  # noqa: PLC0415
    env = Environment(cr, SUPERUSER_ID, context)
    models = [env[model_name] for model_name in model_names]
    env.transaction.will_change_registry()

    try:
        self._post_init_queue: deque[Callable] = deque()
        # (table1, column1) -> (table2, column2, ondelete, model, module)
        self._foreign_keys: dict[tuple[str, str], tuple[str, str, str, BaseModel, str]] = {}
        self._is_install: bool = install

        for model in models:
            model._auto_init()
            model.init()

        env['ir.model']._reflect_models(model_names)
        env['ir.model.fields']._reflect_fields(model_names)
        env['ir.model.fields.selection']._reflect_selections(model_names)
        env['ir.model.constraint']._reflect_constraints(model_names)
        env['ir.model.inherit']._reflect_inherits(model_names)

        self._ordinary_tables = None

        while self._post_init_queue:
            func = self._post_init_queue.popleft()
            func()

        self.check_indexes(cr, model_names)
        self.check_foreign_keys(cr)

        env.flush_all()

        # make sure all tables are present
        self.check_tables_exist(cr)

    finally:
        del self._post_init_queue
        del self._foreign_keys
        del self._is_install


def check_null_constraints(self, cr: Cursor) -> None:
    """ Check that all not-null constraints are set. """
    cr.execute('''
        SELECT c.relname, a.attname
        FROM pg_attribute a
        JOIN pg_class c ON a.attrelid = c.oid
        WHERE c.relnamespace = current_schema::regnamespace
        AND a.attnotnull = true
        AND a.attnum > 0
        AND a.attname != 'id';
    ''')
    not_null_columns = set(cr.fetchall())

    self.not_null_fields.clear()
    for Model in self.models.values():
        if Model._auto and not Model._abstract:
            for field_name, field in Model._fields.items():
                if field_name == 'id':
                    self.not_null_fields.add(field)
                elif field.required and field.column_type:
                    if field.store:
                        if (Model._table, field_name) in not_null_columns:
                            self.not_null_fields.add(field)
                        elif sql.column_exists(cr, Model._table, field_name):
                            _schema.warning("Missing not-null constraint on %s", field)
                    elif field.compute_sql:
                        self.not_null_fields.add(field)


def check_indexes(self, cr: Cursor, model_names: Iterable[str]) -> None:
    """ Create or drop column indexes for the given models. """

    expected = [
        (sql.make_index_name(Model._table, field.name), Model._table, field)
        for model_name in model_names
        for Model in [self.models[model_name]]
        if Model._auto and not Model._abstract
        for field in Model._fields.values()
        if field.column_type and field.store
    ]
    if not expected:
        return

    # retrieve existing indexes with their table and access method
    cr.execute("""
        SELECT idx.relname, tbl.relname, am.amname, ix.indpred IS NOT NULL
          FROM pg_index ix
          JOIN pg_class idx ON idx.oid = ix.indexrelid
          JOIN pg_class tbl ON tbl.oid = ix.indrelid
          JOIN pg_am am ON am.oid = idx.relam
         WHERE idx.relname IN %s
           AND idx.relnamespace = current_schema::regnamespace
    """, [tuple(row[0] for row in expected)])
    existing = {
        indexname: (tablename, method, partial)
        for indexname, tablename, method, partial in cr.fetchall()
    }

    for indexname, tablename, field in expected:
        index = field.index
        assert index in ('btree', 'btree_not_null', 'trigram', True, False, None)

        if index and field.translate and index != 'trigram':
            _schema.warning(f"Index attribute on {field!r} ignored, only trigram index is supported for translated fields")
            continue

        # whether the field should be backed by an index, and the access
        # method (gin for trigram, btree otherwise) it is expected to use
        will_index = bool(index) and (
            (not field.translate and index != 'trigram')
            or (index == 'trigram' and self.has_trigram)
        )
        if indexname in existing:
            # The index exists, check if it is stale.
            expected_method = 'gin' if index == 'trigram' else 'btree'
            stale = existing[indexname][1] != expected_method
            if expected_method == 'btree':
                stale |= existing[indexname][2] != (index == 'btree_not_null')
            will_index &= stale  # create only when stale
        else:
            stale = False

        if will_index:
            column_expression = f'"{field.name}"'
            if index == 'trigram':
                if field.translate:
                    column_expression = f'''(jsonb_path_query_array({column_expression}, '$.*')::text)'''
                # add `unaccent` to the trigram index only because the
                # trigram indexes are mainly used for (=)ilike search and
                # unaccent is added only in these cases when searching
                from odoo.modules.db import FunctionStatus  # noqa: PLC0415
                if self.has_unaccent == FunctionStatus.INDEXABLE:
                    column_expression = self.unaccent(column_expression)
                elif self.has_unaccent:
                    warnings.warn(
                        "PostgreSQL function 'unaccent' is present but not immutable, "
                        "therefore trigram indexes may not be effective.",
                        stacklevel=1,
                    )
                expression = f'{column_expression} gin_trgm_ops'
                method = 'gin'
                where = ''
            elif index == 'btree_not_null' and field.company_dependent:
                # company dependent condition will use extra
                # `AND col IS NOT NULL` to use the index.
                expression = f'({column_expression} IS NOT NULL)'
                method = 'btree'
                where = f'{column_expression} IS NOT NULL'
            else:  # index in ['btree', 'btree_not_null'， True]
                expression = f'{column_expression}'
                method = 'btree'
                where = f'{column_expression} IS NOT NULL' if index == 'btree_not_null' else ''
            try:
                with cr.savepoint(flush=False):
                    if stale:
                        sql.drop_index(cr, indexname, tablename)
                    sql.create_index(cr, indexname, tablename, [expression], method, where)
            except psycopg2.OperationalError:
                _schema.error("Unable to add index %r for %s", indexname, self)

        elif not index and tablename == existing.get(indexname, (None, None, None))[0]:
            _schema.info("Keep unexpected index %s on table %s", indexname, tablename)


def add_foreign_key(
    self, table1: str, column1: str, table2: str, column2: str,
    ondelete: str, model: BaseModel, module: str,
    force: bool = True,
) -> None:
    """ Specify an expected foreign key. """
    key = (table1, column1)
    val = (table2, column2, ondelete, model, module)
    if force:
        self._foreign_keys[key] = val
    else:
        self._foreign_keys.setdefault(key, val)


def check_foreign_keys(self, cr: Cursor) -> None:
    """ Create or update the expected foreign keys. """
    if not self._foreign_keys:
        return

    # determine existing foreign keys on the tables
    query = """
        SELECT fk.conname, c1.relname, a1.attname, c2.relname, a2.attname, fk.confdeltype
        FROM pg_constraint AS fk
        JOIN pg_class AS c1 ON fk.conrelid = c1.oid
        JOIN pg_class AS c2 ON fk.confrelid = c2.oid
        JOIN pg_attribute AS a1 ON a1.attrelid = c1.oid AND fk.conkey[1] = a1.attnum
        JOIN pg_attribute AS a2 ON a2.attrelid = c2.oid AND fk.confkey[1] = a2.attnum
        WHERE fk.contype = 'f' AND c1.relname IN %s
        AND c1.relnamespace = current_schema::regnamespace
    """
    cr.execute(query, [tuple({table for table, column in self._foreign_keys})])
    existing = {
        (table1, column1): (name, table2, column2, deltype)
        for name, table1, column1, table2, column2, deltype in cr.fetchall()
    }

    # create or update foreign keys
    for key, val in self._foreign_keys.items():
        table1, column1 = key
        table2, column2, ondelete, model, module = val
        deltype = sql._CONFDELTYPES[ondelete.upper()]
        spec = existing.get(key)
        if spec is None:
            sql.add_foreign_key(cr, table1, column1, table2, column2, ondelete)
            conname = sql.get_foreign_keys(cr, table1, column1, table2, column2, ondelete)[0]
            model.env['ir.model.constraint']._reflect_constraint(model, conname, 'f', None, module)
        elif (spec[1], spec[2], spec[3]) != (table2, column2, deltype):
            sql.drop_constraint(cr, table1, spec[0])
            sql.add_foreign_key(cr, table1, column1, table2, column2, ondelete)
            conname = sql.get_foreign_keys(cr, table1, column1, table2, column2, ondelete)[0]
            model.env['ir.model.constraint']._reflect_constraint(model, conname, 'f', None, module)


def check_tables_exist(self, cr: Cursor) -> None:
    """
    Verify that all tables are present and try to initialize those that are missing.
    """
    from odoo.orm.models.environments import Environment  # noqa: PLC0415
    from odoo.orm.models import BaseModel  # noqa: PLC0415
    env = Environment(cr, SUPERUSER_ID, {})
    table2model = {
        model._table: name
        for name, model in env.registry.items()
        if not model._abstract and model._table_sql is BaseModel._table_sql
    }
    missing_tables = set(table2model).difference(sql.existing_tables(cr, table2model))

    if missing_tables:
        missing = {table2model[table] for table in missing_tables}
        _logger.info("Models have no table: %s.", ", ".join(missing))
        # recreate missing tables
        for name in missing:
            _logger.info("Recreate table of model %s.", name)
            env[name].init()
        env.flush_all()
        # check again, and log errors if tables are still missing
        missing_tables = set(table2model).difference(sql.existing_tables(cr, table2model))
        for table in missing_tables:
            _logger.error("Model %s has no table.", table2model[table])


def is_an_ordinary_table(self, model: BaseModel) -> bool:
    """ Return whether the given model has an ordinary table. """
    if self._ordinary_tables is None:
        cr = model.env.cr
        query = """
            SELECT c.relname
              FROM pg_class c
             WHERE c.relname IN %s
               AND c.relkind = 'r'
               AND c.relnamespace = current_schema::regnamespace
        """
        tables = tuple(m._table for m in self.models.values())
        cr.execute(query, [tables])
        self._ordinary_tables = {row[0] for row in cr.fetchall()}

    return model._table in self._ordinary_tables
