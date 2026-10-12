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
import functools
import inspect
import logging
import re
import typing
import warnings
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from operator import itemgetter

import psycopg2.errors
import psycopg2.extensions

from odoo.exceptions import AccessError
from odoo.tools import frozendict, OrderedSet, SQL, sql
from odoo.tools.func import deprecated
from odoo.tools.misc import ReversedIterable
from odoo.tools.safe_eval import _UNSAFE_ATTRIBUTES, safe_checker
from odoo.tools.translate import LazyTranslate

from odoo.orm.core import access as orm_access
from odoo.orm.database import schema as orm_schema

from odoo.orm.core import decorators as api
from odoo.orm.core.domains import Domain
from odoo.orm.fields import Field
from odoo.orm.fields.misc import Id
from odoo.orm.fields.temporal import Datetime
from odoo.orm.fields.textual import Char, StoredTranslations

from odoo.orm.database.query import Query, TableSQL
from odoo.orm.core.utils import OriginIds, Prefetch

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
        return orm_hooks._table_sql(self)

    @property
    def _constraint_methods(self):
        """ Return a list of methods implementing Python constraints. """
        return orm_hooks._constraint_methods(self)

    @property
    def _ondelete_methods(self):
        """ Return a list of methods implementing checks before unlinking. """
        return orm_hooks._ondelete_methods(self)

    @property
    def _onchange_methods(self):
        """ Return a dictionary mapping field names to onchange methods. """
        return orm_hooks._onchange_methods(self)

    def _is_an_ordinary_table(self):
        return self.pool.is_an_ordinary_table(self)

    def _ensure_xml_id(self, skip=False):
        """ Create missing external ids for records in ``self``, and return an
            iterator of pairs ``(record, xmlid)`` for the records in ``self``.

        :rtype: Iterable[Model, str | None]
        """
        return orm_ids._ensure_xml_id(self, skip)

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
        return orm_export.load(self, fields, data)

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
        return orm_create.default_get(self, fields)

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
        return orm_search.search_count(self, domain, limit)

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
        return orm_search.search(self, domain, offset, limit, order)

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
        return orm_search.search_fetch(self, domain, field_names, offset, limit, order)

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
        return orm_search._compute_display_name(self)

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
        return orm_search._search_display_name(self, operator, value)

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
        return orm_search.name_create(self, name)

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
        return orm_search.name_search(self, name, domain, operator, limit)

    @api.model
    def _add_missing_default_values(self, values: ValuesType) -> ValuesType:
        # avoid overriding inherited values when parent is set
        return orm_create._add_missing_default_values(self, values)

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
        return orm_metadata.fields_get(self, allfields, attributes)

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
        return orm_read.read(self, fields, load)

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
        return orm_translations._update_field_translations(self, field_name, translations, digest, source_lang)

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
        return orm_translations._get_stored_translations(self, field_name)

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
        return orm_read._fetch_field(self, field)

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
        return orm_read.fetch(self, field_names)

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
        return orm_read._determine_fields_to_fetch(self, field_names, ignore_when_in_cache)

    def _fetch_query(self, query: Query, fields: Sequence[Field]) -> Self:
        """ Fetch the given fields (iterable of :class:`Field` instances) from
        the given query, put them in cache, and return the fetched records.

        This method may be overridden to change what fields to actually fetch,
        or to change the values that are put in cache.
        """
        return orm_read._fetch_query(self, query, fields)

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
        return orm_metadata.get_metadata(self)

    def get_base_url(self) -> str:
        """ Return rooturl for a specific record.

        By default, it returns the ir.config.parameter of base_url
        but it can be overridden by model.

        :return: the base url for this record
        """
        return orm_metadata.get_base_url(self)

    def _check_company_domain(self, companies) -> Domain:
        """Domain to be used for company consistency between records regarding this model.

        :param companies: the allowed companies for the related record
        :type companies: BaseModel or list or tuple or int or unquote
        """
        return orm_companies._check_company_domain(self, companies)

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
        return orm_companies._check_company(self, fnames)

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
        return orm_write.unlink(self)

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
        return orm_write.write(self, vals)

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
        return orm_create.create(self, vals_list)

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
        return orm_create._create(self, data_list)

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
        return orm_create._load_records_write(self, values)

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
        return orm_create._load_records(self, data_list, update)

    def _check_qorder(self, word: str) -> None:
        return orm_search._check_qorder(self, word)

    def _order_to_sql(self, table: TableSQL, order: str, reverse: bool = False) -> SQL:
        """ Return an :class:`SQL` object that represents the given ORDER BY
        clause, without the ORDER BY keyword.  The method also checks whether
        the fields in the order are accessible for reading.
        """
        return orm_search._order_to_sql(self, table, order, reverse)

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
        return orm_search._order_field_to_sql(self, table, field_expr, direction, nulls)

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
        return orm_search._search(self, domain, offset, limit, order, active_test=active_test, bypass_access=bypass_access)

    def _as_query(self, ordered: bool = True) -> Query:
        """ Return a :class:`Query` that corresponds to the recordset ``self``.
        This method is convenient for making a query object with a known result.

        :param ordered: whether the recordset order must be enforced by the query
        """
        return orm_search._as_query(self, ordered)

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        """
        Copy given record's data with all its fields values

        :param default: field values to override in the original values of the copied record
        :return: list of dictionaries containing all the field values
        """
        return orm_copy.copy_data(self, default)

    def copy(self, default: ValuesType | None = None) -> Self:
        """ Duplicate record ``self`` updating it with default values.

        :param default: dictionary of field values to override in the
               original values of the copied record, e.g: ``{'field_name': overridden_value, ...}``
        :returns: new records

        """
        return orm_copy.copy(self, default)

    @api.private
    def exists(self) -> Self:
        """ The subset of records in ``self`` that exist.
        It can be used as a test on records::

            if record.exists():
                ...

        By convention, new records are returned as existing.
        """
        return orm_locking.exists(self)

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
        return orm_locking.lock_for_update(self, allow_referencing=allow_referencing)

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
        return orm_locking.try_lock_for_update(self, allow_referencing=allow_referencing, limit=limit)

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
        return orm_ids._get_external_ids(self)

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
        return orm_ids.get_external_id(self)

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
        return orm_search.search_read(self, domain, fields, offset, limit, order, **read_kwargs)

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
        return orm_metadata._get_redirect_suggested_company(self)

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
        return orm_metadata._can_return_content(self, field_name, access_token)

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
        return orm_records.browse(self, ids)

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
        return orm_records.ensure_one(self)

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
        return orm_records.sudo(self, flag)

    @api.private
    def with_user(self, user: BaseModel | IdType) -> Self:
        """ Return a new version of this recordset attached to the given user, in
        non-superuser mode, unless `user` is the superuser (by convention, the
        superuser is always in superuser mode.)
        """
        return orm_records.with_user(self, user)

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
        return orm_records.with_company(self, company)

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
        return orm_records.with_context(self, ctx, **overrides)

    @api.private
    def with_prefetch(self, prefetch_ids: Reversible[IdType] | None = None) -> Self:
        """ Return a new version of this recordset that uses the given prefetch ids,
        or ``self``'s ids if not given.
        """
        return orm_records.with_prefetch(self, prefetch_ids)

    def _update_cache(self, values: ValuesType, validate: bool = True) -> None:
        """ Update the cache of ``self`` with ``values``.

            :param values: dict of field values, in any format.
            :param validate: whether values must be checked
        """
        return orm_records._update_cache(self, values, validate)

    def _convert_to_record(self, values):
        """ Convert the ``values`` dictionary from the cache format to the
        record format.
        """
        return orm_records._convert_to_record(self, values)

    def _convert_to_write(self, values):
        """ Convert the ``values`` dictionary into the format of :meth:`write`. """
        return orm_records._convert_to_write(self, values)

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
        return orm_recordset.mapped(self, func)

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
        return orm_recordset.grouped(self, key)

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
        return orm_records.new(self, values, origin, ref)

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
        return orm_records.concat(self, it, *args)

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
        return orm_records.union(self, it, *args)

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
        return orm_records._invalidate_cache(self, fnames, ids)

    @api.private
    def modified(self, fnames: Collection[str], create: bool = False, before: bool = False) -> None:
        """ Notify that fields will be or have been modified on ``self``. This
        invalidates the cache where necessary, and prepares the recomputation of
        dependent stored fields.

        :param fnames: iterable of field names modified on records ``self``
        :param create: whether called in the context of record creation
        :param before: whether called before modifying records ``self``
        """
        return orm_recompute.modified(self, fnames, create, before)

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
from odoo.orm.models import search as orm_search
from odoo.orm.models import read as orm_read
from odoo.orm.models import create as orm_create
from odoo.orm.models import copy as orm_copy
from odoo.orm.models import locking as orm_locking
from odoo.orm.models import ids as orm_ids
from odoo.orm.models import metadata as orm_metadata
from odoo.orm.models import companies as orm_companies
from odoo.orm.models import records as orm_records
from odoo.orm.models import hooks as orm_hooks
