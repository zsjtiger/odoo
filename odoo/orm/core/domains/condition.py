"""The conditions on a field: their checks, their optimizations and their predicates."""

from __future__ import annotations

import logging
import typing
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL, OrderedSet
from odoo.orm.core.identifiers import NewId
from odoo.orm.database.query import Query, TableSQL
from odoo.orm.core.utils import COLLECTION_TYPES, parse_field_expr
from .constants import CONDITION_OPERATORS, NEGATIVE_CONDITION_OPERATORS, OptimizationLevel, STANDARD_CONDITION_OPERATORS, _INVERSE_INEQUALITY, _INVERSE_OPERATOR
from .registry import _OPTIMIZATIONS_FOR, field_type_optimization

if typing.TYPE_CHECKING:
    from odoo.orm.fields import Field
    from odoo.orm.models import BaseModel

from .base import Domain
from .boolean import DomainBool

_logger = logging.getLogger('odoo.domains')


class DomainCondition(Domain):
    """Domain condition on field: (field, operator, value)

    A field (or expression) is compared to a value. The list of supported
    operators are described in CONDITION_OPERATORS.
    """
    __slots__ = ('_field_instance', 'field_expr', 'operator', 'value')
    _field_instance: Field | None  # mutable cached property
    field_expr: str
    operator: str
    value: typing.Any

    def __new__(cls, field_expr: str, operator: str, value):
        """Init a new simple condition (internal init)

        :param field_expr: Field name or field path
        :param operator: A valid operator
        :param value: A value for the comparison
        """
        self = object.__new__(cls)
        object.__setattr__(self, 'field_expr', field_expr)
        object.__setattr__(self, 'operator', operator)
        object.__setattr__(self, 'value', value)
        object.__setattr__(self, '_field_instance', None)
        object.__setattr__(self, '_opt_level', OptimizationLevel.NONE)
        return self

    def checked(self) -> DomainCondition:
        """Validate `self` and return it if correct, otherwise raise an exception."""
        if not isinstance(self.field_expr, str) or not self.field_expr:
            self._raise("Empty field name", error=TypeError)
        operator = self.operator
        if operator not in CONDITION_OPERATORS:
            self._raise("Invalid operator")
        # check already the consistency for domain manipulation
        # these are common mistakes and optimizations, do them here to avoid recreating the domain
        # - NewId is not a value
        # - records are not accepted, use values
        # - Query and Domain values should be using a relational operator
        from odoo.orm.models import BaseModel  # noqa: PLC0415
        value = self.value
        if value is None:
            value = False
        elif isinstance(value, NewId):
            _logger.warning("Domains don't support NewId, use .ids instead, for %r", (self.field_expr, self.operator, self.value))
            operator = 'not in' if operator in NEGATIVE_CONDITION_OPERATORS else 'in'
            value = []
        elif isinstance(value, BaseModel):
            _logger.warning("The domain condition %r should not have a value which is a model", (self.field_expr, self.operator, self.value))
            value = value.ids
        elif isinstance(value, (Domain, Query, SQL)) and operator not in ('any', 'not any', 'any!', 'not any!', 'in', 'not in'):
            # accept SQL object in the right part for simple operators
            # use case: compare 2 fields
            _logger.warning("The domain condition %r should use the 'any' or 'not any' operator.", (self.field_expr, self.operator, self.value))
        if value is not self.value:
            return DomainCondition(self.field_expr, operator, value)
        return self

    def __invert__(self):
        # do it only for simple fields (not expressions)
        # inequalities are handled in _negate()
        if "." not in self.field_expr and (neg_op := _INVERSE_OPERATOR.get(self.operator)):
            return DomainCondition(self.field_expr, neg_op, self.value)
        return super().__invert__()

    def _negate(self, model):
        # inverse of the operators is handled by construction
        # except for inequalities for which we must know the field's type
        if neg_op := _INVERSE_INEQUALITY.get(self.operator):
            # Inverse and add a self "or field is null"
            # when the field does not have a falsy value.
            # Having a falsy value is handled correctly in the SQL generation.
            condition = DomainCondition(self.field_expr, neg_op, self.value)
            if self._field(model).falsy_value is None:
                is_null = DomainCondition(self.field_expr, 'in', OrderedSet([False]))
                condition = is_null | condition
            return condition

        return super()._negate(model)

    def __iter__(self):
        field_expr, operator, value = self.field_expr, self.operator, self.value
        # if the value is a domain or set, change it into a list
        if isinstance(value, (*COLLECTION_TYPES, Domain)):
            value = list(value)
        yield (field_expr, operator, value)

    def __eq__(self, other):
        return self is other or (
            isinstance(other, DomainCondition)
            and self.field_expr == other.field_expr
            and self.operator == other.operator
            # we want stricter equality than this: `OrderedSet([x]) == {x}`
            # to ensure that optimizations always return OrderedSet values
            and self.value.__class__ is other.value.__class__
            and self.value == other.value
        )

    def is_condition(self,
        field_expr: str = '',
        operator: str | tuple[str] = (),
        value: type | tuple[type] = (),
    ) -> bool:
        return (
            not field_expr or self.field_expr == field_expr
        ) and (
            not operator or self.operator in ((operator,) if isinstance(operator, str) else operator)
        ) and (
            not value or isinstance(self.value, value)
        )

    def iter_conditions(self):
        yield self

    def map_conditions(self, function) -> Domain:
        result = function(self)
        assert isinstance(result, Domain), "result of map_conditions is not a Domain"
        return result

    def _raise(self, message: str, *args, error=ValueError) -> typing.NoReturn:
        """Raise an error message for this condition"""
        message += ' in condition (%r, %r, %r)'
        raise error(message % (*args, self.field_expr, self.operator, self.value))

    def _field(self, model: BaseModel) -> Field:
        """Cached Field instance for the expression."""
        field = self._field_instance  # type: ignore[arg-type]
        if field is None or field is not model._fields[field.name]:
            field, _ = self.__get_field(model)
        return field

    def __get_field(self, model: BaseModel) -> tuple[Field, str]:
        """Get the field or raise an exception"""
        field_name, property_name = parse_field_expr(self.field_expr)
        try:
            field = model._fields[field_name]
        except KeyError:
            self._raise("Invalid field %s.%s", model._name, field_name)
        # cache field value, with this hack to bypass immutability
        object.__setattr__(self, '_field_instance', field)
        return field, property_name or ''

    def _optimize_step(self, model: BaseModel, level: OptimizationLevel) -> Domain:
        """Optimization step.

        Apply some generic optimizations and then dispatch optimizations
        according to the operator and the type of the field.
        Optimize recursively until a fixed point is found.

        - Validate the field.
        - Decompose *paths* into domains using 'any'.
        - If the field is *not stored*, run the search function of the field.
        - Run optimizations.
        - Check the output.
        """
        assert level is self._opt_level.next_level, f"Trying to skip optimization level after {self._opt_level}"

        if level == OptimizationLevel.BASIC:
            # optimize path
            field, property_name = self.__get_field(model)
            if property_name and field.relational:
                sub_domain = DomainCondition(property_name, self.operator, self.value)
                return DomainCondition(field.name, 'any', sub_domain)
        else:
            field = self._field(model)

        if level == OptimizationLevel.FULL:
            # resolve inherited fields
            # inherits implies both Field.delegate=True and Field.bypass_search_access=True
            # so no additional permissions will be added by the 'any' operator below
            if field.inherited:
                assert field.related
                parent_fname = field.related.split('.')[0]
                parent_domain = DomainCondition(self.field_expr, self.operator, self.value)
                return DomainCondition(parent_fname, 'any', parent_domain)

            # handle searchable fields
            if field.search and field.name == self.field_expr:
                if field.type == 'boolean' and isinstance(domain := _optimize_boolean_in_all(self, model), DomainBool):
                    # apply the tautology before trying the search method
                    # this is a basic optimization, but for active flag it is left for later
                    return domain
                domain = self._optimize_field_search_method(model)
                # The domain is optimized so that value data types are comparable.
                # Only simple optimization to avoid endless recursion.
                domain = domain.optimize(model)
                if domain != self:
                    return domain

            if not field.store and not field.compute_sql:
                self._raise("Field has no SQL representation because it is not stored")

        # apply optimizations of the level for operator and type
        optimizations = _OPTIMIZATIONS_FOR[level]
        for opt in optimizations.get(self.operator, ()):
            domain = opt(self, model)
            if domain != self:
                return domain
        for opt in optimizations.get(field.type, ()):
            domain = opt(self, model)
            if domain != self:
                return domain

        # final checks
        if self.operator not in STANDARD_CONDITION_OPERATORS and level == OptimizationLevel.FULL:
            self._raise("Not standard operator left")

        return self

    def _optimize_field_search_method(self, model: BaseModel) -> Domain:
        field = self._field(model)
        operator, value = self.operator, self.value
        env = model.env
        if not env.su:
            if operator not in ('any!', 'not any!'):
                model.check_field_access(field, 'read')
            if field.compute_sudo:
                # run search in sudo because the compute is done in sudo as well
                model = model.sudo()
        if (
            operator in ('any', 'not any', 'any!', 'not any!')
            and field.relational
            and isinstance(value, Domain)
            and not field.related  # related fields handle 'any' properly
            # accept domains which are not context-dependent
            and any(not isinstance(cond.value, (SQL, Query)) for cond in value.iter_conditions())
        ):
            comodel = env[field.comodel_name]
            if field.type in ('many2many', 'one2many'):
                comodel = comodel.with_context(**field.context)
            else:
                comodel = comodel.with_context(active_test=False)
            query = comodel._search(value, bypass_access='!' in operator or field.bypass_search_access)
            value = DomainCondition('id', 'any!', query)

        # use the `Field.search` function
        original_exception = None
        try:
            computed_domain = field.determine_domain(model, operator, value)
        except (NotImplementedError, UserError) as e:
            computed_domain = NotImplemented
            original_exception = e
        else:
            if computed_domain is not NotImplemented:
                return Domain(computed_domain, internal=True)
        # try with the positive operator
        if (
            original_exception is None
            and (inversed_opeator := _INVERSE_OPERATOR.get(operator))
        ):
            try:
                computed_domain = field.determine_domain(model, inversed_opeator, value)
            except (NotImplementedError, UserError):
                pass
            else:
                if computed_domain is not NotImplemented:
                    return ~Domain(computed_domain, internal=True)
        # compatibility for 'any!'
        try:
            if operator in ('any!', 'not any!') and not isinstance(original_exception, AccessError):
                # Not strictly equivalent! If a search is executed, it will be done using sudo.
                computed_domain = DomainCondition(self.field_expr, operator.rstrip('!'), value)
                computed_domain = computed_domain._optimize_field_search_method(model.sudo())
                _logger.warning("Field %s should implement 'any!' operator", field)
                return computed_domain
        except (NotImplementedError, UserError) as e:
            if original_exception is None:
                original_exception = e
        # compatibility for '=' and '!='
        try:
            if operator == 'in':
                return Domain.OR(Domain(field.determine_domain(model, '=', v), internal=True) for v in value)
            if operator == 'not in':
                return Domain.AND(Domain(field.determine_domain(model, '!=', v), internal=True) for v in value)
        except (NotImplementedError, UserError) as e:
            if original_exception is None:
                original_exception = e
        # raise the error
        if isinstance(original_exception, UserError):
            raise original_exception
        raise UserError(env._(
            "Unsupported operator on %(field_label)s %(model_label)s in %(domain)s",
            domain=repr(self),
            field_label=self._field(model).get_description(model.env, ['string'])['string'],
            model_label=f"{model.env['ir.model']._get(model._name).name!r} ({model._name})",
        )) from original_exception

    def _as_predicate(self, records):
        if not records:
            return lambda _: False

        if self._opt_level < OptimizationLevel.DYNAMIC_VALUES:
            return self._optimize(records, OptimizationLevel.DYNAMIC_VALUES)._as_predicate(records)

        operator = self.operator
        if operator in ('child_of', 'parent_of'):
            # TODO have a specific implementation for these
            return self._optimize(records, OptimizationLevel.FULL)._as_predicate(records)

        assert operator in STANDARD_CONDITION_OPERATORS, "Expecting a sub-set of operators"
        field_expr, value = self.field_expr, self.value
        positive_operator = NEGATIVE_CONDITION_OPERATORS.get(operator, operator)

        if isinstance(value, SQL):
            # transform into an Query value
            if positive_operator == operator:
                condition = self
                operator = 'any!'
            else:
                condition = ~self
                operator = 'not any!'
            positive_operator = 'any!'
            field_expr = 'id'
            # similar to a search with [('id', 'in', records.ids), *condition]
            value = records._filtered_access('read')._as_query(ordered=False)
            value.add_where(condition.optimize_full(records, search_domain=Domain('id', 'any!', value))._to_sql(value.table))
            assert isinstance(value, Query)

        if isinstance(value, Query):
            # rebuild a domain with an 'in' values
            if positive_operator not in ('in', 'any', 'any!'):
                self._raise("Cannot filter using Query without the 'any' or 'in' operator")
            if positive_operator != 'in':
                operator = 'in' if positive_operator == operator else 'not in'
                positive_operator = 'in'
            value = set(value.get_result_ids())
            return DomainCondition(field_expr, operator, value)._as_predicate(records)

        field = self._field(records)
        if field_expr == 'display_name':
            # when searching by name, ignore AccessError
            field_expr = 'display_name.no_error'
        elif field_expr == 'id':
            # for new records, compare to their origin
            field_expr = 'id.origin'

        func = field.filter_function(records, field_expr, positive_operator, value)
        return func if positive_operator == operator else lambda rec: not func(rec)

    def _to_sql(self, table: TableSQL) -> SQL:
        field_expr, operator, value = self.field_expr, self.operator, self.value
        assert operator in STANDARD_CONDITION_OPERATORS, \
            f"Invalid operator {operator!r} for SQL in domain term {(field_expr, operator, value)!r}"
        assert self._opt_level >= OptimizationLevel.FULL, \
            f"Must fully optimize before generating the query {(field_expr, operator, value)}"

        model = table._model
        field = self._field(model)
        model.check_field_access(field, 'read')
        return field.condition_to_sql(table, field_expr, operator, value)


@field_type_optimization(['boolean'], OptimizationLevel.FULL)
def _optimize_boolean_in_all(condition, model):
    """b in [True, False]  =>  True"""
    if isinstance(condition.value, COLLECTION_TYPES) and set(condition.value) == {False, True}:
        # tautology is simplified to a boolean
        # note that this optimization removes fields (like active) from the domain
        # so we do this only on FULL level to avoid removing it from sub-domains
        return Domain(condition.operator == 'in')
    return condition
