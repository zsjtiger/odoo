"""Setup of the fields: the attributes of a field from its definition, and the dependencies of the computed fields."""

from __future__ import annotations

import logging
import typing
import warnings
from odoo.tools import reset_cached_properties
from odoo.tools.misc import unique

if typing.TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from odoo.orm.models.registry import Registry
    from odoo.orm.core.types import BaseModel

from .base import Field
from .base import COMPANY_DEPENDENT_FIELDS, resolve_mro

_logger = logging.getLogger('odoo.fields')


def __set_name__(self, owner: type[BaseModel], name: str) -> None:
    """ Perform the base setup of a field.

    :param owner: the owner class of the field (the model's definition or registry class)
    :param name: the name of the field
    """
    # during initialization, when importing `_models` at the end of this
    # file, it is not yet available and we already declare fields:
    # id and display_name
    from odoo.orm import models as _models  # noqa: PLC0415
    assert not hasattr(_models, 'MetaModel') or isinstance(owner, _models.MetaModel)
    is_model_definition = getattr(owner, 'pool', None) is None  # models.is_model_definition(owner)

    if self._args__ is None:
        # assert self in FIELD_CACHE.values()
        assert not is_model_definition  # model registry class
        assert self._shareable
        assert self.name in ('id', 'display_name') or self._module is not None
        assert owner._name == self.model_name
        assert name == self.name
        return

    self.model_name = owner._name
    self.name = name

    if is_model_definition:
        assert '_base_fields__' not in self._args__
        self._module = owner._module
        owner._field_definitions.append(self)
        if self._shareable and (self._args__.get('related') or not self._args__.get('_shareable', True)):
            self._shareable = False
        if self._shareable:
            # non shareable field objects in model definition classes won't be in a model registry class,
            # skipping setting attributes for them to save memory
            self._setup_attrs__(owner, name)
    else:  # model registry class
        self._setup_attrs__(owner, name)
        # free memory from stuff that is no longer useful
        self.__dict__.pop('_args__', None)
        if not self.related:
            # keep _base_fields__ on related fields for incremental model setup
            self.__dict__.pop('_base_fields__', None)


