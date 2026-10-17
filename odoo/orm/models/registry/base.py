"""The registry of the models of a database: the loading of the models, their lookup, and the access to the cursors."""

from __future__ import annotations

import contextvars
import functools
import logging
import threading
import time
import typing
from collections import defaultdict
from collections.abc import Mapping
from contextlib import closing, ExitStack
import psycopg2.sql
from odoo.orm.database import sql_db
from odoo.exceptions import ConcurrencyError
from odoo.tools import SQL, OrderedSet, config, remove_accents
from odoo.tools.profiling import gc
from odoo.tools.func import locked, reset_cached_properties
from odoo.tools.lru import LRU
from odoo.tools.misc import Collector
from odoo.tools.system.version_tag_reset import reset_classes_tp_versions_used
from odoo.orm.models import classes as model_classes

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, MutableMapping
    from odoo.fields import Field
    from odoo.models import BaseModel
    from odoo.orm.database.sql_db import BaseCursor, Connection, Cursor
    from odoo.modules import module_graph

from .triggers import TriggerTree

class Registry(Mapping[str, type["BaseModel"]]):
    """ Model registry for a particular database.

    The registry is essentially a mapping between model names and model classes.
    There is one registry instance per database.

    """
    _lock = threading.RLock()
    idle_timeout = 0
    registries = LRU[str, "Registry"](42)  # random default value
    """ A mapping from database names to registries. """
    def __new__(cls, db_name: str):
        """ Return the registry for the given database name."""
        assert db_name, "Missing database name"
        # set the database name for logging
        current_thread = threading.current_thread()
        current_thread.dbname = db_name
        with cls._lock:
            try:
                registry = cls.registries[db_name]
                registry.last_used = time.monotonic()
                return registry
            except KeyError:
                return cls.new(db_name)
    ready: bool  # whether everything is set up
    loaded: bool  # whether all modules are loaded
    models: dict[str, type[BaseModel]]
    @classmethod
    @locked
    def new(
        cls,
        db_name: str,
        *,
        update_module: bool = False,
        install_modules: Collection[str] = (),
        upgrade_modules: Collection[str] = (),
        reinit_modules: Collection[str] = (),
        new_db_demo: bool | None = None,
        lock_wait: int = 15,
    ) -> Registry:
        """Create and return a new registry for the given database name.

        :param db_name: The name of the database to associate with the Registry instance.
        :param update_module: If ``True``, update modules while loading the registry. Defaults to ``False``.
        :param install_modules: Names of modules to install.

          * If a specified module is **not installed**, it and all of its direct and indirect
            dependencies will be installed.

          Defaults to an empty tuple.

        :param upgrade_modules: Names of modules to upgrade. Their direct or indirect dependent
          modules will also be upgraded. Defaults to an empty tuple.
        :param reinit_modules: Names of modules to reinitialize.

          * If a specified module is **already installed**, it and all of its installed direct and
            indirect dependents will be re-initialized. Re-initialization means the module will be
            upgraded without running upgrade scripts, but with data loaded in ``'init'`` mode.

        :param new_db_demo: Whether to install demo data for the new database. If set to ``None``, the value will be
          determined by the ``config['with_demo']``. Defaults to ``None``
        :param lock_wait: How long to wait to acquire the lock on the database (in seconds).
        """
        if (registry := cls.registries.get(db_name)) and not registry.ready:
            raise Exception('Registry for database %s can not be loaded recursively' % db_name)

        from odoo.modules import db  # noqa: PLC0415
        from odoo.modules.loading import load_modules, reset_modules_state  # noqa: PLC0415

        t0 = time.time()
        registry: Registry = object.__new__(cls)
        registry.init(db_name)
        first_registry = not cls.registries

        # Initializing a registry will call general code which will in
        # turn call Registry() to obtain the registry being initialized.
        # Make it available in the registries dictionary then remove it
        # if an exception is raised.
        cls.registries[db_name] = registry  # pylint: disable=unsupported-assignment-operation
        logger_level = logging.ERROR
        try:
            registry.setup_signaling()
            if upgrade_modules or install_modules or reinit_modules:
                update_module = True

            with ExitStack() as exit_stack:
                # The transaction 'cr' defines a critical section for multi-worker concurrency
                # control. It uses a shared lock to avoid registry updates while loading modules,
                # and an exclusive lock when updating the registry.
                cr = exit_stack.enter_context(registry.cursor())
                assert lock_wait >= 0
                cr.execute(f"SET SESSION lock_timeout = '{int(lock_wait)}s'")

                # acquire the exclusive or shared lock at the session level; this enables to guard
                # several transactions under the lock until the cursor is closed
                if not update_module:
                    logger_level = logging.WARNING
                    cr.execute("SELECT pg_advisory_lock_shared(hashtext('registry_loading'))", log_exceptions=False)
                    logger_level = logging.ERROR
                    if db.is_initialized(cr):
                        # check whether we have a partially upgraded database that needs updating;
                        # PostgreSQL will detect deadlocks if several processes have the shared
                        # lock and try to acquire the exclusive lock
                        cr.commit()  # commit after acquiring the lock to re-start the transaction
                        cr.execute("""
                            SELECT FROM ir_module_module
                            WHERE state IN ('to upgrade', 'to install', 'to remove')
                            LIMIT 1
                        """)
                        if cr.rowcount:
                            _logger.info("Force module updates, some modules must be installed/uninstalled/upgraded")
                            update_module = True
                if update_module:
                    try:
                        logger_level = logging.WARNING
                        cr.execute("SELECT pg_advisory_lock(hashtext('registry_loading'))", log_exceptions=False)
                        logger_level = logging.ERROR
                    except psycopg2.errors.DeadlockDetected:
                        # multiple workers were loading the database and try to upgrade it, only one will succeed
                        raise ConcurrencyError("Deadlock when waiting for lock to update the registry") from None
                    cr.commit()  # commit after acquiring the lock to re-start the transaction

                # now load modules
                if new_db_demo is None:
                    new_db_demo = config['with_demo']
                if first_registry and not update_module:
                    exit_stack.enter_context(gc.disabling_gc())
                retries = 5 if update_module else 1
                for _ in range(retries):
                    # load_modules multiple times in case there are modules to be uninstalled
                    # the load happens in a new context to be independent from things such as requests
                    try:
                        contextvars.Context().run(
                            load_modules,
                            registry,
                            cr=cr,
                            update_module=update_module,
                            upgrade_modules=upgrade_modules,
                            install_modules=install_modules,
                            reinit_modules=reinit_modules,
                            new_db_demo=new_db_demo,
                        )
                        cr.commit()
                    except Exception:
                        cr.rollback()
                        reset_modules_state(cr)
                        cr.commit()
                        raise
                    if registry.loaded:
                        break
                    models_to_check = registry._models_to_check
                    registry = object.__new__(cls)
                    registry.init(db_name, models_to_check=models_to_check)
                    cls.registries[db_name] = registry  # pylint: disable=unsupported-assignment-operation
                    cr.transaction.reset()  # rebind the transaction to the new registry
                    upgrade_modules = install_modules = reinit_modules = ()
                else:
                    raise Exception(f'Failed to load registry after {retries} attempts')  # noqa: TRY301
        except Exception:
            del cls.registries[db_name]
            _logger.log(logger_level, 'Failed to load registry')
            raise

        del registry.loaded_xmlids
        del registry._force_upgrade_scripts
        del registry._reinit_modules
        del registry._models_to_check

        # load_modules() above can replace the registry by calling
        # indirectly new() again (when modules have to be uninstalled).
        # Yeah, crazy.
        registry = cls.registries[db_name]  # pylint: disable=unsubscriptable-object

        reset_classes_tp_versions_used([*registry.values(), Registry], reset_above_ratio=0.3)  # cpython optimisation
        registry.ready = True
        registry.last_used = time.monotonic()

        _logger.info("Registry loaded in %.3fs", time.time() - t0)
        cls._drop_idle()
        return registry
    def init(self, db_name: str, models_to_check: OrderedSet[str] | None = None) -> None:
        self.loaded = False
        self.ready = False
        self.last_used = time.monotonic()

        self.models: dict[str, type[BaseModel]] = {}    # model name/model instance mapping
        self._sql_constraints = set()  # type: ignore
        self._database_translated_fields: dict[str, str] = {}  # names and translate function names of translated fields in database {"{model}.{field_name}": "translate_func"}
        self._database_company_dependent_fields: set[str] = set()  # names of company dependent fields in database
        if config['test_enable']:
            from odoo.tests.result import OdooTestResult  # noqa: PLC0415
            self._assertion_report: OdooTestResult | None = OdooTestResult()
        else:
            self._assertion_report = None
        self._ordinary_tables: set[str] | None = None  # cached names of regular tables
        self._constraint_queue: dict[typing.Any, Callable[[BaseCursor], None]] = {}  # queue of functions to call on finalization of constraints

        # update context during loading modules
        self.loaded_xmlids: set[str] = set()           # loaded xmlids for IrModelData._process_end()
        self._force_upgrade_scripts: set[str] = set()  # force the execution of the upgrade script for these modules
        self._reinit_modules: set[str] = set()  # modules to reinitialize
        self._models_to_check: OrderedSet[str] = models_to_check or OrderedSet()

        # modules fully loaded (maintained during init phase by `loading` module)
        self._init_modules: set[str] = set()         # modules have been initialized
        self.updated_modules: list[str] = []         # installed/updated modules
        self.uninstalling_modules: set[str] = set()  # modules being uninstalled

        self.db_name = db_name
        self._db: Connection = sql_db.db_connect(db_name, readonly=False)
        self._db_readonly: Connection | None = None
        self._db_readonly_failed_time: float | None = None
        if config['db_replica_host'] or config['test_enable'] or 'replica' in config['dev_mode']:  # by default, only use readonly pool if we have a db_replica_host defined.
            self._db_readonly = sql_db.db_connect(db_name, readonly=True)

        # field dependencies
        self.field_depends: Collector[Field, str] = Collector()
        self.field_depends_context: Collector[Field, str] = Collector()

        # field inverses
        self.many2many_relations: defaultdict[tuple[str, str, str], OrderedSet[tuple[str, str]]] = defaultdict(OrderedSet)

        # field setup dependents: this enables to invalidate the setup of
        # related fields when some of their dependencies are invalidated
        # (for incremental model setup)
        self.field_setup_dependents: Collector[Field, Field] = Collector()

        # company dependent
        self.many2one_company_dependents: Collector[str, Field] = Collector()  # {model_name: (field1, field2, ...)}

        # constraint checks
        self.not_null_fields: set[Field] = set()

        # Inter-process signaling:
        # The `orm_signaling_...` sequence indicates that the corresponding
        # cache is invalid if the sequence is different. The 'registry' sequence
        # applies to the whole registry which must be rebuilt.
        self.registry_sequence: int = -1
        self.registry_caches__: dict[str, tuple[int, MutableMapping]] = {}
        self.registry_cache_lock = threading.RLock()
        self._template_code__ = LRU(_REGISTRY_CACHES['templates'])  # memo for code templates

        from odoo.modules import db  # noqa: PLC0415
        with closing(self.cursor()) as cr:
            self.has_unaccent = db.has_unaccent(cr)
            self.has_trigram = db.has_trigram(cr)

        self.unaccent = _unaccent if self.has_unaccent else lambda x: x  # type: ignore
        self.unaccent_python = remove_accents if self.has_unaccent else lambda x: x

        self.new = self.init = self.registries = None  # type: ignore
    @classmethod
    @locked
    def delete(cls, db_name: str) -> None:
        """ Delete the registry linked to a given database. """
        if db_name in cls.registries:  # pylint: disable=unsupported-membership-test
            del cls.registries[db_name]  # pylint: disable=unsupported-delete-operation
    @classmethod
    @locked
    def delete_all(cls):
        """ Delete all the registries. """
        cls.registries.clear()
    @classmethod
    @locked
    def _drop_idle(cls) -> None:
        """ Drop registries that have not been used for a while. """
        if cls.idle_timeout <= 0:
            return
        now = time.monotonic()
        gc_list = []
        for db_name, registry in cls.registries.items():
            if now - registry.last_used > cls.idle_timeout:
                gc_list.append(db_name)
        for db_name in gc_list:
            _logger.info("Drop idle registry for %s", db_name)
            cls.delete(db_name)
    def __len__(self):
        """ Return the size of the registry. """
        return len(self.models)
    def __iter__(self):
        """ Return an iterator over all model names. """
        return iter(self.models)
    def __getitem__(self, model_name: str) -> type[BaseModel]:
        """ Return the model with the given name or raise KeyError if it doesn't exist."""
        return self.models[model_name]
    def __setitem__(self, model_name: str, model: type[BaseModel]):
        """ Add or replace a model in the registry."""
        self.models[model_name] = model
    def __delitem__(self, model_name: str):
        """ Remove a (custom) model from the registry. """
        del self.models[model_name]
        # the custom model can inherit from mixins ('mail.thread', ...)
        for Model in self.models.values():
            Model._inherit_children.discard(model_name)
    def descendants(self, model_names: Iterable[str], *kinds: typing.Literal['_inherit', '_inherits']) -> OrderedSet[str]:
        return _setup.descendants(self, model_names, *kinds)
    def load(self, module: module_graph.ModuleNode) -> list[str]:
        """ Load a given module in the registry, and return the names of the
        directly modified models.

        At the Python level, the modules are already loaded, but not yet on a
        per-registry level. This method populates a registry with the given
        modules, i.e. it instantiates all the classes of a the given module
        and registers them in the registry.

        In order to determine all the impacted models, one should invoke method
        :meth:`descendants` with `'_inherit'` and `'_inherits'`.
        """
        from odoo.orm import models  # noqa: PLC0415

        # clear cache to ensure consistency, but do not signal it
        assert not self.ready, "Cannot load() when registry is ready"
        for _seq, cache in self.registry_caches__.values():
            cache.clear()

        reset_cached_properties(self)

        # Instantiate registered classes (via the MetaModel automatic discovery
        # or via explicit constructor call), and add them to the pool.
        model_names = []
        for model_def in models.MetaModel._module_to_models__.get(module.name, []):
            # models register themselves in self.models
            model_cls = model_classes.add_to_registry(self, model_def)
            model_names.append(model_cls._name)

        return model_names
    def _setup_models__(self, cr: BaseCursor, model_names: Iterable[str] | None=None) -> None:
        return _setup._setup_models__(self, cr, model_names)
    @functools.cached_property
    def field_inverses(self) -> Collector[Field, Field]:
        return _setup.field_inverses(self)
    @functools.cached_property
    def field_computed(self) -> dict[Field, list[Field]]:
        return _setup.field_computed(self)
    def get_trigger_tree(self, fields: list[Field], select: Callable[[Field], bool]=bool) -> TriggerTree:
        return _triggers.get_trigger_tree(self, fields, select)
    def get_dependent_fields(self, field: Field) -> Iterator[Field]:
        return _triggers.get_dependent_fields(self, field)
    def _discard_fields(self, fields: list[Field]) -> None:
        return _triggers._discard_fields(self, fields)
    @functools.cached_property
    def _field_trigger_trees(self) -> dict[Field, TriggerTree]:
        return _triggers._field_trigger_trees(self)
    def get_field_trigger_tree(self, field: Field) -> TriggerTree:
        return _triggers.get_field_trigger_tree(self, field)
    @functools.cached_property
    def _field_triggers(self) -> defaultdict[Field, defaultdict[tuple[str, ...], OrderedSet[Field]]]:
        return _triggers._field_triggers(self)
    @functools.cached_property
    def _is_modifying_relations(self) -> dict[Field, bool]:
        return _triggers._is_modifying_relations(self)
    def is_modifying_relations(self, field: Field) -> bool:
        return _triggers.is_modifying_relations(self, field)
    def post_init(self, func: Callable, *args, **kwargs) -> None:
        return _schema.post_init(self, func, *args, **kwargs)
    def post_constraint(self, cr: BaseCursor, func: Callable[[BaseCursor], None], key) -> None:
        return _schema.post_constraint(self, cr, func, key)
    def finalize_constraints(self, cr: Cursor) -> None:
        return _schema.finalize_constraints(self, cr)
    def init_models(self, cr: Cursor, model_names: Iterable[str], context: dict[str, typing.Any], install: bool=True):
        return _schema.init_models(self, cr, model_names, context, install)
    def check_null_constraints(self, cr: Cursor) -> None:
        return _schema.check_null_constraints(self, cr)
    def check_indexes(self, cr: Cursor, model_names: Iterable[str]) -> None:
        return _schema.check_indexes(self, cr, model_names)
    def add_foreign_key(self, table1: str, column1: str, table2: str, column2: str, ondelete: str, model: BaseModel, module: str, force: bool=True) -> None:
        return _schema.add_foreign_key(self, table1, column1, table2, column2, ondelete, model, module, force)
    def check_foreign_keys(self, cr: Cursor) -> None:
        return _schema.check_foreign_keys(self, cr)
    def check_tables_exist(self, cr: Cursor) -> None:
        return _schema.check_tables_exist(self, cr)
    def is_an_ordinary_table(self, model: BaseModel) -> bool:
        return _schema.is_an_ordinary_table(self, model)
    def setup_signaling(self) -> None:
        return _signaling.setup_signaling(self)
    def get_sequences(self, cr: BaseCursor) -> tuple[int, dict[str, int]]:
        return _signaling.get_sequences(self, cr)
    def _signal_changes(self, cr: BaseCursor, names: Collection[str]) -> None:
        return _signaling._signal_changes(self, cr, names)
    def cursor(self, /, readonly: bool=False) -> BaseCursor:
        return _signaling.cursor(self, readonly)


