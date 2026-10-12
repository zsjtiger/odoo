# Part of Odoo. See LICENSE file for full copyright and licensing details.


"""
    Object Relational Mapping module:
     * Hierarchical structure
     * Constraints consistency and validation, indexes
     * Object metadata depends on its status
     * Optimised processing by complex query (multiple actions at once)
     * Default field values
     * Permissions optimisation
     * Persistent object: DB postgresql
     * Data conversion
     * Multi-level caching system
     * Two different inheritance mechanisms
     * Rich set of field types:
          - classical (varchar, integer, boolean, ...)
          - relational (one2many, many2one, many2many)
          - functional

"""
from __future__ import annotations

import collections
import contextlib
import functools
import inspect
import itertools
import io
import json
import logging
import re
import typing
import uuid
import warnings
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
from inspect import getmembers
from operator import itemgetter

import psycopg2.errors
import psycopg2.extensions

from odoo.exceptions import AccessError, LockError, MissingError, ValidationError, UserError
from odoo.tools import (
    clean_context, frozendict, OrderedSet,
    partition, split_every,
    SQL, sql,
)
from odoo.tools.constants import BIG_RECORDSET_SIZE, IN_MAX
from odoo.tools.func import deprecated
from odoo.tools.lru import LRU
from odoo.tools.misc import ReversedIterable, unquote
from odoo.tools.safe_eval import _UNSAFE_ATTRIBUTES, safe_checker
from odoo.tools.translate import _, LazyTranslate

from odoo.orm.core import access as orm_access
from odoo.orm.database import schema as orm_schema

from odoo.orm.core import decorators as api
from odoo.orm.core.commands import Command
from odoo.orm.core.domains import Domain
from odoo.orm.fields import Field
from odoo.orm.fields.misc import Id
from odoo.orm.fields.temporal import Datetime
from odoo.orm.fields.textual import Char, StoredTranslations

from odoo.orm.core.identifiers import NewId
from odoo.orm.database.query import Query, TableSQL
from odoo.orm.core.utils import (
    OriginIds, Prefetch, parse_field_expr,
    COLLECTION_TYPES,
    SUPERUSER_ID,
)

if typing.TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Reversible, Sequence
    from types import MappingProxyType
    from typing import Self
    from odoo.orm.database.table_objects import TableObject
    from odoo.orm.models.environments import Environment
    from odoo.orm.models.registry import Registry, TriggerTree
    from odoo.orm.core.types import DomainType, IdType, ModelType, ValuesType


_lt = LazyTranslate('base')
_logger = logging.getLogger('odoo.models')
_unlink = logging.getLogger('odoo.models.unlink')

regex_order = re.compile(r'''
    ^
    (\s*
        (?P<term>((?P<field>[a-z0-9_]+)(\.(?P<property>[a-z0-9_]+))?(:(?P<func>[a-z_]+))?))
        (\s+(?P<direction>desc|asc))?
        (\s+(?P<nulls>nulls\ first|nulls\ last))?
        \s*
        (,|$)
    )+
    (?<!,)
    $
''', re.IGNORECASE | re.VERBOSE)
regex_order_part_read_group = re.compile(r"""
    \s*
    (?P<term>(?P<field>[a-z0-9_]+)(\.([\w\.]+))?(:(?P<func>[a-z_]+))?)
    (\s+(?P<direction>desc|asc))?
    (\s+(?P<nulls>nulls\ first|nulls\ last))?
    \s*
""", re.IGNORECASE | re.VERBOSE)
regex_field_agg = re.compile(r'(\w+)(?::(\w+)(?:\((\w+)\))?)?')  # For read_group
regex_read_group_spec = re.compile(r'(\w+)(\.([\w\.]+))?(?::(\w+))?$')  # For _read_group

INSERT_BATCH_SIZE = 100
UPDATE_BATCH_SIZE = 100
SQL_DEFAULT = psycopg2.extensions.AsIs("DEFAULT")

from odoo.orm.core.access import NO_ACCESS


def parse_read_group_spec(spec: str) -> tuple:
    """ Return a triplet corresponding to the given field/property_name/aggregate specification. """
    res_match = regex_read_group_spec.match(spec)
    if not res_match:
        raise ValueError(
            f'Invalid aggregate/groupby specification {spec!r}.\n'
            '- Valid aggregate specification looks like "<field_name>:<agg>" example: "quantity:sum".\n'
            '- Valid groupby specification looks like "<no_datish_field_name>" or "<datish_field_name>:<granularity>" example: "date:month" or "<properties_field_name>.<property>:<granularity>".'
        )

    groups = res_match.groups()
    return groups[0], groups[2], groups[3]


def fix_import_export_id_paths(fieldname):
    """
    Fixes the id fields in import and exports, and splits field paths
    on '/'.

    :param str fieldname: name of the field to import/export
    :return: split field name
    :rtype: list of str
    """
    fixed_db_id = re.sub(r'([^/])\.id', r'\1/.id', fieldname)
    fixed_external_id = re.sub(r'([^/]):id', r'\1/id', fixed_db_id)
    return fixed_external_id.split('/')


def to_record_ids(arg) -> list[int]:
    """ Return the record ids of ``arg``, which may be a recordset, an integer or a list of integers. """
    if isinstance(arg, BaseModel):
        return arg.ids
    elif isinstance(arg, int):
        return [arg] if arg else []
    else:
        return [id_ for id_ in arg if id_]


def check_company_domain_parent_of(self, companies):
    """ A `_check_company_domain` function that lets a record be used if either:
        - record.company_id = False (which implies that it is shared between all companies), or
        - record.company_id is a parent of any of the given companies.
    """
    if isinstance(companies, str):
        return ['|', ('company_id', '=', False), ('company_id', 'parent_of', companies)]

    companies = to_record_ids(companies)
    if not companies:
        return [('company_id', '=', False)]

    return [('company_id', 'in', [
        int(parent)
        for rec in self.env['res.company'].sudo().browse(companies)
        for parent in rec.parent_path.split('/')[:-1]
    ] + [False])]


def check_companies_domain_parent_of(self, companies):
    """ A `_check_company_domain` function that lets a record be used if
        any company in record.company_ids is a parent of any of the given companies.
    """
    if isinstance(companies, str):
        return [('company_ids', 'parent_of', companies)]

    companies = to_record_ids(companies)
    if not companies:
        return []

    return [('company_ids', 'in', [
        int(parent)
        for rec in self.env['res.company'].sudo().browse(companies)
        for parent in rec.parent_path.split('/')[:-1]
    ])]


def get_public_method(model: BaseModel, name: str) -> callable:
    """ Get the public unbound method from a model.

    When the method does not exist or is inaccessible, raise appropriate errors.
    Accessible methods are public (in sense that python defined it:
    not prefixed with "_") and are not decorated with `@api.private`.
    """
    assert isinstance(model, BaseModel)
    e = f"Private methods (such as '{model._name}.{name}') cannot be called remotely."
    if name.startswith('_') or name in _UNSAFE_ATTRIBUTES:
        raise AccessError(e)

    cls = type(model)
    method = getattr(cls, name, None)
    if not callable(method):
        raise AttributeError(f"The method '{model._name}.{name}' does not exist")  # noqa: TRY004
    if method == getattr(model, name, None):  # classmethod, staticmethod
        e = f"The method '{model._name}.{name}' cannot be called remotely."
        raise AccessError(e)

    for mro_cls in cls.mro():
        if not (cla_method := getattr(mro_cls, name, None)):
            continue
        if getattr(cla_method, '_api_private', False):
            raise AccessError(e)

    return method


class MetaModel(type):
    """ The metaclass of all model classes.
        Its main purpose is to register the models per module.
    """
    _module_to_models__: defaultdict[str, list[MetaModel]] = defaultdict(list)

    pool: Registry | None
    """Reference to the registry for registry classes, otherwise it is a definition class."""

    _field_definitions: list[Field]
    _table_object_definitions: list[TableObject]
    _name: str
    _register: bool  # need to define on each Model, default: True
    _log_access: bool  # when defined, add update log columns
    _module: str | None
    _abstract: bool
    _auto: bool
    _inherit__: list[str] | None

    def __new__(meta, name, bases, attrs):
        # this prevents assignment of non-fields on recordsets
        attrs.setdefault('__slots__', ())
        # this collects the fields defined on the class (via Field.__set_name__())
        attrs.setdefault('_field_definitions', [])
        # this collects the table object definitions on the class (via TableObject.__set_name__())
        attrs.setdefault('_table_object_definitions', [])

        if attrs.get('_register', True):
            # determine '_module'
            if '_module' not in attrs:
                module = attrs['__module__']
                assert module.startswith('odoo.addons.'), \
                    f"Invalid import of {module}.{name}, it should start with 'odoo.addons'."
                attrs['_module'] = module.split('.')[2]

            _inherit = attrs.get('_inherit')
            if _inherit and isinstance(_inherit, str):
                attrs.setdefault('_name', _inherit)
                attrs['_inherit'] = [_inherit]

            if not attrs.get('_name'):
                # add '.' before every uppercase letter preceded by any non-underscore char
                attrs['_name'] = re.sub(r"(?<=[^_])([A-Z])", r".\1", name).lower()
                _logger.warning("Class %s has no _name, please make it explicit: _name = %r", name, attrs['_name'])

            assert attrs.get('_name')

        if '_inherit' in attrs:
            attrs['_inherit__'] = attrs.pop('_inherit')

        return super().__new__(meta, name, bases, attrs)

    def __init__(self, name, bases, attrs):
        super().__init__(name, bases, attrs)

        if '__init__' in attrs and len(inspect.signature(attrs['__init__']).parameters) != 4:
            _logger.warning("The method %s.__init__ doesn't match the new signature in module %s", name, attrs.get('__module__'))

        if not attrs.get('_register', True):
            return

        # Remember which models to instantiate for this module.
        if self._module:
            self._module_to_models__[self._module].append(self)

        if not self._abstract and self._name not in self._inherit:
            # this class defines a model: add magic fields
            def add_default(name, field):
                if name not in attrs:
                    setattr(self, name, field)
                    field.__set_name__(self, name)

            # make sure `id` field is still a `fields.Id`
            if not isinstance(self.id, Id):
                raise TypeError(f"Field {self.id} is not an instance of fields.Id")

            if attrs.get('_log_access', self._auto):
                from odoo.orm.fields.relational import Many2one  # noqa: PLC0415
                add_default('create_uid', Many2one(
                    'res.users', string='Created by', readonly=True))
                add_default('create_date', Datetime(
                    string='Created on', readonly=True))
                add_default('write_uid', Many2one(
                    'res.users', string='Last Updated by', readonly=True))
                add_default('write_date', Datetime(
                    string='Last Updated on', readonly=True))

    @property
    def _inherit(cls):
        if getattr(cls, 'pool', None) is not None:
            raise AttributeError("Registry Class shouldn't access attribute '_inherit'. Please use issubclass instead")
        return cls._inherit__


safe_checker.add_hook(MetaModel, None)  # Optimization to serialize model class(es) faster

# special columns automatically created by the ORM
LOG_ACCESS_COLUMNS = ['create_uid', 'create_date', 'write_uid', 'write_date']
MAGIC_COLUMNS = ['id'] + LOG_ACCESS_COLUMNS

# valid SQL aggregation functions
READ_GROUP_AGGREGATE = {
    'sum': lambda table, expr: SQL('SUM(%s)', expr),
    'avg': lambda table, expr: SQL('AVG(%s)', expr),
    'max': lambda table, expr: SQL('MAX(%s)', expr),
    'min': lambda table, expr: SQL('MIN(%s)', expr),
    'bool_and': lambda table, expr: SQL('BOOL_AND(%s)', expr),
    'bool_or': lambda table, expr: SQL('BOOL_OR(%s)', expr),
    'array_agg': lambda table, expr: SQL('ARRAY_AGG(%s ORDER BY %s)', expr, table.id),
    'array_agg_distinct': lambda table, expr: SQL('ARRAY_AGG(DISTINCT %s ORDER BY %s)', expr, expr),
    # 'recordset' aggregates will be post-processed to become recordsets
    'recordset': lambda table, expr: SQL('ARRAY_AGG(%s ORDER BY %s)', expr, table.id),
    'count': lambda table, expr: SQL('COUNT(%s)', expr),
    'count_distinct': lambda table, expr: SQL('COUNT(DISTINCT %s)', expr),
}

READ_GROUP_DISPLAY_FORMAT = {
    # Careful with week/year formats:
    #  - yyyy (lower) must always be used, *except* for week+year formats
    #  - YYYY (upper) must always be used for week+year format
    #         e.g. 2006-01-01 is W52 2005 in some locales (de_DE),
    #                         and W1 2006 for others
    #
    # Mixing both formats, e.g. 'MMM YYYY' would yield wrong results,
    # such as 2006-01-01 being formatted as "January 2005" in some locales.
    # Cfr: http://babel.pocoo.org/en/latest/dates.html#date-fields
    'hour': 'HH:00 dd MMM',
    'day': 'dd MMM yyyy', # yyyy = normal year
    'week': "'W'w YYYY",  # w YYYY = ISO week-year
    'month': 'MMMM yyyy',
    'quarter': 'QQQ yyyy',
    'year': 'yyyy',
}