def _get_attrs(self, model_class: type[BaseModel], name: str) -> dict[str, typing.Any]:
    """ Return the field parameter attributes as a dictionary. """
    # determine all inherited field attributes
    attrs = {}
    modules: list[str] = []
    for field in self._args__.get('_base_fields__', ()):
        if not isinstance(self, type(field)):
            # 'self' overrides 'field' and their types are not compatible;
            # so we ignore all the parameters collected so far
            attrs.clear()
            modules.clear()
            continue
        attrs.update(field._args__)
        if field._module:
            modules.append(field._module)
    attrs.update(self._args__)
    if self._module:
        modules.append(self._module)

    attrs['model_name'] = model_class._name
    attrs['name'] = name
    attrs['_module'] = modules[-1] if modules else None
    # the following is faster than calling unique or using OrderedSet
    attrs['_modules'] = tuple(unique(modules) if len(modules) > 1 else modules)

    # initialize ``self`` with ``attrs``
    if name == 'state':
        # by default, `state` fields should be reset on copy
        attrs['copy'] = attrs.get('copy', False)
    if attrs.get('_shareable'):
        warnings.warn(f"_shareable attribute shouldn't be set to True on field {self}")
    if attrs.get('compute_sql'):
        if not attrs.get('compute'):
            warnings.warn(f"compute_sql attribute makes sense only if {self} is a computed field")
        if 'compute_sudo' not in attrs:
            warnings.warn(f"compute_sql requires an explicit compute_sudo parameter on {self}")
    if attrs.get('related'):
        if attrs.pop('compute', None):
            warnings.warn(f"Field {self} is both compute and related. Set one of them to None.")
        # by default, related fields are not stored, computed in superuser
        # mode, not copied and readonly
        attrs['store'] = store = attrs.get('store', False)
        attrs['compute_sudo'] = attrs.get('compute_sudo', attrs.get('related_sudo', True))
        attrs['copy'] = attrs.get('copy', False)
        attrs['readonly'] = attrs.get('readonly', True)
    elif attrs.get('compute'):
        # by default, computed fields are not stored, computed in superuser
        # mode if stored, not copied (unless stored and explicitly not
        # readonly), and readonly (unless inversible)
        attrs['store'] = store = attrs.get('store', False)
        attrs['compute_sudo'] = attrs.get('compute_sudo', store)
        if not (attrs['store'] and not attrs.get('readonly', True)):
            attrs['copy'] = attrs.get('copy', False)
        attrs['readonly'] = attrs.get('readonly', not attrs.get('inverse'))
    if attrs.get('precompute'):
        if not attrs.get('compute') and not attrs.get('related'):
            warnings.warn(f"precompute attribute doesn't make any sense on non computed field {self}", stacklevel=1)
            attrs['precompute'] = False
        elif not attrs.get('store'):
            warnings.warn(f"precompute attribute has no impact on non stored field {self}", stacklevel=1)
            attrs['precompute'] = False
    if attrs.get('company_dependent'):
        if attrs.get('required'):
            warnings.warn(f"company_dependent field {self} cannot be required", stacklevel=1)
        if attrs.get('translate'):
            warnings.warn(f"company_dependent field {self} cannot be translated", stacklevel=1)
        if self.type not in COMPANY_DEPENDENT_FIELDS:
            warnings.warn(f"company_dependent field {self} is not one of the allowed types {COMPANY_DEPENDENT_FIELDS}", stacklevel=1)
        attrs['copy'] = attrs.get('copy', False)
        # speed up search and on delete
        attrs['index'] = attrs.get('index', 'btree_not_null')
        attrs['prefetch'] = attrs.get('prefetch', 'company_dependent')
        attrs['_depends_context'] = ('company',)
    # parameters 'depends' and 'depends_context' are stored in attributes
    # '_depends' and '_depends_context', respectively
    if 'depends' in attrs:
        attrs['_depends'] = tuple(attrs.pop('depends'))
    if 'depends_context' in attrs:
        attrs['_depends_context'] = tuple(attrs.pop('depends_context'))

    return attrs


def _setup_attrs__(self, model_class: type[BaseModel], name: str) -> None:
    """ Initialize the field parameter attributes. """
    attrs = self._get_attrs(model_class, name)

    # determine parameters that must be validated
    extra_keys = tuple(key for key in attrs if not hasattr(self, key))
    if extra_keys:
        attrs['_extra_keys__'] = extra_keys

    self.__dict__.update(attrs)

    # prefetch only stored, column, non-manual fields
    if not self.store or not self.column_type or self.manual:
        self.prefetch = False

    if not self.string and not self.related:
        # related fields get their string from their parent field
        self.string = (
            name[:-4] if name.endswith('_ids') else
            name[:-3] if name.endswith('_id') else name
        ).replace('_', ' ').title()

    # self.default must be either None or a callable
    if self.default is not None and not callable(self.default):
        value = self.default
        self.default = lambda model: value


def prepare_setup(self) -> None:
    self._setup_done = False


def setup(self, model: BaseModel) -> None:
    """ Perform the complete setup of a field. """
    if not self._setup_done:
        # validate field params
        for key in self._extra_keys__:
            if not model._valid_field_parameter(self, key):
                _logger.warning(
                    "Field %s: unknown parameter %r, if this is an actual"
                    " parameter you may want to override the method"
                    " _valid_field_parameter on the relevant model in order to"
                    " allow it",
                    self, key
                )
        if self.related:
            self.setup_related(model)
        else:
            self.setup_nonrelated(model)

        if not isinstance(self.required, bool):
            warnings.warn(f'Property {self}.required should be a boolean ({self.required}).', stacklevel=1)

        if not isinstance(self.readonly, bool):
            warnings.warn(f'Property {self}.readonly should be a boolean ({self.readonly}).', stacklevel=1)

        if self.store and self._depends_context and not all(
            (self.translate and c == 'lang')
            or (self.company_dependent and c == 'company')
            for c in self._depends_context
        ):
            warnings.warn(f'Stored field {self} should not depend on context ({self._depends_context}).', stacklevel=1)

        self._setup_done = True
        # column_type might be changed during Field.setup
        reset_cached_properties(self)