_logger = logging.getLogger('odoo.registry')


_schema = logging.getLogger('odoo.schema')


_REGISTRY_CACHES = {
    'default': 8192,
    'assets': 512,
    'stable': 1024,
    'templates': 1024,
    'routing': 1024,  # 2 entries per website
    'routing.rewrites': 8192,  # url_rewrite entries
    'templates.cached_values': 2048, # arbitrary
    'groups': 64,  # see res.groups
}


_CACHES_BY_KEY = {
    'default': ('default', 'templates.cached_values'),
    'assets': ('assets', 'templates.cached_values'),
    'stable': ('stable', 'default', 'templates.cached_values'),
    'templates': ('templates', 'templates.cached_values'),
    'routing': ('routing', 'routing.rewrites', 'templates.cached_values'),
    'groups': ('groups', 'default', 'templates', 'templates.cached_values'),  # The processing of groups is saved in the view
}


_REPLICA_RETRY_TIME = 20 * 60  # 20 minutes


def _unaccent(x: SQL | str | psycopg2.sql.Composable) -> SQL | str | psycopg2.sql.Composed:
    if isinstance(x, SQL):
        return SQL("unaccent(%s)", x)
    if isinstance(x, psycopg2.sql.Composable):
        return psycopg2.sql.SQL('unaccent({})').format(x)
    return f'unaccent({x})'


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import setup as _setup, triggers as _triggers, schema as _schema, signaling as _signaling  # noqa: E402
