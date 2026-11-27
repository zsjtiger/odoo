"""The base class of the fields, the helpers of the fields and the descriptor protocol entry points. The methods are split by concern in the modules of this package."""

from __future__ import annotations

import functools
import logging
import operator as pyoperator
import typing
from operator import attrgetter
from odoo.tools import SQL
from odoo.tools.misc import frozendict, SENTINEL, Sentinel

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, MutableMapping, Sequence
    from typing import Self
    from odoo.orm.models.environments import Environment
    from odoo.orm.core.identifiers import IdType
    from odoo.orm.database.query import FieldSQL, TableSQL
    from odoo.orm.models.registry import Registry
    from odoo.orm.core.types import BaseModel, DomainType, ModelType, ValuesType


IR_MODELS = (
    'ir.model', 'ir.model.data', 'ir.model.fields', 'ir.model.fields.selection',
    'ir.model.relation', 'ir.model.constraint', 'ir.module.module',
)


COMPANY_DEPENDENT_FIELDS = (
    'char', 'float', 'boolean', 'integer', 'text', 'many2one', 'date', 'datetime', 'selection', 'html'
)


PYTHON_INEQUALITY_OPERATOR = {'<': pyoperator.lt, '>': pyoperator.gt, '<=': pyoperator.le, '>=': pyoperator.ge}


_logger = logging.getLogger('odoo.fields')


def resolve_mro(model: BaseModel, name: str, predicate) -> list[typing.Any]:
    """ Return the list of successively overridden values of attribute ``name``
        in mro order on ``model`` that satisfy ``predicate``.  Model registry
        classes are ignored.
    """
    result = []
    for cls in model._model_classes__:
        value = cls.__dict__.get(name, SENTINEL)
        if value is SENTINEL:
            continue
        if not predicate(value):
            break
        result.append(value)
    return result


def determine(needle, records: BaseModel, *args):
    """ Simple helper for calling a method given as a string or a function.

    :param needle: callable or name of method to call on ``records``
    :param BaseModel records: recordset to call ``needle`` on or with
    :params args: additional arguments to pass to the determinant
    :returns: the determined value if the determinant is a method name or callable
    :raise TypeError: if ``records`` is not a recordset, or ``needle`` is not
                      a callable or valid method name
    """
    from odoo.orm import models as _models  # noqa: PLC0415
    if not isinstance(records, _models.BaseModel):
        raise TypeError("Determination requires a subject recordset")
    if isinstance(needle, str):
        needle = getattr(records, needle)
        if needle.__name__.find('__'):
            return needle(*args)
    elif callable(needle):
        if needle.__name__.find('__'):
            return needle(records, *args)

    raise TypeError("Determination requires a callable or method name")