def setup_nonrelated(self, model: BaseModel) -> None:
    """ Determine the dependencies and inverse field(s) of ``self``. """
    pass


def get_depends(self, model: BaseModel) -> tuple[Iterable[str], Iterable[str]]:
    """ Return the field's dependencies and cache dependencies. """
    if self._depends is not None:
        # the parameter 'depends' has priority over 'depends' on compute
        return self._depends, self._depends_context or ()

    if self.related:
        if self._depends_context is not None:
            depends_context = self._depends_context
        else:
            depends_context = []
            field_model_name = model._name
            for field_name in self.related.split('.'):
                field_model = model.env[field_model_name]
                field = field_model._fields[field_name]
                depends_context.extend(field.get_depends(field_model)[1])
                field_model_name = field.comodel_name if field.relational else None
            depends_context = tuple(unique(depends_context))
        return [self.related], depends_context

    if not self.compute:
        return (), self._depends_context or ()

    # determine the functions implementing self.compute
    if isinstance(self.compute, str):
        funcs = resolve_mro(model, self.compute, callable)
    else:
        funcs = [self.compute]

    # collect depends and depends_context
    depends = []
    depends_context = list(self._depends_context or ())
    for func in funcs:
        deps = getattr(func, '_depends', ())
        depends.extend(deps(model) if callable(deps) else deps)
        depends_context.extend(getattr(func, '_depends_context', ()))

    return depends, depends_context


def resolve_depends(self, registry: Registry) -> Iterator[tuple[Field, ...]]:
    """ Return the dependencies of `self` as a collection of field tuples. """
    Model0 = registry[self.model_name]

    for dotnames in registry.field_depends[self]:
        field_seq: list[Field] = []
        model_name = self.model_name
        check_precompute = self.precompute

        for index, fname in enumerate(dotnames.split('.')):
            if not model_name:
                raise ValueError(
                    f"Field {fname} in {self}'s dependencies is not reachable."
                )
            Model = registry[model_name]
            if Model0._transient and not Model._transient:
                # modifying fields on regular models should not trigger
                # recomputations of fields on transient models
                break

            try:
                field = Model._fields[fname]
            except KeyError:
                raise ValueError(
                    f"Wrong @depends on '{self.compute}' (compute method of field {self}). "
                    f"Dependency field '{fname}' not found in model {model_name}."
                ) from None
            if field is self and index and not self.recursive:
                self.recursive = True
                warnings.warn(f"Field {self} should be declared with recursive=True", stacklevel=1)

            # precomputed fields can depend on non-precomputed ones, as long
            # as they are reachable through at least one many2one field
            if check_precompute and field.store and field.compute and not field.precompute:
                warnings.warn(f"Field {self} cannot be precomputed as it depends on non-precomputed field {field}", stacklevel=1)
                self.precompute = False

            if field_seq and not field_seq[-1]._description_searchable:
                # the field before this one is not searchable, so there is
                # no way to know which on records to recompute self
                warnings.warn(
                    f"Field {field_seq[-1]!r} in dependency of {self} should be searchable. "
                    f"This is necessary to determine which records to recompute when {field} is modified. "
                    f"You should either make the field searchable, or simplify the field dependency.",
                    stacklevel=1,
                )

            field_seq.append(field)

            # do not make self trigger itself: for instance, a one2many
            # field line_ids with domain [('foo', ...)] will have
            # 'line_ids.foo' as a dependency
            if not (field is self and not index):
                yield tuple(field_seq)

            if field.type == 'one2many':
                for inv_field in Model.pool.field_inverses[field]:
                    yield tuple(field_seq) + (inv_field,)

            if check_precompute and field.type == 'many2one':
                check_precompute = False

            model_name = field.comodel_name if field.relational else None