class BaseModel(metaclass=MetaModel):
    """Base class for Odoo models.

    Odoo models are created by inheriting one of the following:

    *   :class:`Model` for regular database-persisted models

    *   :class:`TransientModel` for temporary data, stored in the database but
        automatically vacuumed every so often

    *   :class:`AbstractModel` for abstract super classes meant to be shared by
        multiple inheriting models

    The system automatically instantiates every model once per database. Those
    instances represent the available models on each database, and depend on
    which modules are installed on that database. The actual class of each
    instance is built from the Python classes that create and inherit from the
    corresponding model.

    Every model instance is a "recordset", i.e., an ordered collection of
    records of the model. Recordsets are returned by methods like
    :meth:`~.browse`, :meth:`~.search`, or field accesses. Records have no
    explicit representation: a record is represented as a recordset of one
    record.

    To create a class that should not be instantiated,
    the :attr:`~odoo.models.BaseModel._register` attribute may be set to False.
    """
    __slots__ = ['env', '_ids', '_prefetch_ids']

    pool: Registry  # all registry classes have a registry on the class
    # TODO replace most usages with self.env.registry; pool is reserved for class instance

    _fields__: dict[str, Field]
    _fields: MappingProxyType[str, Field]

    _fields_update_order__: dict[Field, tuple[int, int]]
    """Field update/inverse order.

    ``{field: (write_sequence, field_index)}``
    Sort by ``field.write_sequence``, then :attr:`_fields` index.
    """

    _auto: bool = False
    """Whether a database table should be created.
    If set to ``False``, override :meth:`~odoo.models.BaseModel.init`
    to create the database table.

    Automatically defaults to `True` for abstract models.

    .. tip:: To create a model without any table, inherit
            from :class:`~odoo.models.AbstractModel`.
    """
    _register: bool = False           #: registry visibility
    _abstract: bool = True
    """ Whether the model is *abstract*.

    .. seealso:: :class:`AbstractModel`
    """
    _transient: bool = False
    """ Whether the model is *transient*.

    .. seealso:: :class:`TransientModel`
    """

    _name: str = None                   #: the model name (in dot-notation, module namespace)
    _description: str | None = None     #: the model's informal name
    _explanation: str | None = None     #: the model's verbose explanation (what purpuse does it serve)
    _module: str | None = None          #: the model's module (in the Odoo sense)
    _custom: bool = False               #: should be True for custom models only

    _inherit: str | list[str] | tuple[str, ...] = ()
    """Python-inherited models:

    :type: str or list(str) or tuple(str)

    .. note::

        * If :attr:`._name` is set, name(s) of parent models to inherit from
        * If :attr:`._name` is unset, name of a single model to extend in-place
    """
    _inherits: Mapping[str, str] = frozendict()
    """dictionary {'parent_model': 'm2o_field'} mapping the _name of the parent business
    objects to the names of the corresponding foreign key fields to use::

      _inherits = {
          'a.model': 'a_field_id',
          'b.model': 'b_field_id'
      }

    implements composition-based inheritance: the new model exposes all
    the fields of the inherited models but stores none of them:
    the values themselves remain stored on the linked record.

    .. warning::

      if multiple fields with the same name are defined in the
      :attr:`~odoo.models.Model._inherits`-ed models, the inherited field will
      correspond to the last one (in the inherits list order).
    """
    _check_inherits_access: bool = True           #: check access for _inherits models
    _table: str = ''                 #: SQL table name used by model if :attr:`_auto`
    _table_objects: dict[str, TableObject] = frozendict()  #: SQL/Table objects
    _inherit_children: OrderedSet[str]

    _rec_name: str = ''                           #: field to use for labeling records, default: ``name``
    _rec_names_search: Collection[str] = ()       #: fields to consider in ``name_search``
    _order: str = 'id'                            #: default order field for searching results
    _parent_name: str = 'parent_id'               #: the many2one field used as parent field
    _parent_store: bool = False
    """set to True to compute parent_path field.

    Alongside a :attr:`~.parent_path` field, sets up an indexed storage
    of the tree structure of records, to enable faster hierarchical queries
    on the records of the current model using the ``child_of`` and
    ``parent_of`` domain operators.
    """
    _active_name: str | None = None
    """field to use for active records, automatically set to either ``"active"``
    or ``"x_active"``.
    """
    _fold_name: str = 'fold'         #: field to determine folded groups in kanban views

    _clear_cache_name: str = ''      # cache to clear on create/write/update
    _clear_cache_on_fields: Iterable[str] | None = None
    """the fields that trigger invalidation of cache named ``_clear_cache_name``,
    ``None`` meaning all fields
    """

    _translate: bool = True           # False disables translations export for this model (Old API) TODO deprecate/remove
    _check_company_auto: bool = False
    """On write and create, call ``_check_company`` to ensure companies
    consistency on the relational fields having ``check_company=True``
    as attribute.
    """

    _allow_sudo_commands: bool = True
    """Allow One2many and Many2many Commands targeting this model in an environment using `sudo()` or `with_user()`.
    By disabling this flag, security-sensitive models protect themselves
    against malicious manipulation of One2many or Many2many fields
    through an environment using `sudo` or a more privileged user.
    """

    _depends: Mapping[str, Iterable[str]] = frozendict()
    """dependencies of models backed up by SQL views
    ``{model_name: field_names}``, where ``field_names`` is an iterable.
    This is only used to determine the changes to flush to database before
    executing any search/read operations. It won't be used for cache
    invalidation or recomputing fields.
    """

    id = Id()
    display_name = Char(
        string='Display Name',
        compute='_compute_display_name',
        search='_search_display_name',
    )

    def _valid_field_parameter(self, field, name):
        """ Return whether the given parameter name is valid for the field. """
        return name == 'related_sudo'

    @api.model
    def _post_model_setup__(self):
        """ Method called after the model has been setup. """
        pass

    @property
    def _table_sql(self) -> SQL:
        """ Return an :class:`SQL` object that represents SQL table identifier
        or table query.
        """
        table_sql = SQL.identifier(self._table)
        if not self._depends:
            return table_sql

        # add self._depends (and its transitive closure) as metadata to table_sql
        fields_to_flush: list[Field] = []
        models = [self]
        while models:
            current_model = models.pop()
            for model_name, field_names in current_model._depends.items():
                model = self.env[model_name]
                models.append(model)
                fields_to_flush.extend(model._fields[fname] for fname in field_names)

        return SQL("%s", table_sql, to_flush=fields_to_flush)

    @property
    def _constraint_methods(self):
        """ Return a list of methods implementing Python constraints. """
        def is_constraint(func):
            return callable(func) and hasattr(func, '_constrains')

        def wrap(func, names):
            # wrap func into a proxy function with explicit '_constrains'
            @api.constrains(*names)
            def wrapper(self):
                return func(self)
            return wrapper

        cls = self.env.registry[self._name]
        methods = []
        for attr, func in getmembers(cls, is_constraint):
            if callable(func._constrains):
                func = wrap(func, func._constrains(self.sudo()))
            for name in func._constrains:
                field = cls._fields.get(name)
                if not field:
                    _logger.warning("method %s.%s: @constrains parameter %r is not a field name", cls._name, attr, name)
                elif not (field.store or field.inverse or field.inherited):
                    _logger.warning("method %s.%s: @constrains parameter %r is not writeable", cls._name, attr, name)
            methods.append(func)

        # optimization: memoize result on cls, it will not be recomputed
        cls._constraint_methods = methods
        return methods

    @property
    def _ondelete_methods(self):
        """ Return a list of methods implementing checks before unlinking. """
        def is_ondelete(func):
            return callable(func) and hasattr(func, '_ondelete')

        cls = self.env.registry[self._name]
        methods = [func for _, func in getmembers(cls, is_ondelete)]
        # optimization: memoize results on cls, it will not be recomputed
        cls._ondelete_methods = methods
        return methods

    @property
    def _onchange_methods(self):
        """ Return a dictionary mapping field names to onchange methods. """
        def is_onchange(func):
            return callable(func) and hasattr(func, '_onchange')

        # collect onchange methods on the model's class
        cls = self.env.registry[self._name]
        methods = defaultdict(list)
        for _attr, func in getmembers(cls, is_onchange):
            missing = []
            for name in func._onchange:
                if name not in cls._fields:
                    missing.append(name)
                methods[name].append(func)
            if missing:
                _logger.warning(
                    "@api.onchange%r parameters must be field names -> not valid: %s",
                    func._onchange, missing
                )

        # add onchange methods to implement "change_default" on fields
        def onchange_default(field, self):
            value = field.convert_to_write(self[field.name], self)
            condition = "%s=%s" % (field.name, value)
            defaults = self.env['ir.default']._get_model_defaults(self._name, condition)
            self.update(defaults)

        for name, field in cls._fields.items():
            if field.change_default:
                methods[name].append(functools.partial(onchange_default, field))

        # optimization: memoize result on cls, it will not be recomputed
        cls._onchange_methods = methods
        return methods

    def _is_an_ordinary_table(self):
        return self.pool.is_an_ordinary_table(self)

    def _ensure_xml_id(self, skip=False):
        """ Create missing external ids for records in ``self``, and return an
            iterator of pairs ``(record, xmlid)`` for the records in ``self``.

        :rtype: Iterable[Model, str | None]
        """
        if skip:
            return ((record, None) for record in self)

        if not self:
            return iter([])

        if not self._is_an_ordinary_table():
            raise Exception(
                "You can not export the column ID of model %s, because the "
                "table %s is not an ordinary table."
                % (self._name, self._table))

        modname = '__export__'

        cr = self.env.cr
        cr.execute(SQL("""
            SELECT res_id, module, name
            FROM ir_model_data
            WHERE model = %s AND res_id IN %s
        """, self._name, tuple(self.ids)))
        xids = {
            res_id: (module, name)
            for res_id, module, name in cr.fetchall()
        }
        def to_xid(record_id):
            (module, name) = xids[record_id]
            return ('%s.%s' % (module, name)) if module else name

        # create missing xml ids
        missing = self.filtered(lambda r: r.id not in xids)
        if not missing:
            return (
                (record, to_xid(record.id))
                for record in self
            )

        xids.update(
            (r.id, (modname, '%s_%s_%s' % (
                r._table,
                r.id,
                uuid.uuid4().hex[:8],
            )))
            for r in missing
        )
        fields = ['module', 'model', 'name', 'res_id']

        # disable eventual async callback / support for the extent of
        # the COPY FROM, as these are apparently incompatible
        callback = psycopg2.extensions.get_wait_callback()
        psycopg2.extensions.set_wait_callback(None)
        try:
            cr.copy_from(io.StringIO(
                u'\n'.join(
                    u"%s\t%s\t%s\t%d" % (
                        modname,
                        record._name,
                        xids[record.id][1],
                        record.id,
                    )
                    for record in missing
                )),
                table='ir_model_data',
                columns=fields,
            )
        finally:
            psycopg2.extensions.set_wait_callback(callback)
        self.env['ir.model.data'].invalidate_model(fields)

        return (
            (record, to_xid(record.id))
            for record in self
        )

    def _export_rows(self, fields, *, _is_toplevel_call=True):
        """ Export fields of the records in ``self``.

        :param list fields: list of lists of fields to traverse
        :param bool _is_toplevel_call:
            used when recursing, avoid using when calling from outside
        :return: list of lists of corresponding values
        """
        return orm_export._export_rows(self, fields, _is_toplevel_call=_is_toplevel_call)

    def export_data(self, fields_to_export):
        """ Export fields for selected objects

        This method is used when exporting data via client menu

        A field path may be suffixed with ``@`` and a language code (e.g.
        ``name@fr_FR``) to export the translation of a translated field in
        that language, using the same convention as the import.

        :param list fields_to_export: list of fields
        :returns: dictionary with a *datas* matrix
        :rtype: dict
        """
        return orm_export.export_data(self, fields_to_export)

    @api.model
    def load(self, fields, data):
        """
        Attempts to load the data matrix, and returns a list of ids (or
        ``False`` if there was an error and no id could be generated) and a
        list of messages.

        The ids are those of the records created and saved (in database), in
        the same order they were extracted from the file. They can be passed
        directly to :meth:`~read`

        :param fields: list of fields to import, at the same index as the corresponding data
        :type fields: list(str)
        :param data: row-major matrix of data to import
        :type data: list(list(str))
        :returns: {ids: list(int)|False, messages: [Message][, lastrow: int]}
        """
        from odoo.orm.fields.relational import One2many  # noqa: PLC0415

        # determine values of mode, current_module and noupdate
        mode = self.env.context.get('mode', 'init')
        current_module = self.env.context.get('module', '__import__')
        noupdate = self.env.context.get('noupdate', False)
        # add current module in context for the conversion of xml ids
        self = self.with_context(_import_current_module=current_module)

        cr = self.env.cr
        savepoint = cr.savepoint()

        fields = [fix_import_export_id_paths(f) for f in fields]

        ids = []
        messages = []

        # list of (xid, vals, info) for records to be created in batch
        batch = []
        batch_xml_ids = set()
        # models in which we may have created / modified data, therefore might
        # require flushing in order to name_search: the root model and any
        # o2m
        creatable_models = {self._name}
        for field_path in fields:
            if field_path[0] in (None, 'id', '.id'):
                continue
            model_fields = self._fields
            for field_name in field_path:
                if field_name in (None, 'id', '.id'):
                    break

                if isinstance(model_fields.get(field_name), One2many):
                    comodel = model_fields[field_name].comodel_name
                    creatable_models.add(comodel)
                    model_fields = self.env[comodel]._fields

        def flush(*, xml_id=None, model=None):
            if not batch:
                return

            assert not (xml_id and model), \
                "flush can specify *either* an external id or a model, not both"

            if xml_id and xml_id not in batch_xml_ids:
                if xml_id not in self.env:
                    return
            if model and model not in creatable_models:
                return

            data_list = [
                dict(xml_id=xid, values=vals, info=info, noupdate=noupdate)
                for xid, vals, info in batch
            ]
            batch.clear()
            batch_xml_ids.clear()

            # try to create in batch
            global_error_message = None
            try:
                with cr.savepoint():
                    recs = self._load_records(data_list, mode == 'update')
                    ids.extend(recs.ids)
                return
            except psycopg2.InternalError as e:
                # broken transaction, exit and hope the source error was already logged
                if not any(message['type'] == 'error' for message in messages):
                    info = data_list[0]['info']
                    messages.append(dict(info, type='error', message=_(u"Unknown database error: '%s'", e)))
                return
            except UserError as e:
                global_error_message = dict(data_list[0]['info'], type='error', message=str(e))
            except Exception:
                pass

            errors = 0
            # try again, this time record by record
            for i, rec_data in enumerate(data_list, 1):
                try:
                    rec = self._load_records([rec_data], mode == 'update')
                    cr.flush()  # make sure flush exceptions are raised here
                    ids.append(rec.id)
                except psycopg2.Warning as e:
                    savepoint.rollback()
                    info = rec_data['info']
                    messages.append(dict(info, type='warning', message=str(e)))
                except psycopg2.Error as e:
                    savepoint.rollback()
                    info = rec_data['info']
                    pg_error_info = {'message': self._sql_error_to_message(e)}
                    if e.diag.table_name == self._table:
                        e_fields = orm_schema.get_columns_from_sql_diagnostics(self.env.cr, e.diag, check_registry=True)
                        if len(e_fields) == 1:
                            pg_error_info['field'] = e_fields[0]
                    messages.append(dict(info, type='error', **pg_error_info))
                    # Failed to write, log to messages, rollback savepoint (to
                    # avoid broken transaction) and keep going
                    errors += 1
                except UserError as e:
                    savepoint.rollback()
                    info = rec_data['info']
                    messages.append(dict(info, type='error', message=str(e)))
                    errors += 1
                except Exception as e:  # noqa: BLE001
                    savepoint.rollback()
                    _logger.debug("Error while loading record", exc_info=True)
                    info = rec_data['info']
                    message = _('Unknown error during import: %(error_type)s: %(error_message)s', error_type=e.__class__, error_message=e)
                    moreinfo = _('Resolve other errors first')
                    messages.append(dict(info, type='error', message=message, moreinfo=moreinfo))
                    # Failed for some reason, perhaps due to invalid data supplied,
                    # rollback savepoint and keep going
                    errors += 1
                if errors >= 10 and (errors >= i / 10):
                    messages.append({
                        'type': 'warning',
                        'message': _("Found more than 10 errors and more than one error per 10 records, interrupted to avoid showing too many errors.")
                    })
                    break
            if errors > 0 and global_error_message and global_error_message not in messages:
                # If we cannot create the records 1 by 1, we display the error raised when we created the records simultaneously
                messages.insert(0, global_error_message)

        # make 'flush' available to the methods below, in the case where XMLID
        # resolution fails, for instance
        flush_recordset = self.with_context(import_flush=flush, import_cache=LRU(10000))

        # TODO: break load's API instead of smuggling via context?
        limit = self.env.context.get('_import_limit')
        if limit is None:
            limit = float('inf')
        extracted = flush_recordset._extract_records(fields, data, log=messages.append, limit=limit)

        converted = flush_recordset._convert_records(extracted, log=messages.append, savepoint=savepoint)

        info = {'rows': {'to': -1}}
        for id, xid, record, info in converted:
            if self.env.context.get('import_file') and self.env.context.get('import_skip_records'):
                if any([record.get(field) is None for field in self.env.context['import_skip_records']]):
                    continue
            if xid:
                xid = xid if '.' in xid else "%s.%s" % (current_module, xid)
                batch_xml_ids.add(xid)
            elif id:
                record['id'] = id
            batch.append((xid, record, info))

        flush()
        if any(message['type'] == 'error' for message in messages):
            savepoint.rollback()
            ids = False
        savepoint.close(rollback=False)

        nextrow = info['rows']['to'] + 1
        if nextrow < limit:
            nextrow = 0
        return {
            'ids': ids,
            'messages': messages,
            'nextrow': nextrow,
        }

    def _extract_records(self, field_paths, data, log=lambda a: None, limit=float('inf')):
        """ Generates record dicts from the data sequence.

        The result is a generator of dicts mapping field names to raw
        (unconverted, unvalidated) values.

        For relational fields, if sub-fields were provided the value will be
        a list of sub-records

        The following sub-fields may be set on the record (by key):

        * None is the display_name for the record (to use with name_create/name_search)
        * "id" is the External ID for the record
        * ".id" is the Database ID for the record
        """
        return orm_export._extract_records(self, field_paths, data, log, limit)

    @api.model
    def _convert_records(self, records, *, log=lambda a: None, savepoint):
        """ Converts records from the source iterable (recursive dicts of
        strings) into forms which can be written to the database (via
        ``self.create`` or ``(ir.model.data)._update``)

        :returns: a list of triplets of (id, xid, record)
        :rtype: list[(int|None, str|None, dict)]
        """
        return orm_export._convert_records(self, records, log=log, savepoint=savepoint)

    def _validate_fields(self, field_names: Iterable[str], excluded_names: Iterable[str] = ()) -> None:
        """ Invoke the constraint methods for which at least one field name is
        in ``field_names`` and none is in ``excluded_names``.
        """
        return orm_export._validate_fields(self, field_names, excluded_names)

    @api.model
    def default_get(self, fields: Sequence[str]) -> ValuesType:
        """Return default values for the fields in ``fields_list``. Default
        values are determined by the context, user defaults, user fallbacks
        and the model itself.

        :param fields: names of field whose default is requested
        :return: a dictionary mapping field names to their corresponding default values,
            if they have a default value.

        .. note::

            Unrequested defaults won't be considered, there is no need to return a
            value for fields whose names are not in `fields_list`.
        """
        defaults = {}
        parent_fields = defaultdict(list)
        self = self.browse()  # noqa: PLW0642
        ir_defaults = self.env['ir.default']._get_model_defaults(self._name)

        for name in fields:
            # 1. look up context
            key = 'default_' + name
            if key in self.env.context:
                defaults[name] = self.env.context[key]
                continue

            field = self._fields.get(name)
            if not field:
                continue

            # 2. look up default for non-company_dependent fields
            if not field.company_dependent and name in ir_defaults:
                defaults[name] = ir_defaults[name]
                continue

            # 3. look up field.default
            if field.default:
                defaults[name] = field.default(self)
                continue

            # 4. look up fallback for company_dependent fields
            if field.company_dependent and name in ir_defaults:
                defaults[name] = ir_defaults[name]
                continue

            # 5. delegate to parent model
            if field.inherited and self.has_field_access(field, 'write'):
                field = field.related_field
                parent_fields[field.model_name].append(field.name)

        # convert default values to the right format
        #
        # we explicitly avoid using _convert_to_write() for x2many fields,
        # because the latter leaves values like [(Command.LINK, 2),
        # (Command.LINK, 3)], which are not supported by the web client as
        # default values; stepping through the cache allows to normalize
        # such a list to [(Command.SET, 0, [2, 3])], which is properly
        # supported by the web client
        for fname, value in defaults.items():
            if fname in self._fields:
                field = self._fields[fname]
                if (
                    field.relational
                    and not self.env.su
                    and isinstance(value, Iterable)
                ):
                    # since the value will be converted into a SET, we still
                    # need to check permissions for these actions
                    for cmd in value:
                        command_code = cmd[0] if isinstance(cmd, (tuple, list)) and len(cmd) >= 2 else None
                        if command_code == Command.UPDATE:
                            updated_fields = cmd[2]
                        elif field.type == 'one2many' and command_code in (Command.LINK, Command.UNLINK):
                            updated_fields = (field.inverse_name,)
                        else:
                            updated_fields = None
                        if updated_fields is not None:
                            corecord = self.env[field.comodel_name].browse(cmd[1])
                            corecord.check_access('write')
                            for fname in updated_fields:
                                corecord.check_field_access(corecord._fields[fname], 'write')
                        elif command_code == Command.DELETE:
                            self.env[field.comodel_name].browse(cmd[1]).check_access('unlink')
                value = field.convert_to_cache(value, self)
                defaults[fname] = field.convert_to_write(value, self)

        # add default values for inherited fields
        for model, names in parent_fields.items():
            defaults.update(self.env[model].default_get(names))

        return defaults

    @api.model
    def _rec_name_fallback(self) -> str:
        # if self._rec_name is set, it belongs to self._fields
        return self._rec_name or 'id'

    @api.model
    @api.readonly
    def search_count(self, domain: DomainType, limit: int | None = None) -> int:
        """Return the number of records in the current model matching
        :ref:`the provided domain <reference/orm/domains>`.

        :param domain: :ref:`A search domain <reference/orm/domains>`. Use an empty
                     list to match all records.
        :param limit: maximum number of record to count (upperbound) (default: all)

        This is a high-level method, which should not be overridden. Its actual
        implementation is done by method :meth:`_search`.
        """
        query = self._search(domain, limit=limit)
        return len(query)

    @api.model
    @api.readonly
    def search(self, domain: DomainType, offset: int = 0, limit: int | None = None, order: str | None = None) -> Self:
        """Search for the records that satisfy the given ``domain``
        :ref:`search domain <reference/orm/domains>`.

        :param domain: :ref:`A search domain <reference/orm/domains>`. Use an empty
                     list to match all records.
        :param offset: number of results to ignore (default: none)
        :param limit: maximum number of records to return (default: all)
        :param order: sort string
        :returns: at most ``limit`` records matching the search criteria
        :raise AccessError: if user is not allowed to access requested information

        This is a high-level method, which should not be overridden. Its actual
        implementation is done by method :meth:`_search`.
        """
        return self.search_fetch(domain, [], offset=offset, limit=limit, order=order)

    @api.model
    @api.private
    @api.readonly
    def search_fetch(
        self,
        domain: DomainType,
        field_names: Sequence[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> Self:
        """Search for the records that satisfy the given ``domain``
        :ref:`search domain <reference/orm/domains>`, and fetch the given fields
        to the cache.  This method is like a combination of methods :meth:`search`
        and :meth:`fetch`, but it performs both tasks with a minimal number of
        SQL queries.

        :param domain: :ref:`A search domain <reference/orm/domains>`. Use an empty
                     list to match all records.
        :param field_names: a collection of field names to fetch, or ``None`` for
            all accessible fields marked with ``prefetch=True``
        :param offset: number of results to ignore (default: none)
        :param limit: maximum number of records to return (default: all)
        :param order: sort string
        :returns: at most ``limit`` records matching the search criteria
        :raise AccessError: if user is not allowed to access requested information
        """
        # first determine a query that satisfies the domain and access rules
        query = self._search(domain, offset=offset, limit=limit, order=order or self._order)

        if query.is_empty():
            # optimization: don't execute the query at all
            if not self.env.su:  # check access to fields
                self._determine_fields_to_fetch(field_names)
            return self.browse()

        fields_to_fetch = self._determine_fields_to_fetch(field_names)

        fetched = self._fetch_query(query, fields_to_fetch)
        if not self.env.su:
            self.env._add_to_access_cache(fetched)

        # force computation of fields
        for field_name in (field_names or ()):
            field = self._fields[field_name]
            if not field.store and any(field._cache_missing_ids(fetched)):
                fetched.mapped(field_name)

        return fetched

    #
    # display_name, name_create, name_search
    #

    @api.depends(lambda self: (self._rec_name,) if self._rec_name else ())
    def _compute_display_name(self):
        """Compute the value of the `display_name` field.

        The `display_name` field is a textual representation of the record.
        This method can be overridden to change the representation.  If needed,
        it can be made field-dependent using :attr:`~odoo.api.depends` and
        context-dependent using :attr:`~odoo.api.depends_context`.
        """
        if self._rec_name:
            convert = self._fields[self._rec_name].convert_to_display_name
            for record in self:
                record.display_name = convert(record[self._rec_name], record)
        else:
            for record in self:
                record.display_name = f"{record._name},{record.id}"

    @api.model
    def _search_display_name(self, operator, value):
        """
        Returns a domain that matches records whose display name matches the
        given ``name`` pattern when compared with the given ``operator``.
        This method is used to implement the search on the ``display_name``
        field, and can be overridden to change the search criteria.
        The default implementation searches the fields defined in `_rec_names_search`
        or `_rec_name`.
        """
        search_fnames = self._rec_names_search or ([self._rec_name] if self._rec_name else [])
        if not search_fnames:
            _logger.warning("Cannot search on display_name, no _rec_name or _rec_names_search defined on %s", self._name)
            # do not restrain anything
            return Domain.TRUE
        if operator.endswith('like') and not value and '=' not in operator:
            # optimize out the default criterion of ``like ''`` that matches everything
            # return all when operator is positive
            return Domain.FALSE if operator in Domain.NEGATIVE_OPERATORS else Domain.TRUE
        aggregator = Domain.AND if operator in Domain.NEGATIVE_OPERATORS else Domain.OR
        domains = []
        for field_name in search_fnames:
            # field_name may be a sequence of field names (partner_id.name)
            # retrieve the last field in the sequence
            model = self
            for fname in field_name.split('.'):
                if model is None:
                    raise ValueError(f"Traversing non-relational field in {self._name}._rec_names_search or {self._name}._rec_name")
                field = model._fields[fname]
                comodel_name = field.comodel_name if field.relational else None
                model = self.env.get(comodel_name) if comodel_name else None
            # depending on the operator, we may need to cast the value to the type of the field
            # ignore if we cannot convert
            if field.relational:
                # relational fields will search on the display_name
                domains.append([(field_name + '.display_name', operator, value)])
            elif operator.endswith('like'):
                domains.append([(field_name, operator, value)])
            elif isinstance(value, COLLECTION_TYPES):
                typed_value = []
                for v in value:
                    with contextlib.suppress(ValueError, TypeError):
                        typed_value.append(field.convert_to_write(v, self))
                domains.append([(field_name, operator, typed_value)])
            else:
                with contextlib.suppress(ValueError):
                    typed_value = field.convert_to_write(value, self)
                    domains.append([(field_name, operator, typed_value)])
                continue
            with contextlib.suppress(ValueError, TypeError):
                # ignore that case if the value doesn't match the field type
                domains.append([(field_name, operator, field.convert_to_write(value, self))])
        return aggregator(domains)

    @api.model
    def name_create(self, name: str) -> tuple[int, str]:
        """Create a new record by calling :meth:`~.create` with only one value
        provided: the display name of the new record.

        The new record will be initialized with any default values
        applicable to this model, or provided through the context. The usual
        behavior of :meth:`~.create` applies.

        :param name: display name of the record to create
        :return: the (id, display_name) pair value of the created record
        """
        if not self._rec_name:
            raise NotImplementedError(f"Cannot name_create on {self._name}")
        record = self.create({self._rec_name: name})
        return record.id, record.display_name

    @api.model
    @api.readonly
    def name_search(
        self,
        name: str = '',
        domain: DomainType | None = None,
        operator: str = 'ilike',
        limit: int = 100,
    ) -> list[tuple[int, str]]:
        """Search for records that have a display name matching the given
        ``name`` pattern when compared with the given ``operator``, while also
        matching the optional search domain (``domain``).

        This is used for example to provide suggestions based on a partial
        value for a relational field. Should usually behave as the reverse of
        ``display_name``, but that is not guaranteed.

        This method is equivalent to calling :meth:`~.search` with a search
        domain based on ``display_name`` and mapping id and display_name on
        the resulting search.

        :param name: the name pattern to match
        :param domain: search domain (see :meth:`~.search` for syntax),
                       specifying further restrictions
        :param operator: domain operator for matching ``name``,
                         such as ``'like'`` or ``'='``.
        :param limit: max number of records to return
        :return: list of pairs ``(id, display_name)`` for all matching records.
        """
        domain = Domain('display_name', operator, name) & Domain(domain or Domain.TRUE)
        records = self.search_fetch(domain, ['display_name'], limit=limit)
        return [(record.id, record.display_name) for record in records.sudo()]

    @api.model
    def _add_missing_default_values(self, values: ValuesType) -> ValuesType:
        # avoid overriding inherited values when parent is set
        avoid_models = set()
        avoid_models_stack = [self]
        while avoid_models_stack:
            for parent_mname, parent_fname in avoid_models_stack.pop()._inherits.items():
                if parent_fname in values:
                    avoid_models.add(parent_mname)
                else:
                    # manage the case where an ancestor parent field is set
                    avoid_models_stack.append(self.env[parent_mname])

        def avoid(field):
            # check whether the field is inherited from one of avoid_models
            if avoid_models:
                while field.inherited:
                    field = field.related_field
                    if field.model_name in avoid_models:
                        return True
            return False

        # compute missing fields
        missing_defaults = [
            name
            for name, field in self._fields.items()
            if name not in values
            if not avoid(field)
        ]

        if missing_defaults:
            # override defaults with the provided values, never allow the other way around
            defaults = self.default_get(missing_defaults)
            for name, value in defaults.items():
                if self._fields[name].type == 'many2many' and value and isinstance(value[0], int):
                    # convert a list of ids into a list of commands
                    defaults[name] = [Command.set(value)]
                elif self._fields[name].type == 'one2many' and value and isinstance(value[0], dict):
                    # convert a list of dicts into a list of commands
                    defaults[name] = [Command.create(x) for x in value]
            defaults.update(values)

        else:
            defaults = values

        # delegate the default properties to the properties field
        for field in self._fields.values():
            if field.type == 'properties':
                defaults[field.name] = field._add_default_values(self.env, defaults)

        return defaults

    @api.model
    def _read_grouping_sets(
        self,
        domain: DomainType,
        grouping_sets: Sequence[Sequence[str]],
        aggregates: Sequence[str] = (),
        order: str | None = None,
    ) -> list[list[tuple]]:
        """ Performs multiple aggregations with different groupings in a single query if possible.

        This method uses SQL `GROUPING SETS` as a more advanced and efficient
        alternative to calling :meth:`~._read_group` multiple times with different
        `groupby` parameters. It allows you to get different levels of aggregated
        data in one database round-trip.
        Note that for many2many multiple SQL might be needed because of the deduplicated rows.

        :param domain: :ref:`A search domain <reference/orm/domains>` to filter records before grouping
        :param grouping_sets: A list of `groupby` specifications. Each inner list
                              is a set of fields to group by and is equivalent to the
                              `groupby` parameter of the :meth:`~._read_group` method.
                              For example: `[['partner_id'], ['partner_id', 'state']]`.
        :param aggregates: list of aggregates specification.
                Each element is `'field:agg'` (aggregate field with aggregation function `'agg'`).
                The possible aggregation functions are the ones provided by
                `PostgreSQL <https://www.postgresql.org/docs/current/static/functions-aggregate.html>`_,
                `'count_distinct'` with the expected meaning and `'recordset'` to act like `'array_agg'`
                converted into a recordset.
        :param order: optional ``order by`` specification, for
                overriding the natural sort ordering of the groups,
                see also :meth:`~.search`.
        :return: A list of lists of tuples. The outer list's structure mirrors the
                 input `grouping_sets`. Each inner list contains the results for one
                 grouping specification. Each tuple within an inner list contains the
                 values for the grouped fields, followed by the aggregate values,
                 in the order they were specified.

                 For example, given:
                 - `grouping_sets=[['foo'], ['foo', 'bar']]`
                 - `aggregates=['baz:sum']`

                 The returned structure would be:
                  ::

                    [
                        # Results for ['foo']
                        [(foo1_val, baz_sum_1), (foo2_val, baz_sum_2), ...],
                        # Results for ['foo', 'bar']
                        [(foo1_val, bar1_val, baz_sum_3), (foo2_val, bar2_val, baz_sum_4), ...],
                    ]

        :raise AccessError: if user is not allowed to access requested information
        """
        return orm_grouping._read_grouping_sets(self, domain, grouping_sets, aggregates, order)

    @typing.final
    @api.model
    def read_group(
        self,
        domain: DomainType,
        groupby: Sequence[str] = (),
        aggregates: Sequence[str] = (),
        having: DomainType = (),
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[tuple]:
        """ Get fields aggregations specified by ``aggregates`` grouped by the given ``groupby``
        fields where record are filtered by the ``domain``.

        :param domain: :ref:`A search domain <reference/orm/domains>`. Use an empty
                list to match all records.
        :param groupby: list of groupby descriptions by which the records will be grouped.
                A groupby description is either a field (then it will be grouped by that field)
                or a string `'field:granularity'`. Right now, the only supported granularities
                are `'day'`, `'week'`, `'month'`, `'quarter'` or `'year'`, and they only make sense for
                date/datetime fields.
                Additionally integer date parts are also supported:
                `'year_number'`, `'quarter_number'`, `'month_number'`, `'iso_week_number'`, `'day_of_year'`, `'day_of_month'`,
                'day_of_week', 'hour_number', 'minute_number' and 'second_number'.
        :param aggregates: list of aggregates specification.
                Each element is `'field:agg'` (aggregate field with aggregation function `'agg'`).
                The possible aggregation functions are the ones provided by
                `PostgreSQL <https://www.postgresql.org/docs/current/static/functions-aggregate.html>`_,
                `'count_distinct'` with the expected meaning and `'recordset'` to act like `'array_agg'`
                (with ids deduplicated and without NULL values).
        :param having: A domain where the valid "fields" are the aggregates.
        :param offset: optional number of groups to skip
        :param limit: optional max number of groups to return
        :param order: optional ``order by`` specification, for
                overriding the natural sort ordering of the groups,
                see also :meth:`~.search`.
        :return: list of tuples containing in the order the groups values and aggregates values (flatten):
                `[(groupby_1_value, ... , aggregate_1_value_aggregate, ...), ...]`.

        :raise AccessError: if user is not allowed to access requested information
        """
        return orm_grouping.read_group(self, domain, groupby, aggregates, having, offset, limit, order)

    @api.model
    def _read_group(
        self,
        domain: DomainType,
        groupby: Sequence[str] = (),
        aggregates: Sequence[str] = (),
        having: DomainType = (),
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[tuple]:
        """ Get fields aggregations specified by ``aggregates`` grouped by the given ``groupby``
        fields where record are filtered by the ``domain``.

        :param domain: :ref:`A search domain <reference/orm/domains>`.
        :param groupby: list of groupby descriptions by which the records will be grouped.
                A groupby description is either a field (then it will be grouped by that field)
                or a string `'field:granularity'`. Right now, the only supported granularities
                are `'day'`, `'week'`, `'month'`, `'quarter'` or `'year'`, and they only make sense for
                date/datetime fields.
                Additionally integer date parts are also supported:
                `'year_number'`, `'quarter_number'`, `'month_number'`, `'iso_week_number'`, `'day_of_year'`, `'day_of_month'`,
                'day_of_week', 'hour_number', 'minute_number' and 'second_number'.
        :param aggregates: list of aggregates specification.
                Each element is `'field:agg'` (aggregate field with aggregation function `'agg'`).
                The possible aggregation functions are the ones provided by
                `PostgreSQL <https://www.postgresql.org/docs/current/static/functions-aggregate.html>`_,
                `'count_distinct'` with the expected meaning and `'recordset'` to act like `'array_agg'`
                converted into a recordset.
        :param having: A domain where the valid "fields" are the aggregates.
        :param offset: optional number of groups to skip
        :param limit: optional max number of groups to return
        :param order: optional ``order by`` specification, for
                overriding the natural sort ordering of the groups,
                see also :meth:`~.search`.
        :return: list of tuples containing in the order the groups values and aggregates values (flatten):
                `[(groupby_1_value, ... , aggregate_1_value_aggregate, ...), ...]`.
                If group is related field, the value of it will be a recordset (with a correct prefetch set).

        :raise AccessError: if user is not allowed to access requested information
        """
        return orm_grouping._read_group(self, domain, groupby, aggregates, having, offset, limit, order)

    def _read_group_select(self, table: TableSQL, aggregate_spec: str) -> SQL:
        """ Return <SQL expression> corresponding to the given aggregation.
        The method also checks whether the fields used in the aggregate are
        accessible for reading.
        """
        return orm_grouping._read_group_select(self, table, aggregate_spec)

    def _read_group_groupby(self, table: TableSQL, groupby_spec: str) -> SQL:
        """ Return <SQL expression> corresponding to the given groupby element.
        The method also checks whether the fields used in the groupby are
        accessible for reading.
        """
        return orm_grouping._read_group_groupby(self, table, groupby_spec)

    def _read_group_having(self, table: TableSQL, having_domain: list) -> SQL:
        """ Return <SQL expression> corresponding to the having domain.
        """
        return orm_grouping._read_group_having(self, table, having_domain)

    def _read_group_orderby(self, table: TableSQL, order: str, groupby_terms: dict[str, SQL]) -> SQL:
        """ Return (<SQL expression>, <SQL expression>)
        corresponding to the given order and groupby terms.

        Note: this method may change groupby_terms

        :param table: The table of the query we are building
        :param order: the order specification
        :param groupby_terms: the group by terms mapping ({spec: sql_expression})
        """
        return orm_grouping._read_group_orderby(self, table, order, groupby_terms)

    @api.model
    def _read_group_empty_value(self, spec):
        """ Return the empty value corresponding to the given groupby spec or aggregate spec. """
        return orm_grouping._read_group_empty_value(self, spec)

    def _read_group_postprocess_groupby(self, groupby_spec, raw_values):
        """ Convert the given values of ``groupby_spec``
        from PostgreSQL to the format returned by method ``_read_group()``.

        The formatting rules can be summarized as:
        - groupby values of relational fields are converted to recordsets with a correct prefetch set;
        - NULL values are converted to empty values corresponding to the given aggregate.
        """
        return orm_grouping._read_group_postprocess_groupby(self, groupby_spec, raw_values)

    def _read_group_postprocess_aggregate(self, aggregate_spec, raw_values):
        """ Convert the given values of ``aggregate_spec``
        from PostgreSQL to the format returned by method ``_read_group()``.

        The formatting rules can be summarized as:
        - 'recordset' aggregates are turned into recordsets with a correct prefetch set;
        - NULL values are converted to empty values corresponding to the given aggregate.
        """
        return orm_grouping._read_group_postprocess_aggregate(self, aggregate_spec, raw_values)

    @api.model
    def _read_group_expand_full(self, groups: ModelType, domain: DomainType) -> ModelType:
        """Extend the group to include all target records by default."""
        return orm_grouping._read_group_expand_full(self, groups, domain)

    @typing.final
    def _field_to_sql(self, alias: str, field_expr: str, query: (Query | None) = None) -> SQL:
        """ Return an :class:`SQL` object that represents the value of the given
        field from the given table alias, in the context of the given query.
        The method also checks that the field is accessible for reading.

        The query object is necessary for inherited fields, many2one fields and
        properties fields, where joins are added to the query.
        """
        return orm_grouping._field_to_sql(self, alias, field_expr, query)

    @api.model
    def get_property_definition(self, full_name: str) -> dict:
        """Return the definition of the given property.

        :param full_name: Name of the field / property
            (e.g. "property.integer")
        """
        return orm_properties.get_property_definition(self, full_name)

    def _parent_store_compute(self) -> None:
        """ Compute parent_path field from scratch. """
        return orm_parent_store._parent_store_compute(self)

    def _check_removed_columns(self, log=False):
        return orm_schema.check_removed_columns(self, log=log)

    @deprecated("Since 20.0, field initialization is defined in Field.init_storage")
    def _init_column(self, column_name):
        """ Initialize the value of the given column for existing rows. """
        field = self._fields[column_name]
        columns = sql.table_columns(self.env.cr, self._table)
        field.update_db(self, columns)

    @api.ormcache()
    @deprecated("Since 20.0, _table_has_rows is removed")
    def _table_has_rows(self) -> bool:
        """ Return whether the model's table has rows. This method should only
            be used when updating the database schema (:meth:`~._auto_init`).
        """
        self.env.cr.execute(SQL('SELECT 1 FROM %s LIMIT 1', SQL.identifier(self._table)))
        return bool(self.env.cr.rowcount)

    def _auto_init(self) -> None:
        """ Initialize the database schema of ``self``:
            - create the corresponding table,
            - create/update the necessary columns/tables for fields,
            - initialize new columns on existing rows,
            - add the SQL constraints given on the model,
            - add the indexes on indexed fields,

            Also prepare post-init stuff to:
            - add foreign key constraints,
            - reflect models, fields, relations and constraints,
            - mark fields to recompute on existing records.

            Note: you should not override this method. Instead, you can modify
            the model's database schema by overriding method :meth:`~.init`,
            which is called right after this one.
        """
        return orm_schema.auto_init(self)

    @api.private
    def init(self) -> None:
        """ This method is called after :meth:`~._auto_init`, and may be
            overridden to create or modify a model's database schema.
        """

    def _check_parent_path(self):
        return orm_schema.check_parent_path(self)

    def _add_sql_constraints(self):
        """ Modify this model's database table objects so they match the one
        in _table_objects.
        """
        return orm_schema.add_sql_constraints(self)

    @api.model
    def _sql_error_to_message(self, exc: psycopg2.Error) -> str:
        """ Convert a database exception to a user error message depending on the model.

        Note that the cursor on self has to be in a valid state.
        """
        return orm_schema.sql_error_to_message(self, exc=exc)

    @api.model
    def _sql_error_to_message_generic(self, exc: psycopg2.Error) -> str:
        """ Convert a database exception to a generic user error message. """
        return orm_schema.sql_error_to_message_generic(self, exc=exc)

    @api.model
    def fields_get(self, allfields: Collection[str] | None = None, attributes: Collection[str] | None = None) -> dict[str, ValuesType]:
        """ Return the definition of each field.

        The returned value is a dictionary (indexed by field name) of
        dictionaries. The _inherits'd fields are included. The string, help,
        and selection (if present) attributes are translated.

        :param allfields: fields to document, all if empty or not provided
        :param attributes: attributes to return for each field, all if empty or not provided
        :return: dictionary mapping field names to a dictionary mapping attributes to values.
        """
        res = {}
        for fname, field in self._fields.items():
            if allfields and fname not in allfields:
                continue
            if not self.has_field_access(field, 'read'):
                continue

            description = field.get_description(self.env, attributes=attributes)
            if 'readonly' in description:
                description['readonly'] = description['readonly'] or not self.has_field_access(field, 'write')
            res[fname] = description

        return res

    @api.model
    def has_field_access(self, field: Field, operation: typing.Literal['read', 'write']) -> bool:
        """ Determine whether the user access rights on the given field for the given operation.

        :param field: the field to check
        :param operation: one of ``read``, ``write``
        :return: whether the field is accessible
        """
        return orm_access.has_field_access(self, field, operation)

    @api.model
    def _has_field_access(self, field: Field, operation: typing.Literal['read', 'write']) -> bool:
        """ Actual implementation of :meth:`has_field_access`.
        You may override this method to customize the access to fields.

        :param field: the field to check
        :param operation: one of ``read``, ``write``
        :return: whether the field is accessible
        """
        if not field.groups or self.env.su:
            return True
        if field.groups == NO_ACCESS:
            return False
        return self.env.user.has_groups(field.groups)

    @api.model
    def check_field_access(self, field: Field, operation: typing.Literal['read', 'write']) -> None:
        """Check the user access rights on the given field.

        :param field: the field to check
        :param operation: one of ``read``, ``write``
        :raise AccessError: if the user is not allowed to access the provided field
        """
        return orm_access.check_field_access(self, field, operation)

    @api.model
    @deprecated("Since 20.0, use check_field_access()")
    def _check_field_access(self, field: Field, operation: typing.Literal['read', 'write']) -> None:
        return self.check_field_access(field, operation)

    @api.readonly
    def read(self, fields: Sequence[str] | None = None, load: str = '_classic_read') -> list[ValuesType]:
        """Read the requested fields for the records in ``self``, and return their
        values as a list of dicts.

        :param fields: field names to return (default is all fields)
        :param load: loading mode, currently the only option is to set to
            ``None`` to avoid loading the `display_name` of m2o fields
        :return: a list of dictionaries mapping field names to their values,
                 with one dictionary per record
        :raise AccessError: if user is not allowed to access requested information
        :raise ValueError: if a requested field does not exist

        This is a high-level method that is not supposed to be overridden. In
        order to modify how fields are read from database, see methods
        :meth:`_fetch_query` and :meth:`_read_format`.
        """
        if not fields:
            fields = list(self.fields_get(attributes=()))
        elif not self and not self.env.su:  # check field access, otherwise done during fetch()
            self._determine_fields_to_fetch(fields)
        self._origin.fetch(fields)
        return self._read_format(fnames=fields, load=load)

    def update_field_translations(
        self,
        field_name: str,
        translations: dict[str, str | typing.Literal[False] | dict[str, str]],
        source_lang: str = '',
    ) -> bool:
        """ Update the translations for a given field

        See 'self._update_field_translations' docstring for details.
        """
        return orm_translations.update_field_translations(self, field_name, translations, source_lang)

    def _update_field_translations(
        self,
        field_name: str,
        translations: dict[str, str | typing.Literal[False] | dict[str, str]],
        digest: Callable[[str], str] | None = None,
        source_lang: str = '',
    ) -> bool:
        """ Update the translations for a given field, with support for handling
        old terms using an optional digest function.

        :param field_name: The name of the field to update.
        :param translations: The translations to apply.
            If ``field.translate`` is ``True``, the dictionary should be in the
            format::

                {lang: new_value}

            where ``new_value`` can either be:

            * a ``str``, in which case the new translation for the specified
              language.
            * ``False``, in which case it removes the translation for the
                specified language and falls back to the latest en_US value.

            If ``field.translate`` is a callable, the dictionary should be in
            the format::

                {lang: {old_source_lang_term: new_term}}

            or (when ``digest`` is callable)::

                {lang: {digest(old_source_lang_term): new_term}}.

            where ``new_term`` can either be:

            * a non-empty ``str``, in which case the new translation of
              ``old_term`` for the specified language.
            * ``False`` or ``''``, in which case it removes the translation for
                the specified language and falls back to the old
                ``source_lang_term``.

        :param digest: An optional function to generate identifiers for old terms.
        :param source_lang: The language of ``old_source_lang_term`` in
            translations. Assumes ``'en_US'`` when it is not set / empty.
        """
        self.ensure_one()

        self.check_access('write')
        field = self._fields[field_name]
        self.check_field_access(field, 'write')

        valid_langs = set(code for code, _ in self.env['res.lang'].get_installed()) | {'en_US'}
        source_lang = source_lang or 'en_US'
        missing_langs = (set(translations) | {source_lang}) - valid_langs
        if missing_langs:
            raise UserError(
                _("The following languages are not activated: %(missing_names)s",
                missing_names=', '.join(missing_langs))
            )

        if not field.translate:
            return False  # or raise error

        if not field.store and not field.related and field.compute:
            # a non-related non-stored computed field cannot be translated, even if it has inverse function
            return False

        # Strictly speaking, a translated related/computed field cannot be stored
        # because the compute function only support one language
        # `not field.store` is a redundant logic.
        # But some developers store translated related fields.
        # In these cases, only all translations of the first stored translation field will be updated
        # For other stored related translated field, the translation for the flush language will be updated
        if field.related and not field.store:
            related_path, field_name = field.related.rsplit(".", 1)
            return self.mapped(related_path)._update_field_translations(field_name, translations, digest)

        if field.translate is True:
            # falsy values (except emtpy str) are used to void the corresponding translation
            if any(translation and not isinstance(translation, str) for translation in translations.values()):
                raise UserError(_("Translations for model translated fields only accept falsy values and str"))
            value_en = translations.get('en_US', True)
            if not value_en and value_en != '':
                translations.pop('en_US')
            if not translations:
                return False

            drop_langs = {lang for lang, value in translations.items() if not isinstance(value, str)}
            translations = {lang: value for lang, value in translations.items() if lang not in drop_langs}
            if drop_langs:
                stored_translations = self._get_stored_translations(field_name)
                if field.type == 'html':
                    translations = {lang: field._validated_cache_value(value, self.env) for lang, value in translations.items()}
                if stored_translations is None:
                    if not translations:
                        return False
                    write_value = StoredTranslations({
                        'en_US': translations.get(self.env.lang or 'en_US', next(iter(translations.values()))),
                        **translations,
                    })
                else:
                    write_value = StoredTranslations({
                        **{lang: value for lang, value in stored_translations.items() if lang not in drop_langs},
                        **translations,
                    })
            else:
                write_value = translations
            self[field_name] = write_value
            return True
        else:
            stored_translations = self._get_stored_translations(field_name)
            if not stored_translations:
                return False
            write_value = stored_translations.translated(
                self.env, field, source_lang, translations, digest=digest,
                delay_translations=bool(self.env.context.get('delay_translations')),
            )
            self[field_name] = write_value
        return True

    def get_field_translations(self, field_name: str, langs: Collection[str] | None = None) -> tuple[list[dict[str, str]], dict[str, typing.Any]]:
        """ Get model/model_term translations for records.

        :param field_name: field name
        :param langs: languages

        :return: (translations, context) where
            translations: list of dicts like [{"lang": lang, "source": source_term, "value": value_term}]
            context: {"translation_type": "text"/"char", "translation_show_source": True/False}
        """
        return orm_translations.get_field_translations(self, field_name, langs)

    def _get_stored_translations(self, field_name: str) -> StoredTranslations | None:
        """Return the cached StoredTranslations for ``field_name``, or ``None`` if the column is NULL.

        For non-stored related fields, follows the related path to the first stored
        translated field.
        """
        self.ensure_one()
        field = self._fields[field_name]
        record = self
        while field.related and not field.store:
            record = record.mapped(field.related.rsplit('.', 1)[0])[:1]
            if not record:
                return None
            field = field.related_field
        return field._get_stored_translations(record)

    def _get_base_lang(self) -> str:
        """ Return the base language of the record. """
        return orm_translations._get_base_lang(self)

    def _read_format(self, fnames: Sequence[str], load: str = '_classic_read') -> list[ValuesType]:
        """Return a list of dictionaries mapping field names to their values,
        with one dictionary per record that exists.

        The output format is the one expected from the `read` method, which uses
        this method as its implementation for formatting values.

        For the properties fields, call convert_to_read_multi instead of convert_to_read
        to prepare everything (record existences, display name, etc) in batch.

        The current method is different from `read` because it retrieves its
        values from the cache without doing a query when it is avoidable.
        """
        return orm_translations._read_format(self, fnames, load)

    def _fetch_field(self, field: Field) -> None:
        """ Read from the database in order to fetch ``field`` (:class:`Field`
            instance) for ``self`` in cache.
        """
        # determine which fields can be prefetched
        if field.prefetch and self.env.context.get('prefetch_fields', len(self) < BIG_RECORDSET_SIZE):
            fnames = [
                name
                for name, f in self._fields.items()
                # select fields with the same prefetch group
                if f.prefetch == field.prefetch
                # discard fields with groups that the user may not access
                if self.has_field_access(f, 'read')
            ]
            if field.name not in fnames:
                fnames.append(field.name)
        else:
            fnames = [field.name]
        self.fetch(fnames)

    @api.private
    def fetch(self, field_names: Collection[str] | None = None) -> None:
        """ Make sure the given fields are in memory for the records in ``self``,
        by fetching what is necessary from the database.  Non-stored computed
        fields are computed, and their dependencies are fetched with stored
        fields. This method should be called to optimize code.

        :param field_names: a collection of field names to fetch or compute, or
            ``None`` for all accessible fields marked with ``prefetch=True``
        :raise AccessError: if user is not allowed to access requested information

        This method is implemented thanks to methods :meth:`_search` and
        :meth:`_fetch_query`, and should not be overridden.
        """
        self = self._origin  # noqa: PLW0642 filtered out new records
        if not self or not (field_names is None or field_names):
            return

        fields_to_fetch = self._determine_fields_to_fetch(field_names, ignore_when_in_cache=True)
        queries = []
        # first determine a query that satisfies the domain and access rules
        if any(field.column_type for field in fields_to_fetch):
            for ids in split_every(BIG_RECORDSET_SIZE, self._ids):
                queries.append(self._search([('id', 'in', ids)], active_test=False))
        else:
            try:
                self.check_access('read')
            except MissingError:
                # Method fetch() should never raise a MissingError, but method
                # check_access() can, because it must read fields on self.
                # So we restrict 'self' to existing records (to avoid an extra
                # exists() at the end of the method).
                self = self.exists()
                self.check_access('read')
            if not fields_to_fetch:
                return
            # The query is split into domains of BIG_RECORDSET_SIZE so no one
            # query would have a domain large enough to spill to disk and slow
            # the transaction
            for ids in split_every(BIG_RECORDSET_SIZE, self._ids):
                queries.append(self.browse(ids)._as_query(ordered=False))

        # fetch the fields
        fetched = self.browse().union(
            self._fetch_query(query, fields_to_fetch)
            for query in queries
        )
        env = self.env
        if not env.su:
            env._add_to_access_cache(fetched)

        # force computation of fields
        for field_name in (field_names or ()):
            field = self._fields[field_name]
            if not field.store and any(field._cache_missing_ids(fetched)):
                fetched.mapped(field_name)

        # possibly raise exception for the records that could not be read
        if not env.su and fetched != self:
            forbidden = (self - fetched).exists()
            if not forbidden:
                return
            # Given that we have a cache of read permissions, the record may be
            # inaccessible from the query, however it was marked as accessible.
            # In such a case, read the fields in sudo.
            if forbidden.has_access('read'):
                self.sudo().fetch(field_names)
            else:
                # avoid cache pollution
                forbidden.invalidate_recordset([f.name for f in fields_to_fetch])
                domain = self._access_domain('read')
                raise forbidden._make_access_error_message('read', domain)  # noqa: EM101

    def _determine_fields_to_fetch(
            self,
            field_names: Collection[str] | None = None,
            ignore_when_in_cache: bool = False,
        ) -> list[Field]:
        """
        Return the fields to fetch from database among the given field names,
        and following the dependencies of computed fields. The method is used
        by :meth:`fetch` and :meth:`search_fetch`.

        :param field_names: the collection of requested fields, or ``None`` for
            all accessible fields marked with ``prefetch=True``
        :param ignore_when_in_cache: whether to ignore fields that are alreay in cache for ``self``
        :return: the list of fields that must be fetched
        :raise AccessError: when trying to fetch fields to which the user does not have access
        """
        if field_names is None:
            return [
                field
                for field in self._fields.values()
                if field.prefetch is True and self.has_field_access(field, 'read')
            ]

        if not field_names:
            return []

        fields_to_fetch: list[Field] = []
        fields_todo = deque[Field]()
        fields_done = {self._fields['id']}  # trick: ignore 'id'
        for field_name in field_names:
            try:
                field = self._fields[field_name]
            except KeyError as e:
                raise ValueError(f"Invalid field {field_name!r} on {self._name!r}") from e
            self.check_field_access(field, 'read')
            fields_todo.append(field)

        while fields_todo:
            field = fields_todo.popleft()
            if field in fields_done:
                continue
            fields_done.add(field)
            if ignore_when_in_cache and not any(field._cache_missing_ids(self)):
                # field is already in cache: don't fetch it
                continue
            if field.store:
                fields_to_fetch.append(field)
            else:
                # optimization: fetch field dependencies
                for dotname in self.pool.field_depends[field]:
                    dep_field = self._fields[dotname.split('.', 1)[0]]
                    if (
                        (not dep_field.store or dep_field.prefetch is True)
                        and self.has_field_access(dep_field, 'read')
                    ):
                        fields_todo.append(dep_field)

        return fields_to_fetch

    def _fetch_query(self, query: Query, fields: Sequence[Field]) -> Self:
        """ Fetch the given fields (iterable of :class:`Field` instances) from
        the given query, put them in cache, and return the fetched records.

        This method may be overridden to change what fields to actually fetch,
        or to change the values that are put in cache.
        """

        # determine columns fields and those with their own read() method
        column_fields: OrderedSet[Field] = OrderedSet()
        other_fields: OrderedSet[Field] = OrderedSet()
        for field in fields:
            if field.name == 'id':
                continue
            assert field.store or field.compute_sql
            (column_fields if field.column_type else other_fields).add(field)

        if column_fields:
            # the query may involve several tables: we need fully-qualified names
            sql_terms = [SQL.identifier(self._table, 'id')]
            for field in column_fields:
                sql = query.table[field.name]
                # flushing is necessary to retrieve the en_US value of fields without a translation
                # otherwise, re-create the SQL without flushing
                if not field.translate:
                    to_flush = (f for f in sql._sql_tuple[2] if f != field)
                    sql = SQL("%s", sql, to_flush=to_flush)
                sql_terms.append(sql)

            # select the given columns from the rows in the query
            rows = self.env.execute_query(query.select(*sql_terms))

            if not rows:
                return self.browse()

            # rows = [(id1, a1, b1), (id2, a2, b2), ...]
            # column_values = [(id1, id2, ...), (a1, a2, ...), (b1, b2, ...)]
            column_values = zip(*rows)
            ids = next(column_values)
            fetched = self.browse(ids)

            # If we assume that the value of a pending update is in cache, we
            # can avoid flushing pending updates if the fetched values do not
            # overwrite values in cache.
            for field, values in zip(column_fields, column_values, strict=True):
                # store values in cache, but without overwriting
                field._insert_cache(fetched, values)
        else:
            fetched = self.browse(query)

        # process non-column fields
        if fetched:
            for field in other_fields:
                field.read(fetched)

        return fetched

    def get_metadata(self) -> list[ValuesType]:
        """Return some metadata about the given records.

        :returns: list of ownership dictionaries for each requested record with the following keys:

            * id: object id
            * create_uid: user who created the record
            * create_date: date when the record was created
            * write_uid: last user who changed the record
            * write_date: date of the last change to the record
            * xmlid: XML ID to use to refer to this record (if there is one), in format ``module.name``
            * xmlids: list of dict with xmlid in format ``module.name``, and noupdate as boolean
            * noupdate: A boolean telling if the record will be updated or not
        """

        IrModelData = self.env['ir.model.data'].sudo()
        if self._log_access:
            res = self.read(LOG_ACCESS_COLUMNS)
        else:
            res = [{'id': x} for x in self.ids]


        xml_data = defaultdict(list)
        imds = IrModelData.search_read(
            [('model', '=', self._name), ('res_id', 'in', self.ids)],
            ['res_id', 'noupdate', 'module', 'name'],
            order='id DESC'
        )
        for imd in imds:
            xml_data[imd['res_id']].append({
                'xmlid': "%s.%s" % (imd['module'], imd['name']),
                'noupdate': imd['noupdate'],
            })

        for r in res:
            main = xml_data.get(r['id'], [{}])[-1]
            r['xmlid'] = main.get('xmlid', False)
            r['noupdate'] = main.get('noupdate', False)
            r['xmlids'] = xml_data.get(r['id'], [])[::-1]
        return res

    def get_base_url(self) -> str:
        """ Return rooturl for a specific record.

        By default, it returns the ir.config.parameter of base_url
        but it can be overridden by model.

        :return: the base url for this record
        """
        if len(self) > 1:
            raise ValueError("Expected singleton or no record: %s" % self)
        return self.env['ir.config_parameter'].sudo().get_str('web.base.url')

    def _check_company_domain(self, companies) -> Domain:
        """Domain to be used for company consistency between records regarding this model.

        :param companies: the allowed companies for the related record
        :type companies: BaseModel or list or tuple or int or unquote
        """
        if not companies:
            return Domain('company_id', '=', False)
        if isinstance(companies, unquote):
            return Domain('company_id', 'in', unquote(f'{companies} + [False]'))
        return Domain('company_id', 'in', to_record_ids(companies) + [False])

    def _check_company(self, fnames=None):
        """ Check the companies of the values of the given field names.

        :param list fnames: names of relational fields to check
        :raises UserError: if the `company_id` of the value of any field is not
            in `[False, self.company_id]` (or `self` if
            :class:`~odoo.addons.base.models.res_company`).

        For :class:`~odoo.addons.base.models.res_users` relational fields,
        verifies record company is in `company_ids` fields.

        User with main company A, having access to company A and B, could be
        assigned or linked to records in company B.
        """
        if fnames is None or {'company_id', 'company_ids'} & set(fnames):
            fnames = self._fields

        regular_fields = []
        property_fields = []
        for name in fnames:
            field = self._fields[name]
            if field.relational and field.check_company:
                if not field.company_dependent:
                    regular_fields.append(name)
                else:
                    property_fields.append(name)

        if not (regular_fields or property_fields):
            return

        inconsistencies = []
        for record in self:
            # The first part of the check verifies that all records linked via relation fields are compatible
            # with the company of the origin document, i.e. `self.account_id.company_id == self.company_id`
            if regular_fields:
                if self._name == 'res.company':
                    companies = record
                elif 'company_id' in self:
                    companies = record.company_id
                elif 'company_ids' in self:
                    companies = record.company_ids
                else:
                    _logger.warning(_(
                        "Skipping a company check for model %(model_name)s. Its fields %(field_names)s are set as company-dependent, "
                        "but the model doesn't have a `company_id` or `company_ids` field!",
                        model_name=self._name, field_names=regular_fields
                    ))
                    continue
                for name in regular_fields:
                    corecords = record.sudo()[name]
                    if corecords:
                        domain = corecords._check_company_domain(companies)
                        if domain and corecords != corecords.with_context(active_test=False).filtered_domain(domain):
                            inconsistencies.append((record, name, corecords))
            # The second part of the check (for property / company-dependent fields) verifies that the records
            # linked via those relation fields are compatible with the company that owns the property value, i.e.
            # the company for which the value is being assigned, i.e:
            #      `self.property_account_payable_id.company_id == self.env.company
            company = self.env.company
            for name in property_fields:
                corecords = record.sudo()[name]
                if corecords:
                    domain = corecords._check_company_domain(company)
                    if domain and corecords != corecords.with_context(active_test=False).filtered_domain(domain):
                        inconsistencies.append((record, name, corecords))

        if inconsistencies:
            lines = [_("Uh-oh! You’ve got some company inconsistencies here:")]
            company_msg = _lt("- Record is company “%(company)s” while “%(field)s” (%(fname)s: %(values)s) belongs to another company.")
            record_msg = _lt("- “%(record)s” belongs to company “%(company)s” while “%(field)s” (%(fname)s: %(values)s) belongs to another company.")
            root_company_msg = _lt("- Only a root company can be set on “%(record)s”. Currently set to “%(company)s”")
            for record, name, corecords in inconsistencies[:5]:
                if record._name == 'res.company':
                    msg, companies = company_msg, record
                elif record == corecords and name == 'company_id':
                    msg, companies = root_company_msg, record.company_id
                else:
                    msg = record_msg
                    companies = record.company_id if 'company_id' in record else record.company_ids
                field = self.env['ir.model.fields']._get(self._name, name)
                lines.append(str(msg) % {
                    'record': record.display_name,
                    'company': ", ".join(company.display_name for company in companies),
                    'field': field.field_description,
                    'fname': field.name,
                    'values': ", ".join(repr(rec.display_name) for rec in corecords),
                })
            lines.append(_("To avoid a mess, no company crossover is allowed!"))
            raise UserError("\n".join(lines))

    @api.private  # use has_access
    @typing.final
    def check_access(self, operation: str) -> None:
        """ Verify that the current user is allowed to perform ``operation`` on
        all the records in ``self``. The method raises an :class:`AccessError`
        if the operation is forbidden on the model in general, or on any record
        in ``self``.

        In particular, when ``self`` is empty, the method checks whether the
        current user has some permission to perform ``operation`` on the model
        in general::

            # check that user has some minimal permission on the model
            records.browse().check_access(operation)

        """
        return orm_access.check_access(self, operation)

    @typing.final
    def has_access(self, operation: str) -> bool:
        """ Return whether the current user is allowed to perform ``operation``
        on all the records in ``self``. The method is fully consistent with
        method :meth:`check_access` but returns a boolean instead.
        """
        return orm_access.has_access(self, operation)

    @typing.final
    def _filtered_access(self, operation: str) -> typing.Self:
        """ Return the subset of ``self`` for which the current user is allowed
        to perform ``operation``. The method is fully equivalent to::

            self.filtered(lambda record: record.has_access(operation))

        """
        return orm_access.filtered_access(self, operation)


    @deprecated("Since 20.0, use Model._access_domain instead")
    def _check_access(self, operation: str) -> tuple[Self, Callable] | None:
        """ Return ``None`` if the current user has permission to perform
        ``operation`` on the records ``self``. Otherwise, return a pair
        ``(records, function)`` where ``records`` are the forbidden records, and
        ``function`` can be used to create some corresponding exception.

        This method provides the base implementation of
        methods :meth:`check_access`, :meth:`has_access`
        and :meth:`_filtered_access`. The method may be overridden in order to
        restrict the access to ``self``.
        """
        domain = self._access_domain(operation)
        if domain.is_false():
            return self, functools.partial(self._make_access_error_message, operation, domain)

        origin = self._origin
        if (
            origin
            and domain
            and (forbidden := origin - origin.with_context(active_test=False).sudo().filtered_domain(domain))
        ):
            return forbidden, functools.partial(forbidden._make_access_error_message, operation, domain)

        return None

    @api.model
    @api.ormcache('operation', 'self.env._access_context')
    def _access_domain(self, operation: str) -> Domain:
        """Get the security domain for the given operation.

        Return the domain that determines on which records of this model
        the current user is allowed to perform ``operation``.  The domain comes
        from the permissions and restrictions that apply to the current user.
        """
        return orm_access.access_domain(self, operation)

    def _make_access_error_message(self, operation: str, domain: Domain) -> AccessError:
        """Create the access error for the given operation.
        :param operation: operation performed
        :param domain: security domain from :meth:`_access_domain`
        """
        if domain.is_false():
            return self.env['ir.access']._make_model_access_error(self._name, operation)
        return self.env['ir.access']._make_record_access_error(self, operation)

    def unlink(self) -> typing.Literal[True]:
        """ Delete the records in ``self``.

        :raise AccessError: if the user is not allowed to delete all the given records
        :raise UserError: if the record is default property for other records
        """
        if not self:
            return True

        self.check_access('unlink')
        self.env.transaction._wrote__ = True

        for func in self._ondelete_methods:
            # func._ondelete is True => should be called during uninstallation
            # func._ondelete is False => should be called unless its module is being uninstalled
            if (
                func._ondelete
                or not self.pool.uninstalling_modules
                or func.__module__.split('.')[2] not in self.pool.uninstalling_modules
            ):
                func(self)

        # TOFIX: this avoids an infinite loop when trying to recompute a
        # field, which triggers the recomputation of another field using the
        # same compute function, which then triggers again the computation
        # of those two fields
        for field in self._fields.values():
            self.env.remove_to_compute(field, self)

        self.env.flush_all()

        cr = self.env.cr
        Data = self.env['ir.model.data'].sudo().with_context({})
        Defaults = self.env['ir.default'].sudo()
        Attachment = self.env['ir.attachment'].sudo()
        ir_model_data_unlink = Data
        ir_attachment_unlink = Attachment

        # mark fields that depend on 'self' to recompute them after 'self' has
        # been deleted (like updating a sum of lines after deleting one line)
        with self.env.protecting(self._fields.values(), self):
            self.modified(self._fields, before=True)

        for sub_ids in split_every(IN_MAX, self.ids):
            records = self.browse(sub_ids)

            cr.execute(SQL(
                "DELETE FROM %s WHERE id IN %s",
                SQL.identifier(self._table), sub_ids,
            ))

            # Removing the ir_model_data reference if the record being deleted
            # is a record created by xml/csv file, as these are not connected
            # with real database foreign keys, and would be dangling references.
            #
            # Note: the following steps are performed as superuser to avoid
            # access rights restrictions, and with no context to avoid possible
            # side-effects during admin calls.
            data = Data.search([('model', '=', self._name), ('res_id', 'in', sub_ids)])
            ir_model_data_unlink |= data

            # For the same reason, remove the relevant records in ir_attachment
            # (the search is performed with sql as the search method of
            # ir_attachment is overridden to hide attachments of deleted
            # records)
            cr.execute(SQL(
                "SELECT id FROM ir_attachment WHERE res_model=%s AND res_id IN %s",
                self._name, sub_ids,
            ))
            ir_attachment_unlink |= Attachment.browse(row[0] for row in cr.fetchall())

            # don't allow fallback value in ir.default for many2one company dependent fields to be deleted
            # Exception: when 'force_delete', these fallbacks can be deleted by Defaults.discard_records(records)
            if (many2one_fields := self.env.registry.many2one_company_dependents[self._name]) and not self.env.context.get('force_delete'):
                IrModelFields = self.env["ir.model.fields"]
                field_ids = tuple(IrModelFields._get_ids(field.model_name).get(field.name) for field in many2one_fields)
                sub_ids_json_text = tuple(json.dumps(id_) for id_ in sub_ids)
                if default := Defaults.search([('field_id', 'in', field_ids), ('json_value', 'in', sub_ids_json_text)], limit=1, order='id desc'):
                    ir_field = default.field_id.sudo()
                    field = self.env[ir_field.model]._fields[ir_field.name]
                    record = self.browse(json.loads(default.json_value))
                    raise UserError(_('Unable to delete %(record)s because it is used as the default value of %(field)s', record=record, field=field))

            # on delete set null/restrict for jsonb company dependent many2one
            for field in many2one_fields:
                model = self.env[field.model_name]
                if field.ondelete == 'restrict' and not self.env.context.get('force_delete'):
                    if res := self.env.execute_query(SQL(
                        """
                        SELECT id, %(field)s
                        FROM %(table)s
                        WHERE %(field)s IS NOT NULL
                        AND %(field)s @? %(jsonpath)s
                        ORDER BY id
                        LIMIT 1
                        """,
                        table=SQL.identifier(model._table),
                        field=SQL.identifier(field.name),
                        jsonpath=f"$.* ? ({' || '.join(f'@ == {id_}' for id_ in sub_ids)})",
                    )):
                        on_restrict_id, field_json = res[0]
                        to_delete_id = next(iter(id_ for id_ in field_json.values()))
                        on_restrict_record = model.browse(on_restrict_id)
                        to_delete_record = self.browse(to_delete_id)
                        raise UserError(_('You cannot delete %(to_delete_record)s, as it is used by %(on_restrict_record)s',
                                          to_delete_record=to_delete_record, on_restrict_record=on_restrict_record))
                else:
                    self.env.execute_query(SQL(
                        """
                        UPDATE %(table)s
                        SET %(field)s = (
                            SELECT jsonb_object_agg(
                                key,
                                CASE
                                    WHEN value::int4 in %(ids)s THEN NULL
                                    ELSE value::int4
                                END)
                            FROM jsonb_each_text(%(field)s)
                        )
                        WHERE %(field)s IS NOT NULL
                        AND %(field)s @? %(jsonpath)s
                        """,
                        table=SQL.identifier(model._table),
                        field=SQL.identifier(field.name),
                        ids=sub_ids,
                        jsonpath=f"$.* ? ({' || '.join(f'@ == {id_}' for id_ in sub_ids)})",
                    ))

            # For the same reason, remove the defaults having some of the
            # records as value
            Defaults.discard_records(records)

        # invalidate the *whole* cache, since the orm does not handle all
        # changes made in the database, like cascading delete!
        self.env.invalidate_all(flush=False)
        if ir_model_data_unlink:
            ir_model_data_unlink.unlink()
        if ir_attachment_unlink:
            ir_attachment_unlink.unlink()
        if cache_name := self._clear_cache_name:
            self.env.transaction.invalidate_ormcache(cache_name)

        # auditing: deletions are infrequent and leave no trace in the database
        _unlink.info('User #%s deleted %s records with IDs: %r', self.env.uid, self._name, self.ids)

        return True

    def write(self, vals: ValuesType) -> typing.Literal[True]:
        """ Update all records in ``self`` with the provided values.

        :param vals: fields to update and the value to set on them
        :raise AccessError: if user is not allowed to modify the specified records/fields
        :raise ValidationError: if invalid values are specified for selection fields
        :raise UserError: if a loop would be created in a hierarchy of objects a result of the operation (such as setting an object as its own parent)

        * For numeric fields (:class:`~odoo.fields.Integer`,
          :class:`~odoo.fields.Float`) the value should be of the
          corresponding type
        * For :class:`~odoo.fields.Boolean`, the value should be a
          :class:`python:bool`
        * For :class:`~odoo.fields.Selection`, the value should match the
          selection values (generally :class:`python:str`, sometimes
          :class:`python:int`)
        * For :class:`~odoo.fields.Many2one`, the value should be the
          database identifier of the record to set
        * The expected value of a :class:`~odoo.fields.One2many` or
          :class:`~odoo.fields.Many2many` relational field is a list of
          :class:`~odoo.fields.Command` that manipulate the relation the
          implement. There are a total of 7 commands:
          :meth:`~odoo.fields.Command.create`,
          :meth:`~odoo.fields.Command.update`,
          :meth:`~odoo.fields.Command.delete`,
          :meth:`~odoo.fields.Command.unlink`,
          :meth:`~odoo.fields.Command.link`,
          :meth:`~odoo.fields.Command.clear`, and
          :meth:`~odoo.fields.Command.set`.
        * For :class:`~odoo.fields.Date` and `~odoo.fields.Datetime`,
          the value should be either a date(time), or a string.

          .. warning::

            If a string is provided for Date(time) fields,
            it must be UTC-only and formatted according to
            :const:`odoo.tools.misc.DEFAULT_SERVER_DATE_FORMAT` and
            :const:`odoo.tools.misc.DEFAULT_SERVER_DATETIME_FORMAT`

        * Other non-relational fields use a string for value
        """
        if not self:
            return True

        self.check_access('write')
        for field_name in vals:
            try:
                self.check_field_access(self._fields[field_name], 'write')
            except KeyError as e:
                raise ValueError(f"Invalid field {field_name!r} in {self._name!r}") from e
        env = self.env

        bad_names = {'id', 'parent_path'}
        if self._log_access:
            # the superuser can set log_access fields while loading registry
            if not (self.env.uid == SUPERUSER_ID and not self.pool.ready):
                bad_names.update(LOG_ACCESS_COLUMNS)

        # set magic fields
        vals = {key: val for key, val in vals.items() if key not in bad_names}
        if self._log_access:
            vals.setdefault('write_uid', self.env.uid)
            vals.setdefault('write_date', self.env.cr.now())

        field_values = sorted(
            [(self._fields[key], val) for key, val in vals.items()],
            key=lambda item: self._fields_update_order__[item[0]]
        )                                           # [(field, value)]
        determine_inverses = defaultdict(list)      # {inverse: fields}
        fnames_modifying_relations = []
        protected = set()
        for field, value in field_values:
            if field.inverse:
                if field.type in ('one2many', 'many2many'):
                    # The written value is a list of commands that must applied
                    # on the field's current value. Because the field is
                    # protected while being written, the field's current value
                    # will not be computed and default to an empty recordset. So
                    # make sure the field's value is in cache before writing, in
                    # order to avoid an inconsistent update.
                    self[field.name]
                determine_inverses[field.inverse].append(field)
            if self.pool.is_modifying_relations(field):
                fnames_modifying_relations.append(field.name)
            if field.inverse or (field.compute and not field.readonly):
                if field.store or field.type not in ('one2many', 'many2many'):
                    # Protect the field from being recomputed while being
                    # inversed. In the case of non-stored x2many fields, the
                    # field's value may contain unexpeced new records (created
                    # by command 0). Those new records are necessary for
                    # inversing the field, but should no longer appear if the
                    # field is recomputed afterwards. Not protecting the field
                    # will automatically invalidate the field from the cache,
                    # forcing its value to be recomputed once dependencies are
                    # up-to-date.
                    protected.update(self.pool.field_computed.get(field, [field]))

        # force the computation of fields that are computed with some assigned
        # fields, but are not assigned themselves
        to_compute = [field.name
                      for field in protected
                      if field.compute and field.name not in vals]
        if to_compute:
            self._recompute_recordset(to_compute)

        # protect fields being written against recomputation
        with env.protecting(protected, self):
            # Determine records depending on values. When modifying a relational
            # field, you have to recompute what depends on the field's values
            # before and after modification.  This is because the modification
            # has an impact on the "data path" between a computed field and its
            # dependency.  Note that this double call to modified() is only
            # necessary for relational fields.
            #
            # It is best explained with a simple example: consider two sales
            # orders SO1 and SO2.  The computed total amount on sales orders
            # indirectly depends on the many2one field 'order_id' linking lines
            # to their sales order.  Now consider the following code:
            #
            #   line = so1.line_ids[0]      # pick a line from SO1
            #   line.order_id = so2         # move the line to SO2
            #
            # In this situation, the total amount must be recomputed on *both*
            # sales order: the line's order before the modification, and the
            # line's order after the modification.
            self.modified(fnames_modifying_relations, before=True)

            real_recs = self.filtered('id')

            for field, value in field_values:
                field.write(self, value)

            # determine records depending on new values
            #
            # Call modified after write, because the modified can trigger a
            # search which can trigger a flush which can trigger a recompute
            # which remove the field from the recompute list while all the
            # values required for the computation could not be yet in cache.
            # e.g. Write on `name` of `res.partner` trigger the recompute of
            # `display_name`, which triggers a search on child_ids to find the
            # childs to which the display_name must be recomputed, which
            # triggers the flush of `display_name` because the _order of
            # res.partner includes display_name. The computation of display_name
            # is then done too soon because the parent_id was not yet written.
            # (`test_01_website_reset_password_tour`)
            self.modified(vals)

            if self._parent_store and self._parent_name in vals:
                self.flush_model([self._parent_name])

            # validate non-inversed fields first
            inverse_fields = [f.name for fs in determine_inverses.values() for f in fs]
            real_recs._validate_fields(vals, inverse_fields)

            for fields in determine_inverses.values():
                # write again on non-stored fields that have been invalidated from cache
                for field in fields:
                    if not field.store and (not field.inherited or field.type not in ('one2many', 'many2many')) and any(field._cache_missing_ids(real_recs)):
                        field.write(real_recs, vals[field.name])

                # inverse records that are not being computed
                try:
                    fields[0].determine_inverse(real_recs)
                except AccessError as e:
                    if fields[0].inherited:
                        description = self.env['ir.model']._get(self._name).name
                        raise AccessError(_(
                            "%(previous_message)s\n\nImplicitly accessed through '%(document_kind)s' (%(document_model)s).",
                            previous_message=e.args[0],
                            document_kind=description,
                            document_model=self._name,
                        ))
                    raise

            # invalidate the cache
            if real_recs and (cache_name := self._clear_cache_name) and (
                self._clear_cache_on_fields is None
                or not vals.keys().isdisjoint(self._clear_cache_on_fields)
            ):
                self.env.transaction.invalidate_ormcache(cache_name)

            # validate inversed fields
            real_recs._validate_fields(inverse_fields)

        if self._check_company_auto:
            self._check_company(list(vals))
        return True

    def _write(self, vals: ValuesType) -> None:
        """ Low-level implementation of write() """
        self._write_multi([vals] * len(self))

    def _write_multi(self, vals_list: list[ValuesType]) -> None:
        """ Low-level implementation of write() """
        return orm_write._write_multi(self, vals_list)

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        """Create new records for the model.

        The new records are initialized using the values from the list of dicts
        ``vals_list``, and if necessary those from :meth:`~.default_get`.

        :param vals_list:
            values for the model's fields, as a list of dictionaries::

                [{'field_name': field_value, ...}, ...]

            For backward compatibility, ``vals_list`` may be a dictionary.
            It is treated as a singleton list ``[vals]``, and a single record
            is returned.

            see :meth:`~.write` for details

        :return: the created records
        :raise AccessError: if the current user is not allowed to create records of the specified model
        :raise ValidationError: if user tries to enter invalid value for a selection field
        :raise ValueError: if a field name specified in the create values does not exist.
        :raise UserError: if a loop would be created in a hierarchy of objects a result of the operation
          (such as setting an object as its own parent)
        """
        assert isinstance(vals_list, (list, tuple))
        if not vals_list:
            return self.browse()

        self = self.browse()
        self.check_access('create')

        # check access to all user-provided fields
        field_names = OrderedSet(fname for vals in vals_list for fname in vals)
        field_names.update(
            field_name
            for context_key in self.env.context
            if context_key.startswith('default_')
            and (field_name := context_key[8:])
            and field_name in self._fields
        )
        for field_name in field_names:
            field = self._fields.get(field_name)
            if field is None:
                raise ValueError(f"Invalid field {field_name!r} in {self._name!r}")
            self.check_field_access(field, 'write')

        new_vals_list = self._prepare_create_values(vals_list)

        # classify fields for each record
        data_list = []
        determine_inverses = defaultdict(OrderedSet)       # {inverse: fields}

        for vals in new_vals_list:
            precomputed = vals.pop('__precomputed__', ())

            # distribute fields into sets for various purposes
            data = {}
            data['stored'] = stored = {}
            data['inversed'] = inversed = {}
            data['cached_only'] = cached_only = {}
            data['inherited'] = inherited = defaultdict(dict)
            data['protected'] = protected = set()
            for key, val in vals.items():
                field = self._fields.get(key)
                if not field:
                    raise ValueError("Invalid field %r on model %r" % (key, self._name))
                if field.store:
                    stored[key] = val
                if field.inherited:
                    inherited[field.related_field.model_name][key] = val
                elif field.inverse and field not in precomputed:
                    inversed[key] = val
                    determine_inverses[field.inverse].add(field)
                elif not field.store and not field.compute:
                    # cache only fields with `field.inverse` will be handed by `inversed` correctly
                    cached_only[key] = val
                # protect editable computed fields and precomputed fields
                # against (re)computation
                if (field.compute and (not field.readonly or field.precompute)) or key in cached_only:
                    protected.update(self.pool.field_computed.get(field, [field]))
                if field.type == 'many2one' and field.bypass_search_access and not self.env.su:
                    self.env[field.comodel_name].browse(field.convert_to_cache(val, self)).check_access('read')

            data_list.append(data)

        # create or update parent records
        for model_name, parent_name in self._inherits.items():
            parent_data_list = []
            for data in data_list:
                if not data['stored'].get(parent_name):
                    parent_data_list.append(data)
                elif data['inherited'][model_name]:
                    parent = self.env[model_name].browse(data['stored'][parent_name])
                    parent.write(data['inherited'][model_name])

            if parent_data_list:
                parents = self.env[model_name].create([
                    data['inherited'][model_name]
                    for data in parent_data_list
                ])
                for parent, data in zip(parents, parent_data_list):
                    data['stored'][parent_name] = parent.id

        # create records with stored fields
        records = self._create(data_list)

        # protect fields being written against recomputation
        protected_fields = [(data['protected'], data['record']) for data in data_list]
        with self.env.protecting(protected_fields):
            # fill cached_only fields
            for data in data_list:
                if vals := data['cached_only']:
                    data['record']._update_cache(vals)
            # call inverse method for each group of fields
            for fields in sorted(determine_inverses.values(), key=lambda fields: min(self._fields_update_order__[f] for f in fields)):
                # determine which records to inverse for those fields
                inv_names = {field.name for field in fields}
                inv_rec_ids = []
                for data in data_list:
                    if inv_names.isdisjoint(data['inversed']):
                        continue
                    record = data['record']
                    record._update_cache({
                        fname: value
                        for fname, value in data['inversed'].items()
                        if fname in inv_names and fname not in data['stored']
                    })
                    inv_rec_ids.append(record.id)

                inv_records = self.browse(inv_rec_ids)
                next(iter(fields)).determine_inverse(inv_records)
                # Values of non-stored fields were cached before running inverse methods. In case of x2many create
                # commands, the cache may therefore hold NewId records. We must now invalidate those values.
                inv_relational_fnames = [field.name for field in fields if field.type in ('one2many', 'many2many') and not field.store]
                inv_records.invalidate_recordset(fnames=inv_relational_fnames)

        # invalidate the cache
        if cache_name := self._clear_cache_name:
            self.env.transaction.invalidate_ormcache(cache_name)

        # check Python constraints for non-stored inversed fields
        for data in data_list:
            data['record']._validate_fields(data['inversed'], data['stored'])

        if self._check_company_auto:
            records._check_company()

        import_module = self.env.context.get('_import_current_module')
        if not import_module: # not an import -> bail
            return records

        # It is to support setting xids directly in create by
        # providing an "id" key (otherwise stripped by create) during an import
        # (which should strip 'id' from the input data anyway)
        noupdate = self.env.context.get('noupdate', False)

        xids = (v.get('id') for v in vals_list)
        self.env['ir.model.data']._update_xmlids([
            {
                'xml_id': xid if '.' in xid else ('%s.%s' % (import_module, xid)),
                'record': rec,
                # note: this is not used when updating o2ms above...
                'noupdate': noupdate,
            }
            for rec, xid in zip(records, xids)
            if xid and isinstance(xid, str)
        ])

        return records

    def _prepare_create_values(self, vals_list: list[ValuesType]) -> list[ValuesType]:
        """ Clean up and complete the given create values, and return a list of
        new vals containing:

        * default values,
        * discarded forbidden values (magic fields),
        * precomputed fields.

        :param vals_list: List of create values
        :returns: new list of completed create values
        """
        return orm_write._prepare_create_values(self, vals_list)

    def _add_precomputed_values(self, vals_list: list[ValuesType]) -> None:
        """ Add missing precomputed fields to ``vals_list`` values.
        Only applies for precompute=True fields.
        """
        return orm_write._add_precomputed_values(self, vals_list)

    @api.model
    def _create(self, data_list: list[ValuesType]) -> Self:
        """ Create records from the stored field values in ``data_list``. """
        assert data_list
        assert not self._abstract, f"Cannot create records for abstract model {self._name}"
        cr = self.env.cr
        self.env.transaction._wrote__ = True

        # insert rows in batches of maximum INSERT_BATCH_SIZE
        ids: list[int] = []                     # ids of created records
        other_fields: OrderedSet[Field] = OrderedSet()  # non-column fields

        for data_sublist in split_every(INSERT_BATCH_SIZE, data_list):
            stored_list = [data['stored'] for data in data_sublist]
            fnames = sorted({name for stored in stored_list for name in stored})

            columns: list[str] = []
            rows: list[list[typing.Any]] = [[] for _ in stored_list]
            for fname in fnames:
                field = self._fields[fname]
                if field.column_type:
                    columns.append(fname)
                    for stored, row in zip(stored_list, rows):
                        if fname in stored:
                            row.append(field.convert_to_column_insert(stored[fname], self, stored))
                        else:
                            row.append(SQL_DEFAULT)
                else:
                    other_fields.add(field)

                if field.type == 'properties':
                    # force calling fields.create for properties field because
                    # we might want to update the parent definition
                    other_fields.add(field)

            if not columns:
                # manage the case where we create empty records
                columns = ['id']
                for row in rows:
                    row.append(SQL_DEFAULT)

            cr.execute(SQL(
                'INSERT INTO %s (%s) VALUES %s RETURNING "id"',
                SQL.identifier(self._table),
                SQL(', ').join(map(SQL.identifier, columns)),
                SQL(', ').join(tuple(row) for row in rows),
            ))
            ids.extend(id_ for id_, in cr.fetchall())

        # put the new records in cache, and update inverse fields, for many2one
        records = self.browse(ids)
        inverses_update = defaultdict(list)     # {(field, value): ids}
        common_set_vals = set(LOG_ACCESS_COLUMNS + ['id', 'parent_path'])
        for data, record in zip(data_list, records):
            data['record'] = record
            # DLE P104: test_inherit.py, test_50_search_one2many
            vals = dict({k: v for d in data['inherited'].values() for k, v in d.items()}, **data['stored'])
            set_vals = common_set_vals.union(vals)

            # put None in cache for all fields that are not part of the INSERT
            for field in self._fields.values():
                if not field.store:
                    continue
                if field.type in ('one2many', 'many2many'):
                    field._update_cache(record, ())
                elif field.name not in set_vals:
                    field._update_cache(record, None)

            for fname, value in vals.items():
                field = self._fields[fname]
                if field.type not in ('one2many', 'many2many', 'html'):
                    cache_value = field.convert_to_cache(value, record)
                    field._update_cache(record, cache_value)
                    if field.type in ('many2one', 'many2one_reference') and self.pool.field_inverses[field]:
                        inverses_update[(field, cache_value)].append(record.id)

        for (field, value), record_ids in inverses_update.items():
            field._update_inverses(self.browse(record_ids), value)

        # update parent_path
        records._parent_store_create()

        # protect fields being written against recomputation
        protected = [(data['protected'], data['record']) for data in data_list]
        with self.env.protecting(protected):
            # mark computed fields as todo
            records.modified(self._fields, create=True)

            if other_fields:
                # discard default values from context for other fields
                others = records.with_context(clean_context(self.env.context))
                for field in sorted(other_fields, key=lambda field: self._fields_update_order__[field]):
                    field.create([
                        (other, data['stored'][field.name])
                        for other, data in zip(others, data_list)
                        if field.name in data['stored']
                    ])

                # mark fields to recompute
                records.modified([field.name for field in other_fields], create=True)

        # check Python constraints for stored fields
        records._validate_fields(name for data in data_list for name in data['stored'])
        records.check_access('create')
        return records

    def _compute_field_value(self, field: Field) -> None:
        return orm_write._compute_field_value(self, field)

    def _parent_store_create(self) -> None:
        """ Set the parent_path field on ``self`` after its creation. """
        return orm_parent_store._parent_store_create(self)

    def _parent_store_update_prepare(self, vals_list: list[ValuesType]) -> Self:
        """ Return the records in ``self`` that must update their parent_path
            field. This must be called before updating the parent field.
        """
        return orm_parent_store._parent_store_update_prepare(self, vals_list)

    def _parent_store_update(self) -> None:
        """ Update the parent_path field of ``self``. """
        return orm_parent_store._parent_store_update(self)

    def _clean_properties(self) -> None:
        """ Remove all properties of ``self`` that are no longer in the related definition """
        return orm_properties._clean_properties(self)

    def _validate_properties_definition(self, properties_definition, field):
        """Allow to validate additional properties attributes."""

    def _additional_allowed_keys_properties_definition(self):
        """Allow to add more allowed key for properties."""
        return orm_properties._additional_allowed_keys_properties_definition(self)

    def _convert_to_cache_properties_definition(self, value):
        """Allow to patch `convert_to_cache` of the properties definition."""
        return orm_properties._convert_to_cache_properties_definition(self, value)

    def _convert_to_column_properties_definition(self, value):
        """Allow to patch `convert_to_column` of the properties definition."""
        return orm_properties._convert_to_column_properties_definition(self, value)

    def _load_records_write(self, values):
        self.ensure_one()
        to_write = {}  # Deferred the write to avoid using the old definition if it changed
        for fname in list(values):
            if fname not in self._fields or self._fields[fname].type != 'properties':
                continue
            field_converter = self._fields[fname].convert_to_cache
            to_write[fname] = dict(self[fname]._values or {}, **field_converter(values.pop(fname), self, validate=False))

        self.write(values)
        if to_write:
            self.write(to_write)
            # Because we don't know which properties was linked to which definition,
            # we can know clean properties (note that it is not mandatory, we can wait
            # that client change the record in a Form view)
            self._clean_properties()

    def _load_records_create(self, vals_list):
        records = self.create(vals_list)
        if any(field.type == 'properties' for field in self._fields.values()):
            records._clean_properties()
        return records

    def _load_records(self, data_list, update=False):
        """ Create or update records of this model, and assign XMLIDs.

            :param data_list: list of dicts with keys `xml_id` (XMLID to
                assign), `noupdate` (flag on XMLID), `values` (field values)
            :param update: should be ``True`` when upgrading a module

            :return: the records corresponding to ``data_list``
        """
        original_self = self.browse()

        imd = self.env['ir.model.data'].sudo()

        # The algorithm below partitions 'data_list' into three sets: the ones
        # to create, the ones to update, and the others. For each set, we assign
        # data['record'] for each data. All those records are then retrieved for
        # the result.

        # determine existing xml_ids
        xml_ids = [data['xml_id'] for data in data_list if data.get('xml_id')]
        existing = {
            ("%s.%s" % row[1:3]): row
            for row in imd._lookup_xmlids(xml_ids, self)
        }

        # determine which records to create and update
        to_create = []                  # list of data
        to_update = []                  # list of data
        imd_data_list = []              # list of data for _update_xmlids()

        for data in data_list:
            xml_id = data.get('xml_id')
            if not xml_id:
                vals = data['values']
                if vals.get('id'):
                    data['record'] = self.browse(vals['id'])
                    to_update.append(data)
                elif not update:
                    to_create.append(data)
                else:
                    raise ValidationError(_("Cannot update a record without specifying its id or xml_id"))
                continue
            row = existing.get(xml_id)
            if not row:
                to_create.append(data)
                continue
            d_id, d_module, d_name, d_model, d_res_id, d_noupdate, r_id = row
            if self._name != d_model:
                raise ValidationError(  # pylint: disable=missing-gettext
                    f"For external id {xml_id} "
                    f"when trying to create/update a record of model {self._name} "
                    f"found record of different model {d_model} ({d_id})"
                )
            record = self.browse(d_res_id)
            if r_id:
                data['record'] = record
                imd_data_list.append(data)
                if not (update and d_noupdate):
                    to_update.append(data)
            else:
                imd.browse(d_id).unlink()
                to_create.append(data)

        # update existing records
        for data in to_update:
            data['record']._load_records_write(data['values'])

        # check for records to create with an XMLID from another module
        module = self.env.context.get('install_module')
        if module:
            prefix = module + "."
            for data in to_create:
                if data.get('xml_id') and not data['xml_id'].startswith(prefix) and not self.env.context.get('foreign_record_to_create'):
                    _logger.warning("Creating record %s in module %s.", data['xml_id'], module)

        if self.env.context.get('import_file'):
            existing_modules = self.env['ir.module.module'].sudo().search([]).mapped('name')
            for data in to_create:
                xml_id = data.get('xml_id')
                if xml_id and not data.get('noupdate'):
                    module_name, sep, record_id = xml_id.partition('.')
                    if sep and module_name in existing_modules:
                        raise UserError(
                            _("The record %(xml_id)s has the module prefix %(module_name)s. This is the part before the '.' in the external id. Because the prefix refers to an existing module, the record would be deleted when the module is upgraded. Use either no prefix and no dot or a prefix that isn't an existing module. For example, __import__, resulting in the external id __import__.%(record_id)s.",
                              xml_id=xml_id, module_name=module_name, record_id=record_id))

        # create records
        if to_create:
            records = self._load_records_create([data['values'] for data in to_create])
            for data, record in zip(to_create, records):
                data['record'] = record
                if data.get('xml_id'):
                    # add XML ids for parent records that have just been created
                    for parent_model, parent_field in self._inherits.items():
                        if not data['values'].get(parent_field):
                            imd_data_list.append({
                                'xml_id': f"{data['xml_id']}_{parent_model.replace('.', '_')}",
                                'record': record[parent_field],
                                'noupdate': data.get('noupdate', False),
                            })
                    imd_data_list.append(data)

        # create or update XMLIDs
        imd._update_xmlids(imd_data_list, update)

        return original_self + self.browse().concat(data['record'] for data in data_list)

    def _check_qorder(self, word: str) -> None:
        if not regex_order.match(word):
            raise UserError(_(
                "Invalid \"order\" specified (%s)."
                " A valid \"order\" specification is a comma-separated list of valid field names"
                " (optionally followed by asc/desc for the direction)",
                word,
            ))

    def _order_to_sql(self, table: TableSQL, order: str, reverse: bool = False) -> SQL:
        """ Return an :class:`SQL` object that represents the given ORDER BY
        clause, without the ORDER BY keyword.  The method also checks whether
        the fields in the order are accessible for reading.
        """
        order = order or self._order
        if not order:
            return SQL()
        self._check_qorder(order)

        terms = []
        for order_part in order.split(','):
            order_match = regex_order.match(order_part)
            assert order_match is not None, "No match found"
            field_name = order_match['field']

            direction = (order_match['direction'] or '').upper()
            nulls = (order_match['nulls'] or '').upper()
            if reverse:
                direction = 'ASC' if direction == 'DESC' else 'DESC'
                if nulls:
                    nulls = 'NULLS LAST' if nulls == 'NULLS FIRST' else 'NULLS FIRST'

            sql_direction = (
                SQL('ASC') if direction == 'ASC'
                else SQL('DESC') if direction == 'DESC'
                else SQL()
            )
            sql_nulls = (
                SQL('NULLS FIRST') if nulls == 'NULLS FIRST'
                else SQL('NULLS LAST') if nulls == 'NULLS LAST'
                else SQL()
            )

            if property_name := order_match['property']:
                # field_name is an expression
                field_name = f"{field_name}.{property_name}"
            term = self._order_field_to_sql(table, field_name, sql_direction, sql_nulls)
            if term:
                terms.append(term)

        return SQL(", ").join(terms)

    def _order_field_to_sql(
        self, table: TableSQL, field_expr: str,
        direction: SQL, nulls: SQL,
    ) -> SQL:
        """ Return an :class:`SQL` object that represents the ordering by the
        given field.  The method also checks whether the field is accessible for
        reading.

        :param direction: one of ``SQL("ASC")``, ``SQL("DESC")``, ``SQL()``
        :param nulls: one of ``SQL("NULLS FIRST")``, ``SQL("NULLS LAST")``, ``SQL()``
        """
        # field_name is an expression
        fname, property_name = parse_field_expr(field_expr)
        field = self._fields.get(fname)
        if not field:
            raise ValueError(f"Invalid field {fname!r} on model {self._name!r}")

        if field.type == 'many2one':
            seen = self.env.context.get('__m2o_order_seen', ())
            if field in seen:
                return SQL()
            self = self.with_context(__m2o_order_seen=frozenset((field, *seen)))

            # figure out the applicable order_by for the m2o
            # special case: ordering by "x_id.id" doesn't recurse on x_id's comodel
            comodel = self.env[field.comodel_name]
            sql_field = table[fname]
            if property_name == 'id':
                coorder = 'id'
            elif property_name:
                raise ValueError(f"Cannot order by comodel fields in {field_expr!r}")
            else:
                coorder = comodel._order

            if coorder == 'id':
                table._query._order_groupby.append(sql_field)
                return SQL("%s %s %s", sql_field, direction, nulls)

            # instead of ordering by the field's raw value, use the comodel's
            # order on many2one values
            terms = []
            nulls_code = nulls._sql_tuple[0]
            if nulls_code == 'NULLS FIRST':
                terms.append(SQL("%s IS NOT NULL", sql_field))
            elif nulls_code == 'NULLS LAST':
                terms.append(SQL("%s IS NULL", sql_field))

            # LEFT JOIN the comodel table, in order to include NULL values, too
            # Run as sudo because we can order by inaccessible models as we can
            # only order by the default order or the id.
            cotable = table._with_model(self.sudo())._join(fname)

            # delegate the order to the comodel
            reverse = direction._sql_tuple[0] == 'DESC'
            term = comodel._order_to_sql(cotable, coorder, reverse=reverse)
            if term:
                terms.append(term)
            return SQL(", ").join(terms)

        sql_field = table[fname]

        if property_name:
            sql_field = sql_field[property_name]
        if field.type == 'boolean' and field not in self.env.registry.not_null_fields:
            sql_field = SQL("COALESCE(%s, FALSE)", sql_field)
        elif field.type == 'selection':
            sql_keys = list(field.get_values(self.env))
            sql_field = SQL("array_position(%s::text[], %s::text)", sql_keys, sql_field)

        table._query._order_groupby.append(sql_field)

        return SQL("%s %s %s", sql_field, direction, nulls)

    @api.model
    def _search(
        self,
        domain: DomainType,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
        *,
        active_test: bool = True,
        bypass_access: bool = False,
    ) -> Query:
        """
        Private implementation of search() method.

        No default order is applied when the method is invoked without parameter ``order``.

        :return: a :class:`Query` object that represents the matching records

        This method may be overridden to modify the domain being searched, or to
        do some post-filtering of the resulting query object. Be careful with
        the latter option, though, as it might hurt performance. Indeed, by
        default the returned query object is not actually executed, and it can
        be injected as a value in a domain in order to generate sub-queries.

        The `active_test` flag specifies whether to filter only active records.
        The `bypass_access` controls whether or not permissions should be
        checked on the model and record rules should be applied.
        """
        if self.env.su or bypass_access:
            sec_domain = Domain.TRUE
        else:
            sec_domain = self._access_domain('read')
            if sec_domain.is_false():
                self.browse().check_access('read')
                domain = Domain.FALSE

        domain = Domain(domain)
        # inactive records unless they were explicitly asked for
        if (
            self._active_name
            and active_test
            and self.env.context.get('active_test', True)
            and not any(leaf.field_expr == self._active_name for leaf in domain.iter_conditions())
        ):
            # try to create the domain close to what it will look like after optimization
            # to avoid reoptimizing it
            domain = Domain(self._active_name, 'in', OrderedSet((True,))) & domain

        # build the query
        domain = domain.optimize_full(self)
        if domain.is_false():
            return self.browse()._as_query()
        query = Query(self)
        if not domain.is_true():
            query.add_where(domain._to_sql(query.table))

        # security access domain
        if not sec_domain.is_true():
            self_sudo = self.sudo().with_context(active_test=False)
            sec_domain = sec_domain.optimize_full(self_sudo, search_domain=domain)
            if sec_domain.is_false():
                return self.browse()._as_query()
            if (
                sec_domain.is_condition('id', 'any!', Query)
                and (ids := sec_domain.value._ids) is not None
            ):
                # optimization: browse ids and filter using the domain
                records = self.browse(ids)
                self.env._add_to_access_cache(records)
                records = records.filtered_domain(domain)
                if order:
                    records = records.with_prefetch().sorted(order)
                if offset:
                    records = records[offset:]
                if limit:
                    records = records[:limit]
                return records._as_query(ordered=bool(order))
            if not sec_domain.is_true():
                query.add_where(sec_domain._to_sql(query.table._with_model(self_sudo)))

        # add order and limits
        if order:
            query.order = self._order_to_sql(query.table, order)

        # In RPC, None is not available; False is used instead to mean "no limit"
        # Note: True is kept for backward-compatibility (treated as 1)
        if limit is not None and limit is not False:
            query.limit = limit
        if offset is not None:
            query.offset = offset

        return query

    def _as_query(self, ordered: bool = True) -> Query:
        """ Return a :class:`Query` that corresponds to the recordset ``self``.
        This method is convenient for making a query object with a known result.

        :param ordered: whether the recordset order must be enforced by the query
        """
        query = Query(self)
        query.set_result_ids(self._ids, ordered)
        return query

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        """
        Copy given record's data with all its fields values

        :param default: field values to override in the original values of the copied record
        :return: list of dictionaries containing all the field values
        """
        vals_list = []
        default = dict(default or {})
        # avoid recursion through already copied records in case of circular relationship
        if '__copy_data_seen' not in self.env.context:
            self = self.with_context(__copy_data_seen=defaultdict(set))

        # build a black list of fields that should not be copied
        blacklist = {*MAGIC_COLUMNS, 'parent_path'}
        whitelist = {name for name, field in self._fields.items() if not field.inherited}

        blacklist_stack = [self]
        while blacklist_stack:
            for parent_model, parent_field in blacklist_stack.pop()._inherits.items():
                blacklist.add(parent_field)
                if parent_field in default:
                    # all the fields of 'parent_model' are given by the record:
                    # default[parent_field], except the ones redefined in self
                    blacklist.update(set(self.env[parent_model]._fields) - whitelist)
                else:
                    blacklist_stack.append(self.env[parent_model])

        fields_to_copy = {name: field
                          for name, field in self._fields.items()
                          if field.copy and name not in default and name not in blacklist}
        active_langs = self.env['res.lang']._get_active_by('code')

        for record in self:
            seen_map = self.env.context['__copy_data_seen']
            if record.id in seen_map[record._name]:
                vals_list.append(None)
                continue
            seen_map[record._name].add(record.id)

            vals = default.copy()

            for name, field in fields_to_copy.items():
                if callable(field.copy):
                    vals[name] = field.copy(record)
                elif field.type == 'one2many':
                    # duplicate following the order of the ids for deterministic pairing
                    lines = record[name].sorted(key='id').copy_data()
                    # the lines are duplicated using the wrong (old) parent, but then are
                    # reassigned to the correct one thanks to the (Command.CREATE, 0, ...)
                    vals[name] = [Command.create(line) for line in lines if line]
                elif field.type == 'many2many':
                    # copy only links that we can read, otherwise the write will fail
                    vals[name] = [Command.set(record[name]._filtered_access('read').ids)]
                elif field.translate:
                    translations = record._get_stored_translations(name)
                    if not translations:
                        vals[name] = False
                    elif field.translate is True:
                        vals[name] = translations.normalize(record.env, field)
                    else:
                        vals[name] = translations.translated(
                            record.env, field, 'en_US', {lang: {} for lang in active_langs}
                        )
                else:
                    vals[name] = field.convert_to_write(record[name], record)

            vals_list.append(vals)

        return vals_list

    def copy(self, default: ValuesType | None = None) -> Self:
        """ Duplicate record ``self`` updating it with default values.

        :param default: dictionary of field values to override in the
               original values of the copied record, e.g: ``{'field_name': overridden_value, ...}``
        :returns: new records

        """
        vals_list = self.with_context(active_test=False).copy_data(default)
        return self.create(vals_list)

    @api.private
    def exists(self) -> Self:
        """ The subset of records in ``self`` that exist.
        It can be used as a test on records::

            if record.exists():
                ...

        By convention, new records are returned as existing.
        """
        new_ids, ids = partition(lambda i: isinstance(i, NewId), self._ids)
        if not ids:
            return self
        query = Query(self)
        query.add_where(SQL("%s IN %s", SQL.identifier(self._table, 'id'), tuple(ids)))
        real_ids = (id_ for [id_] in self.env.execute_query(query.select()))
        valid_ids = {*real_ids, *new_ids}
        return self.browse(i for i in self._ids if i in valid_ids)

    @api.private
    def lock_for_update(self, *, allow_referencing: bool = False) -> None:
        """ Grab an exclusive write-lock to the rows with the given ids.

        This avoids blocking processing on the records due to concurrent
        modifications. If all records couldn't be locked, a `LockError`
        exception is raised.

        :param allow_referencing: Acquire a row lock which allows for other
            transactions to reference this record. Use only when modifying
            values that are not identifiers.
        :raise LockError: when some records could not be locked
        """
        ids = {id_ for id_ in self._ids if id_}
        if not ids:
            return
        query = Query(self)
        query.add_where(SQL("%s IN %s", SQL.identifier(self._table, 'id'), tuple(ids)))
        # Use SKIP LOCKED instead of NOWAIT because the later aborts the
        # transaction and we do not want to use SAVEPOINTS.
        if allow_referencing:
            lock_sql = SQL("FOR NO KEY UPDATE SKIP LOCKED")
        else:
            lock_sql = SQL("FOR UPDATE SKIP LOCKED")
        rows = self.env.execute_query(SQL("%s %s", query.select(), lock_sql))
        if len(rows) != len(ids):
            raise LockError(self.env._("Cannot grab a lock on records"))

    @api.private
    def try_lock_for_update(self, *, allow_referencing: bool = False, limit: int | None = None) -> Self:
        """ Grab an exclusive write-lock on some rows with the given ids.

        Skip locked records and browse the records that could be locked.

        :param allow_referencing: Acquire a row lock which allows for other
            transactions to reference this record. Use only when modifying
            values that are not identifiers.
        :param limit: The maximum number of rows to lock
        :return: The recordset of locked records
        """
        new_ids, ids = partition(lambda i: isinstance(i, NewId), self._ids)
        if limit is not None:
            if len(new_ids) >= limit:
                return self.browse(new_ids[:limit])
            # keep the order of ids when trying to lock
            query = self.browse(ids)._as_query(ordered=True)
            query.limit = limit - len(new_ids)
        else:
            query = Query(self)
            query.add_where(SQL("%s IN %s", SQL.identifier(self._table, 'id'), tuple(ids)))
        if not ids:
            return self
        if allow_referencing:
            lock_sql = SQL("FOR NO KEY UPDATE SKIP LOCKED")
        else:
            lock_sql = SQL("FOR UPDATE SKIP LOCKED")
        sql = SQL("%s %s", query.select(), lock_sql)
        real_ids = (id_ for [id_] in self.env.execute_query(sql))
        valid_ids = {*real_ids, *new_ids}
        return self.browse(i for i in self._ids if i in valid_ids)

    def _has_cycle(self, field_name=None) -> bool:
        """
        Return whether the records in ``self`` are in a loop by following the
        given relationship of the field.
        By default the **parent** field is used as the relationship.

        Note that since the method does not use EXCLUSIVE LOCK for the sake of
        performance, loops may still be created by concurrent transactions.

        :param field_name: optional field name (default: ``self._parent_name``)
        :return: **True** if a loop was found, **False** otherwise.
        """
        return orm_parent_store._has_cycle(self, field_name)

    def _get_external_ids(self) -> dict[IdType, list[str]]:
        """Retrieve the External ID(s) of any database record.

        **Synopsis**: ``_get_external_ids() -> { 'id': ['module.external_id'] }``

        :return: map of ids to the list of their fully qualified External IDs
                 in the form ``module.key``, or an empty list when there's no External
                 ID for a record, e.g.::

                     { 'id': ['module.ext_id', 'module.ext_id_bis'],
                       'id2': [] }
        """
        result = defaultdict(list)
        domain: DomainType = [('model', '=', self._name), ('res_id', 'in', self.ids)]
        for data in self.env['ir.model.data'].sudo().search_read(domain, ['module', 'name', 'res_id'], order='id'):
            result[data['res_id']].append('%(module)s.%(name)s' % data)
        return {
            record.id: result[record._origin.id]
            for record in self
        }

    def get_external_id(self) -> dict[IdType, str]:
        """Retrieve the External ID of any database record, if there
        is one. This method works as a possible implementation
        for a function field, to be able to add it to any
        model object easily, referencing it as ``Model.get_external_id``.

        When multiple External IDs exist for a record, only one
        of them is returned (randomly).

        :return: map of ids to their fully qualified XML ID,
                 defaulting to an empty string when there's none
                 (to be usable as a function field),
                 e.g.::

                     { 'id': 'module.ext_id',
                       'id2': '' }
        """
        results = self._get_external_ids()
        return {key: val[0] if val else ''
                for key, val in results.items()}

    @classmethod
    def is_transient(cls) -> bool:
        """ Return whether the model is transient.

        See :class:`TransientModel`.

        """
        return cls._transient

    @api.model
    @api.readonly
    def search_read(
        self,
        domain: DomainType | None = None,
        fields: Sequence[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
        **read_kwargs,
    ) -> list[ValuesType]:
        """ Perform a :meth:`search_fetch` followed by a :meth:`_read_format`.

        :param domain: Search domain, see ``args`` parameter in :meth:`search`.
            Defaults to an empty domain that will match all records.
        :param fields: List of fields to read, see ``fields`` parameter in :meth:`read`.
            Defaults to all fields.
        :param offset: Number of records to skip, see ``offset`` parameter in :meth:`search`.
            Defaults to 0.
        :param limit: Maximum number of records to return, see ``limit`` parameter in :meth:`search`.
            Defaults to no limit.
        :param order: Columns to sort result, see ``order`` parameter in :meth:`search`.
            Defaults to no sort.
        :param read_kwargs: All read keywords arguments used to call
            ``read(..., **read_kwargs)`` method e.g. you can use
            ``search_read(..., load='')`` in order to avoid computing display_name
        :return: List of dictionaries containing the asked fields.
        """
        if not fields:
            fields = list(self.fields_get(attributes=()))
        records = self.search_fetch(domain or [], fields, offset=offset, limit=limit, order=order)

        # Method _read_format() ignores 'active_test', but it would forward it
        # to any downstream search call(e.g. for x2m or computed fields), and
        # this is not the desired behavior. The flag was presumably only meant
        # for the main search().
        if 'active_test' in self.env.context:
            context = dict(self.env.context)
            del context['active_test']
            records = records.with_context(context)

        return records._read_format(fnames=fields, **read_kwargs)

    def action_archive(self):
        """Set :attr:`active` to ``False`` on a recordset for active records.

        Note, you probably want to override `write()` method if you want to take
        action once the active field changes.
        """
        field_name = self._active_name
        assert field_name, f"No 'active' field on model {self._name}"
        active_recs = self.filtered(lambda record: record[field_name])
        active_recs[field_name] = False

    def action_unarchive(self):
        """Set :attr:`active` to ``True`` on a recordset for inactive records.

        Note, you probably want to override `write()` method if you want to take
        action once the active field changes.
        """
        field_name = self._active_name
        assert field_name, f"No 'active' field on model {self._name}"
        inactive_recs = self.filtered(lambda record: not record[field_name])
        inactive_recs[field_name] = True

    def _register_hook(self) -> None:
        """ stuff to do right after the registry is built """

    def _unregister_hook(self) -> None:
        """ Clean up what `~._register_hook` has done. """

    def _get_redirect_suggested_company(self) -> BaseModel | typing.Literal[False]:
        """Return the suggested company to be set on the context
        in case of a URL redirection to the record. To avoid multi
        company issues when clicking on a shared link, this
        could be called to try setting the most suited company on
        the allowed_company_ids in the context. This method can be
        overridden, for example on the hr.leave model, where the
        most suited company is the company of the leave type, as
        specified by the access rules.
        """
        if 'company_id' in self:
            return self.company_id
        elif 'company_ids' in self:
            return (self.company_ids & self.env.user.company_ids)[:1]
        return False

    def _can_return_content(
            self, field_name: str | None = None, access_token: str | None = None
    ) -> bool:
        """Determine whether one can export a file or an image from a field of
        record ``self``, even if ``self`` is not accessible to the current user.
        If so, the record will be ``sudo()``-ed to access the corresponding file
        or image.

        :param field_name: image field name to check the access to
        :param access_token: access token to use instead of the
            access rights and access rules
        :return: whether the extra access is allowed
        """
        self.ensure_one()
        return False

    #
    # Instance creation
    #
    # An instance represents an ordered collection of records in a given
    # execution environment. The instance object refers to the environment, and
    # the records themselves are represented by their cache dictionary. The 'id'
    # of each record is found in its corresponding cache dictionary.
    #
    # This design has the following advantages:
    #  - cache access is direct and thus fast;
    #  - one can consider records without an 'id' (see new records);
    #  - the global cache is only an index to "resolve" a record 'id'.
    #

    def __init__(self, env: Environment, ids: tuple[IdType, ...], prefetch_ids: Reversible[IdType]):
        """ Create a recordset instance.

        :param env: an environment
        :param ids: a tuple of record ids
        :param prefetch_ids: a reversible iterable of record ids (for prefetching)
        """
        self.env = env
        self._ids = ids
        self._prefetch_ids = prefetch_ids

    @api.private
    def browse(self, ids: int | typing.Iterable[IdType] = ()) -> Self:
        """Return a recordset for the ids provided as parameter in the current
        environment.

        .. code-block:: python

            self.browse([7, 18, 12])
            res.partner(7, 18, 12)
        """
        if not ids:
            ids = ()
        elif ids.__class__ is int:
            ids = (ids,)
        else:
            ids = tuple(ids)
            assert all(ids) or all(isinstance(x, NewId) or x for x in ids), "Invalid falsy real id"
        return self.__class__(self.env, ids, ids)

    #
    # Internal properties, for manipulating the instance's implementation
    #

    @property
    def ids(self) -> list[int]:
        """ Return the list of actual record ids corresponding to ``self``. """
        if all(self._ids):
            return list(self._ids)  # already real records
        return list(OriginIds(self._ids))

    @property
    @deprecated("Deprecated since 19.0, use self.env.cr directly")
    def _cr(self):
        return self.env.cr

    @property
    @deprecated("Deprecated since 19.0, use self.env.uid directly")
    def _uid(self):
        return self.env.uid

    @property
    @deprecated("Deprecated since 19.0, use self.env.context directly")
    def _context(self):
        return self.env.context

    #
    # Conversion methods
    #

    @api.private
    def ensure_one(self) -> Self:
        """Verify that the current recordset holds a single record.

        :raise odoo.exceptions.ValueError: ``len(self) != 1``
        """
        try:
            # unpack to ensure there is only one value is faster than len when true and
            # has a significant impact as this check is largely called
            _id, = self._ids
            return self
        except ValueError:
            raise ValueError("Expected singleton: %s" % self)

    @api.private
    def with_env(self, env: Environment) -> Self:
        """Return a new version of this recordset attached to the provided environment.

        .. note::
            The returned recordset has the same prefetch object as ``self``.
        """
        return self.__class__(env, self._ids, self._prefetch_ids)

    @api.private
    def sudo(self, flag: bool = True) -> Self:
        """ Return a new version of this recordset with superuser mode enabled or
        disabled, depending on `flag`. The superuser mode does not change the
        current user, and simply bypasses access rights checks.

        .. warning::

            Using ``sudo`` could cause data access to cross the
            boundaries of record rules, possibly mixing records that
            are meant to be isolated (e.g. records from different
            companies in multi-company environments).

            It may lead to un-intuitive results in methods which select one
            record among many - for example getting the default company, or
            selecting a Bill of Materials.

        .. note::

            The returned recordset has the same prefetch object as ``self``.

        """
        assert isinstance(flag, bool)
        if flag == self.env.su:
            return self
        return self.with_env(self.env(su=flag))

    @api.private
    def with_user(self, user: BaseModel | IdType) -> Self:
        """ Return a new version of this recordset attached to the given user, in
        non-superuser mode, unless `user` is the superuser (by convention, the
        superuser is always in superuser mode.)
        """
        if not user:
            return self
        return self.with_env(self.env(user=user, su=False))

    @api.private
    def with_company(self, company: BaseModel | IdType) -> Self:
        """ Return a new version of this recordset with a modified context, such that::

            result.env.company = company
            result.env.companies = company | self.env.companies

        Note that the second equality specifies the order of ``result.env.companies``.

        .. warning::

            When using an unauthorized company for current user,
            accessing the company(ies) on the environment may trigger
            an AccessError if not done in a sudoed environment.
        """
        if not company:
            # With company = None/False/0/[]/empty recordset: keep current environment
            return self

        company_id = int(company)
        allowed_company_ids = self.env.companies.ids
        if company_id == allowed_company_ids[0]:
            return self
        if company_id in allowed_company_ids:
            allowed_company_ids.remove(company_id)
        allowed_company_ids.insert(0, company_id)

        return self.with_context(allowed_company_ids=allowed_company_ids)

    @api.private
    def with_context(self, ctx: dict[str, typing.Any] | None = None, /, **overrides) -> Self:
        """ Return a new version of this recordset attached to an extended
        context.

        The extended context is either the provided ``context`` in which
        ``overrides`` are merged or the *current* context in which
        ``overrides`` are merged e.g.::

            # current context is {'key1': True}
            r2 = records.with_context({}, key2=True)
            # -> r2.env.context is {'key2': True}
            r2 = records.with_context(key2=True)
            # -> r2.env.context is {'key1': True, 'key2': True}

        .. note:

            The returned recordset has the same prefetch object as ``self``.
        """  # noqa: RST210
        context = dict(ctx if ctx is not None else self.env.context, **overrides)
        if 'company' in context:
            warnings.warn(
                "Context key 'company' is not recommended, because "
                "of its special meaning in @depends_context.",
            )
        if 'allowed_company_ids' not in context and 'allowed_company_ids' in self.env.context:
            # Force 'allowed_company_ids' to be kept when context is overridden
            # without 'allowed_company_ids'
            context['allowed_company_ids'] = self.env.context['allowed_company_ids']
        return self.with_env(self.env(context=context))

    @api.private
    def with_prefetch(self, prefetch_ids: Reversible[IdType] | None = None) -> Self:
        """ Return a new version of this recordset that uses the given prefetch ids,
        or ``self``'s ids if not given.
        """
        if prefetch_ids is None:
            prefetch_ids = self._ids
        return self.__class__(self.env, self._ids, prefetch_ids)

    def _update_cache(self, values: ValuesType, validate: bool = True) -> None:
        """ Update the cache of ``self`` with ``values``.

            :param values: dict of field values, in any format.
            :param validate: whether values must be checked
        """
        self.ensure_one()
        fields = self._fields
        try:
            field_values = [(fields[name], value) for name, value in values.items() if name != 'id']
        except KeyError as e:
            raise ValueError("Invalid field %r on model %r" % (e.args[0], self._name))

        # convert monetary fields after other columns for correct value rounding
        for field, value in sorted(field_values, key=lambda item: self._fields_update_order__[item[0]]):
            value = field.convert_to_cache(value, self, validate)
            field._update_cache(self, value)

            # set inverse fields on new records in the comodel
            if field.relational:
                inv_recs = self[field.name].filtered(lambda r: not r.id)
                if not inv_recs:
                    continue
                # we need to adapt the value of the inverse fields to integrate self into it:
                # x2many fields should add self, while many2one fields should replace with self
                for invf in self.pool.field_inverses[field]:
                    invf._update_inverse(inv_recs, self)

    def _convert_to_record(self, values):
        """ Convert the ``values`` dictionary from the cache format to the
        record format.
        """
        return {
            name: self._fields[name].convert_to_record(value, self)
            for name, value in values.items()
        }

    def _convert_to_write(self, values):
        """ Convert the ``values`` dictionary into the format of :meth:`write`. """
        fields = self._fields
        result = {}
        for name, value in values.items():
            if name in fields:
                field = fields[name]
                value = field.convert_to_write(value, self)
                if not isinstance(value, NewId):
                    result[name] = value
        return result

    #
    # Record traversal and update
    #

    @typing.overload
    def mapped(self, func: str) -> list[typing.Any] | BaseModel:
        ...

    @typing.overload
    def mapped[T](self, func: Callable[[Self], T]) -> list[T] | BaseModel:
        ...

    @api.private
    def mapped[T](self, func: str | Callable[[Self], T]) -> list | BaseModel:
        """Apply ``func`` on all records in ``self``, and return the result as a
        list or a recordset (if ``func`` return recordsets). In the latter
        case, the order of the returned recordset is arbitrary.

        :param func: a function or a dot-separated sequence of field names
        :return: self if func is falsy, result of func applied to all ``self`` records.

        .. code-block:: python3

            # returns a list of summing two fields for each record in the set
            records.mapped(lambda r: r.field1 + r.field2)

        The provided function can be a string to get field values:

        .. code-block:: python3

            # returns a list of names
            records.mapped('name')

            # returns a recordset of partners
            records.mapped('partner_id')

            # returns the union of all partner banks, with duplicates removed
            records.mapped('partner_id.bank_ids')
        """
        if not func:
            return self                 # support for an empty path of fields

        if isinstance(func, str):
            # special case: sequence of field names
            *rel_field_names, field_name = func.split('.')
            records = self
            for rel_field_name in rel_field_names:
                records = records[rel_field_name]
            field = records._fields[field_name]
            getter = field.__get__
            if field.relational:
                # union of records
                return getter(records)
            return [getter(record) for record in records]

        if self:
            vals = [func(rec) for rec in self]
            if isinstance(vals[0], BaseModel):
                return vals[0].browse().union(vals)
            return vals
        else:
            # we want to follow-up the comodel from the function
            # so we pass an empty recordset
            vals = func(self)
            return vals if isinstance(vals, BaseModel) else []

    @api.private
    def filtered(self, func: str | Callable[[Self], bool] | Domain) -> Self:
        """Return the records in ``self`` satisfying ``func``.

        :param func: a function, Domain or a dot-separated sequence of field names
        :return: recordset of records satisfying func, may be empty.

        .. code-block:: python3

            # only keep records whose company is the current user's
            records.filtered(lambda r: r.company_id == user.company_id)

            # only keep records whose partner has VAT
            records.filtered("partner_id.vat")
        """
        return orm_recordset.filtered(self, func)

    @typing.overload
    def grouped(self, key: str) -> dict[typing.Any, Self]:
        ...

    @typing.overload
    def grouped[T](self, key: Callable[[Self], T]) -> dict[T, Self]:
        ...

    @api.private
    def grouped[T](self, key: str | Callable[[Self], T]) -> dict[typing.Any, Self]:
        """Eagerly groups the records of ``self`` by the ``key``, returning a
        dict from the ``key``'s result to recordsets. All the resulting
        recordsets are guaranteed to be part of the same prefetch-set.

        Provides a convenience method to partition existing recordsets without
        the overhead of a :meth:`~._read_group`, but performs no aggregation.

        .. note:: unlike :func:`itertools.groupby`, does not care about input
                  ordering, however the tradeoff is that it can not be lazy

        :param key: either a callable from a :class:`Model` to a (hashable)
                    value, or a field name. In the latter case, it is equivalent
                    to ``itemgetter(key)`` (aka the named field's value)
        """
        if isinstance(key, str):
            key = itemgetter(key)

        collator = defaultdict(list)
        for record in self:
            collator[key(record)].extend(record._ids)

        browse = functools.partial(type(self), self.env, prefetch_ids=self._prefetch_ids)
        return {key: browse(tuple(ids)) for key, ids in collator.items()}

    @api.private
    def filtered_domain(self, domain: DomainType) -> Self:
        """Return the records in ``self`` satisfying the domain and keeping the same order.

        :param domain: :ref:`A search domain <reference/orm/domains>`.
        """
        return orm_recordset.filtered_domain(self, domain)

    @api.private
    def sorted(self, key: Callable[[Self], typing.Any] | str | None = None, reverse: bool = False) -> Self:
        """Return the recordset ``self`` ordered by ``key``.

        :param key:
            It can be either of:

            * a function of one argument that returns a comparison key for each record
            * a string representing a comma-separated list of field names with optional
              NULLS (FIRST|LAST), and (ASC|DESC) directions
            * ``None``, in which case records are ordered according the default model's order
        :param reverse: if ``True``, return the result in reverse order

        .. code-block:: python3

            # sort records by name
            records.sorted(key=lambda r: r.name)
            # sort records by name in descending order, then by id
            records.sorted('name DESC, id')
            # sort records using default order
            records.sorted()
        """
        return orm_recordset.sort(self, key, reverse)

    @api.model
    def _sorted_order_to_function(self, order: str) -> Callable[[BaseModel], tuple]:
        return orm_recordset._sorted_order_to_function(self, order)

    @api.private
    def update(self, values: ValuesType) -> None:
        """ Update the records in ``self`` with ``values``. """
        for name, value in values.items():
            self[name] = value

    @api.private
    def flush_model(self, fnames: Collection[str] | None = None) -> None:
        """ Process the pending computations and database updates on ``self``'s
        model.  When the parameter is given, the method guarantees that at least
        the given fields are flushed to the database.  More fields can be
        flushed, though.

        :param fnames: optional iterable of field names to flush
        """
        return orm_recompute.flush_model(self, fnames)

    @api.private
    def flush_recordset(self, fnames: Collection[str] | None = None) -> None:
        """ Process the pending computations and database updates on the records
        ``self``.   When the parameter is given, the method guarantees that at
        least the given fields on records ``self`` are flushed to the database.
        More fields and records can be flushed, though.

        :param fnames: optional iterable of field names to flush
        """
        return orm_recompute.flush_recordset(self, fnames)

    def _flush(self) -> None:
        # pop dirty fields and their corresponding record ids from cache
        return orm_recompute._flush(self)

    #
    # New records - represent records that do not exist in the database yet;
    # they are used to perform onchanges.
    #

    @api.model
    @api.private
    def new(self, values: ValuesType | None = None, origin: Self | None = None, ref: str | None = None) -> Self:
        """ Return a new record instance attached to the current environment and
        initialized with the provided ``value``. The record is *not* created
        in database, it only exists in memory.

        One can pass an ``origin`` record, which is the actual record behind the
        result. It is retrieved as ``record._origin``. Two new records with the
        same origin record are considered equal.

        One can also pass a ``ref`` value to identify the record among other new
        records. The reference is encapsulated in the ``id`` of the record.
        """
        assert not self._abstract, f"Cannot instantiate abstract model {self._name}"
        if values is None:
            values = {}
        if origin is not None:
            origin = origin.id
        record = self.browse((NewId(origin, ref),))
        record._update_cache(values, validate=False)

        return record

    @property
    def _origin(self) -> Self:
        """ Return the actual records corresponding to ``self``. """
        if all(self._ids):
            return self  # already real records
        ids = tuple(OriginIds(self._ids))
        prefetch_ids = OriginIds(self._prefetch_ids)
        return self.__class__(self.env, ids, prefetch_ids)

    #
    # "Dunder" methods
    #

    def __bool__(self) -> bool:
        """ Test whether ``self`` is nonempty. """
        return True if self._ids else False  # fast version of bool(self._ids)

    def __len__(self) -> int:
        """ Return the size of ``self``. """
        return len(self._ids)

    def __iter__(self) -> Iterator[Self]:
        """ Return an iterator over ``self``. """
        ids = self._ids
        size = len(ids)
        if size <= 1:
            # detect and handle small recordsets (single `1f`)
            # early return if no records and avoid allocation if we have a one
            if size == 1:
                yield self
            return
        cls = self.__class__
        env = self.env
        prefetch_ids = self._prefetch_ids
        for id_ in ids:
            yield cls(env, (id_,), prefetch_ids)

    def __reversed__(self) -> Iterator[Self]:
        """ Return an reversed iterator over ``self``. """
        # same as __iter__ but reversed
        ids = self._ids
        size = len(ids)
        if size <= 1:
            if size == 1:
                yield self
            return
        cls = self.__class__
        env = self.env
        prefetch_ids = ReversedIterable(self._prefetch_ids)
        for id_ in reversed(ids):
            yield cls(env, (id_,), prefetch_ids)

    def __contains__(self, item: BaseModel | str) -> bool:
        """ Test whether ``item`` (record or field name) is an element of ``self``.

            In the first case, the test is fully equivalent to::

                any(item == record for record in self)

            In the second case, we check whether the model has a field named
            ``item``.
        """
        try:
            if self._name == item._name:
                return len(item) == 1 and item.id in self._ids
            raise TypeError(f"inconsistent models in: {item} in {self}")
        except AttributeError:
            if isinstance(item, str):
                return item in self._fields
            raise TypeError(f"unsupported operand types in: {item!r} in {self}")

    def __add__(self, other) -> Self:
        """ Return the concatenation of two recordsets. """
        try:
            if other._name != self._name:
                raise TypeError(f"inconsistent models in: {self} + {other}")
            if other:
                ids = self._ids + other._ids
                return self.__class__(self.env, ids, Prefetch.union(ids, self._prefetch_ids, other._prefetch_ids))
        except AttributeError:
            raise TypeError(f"unsupported operand types in: {self} + {other!r}")
        return self

    @api.private
    def concat(self, it: Iterable[Self] = (), /, *args: Self) -> Self:
        """ Return the concatenation of ``self`` with all the arguments (in
            linear time complexity).
        """
        if args:
            warnings.warn("Since 20.0, use concat() with only one iterable")
        if self:
            warnings.warn("Since 20.0, use concat() on an empty recordset")
        ids = []
        prefetch_ids_list = []
        for arg in (self, *it, *args):
            try:
                if arg._name != self._name:
                    raise TypeError(f"inconsistent models in: {self} + {arg}")
                if not arg._ids:
                    continue
                ids.extend(arg._ids)
                prefetch_ids_list.append(arg._prefetch_ids)
            except AttributeError:
                raise TypeError(f"unsupported operand types in: {self} + {arg!r}")
        ids = tuple(ids)
        if len(prefetch_ids_list) == 1:
            prefetch_ids = prefetch_ids_list[0]
        else:
            prefetch_ids = Prefetch.union(ids, *prefetch_ids_list)
        return self.__class__(self.env, ids, prefetch_ids)

    def __sub__(self, other) -> Self:
        """ Return the recordset of all the records in ``self`` that are not in
            ``other``. Note that recordset order is preserved.
        """
        try:
            if self._name != other._name:
                raise TypeError(f"inconsistent models in: {self} - {other}")
            other_ids = set(other._ids)
            ids = tuple(id_ for id_ in self._ids if id_ not in other_ids)
            return self.__class__(self.env, ids, Prefetch.union(ids, self._prefetch_ids))
        except AttributeError:
            raise TypeError(f"unsupported operand types in: {self} - {other!r}")

    def __and__(self, other) -> Self:
        """ Return the intersection of two recordsets.
            Note that first occurrence order is preserved.
        """
        try:
            if self._name != other._name:
                raise TypeError(f"inconsistent models in: {self} & {other}")
            other_ids = set(other._ids)
            ids = tuple({id_: None for id_ in self._ids if id_ in other_ids})
            return self.__class__(self.env, ids, Prefetch.union(ids, self._prefetch_ids))
        except AttributeError:
            raise TypeError(f"unsupported operand types in: {self} & {other!r}")

    def __or__(self, other) -> Self:
        """ Return the union of two recordsets.
            Note that first occurrence order is preserved.
        """
        try:
            if other._name != self._name:
                raise TypeError(f"inconsistent models in: {self} | {other}")
            if other:
                ids = tuple(dict.fromkeys(self._ids + other._ids))
                return self.__class__(self.env, ids, Prefetch.union(ids, self._prefetch_ids, other._prefetch_ids))
        except AttributeError:
            raise TypeError(f"unsupported operand types in: {self} | {other!r}")
        return self

    @api.private
    def union(self, it: Iterable[Self] = (), /, *args: Self) -> Self:
        """ Return the union of ``self`` with all the arguments (in linear time
            complexity, with first occurrence order preserved).
        """
        if args:
            warnings.warn("Since 20.0, use union() with only one iterable")
        if self:
            warnings.warn("Since 20.0, use union() on an empty recordset")
        ids = []
        prefetch_ids_list = []
        for arg in (self, *it, *args):
            try:
                if arg._name != self._name:
                    raise TypeError(f"inconsistent models in: {self} | {arg}")
                if not arg._ids:
                    continue
                ids.extend(arg._ids)
                prefetch_ids_list.append(arg._prefetch_ids)
            except AttributeError:
                raise TypeError(f"unsupported operand types in: {self} | {arg!r}")
        ids = tuple(dict.fromkeys(ids))
        if len(prefetch_ids_list) == 1:
            prefetch_ids = prefetch_ids_list[0]
        else:
            prefetch_ids = Prefetch.union(ids, *prefetch_ids_list)
        return self.__class__(self.env, ids, prefetch_ids)

    def __eq__(self, other):
        """ Test whether two recordsets are equivalent (up to reordering). """
        try:
            return self._name == other._name and set(self._ids) == set(other._ids)
        except AttributeError:
            if other:
                warnings.warn(f"unsupported operand type(s) for \"==\": '{self._name}()' == '{other!r}'", stacklevel=2)
        return NotImplemented

    def __lt__(self, other):
        try:
            if self._name == other._name:
                return set(self._ids) < set(other._ids)
        except AttributeError:
            pass
        return NotImplemented

    def __le__(self, other):
        try:
            if self._name == other._name:
                # these are much cheaper checks than a proper subset check, so
                # optimise for checking if a null or singleton are subsets of a
                # recordset
                if not self or self in other:
                    return True
                return set(self._ids) <= set(other._ids)
        except AttributeError:
            pass
        return NotImplemented

    def __gt__(self, other):
        try:
            if self._name == other._name:
                return set(self._ids) > set(other._ids)
        except AttributeError:
            pass
        return NotImplemented

    def __ge__(self, other):
        try:
            if self._name == other._name:
                if not other or other in self:
                    return True
                return set(self._ids) >= set(other._ids)
        except AttributeError:
            pass
        return NotImplemented

    def __int__(self) -> int:
        return self.id or 0

    def __repr__(self):
        return f"{self._name}{self._ids!r}"

    def __hash__(self):
        return hash((self._name, frozenset(self._ids)))

    def __deepcopy__(self, memo):
        return self

    @typing.overload
    def __getitem__(self, key: int | slice) -> Self: ...

    @typing.overload
    def __getitem__(self, key: str) -> typing.Any: ...

    def __getitem__(self, key):
        """ If ``key`` is an integer or a slice, return the corresponding record
            selection as an instance (attached to ``self.env``).
            Otherwise read the field ``key`` of the first record in ``self``.

            Examples::

                inst = model.search(dom)    # inst is a recordset
                r4 = inst[3]                # fourth record in inst
                rs = inst[10:20]            # subset of inst
                nm = rs['name']             # name of first record in inst
        """
        if isinstance(key, str):
            # important: one must call the field's getter
            return self._fields[key].__get__(self)
        if isinstance(key, slice):
            ids = self._ids[key]
            prefetch_ids = Prefetch.union(ids, self._prefetch_ids)
        else:
            ids = (self._ids[key],)
            prefetch_ids = self._prefetch_ids
        return self.__class__(self.env, ids, prefetch_ids)

    def __setitem__(self, key: str, value: typing.Any):
        """ Assign the field ``key`` to ``value`` in record ``self``. """
        # important: one must call the field's setter
        return self._fields[key].__set__(self, value)

    #
    # Cache and recomputation management
    #

    @property
    def _cache(self):
        """ Return the cache of ``self``, mapping field names to values. """
        return RecordCache(self)

    @api.private
    def invalidate_model(self, fnames: Collection[str] | None = None, flush: bool = True) -> None:
        """ Invalidate the cache of all records of ``self``'s model, when the
        cached values no longer correspond to the database values.  If the
        parameter is given, only the given fields are invalidated from cache.

        :param fnames: optional iterable of field names to invalidate
        :param flush: whether pending updates should be flushed before invalidation.
            It is ``True`` by default, which ensures cache consistency.
            Do not use this parameter unless you know what you are doing.
        """
        return orm_recompute.invalidate_model(self, fnames, flush)

    @api.private
    def invalidate_recordset(self, fnames: Collection[str] | None = None, flush: bool = True) -> None:
        """ Invalidate the cache of the records in ``self``, when the cached
        values no longer correspond to the database values.  If the parameter
        is given, only the given fields on ``self`` are invalidated from cache.

        :param fnames: optional iterable of field names to invalidate
        :param flush: whether pending updates should be flushed before invalidation.
            It is ``True`` by default, which ensures cache consistency.
            Do not use this parameter unless you know what you are doing.
        """
        return orm_recompute.invalidate_recordset(self, fnames, flush)

    def _invalidate_cache(self, fnames: Collection[str] | None = None, ids: Sequence[IdType] | None = None) -> None:
        if ids is not None and not ids:  # Avoid invalidating field_inverses for no reason
            return

        if fnames is None:
            fields = self._fields.values()
        else:
            fields = [self._fields[fname] for fname in fnames]

        env = self.env
        for field in fields:
            field._invalidate_cache(env, ids)
            if field.type == 'one2many':
                # skip invalidation of inverse for o2m fields
                # (o2m is "computed" from m2o)
                continue
            for invf in self.pool.field_inverses[field]:
                self.env[invf.model_name].flush_model([invf.name])
                invf._invalidate_cache(env)
        self.env.transaction.invalidate_access_cache(self._name)

    @api.private
    def modified(self, fnames: Collection[str], create: bool = False, before: bool = False) -> None:
        """ Notify that fields will be or have been modified on ``self``. This
        invalidates the cache where necessary, and prepares the recomputation of
        dependent stored fields.

        :param fnames: iterable of field names modified on records ``self``
        :param create: whether called in the context of record creation
        :param before: whether called before modifying records ``self``
        """
        if not self or not fnames:
            return

        # The triggers of a field F is a tree that contains the fields that
        # depend on F, together with the fields to inverse to find out which
        # records to recompute.
        #
        # For instance, assume that G depends on F, H depends on X.F, I depends
        # on W.X.F, and J depends on Y.F. The triggers of F will be the tree:
        #
        #                              [G]
        #                            X/   \Y
        #                          [H]     [J]
        #                        W/
        #                      [I]
        #
        # This tree provides perfect support for the trigger mechanism:
        # when F is # modified on records,
        #  - mark G to recompute on records,
        #  - mark H to recompute on inverse(X, records),
        #  - mark I to recompute on inverse(W, inverse(X, records)),
        #  - mark J to recompute on inverse(Y, records).

        if before:
            # When called before modification, we should determine what
            # currently depends on self, and it should not be recomputed before
            # the modification.  So we only collect what should be marked for
            # recomputation.
            marked = self.env.transaction.tocompute     # {field: ids}
            tomark = defaultdict(OrderedSet)            # {field: ids}
        else:
            # When called after modification, one should traverse backwards
            # dependencies by taking into account all fields already known to
            # be recomputed.  In that case, we mark fieds to compute as soon as
            # possible.
            marked = {}
            tomark = self.env.transaction.tocompute

        # determine what to trigger (with iterators)
        todo = [self._modified([self._fields[fname] for fname in fnames], create)]

        # process what to trigger by lazily chaining todo
        for field, records, create in itertools.chain.from_iterable(todo):
            records -= self.env.protected(field)
            if not records:
                continue

            if field.recursive:
                # discard already processed records, in order to avoid cycles
                if field.compute and field.store:
                    ids = (marked.get(field) or set()) | (tomark.get(field) or set())
                    records = records.browse(id_ for id_ in records._ids if id_ not in ids)
                else:
                    # get only records that have a value in cache (in any context)
                    ids_in_cache = field._get_all_cache_ids(self.env)
                    records = records.browse(id_ for id_ in records._ids if id_ in ids_in_cache)
                if not records:
                    continue
                # recursively trigger recomputation of field's dependents
                todo.append(records._modified([field], create))

            # mark for recomputation (now or later, depending on 'before')
            if field.compute and field.store:
                tomark[field].update(records._ids)
            else:
                # Don't force the recomputation of compute fields which are
                # not stored as this is not really necessary.
                field._invalidate_cache(self.env, records._ids)

        if before:
            # effectively mark for recomputation now
            for field, ids in tomark.items():
                records = self.env[field.model_name].browse(ids)
                self.env.add_to_compute(field, records)

    def _modified(self, fields: list[Field], create: bool) -> Iterable[tuple[Field, BaseModel, bool]]:
        """ Return an iterator traversing a tree of field triggers on ``self``,
        traversing backwards field dependencies along the way, and yielding
        tuple ``(field, records, created)`` to recompute.
        """
        return orm_recompute._modified(self, fields, create)

    def _modified_triggers(self, tree: TriggerTree, create: bool = False) -> Iterable[tuple[Field, BaseModel, bool]]:
        """ Return an iterator traversing a tree of field triggers on ``self``,
        traversing backwards field dependencies along the way, and yielding
        tuple ``(field, records, created)`` to recompute.
        """
        return orm_recompute._modified_triggers(self, tree, create)

    def _recompute_model(self, fnames: Collection[str] | None = None) -> None:
        """ Process the pending computations of the fields of ``self``'s model.

        :param fnames: optional iterable of field names to compute
        """
        return orm_recompute._recompute_model(self, fnames)

    def _recompute_recordset(self, fnames: Collection[str] | None = None) -> None:
        """ Process the pending computations of the fields of the records in ``self``.

        :param fnames: optional iterable of field names to compute
        """
        return orm_recompute._recompute_recordset(self, fnames)

    def _recompute_field(self, field: Field, ids: Sequence[IdType] | None = None) -> None:
        return orm_recompute._recompute_field(self, field, ids)

    #
    # Generic onchange method
    #

    def _has_onchange(self, field: Field, other_fields: Collection[Field]) -> bool:
        """ Return whether ``field`` should trigger an onchange event in the
            presence of ``other_fields``.
        """
        return orm_onchange._has_onchange(self, field, other_fields)

    def _apply_onchange_methods(self, field_name: str, result: dict, excluded_methods=()) -> None:
        """ Apply onchange method(s) (not in ``excluded_methods``) for field ``field_name`` on ``self``.
        Value assignments are applied on ``self``, while warning messages are put in dictionary ``result``.
        """
        return orm_onchange._apply_onchange_methods(self, field_name, result, excluded_methods)

    def onchange(self, values: dict, field_names: list[str], fields_spec: dict) -> dict:
        raise NotImplementedError("onchange() is implemented in module 'web'")

    def _get_placeholder_filename(self, field: str) -> bool:
        """ Returns the filename of the placeholder to use,
            set on web/static/img by default, or the
            complete path to access it (eg: module/path/to/image.png).
        """
        return False


collections.abc.Set.register(BaseModel)
# not exactly true as BaseModel doesn't have index or count
collections.abc.Sequence.register(BaseModel)


class RecordCache(Mapping[str, typing.Any]):
    """ A mapping from field names to values, to read the cache of a record. """
    __slots__ = ['_record']

    def __init__(self, record: BaseModel):
        assert len(record) == 1, "Unexpected RecordCache(%s)" % record
        self._record = record

    def __contains__(self, name):
        """ Return whether `record` has a cached value for field ``name``. """
        record = self._record
        field = record._fields[name]
        return record.id in field._get_cache(record.env)

    def __getitem__(self, name):
        """ Return the cached value of field ``name`` for `record`. """
        record = self._record
        field = record._fields[name]
        return field._get_cache(record.env)[record.id]

    def __iter__(self):
        """ Iterate over the field names with a cached value. """
        record = self._record
        id_ = record.id
        env = record.env
        for name, field in record._fields.items():
            if id_ in field._get_cache(env):
                yield name

    def __len__(self):
        """ Return the number of fields with a cached value. """
        return sum(1 for name in self)


AbstractModel = BaseModel


class Model(AbstractModel):
    """ Main super-class for regular database-persisted Odoo models.

    Odoo models are created by inheriting from this class::

        class ResUsers(Model):
            ...

    The system will later instantiate the class once per database (on
    which the class' module is installed).
    """
    _auto: bool = True          # automatically create database backend
    _register: bool = False     # not visible in ORM registry, meant to be python-inherited only
    _abstract: typing.Literal[False] = False  # not abstract


def itemgetter_tuple(items):
    """ Fixes itemgetter inconsistency (useful in some cases) of not returning
    a tuple if len(items) == 1: always returns an n-tuple where n = len(items)
    """
    if len(items) == 0:
        return lambda a: ()
    if len(items) == 1:
        return lambda gettable: (gettable[items[0]],)
    return itemgetter(*items)


# delegation targets, imported last since they import helpers of this module
from odoo.orm.models import grouping as orm_grouping
from odoo.orm.models import export as orm_export
from odoo.orm.models import translations as orm_translations
from odoo.orm.models import properties as orm_properties
from odoo.orm.models import write as orm_write
from odoo.orm.models import parent_store as orm_parent_store
from odoo.orm.models import recompute as orm_recompute
from odoo.orm.models import recordset as orm_recordset
from odoo.orm.models import onchange as orm_onchange