class Field[T]:
    """The field descriptor contains the field definition, and manages accesses
    and assignments of the corresponding field on records. The following
    attributes may be provided when instantiating a field:

    :param str string: the label of the field seen by users; if not
        set, the ORM takes the field name in the class (capitalized).

    :param str help: the tooltip of the field seen by users

    :param bool readonly: whether the field is readonly (default: ``False``)

        This only has an impact on the UI. Any field assignation in code will work
        (if the field is a stored field or an inversable one).

    :param bool required: whether the value of the field is required (default: ``False``)

    :param str index: whether the field is indexed in database, and the kind of index.
        Note: this has no effect on non-stored and virtual fields.
        The possible values are:

        * ``"btree"`` or ``True``: standard index, good for many2one
        * ``"btree_not_null"``: BTREE index without NULL values (useful when most
                                values are NULL, or when NULL is never searched for)
        * ``"trigram"``: Generalized Inverted Index (GIN) with trigrams (good for full-text search)
        * ``None`` or ``False``: no index (default)

    :param default: the default value for the field; this is either a static
        value, or a function taking a recordset and returning a value; use
        ``default=None`` to discard default values for the field
    :type default: value or callable

    :param str init_storage: the function that initializes null values in the column in the database;

        The function can initialize the column/relation in the database. It may
        call `model.pool.post_init` to delay the initialization after other
        columns. If the function returns a truthy value, the ORM will recompute
        the field. The ORM cannot be used in this function!

    :param str groups: comma-separated list of group xml ids (string); this
        restricts the field access to the users of the given groups only

    :param bool company_dependent: whether the field value is dependent of the current company;

        The value is stored on the model table as jsonb dict with the company id as the key.

        The field's default values stored in model ir.default are used as fallbacks for
        unspecified values in the jsonb dict.

    :param bool|callable copy: whether the field value should be copied when the
        record is duplicated (default: ``True`` for normal fields, ``False`` for
        ``one2many`` and computed fields, including property fields and
        related fields). Can also be a ``(record) -> value`` callable used by
        :meth:`~odoo.models.Model.copy_data` to produce the copied value
        (e.g. ``copy=mark_as_copy('name')``).
        Not called when the field is provided in ``default``.

    :param bool store: whether the field is stored in database
        (default:``True``, ``False`` for computed fields)

    :param bool default_export_compatible: whether the field must be exported
        by default in an import-compatible export

    :param str search: name of a method that implements search on the field.
        The method takes an operator and value. Basic domain optimizations are
        ran before calling this function.
        For instance, all ``'='`` are transformed to ``'in'``, and boolean
        fields conditions are made such that operator is ``'in'``/``'not in'``
        and value is ``[True]``.

        The method should ``return NotImplemented`` if it does not support the
        operator.
        In that case, the ORM can try to call it with other, semantically
        equivalent, operators. For instance, try with the positive operator if
        its corresponding negative operator is not implemented.
        The method must return a :ref:`reference/orm/domains` that replaces
        ``(field, operator, value)`` in its domain.

        Note that a stored field can actually have a search method. The search
        method will be invoked to rewrite the condition. This may be useful for
        sanitizing the values used in the condition, for instance.

        .. code-block:: python

            def _search_partner_ref(self, operator, value):
                if operator not in ('in', 'like'):
                    return NotImplemented
                ...  # add your logic here, example
                return Domain('partner_id.ref', operator, value)

    .. rubric:: Aggregation

    :param str aggregator: default aggregate function used by the webclient
        on this field when using "Group By" feature.

        Supported aggregators are:

        * ``count`` : number of rows
        * ``count_distinct`` : number of distinct rows
        * ``bool_and`` : true if all values are true, otherwise false
        * ``bool_or`` : true if at least one value is true, otherwise false
        * ``max`` : maximum value of all values
        * ``min`` : minimum value of all values
        * ``avg`` : the average (arithmetic mean) of all values
        * ``sum`` : sum of all values

    :param str group_expand: function used to expand results when grouping on the
        current field for kanban/list/gantt views. For selection fields,
        ``group_expand=True`` automatically expands groups for all selection keys.

        .. code-block:: python

            @api.model
            def _read_group_selection_field(self, values, domain):
                return ['choice1', 'choice2', ...] # available selection choices.

            @api.model
            def _read_group_many2one_field(self, records, domain):
                return records + self.search([custom_domain])

    .. rubric:: Computed Fields

    :param str compute: name of a method that computes the field

        .. seealso:: :ref:`Advanced Fields/Compute fields <reference/fields/compute>`

    :param bool precompute: whether the field should be computed before record insertion
        in database.  Should be used to specify manually some fields as precompute=True
        when the field can be computed before record insertion.
        (e.g. avoid statistics fields based on search/_read_group), many2one
        linking to the previous record, ... (default: `False`)

        .. warning::

            Precomputation only happens when no explicit value and no default
            value is provided to create().  This means that a default value
            disables the precomputation, even if the field is specified as
            precompute=True.

            Precomputing a field can be counterproductive if the records of the
            given model are not created in batch.  Consider the situation were
            many records are created one by one.  If the field is not
            precomputed, it will normally be computed in batch at the flush(),
            and the prefetching mechanism will help making the computation
            efficient.  On the other hand, if the field is precomputed, the
            computation will be made one by one, and will therefore not be able
            to take advantage of the prefetching mechanism.

            Following the remark above, precomputed fields can be interesting on
            the lines of a one2many, which are usually created in batch by the
            ORM itself, provided that they are created by writing on the record
            that contains them.

    :param bool compute_sudo: whether the field should be recomputed as superuser
        to bypass access rights (by default ``True`` for stored fields, ``False``
        for non stored fields)

    :param bool recursive: whether the field has recursive dependencies (the field
        ``X`` has a dependency like ``parent_id.X``); declaring a field recursive
        must be explicit to guarantee that recomputation is correct

    :param str compute_sql: name of a method that produces SQL for the field

        .. seealso:: :ref:`Advanced Fields/Compute fields <reference/fields/compute>`

    :param str inverse: name of a method that inverses the field (optional)

    :param str related: sequence of field names

        .. seealso:: :ref:`Advanced fields/Related fields <reference/fields/related>`
    """
    type: str                           # type of the field (string)
    relational: bool = False            # whether the field is a relational one
    translate: bool = False             # whether the field is translated
    is_text: bool = False               # whether the field is a text type in the database
    falsy_value: T | None = None        # falsy value for comparisons (optional)
    write_sequence: int = 0
    _column_type: tuple[str, str] | None = None
    _args__: dict[str, typing.Any] | None = None  # the parameters given to __init__()
    _module: str | None = None          # the field's module name
    _modules: tuple[str, ...] = ()      # modules that define this field
    _setup_done = True                  # whether the field is completely set up
    _base_fields__: tuple[Self, ...] = ()  # the fields defining self, in override order
    _extra_keys__: tuple[str, ...] = ()  # unknown attributes set on the field
    _shareable: bool = True             # whether self can be shared across registries
    inherited: bool = False             # whether the field is inherited (_inherits)
    inherited_field: Field | None = None  # the corresponding inherited field
    name: str = ''                      # name of the field
    model_name: str = ''                # name of the model of this field
    store: bool = True                  # whether the field is stored in database
    index: str | None = None            # how the field is indexed in database
    manual: bool = False                # whether the field is a custom field
    copy: bool | Callable[[BaseModel], typing.Any] = True  # copied by BaseModel.copy()
    _depends: Collection[str] | None = None  # collection of field dependencies
    _depends_context: Collection[str] | None = None  # collection of context key dependencies
    recursive: bool = False             # whether self depends on itself
    compute: str | Callable[[BaseModel], None] | None = None   # compute(recs) computes field on recs
    compute_sudo: bool = False          # whether field should be recomputed as superuser
    precompute: bool = False            # whether field has to be computed before creation
    compute_sql: str | Callable[[BaseModel, TableSQL], SQL] | None = None      # compute_sql(model, alias, query) that gets the SQL for the field
    inverse: str | Callable[[BaseModel], None] | None = None  # inverse(recs) inverses field on recs
    search: str | Callable[[BaseModel, str, typing.Any], DomainType] | None = None  # search(recs, operator, value) searches on self
    related: str | None = None          # sequence of field names, for related fields
    company_dependent: bool = False     # whether ``self`` is company-dependent (property field)
    default: Callable[[BaseModel], T] | T | None = None  # default(recs) returns the default value
    init_storage: str | Callable[[BaseModel], bool | None] | None = None  # initialize field values
    string: str | None = None           # field label
    export_string_translation: bool = True  # whether the field label translations are exported
    help: str | None = None             # field tooltip
    readonly: bool = False              # whether the field is readonly
    required: bool = False              # whether the field is required (NOT NULL in database)
    groups: str | None = None           # csv list of group xml ids
    change_default = False              # whether the field may trigger a "user-onchange"
    related_field: Field | None = None  # corresponding related field
    aggregator: str | None = None       # operator for aggregating values
    group_expand: str | Callable[[BaseModel, ModelType, DomainType], ModelType] | None = None  # name of method to expand groups in formatted_read_group()
    falsy_value_label: str | None = None  # value to display when the field is not set (webclient attr)
    prefetch: bool | str = True         # the prefetch group (False means no group)
    default_export_compatible: bool = False  # whether the field must be exported by default in an import-compatible export
    exportable: bool = True
    _by_type__: dict[str, Field] = {}
    def __init__(self, string: str | Sentinel = SENTINEL, **kwargs):
        kwargs['string'] = string
        self._args__ = frozendict({key: val for key, val in kwargs.items() if val is not SENTINEL})
    def __str__(self):
        if not self.name:
            return "<%s.%s>" % (__name__, type(self).__name__)
        return "%s.%s" % (self.model_name, self.name)
    def __repr__(self):
        return repr(str(self))
    def __init_subclass__(cls):
        super().__init_subclass__()
        if not hasattr(cls, 'type'):
            return

        if cls.type:
            cls._by_type__.setdefault(cls.type, cls)

        # compute class attributes to avoid calling dir() on fields
        cls.related_attrs = []
        cls.description_attrs = []
        for attr in dir(cls):
            if attr.startswith('_related_'):
                cls.related_attrs.append((attr[9:], attr))
            elif attr.startswith('_description_'):
                cls.description_attrs.append((attr[13:], attr))
        cls.related_attrs = tuple(cls.related_attrs)
        cls.description_attrs = tuple(cls.description_attrs)
    def __set_name__(self, owner: type[BaseModel], name: str) -> None:
        return _setup.__set_name__(self, owner, name)
    def _get_attrs(self, model_class: type[BaseModel], name: str) -> dict[str, typing.Any]:
        return _setup._get_attrs(self, model_class, name)
    def _setup_attrs__(self, model_class: type[BaseModel], name: str) -> None:
        return _setup._setup_attrs__(self, model_class, name)
    def prepare_setup(self) -> None:
        return _setup.prepare_setup(self)
    def setup(self, model: BaseModel) -> None:
        return _setup.setup(self, model)
    def setup_nonrelated(self, model: BaseModel) -> None:
        return _setup.setup_nonrelated(self, model)
    def get_depends(self, model: BaseModel) -> tuple[Iterable[str], Iterable[str]]:
        return _setup.get_depends(self, model)
    def setup_related(self, model: BaseModel) -> None:
        return _related.setup_related(self, model)
    def _compute_related(self, records: BaseModel) -> None:
        return _related._compute_related(self, records)
    def _compute_sql_related(self, model, table: TableSQL) -> SQL:
        return _related._compute_sql_related(self, model, table)
    def _process_related(self, value, env: Environment):
        return _related._process_related(self, value, env)
    def _inverse_related(self, records: BaseModel) -> None:
        return _related._inverse_related(self, records)
    def _search_related(self, records: BaseModel, operator: str, value) -> DomainType:
        return _related._search_related(self, records, operator, value)
    def _init_column_related(self, model: BaseModel) -> bool:
        return _related._init_column_related(self, model)
    def _init_column_related_update(self, model: BaseModel) -> None:
        return _related._init_column_related_update(self, model)
    _related_string = property(attrgetter('string'))
    _related_help = property(attrgetter('help'))
    _related_groups = property(attrgetter('groups'))
    _related_aggregator = property(attrgetter('aggregator'))
    @functools.cached_property
    def column_type(self) -> tuple[str, str] | None:
        return _schema.column_type(self)
    @functools.cached_property
    def stored_sql_column_type(self) -> SQL:
        return _schema.stored_sql_column_type(self)
    @functools.cached_property
    def sql_column_type(self) -> SQL:
        return _schema.sql_column_type(self)
    @property
    def base_field(self) -> Self:
        """ Return the base field of an inherited field, or ``self``. """
        return self.inherited_field.base_field if self.inherited_field else self
    def get_company_dependent_fallback(self, records):
        return _records.get_company_dependent_fallback(self, records)
    def resolve_depends(self, registry: Registry) -> Iterator[tuple[Field, ...]]:
        return _setup.resolve_depends(self, registry)
    def get_description(self, env: Environment, attributes: Collection[str] | None=None) -> ValuesType:
        return _description.get_description(self, env, attributes)
    _description_name = property(attrgetter('name'))
    _description_type = property(attrgetter('type'))
    _description_store = property(attrgetter('store'))
    _description_manual = property(attrgetter('manual'))
    _description_related = property(attrgetter('related'))
    _description_company_dependent = property(attrgetter('company_dependent'))
    _description_readonly = property(attrgetter('readonly'))
    _description_required = property(attrgetter('required'))
    _description_groups = property(attrgetter('groups'))
    _description_change_default = property(attrgetter('change_default'))
    _description_default_export_compatible = property(attrgetter('default_export_compatible'))
    _description_exportable = property(attrgetter('exportable'))
    def _description_depends(self, env: Environment):
        return _description._description_depends(self, env)
    @property
    def _description_searchable(self) -> bool:
        return _description._description_searchable(self)
    def _description_sortable(self, env: Environment):
        return _description._description_sortable(self, env)
    def _description_groupable(self, env: Environment):
        return _description._description_groupable(self, env)
    def _description_aggregator(self, env: Environment):
        return _description._description_aggregator(self, env)
    def _description_string(self, env: Environment) -> str:
        return _description._description_string(self, env)
    def _description_help(self, env: Environment):
        return _description._description_help(self, env)
    def _description_falsy_value_label(self, env) -> str | None:
        return _description._description_falsy_value_label(self, env)
    def _description_group_expand(self, env) -> bool:
        return _description._description_group_expand(self, env)
    def is_editable(self) -> bool:
        return _description.is_editable(self)
    def convert_to_column(self, value, record, values=None, validate=True):
        return _conversion.convert_to_column(self, value, record, values, validate)
    def convert_to_column_insert(self, value, record, values=None, validate=True):
        return _conversion.convert_to_column_insert(self, value, record, values, validate)
    def get_column_update(self, record: BaseModel):
        return _schema.get_column_update(self, record)
    def convert_to_cache(self, value, records, validate=True):
        return _conversion.convert_to_cache(self, value, records, validate)
    def convert_to_record(self, value, record):
        return _conversion.convert_to_record(self, value, record)
    def convert_to_read(self, value, record, use_display_name=True):
        return _conversion.convert_to_read(self, value, record, use_display_name)
    def convert_to_write(self, value, record):
        return _conversion.convert_to_write(self, value, record)
    def convert_to_export(self, value, record):
        return _conversion.convert_to_export(self, value, record)
    def convert_to_display_name(self, value, record):
        return _conversion.convert_to_display_name(self, value, record)
    @property
    def column_order(self) -> int:
        return _schema.column_order(self)
    def update_db(self, model: BaseModel, columns: dict[str, dict[str, typing.Any]]) -> None:
        return _schema.update_db(self, model, columns)
    def update_db_column(self, model: BaseModel, column: dict[str, typing.Any]):
        return _schema.update_db_column(self, model, column)
    def _convert_db_column(self, model: BaseModel, column: dict[str, typing.Any]):
        return _schema._convert_db_column(self, model, column)
    def _init_column_data(self, model: BaseModel) -> None:
        return _schema._init_column_data(self, model)
    def _init_column_notify_compute(self, records):
        return _schema._init_column_notify_compute(self, records)
    def to_sql(self, table: TableSQL) -> SQL:
        return _query.to_sql(self, table)
    def property_to_sql(self, field_sql: FieldSQL, property_name: str) -> SQL:
        return _query.property_to_sql(self, field_sql, property_name)
    def condition_to_sql(self, table: TableSQL, field_expr: str, operator: str, value) -> SQL:
        return _query.condition_to_sql(self, table, field_expr, operator, value)
    def _condition_to_sql(self, table: TableSQL, field_expr: str, operator: str, value) -> SQL:
        return _query._condition_to_sql(self, table, field_expr, operator, value)
    def _condition_to_sql_company(self, table: TableSQL, sql_expr: SQL, field_expr: str, operator: str, value) -> SQL:
        return _query._condition_to_sql_company(self, table, sql_expr, field_expr, operator, value)
    def expression_getter(self, field_expr: str) -> Callable[[BaseModel], typing.Any]:
        return _query.expression_getter(self, field_expr)
    def filter_function[M: BaseModel](self, records: M, field_expr: str, operator: str, value) -> Callable[[M], M]:
        return _query.filter_function(self, records, field_expr, operator, value)
    def read(self, records: BaseModel) -> None:
        return _records.read(self, records)
    def create(self, record_values: Sequence[tuple[BaseModel, typing.Any]]) -> None:
        return _records.create(self, record_values)
    def write(self, records: BaseModel, value: typing.Any) -> None:
        return _records.write(self, records, value)
    @typing.final
    def _get_cache(self, env: Environment) -> MutableMapping[IdType, typing.Any]:
        return _cache._get_cache(self, env)
    def _get_cache_impl(self, env: Environment) -> MutableMapping[IdType, typing.Any]:
        return _cache._get_cache_impl(self, env)
    def _invalidate_cache(self, env: Environment, ids: Collection[IdType] | None=None) -> None:
        return _cache._invalidate_cache(self, env, ids)
    def _get_all_cache_ids(self, env: Environment) -> Collection[IdType]:
        return _cache._get_all_cache_ids(self, env)
    def _cache_missing_ids(self, records: BaseModel) -> Iterator[IdType]:
        return _cache._cache_missing_ids(self, records)
    def _filter_not_equal(self, records: ModelType, cache_value: typing.Any) -> ModelType:
        return _cache._filter_not_equal(self, records, cache_value)
    def _to_prefetch(self, record: ModelType) -> ModelType:
        return _cache._to_prefetch(self, record)
    def _insert_cache(self, records: BaseModel, values: Iterable) -> None:
        return _cache._insert_cache(self, records, values)
    def _update_cache(self, records: BaseModel, cache_value: typing.Any, dirty: bool=False) -> None:
        return _cache._update_cache(self, records, cache_value, dirty)
    def __get__(self, record: BaseModel, owner=None) -> T:
        return _records.get_value(self, record, owner)
    def __set__(self, records: BaseModel, value) -> None:
        return _records.set_value(self, records, value)
    def recompute(self, records: BaseModel) -> None:
        return _records.recompute(self, records)
    def compute_value(self, records: BaseModel) -> None:
        return _records.compute_value(self, records)
    def determine_inverse(self, records):
        return _query.determine_inverse(self, records)
    def determine_domain(self, records: BaseModel, operator: str, value) -> typing.Any:
        return _query.determine_domain(self, records, operator, value)
    def determine_group_expand(self, records, values, domain):
        return _query.determine_group_expand(self, records, values, domain)


# the delegated methods of the field, at the end: they import this module
from . import setup as _setup, related as _related, description as _description, conversion as _conversion, schema as _schema, query as _query, cache as _cache, records as _records  # noqa: E402
