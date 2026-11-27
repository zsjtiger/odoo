"""The environments of the models: the user, the company, the context and the access to the records and the fields of the transaction."""

from __future__ import annotations

import functools
import logging
import typing
from collections import defaultdict
from collections.abc import Mapping, MutableMapping
from contextlib import contextmanager
from datetime import UTC
from zoneinfo import ZoneInfo
from odoo.exceptions import AccessError, UserError
from odoo.orm.database.sql_db import BaseCursor
from odoo.tools import clean_context, frozendict, reset_cached_properties, OrderedSet, SQL
from odoo.tools.func import deprecated
from odoo.tools.text.translate import get_translation, get_translated_module, LazyGettext
from odoo.orm.models.registry import Registry
from odoo.orm.core.utils import SUPERUSER_ID

if typing.TYPE_CHECKING:
    from collections.abc import Collection, Iterator
    from datetime import tzinfo
    from odoo.orm.core.identifiers import IdType
    from odoo.orm.core.types import BaseModel, Field


_logger = logging.getLogger('odoo.api')


MAX_FIXPOINT_ITERATIONS = 10


class Environment(Mapping[str, "BaseModel"]):
    """ The environment stores various contextual data used by the ORM:

    - :attr:`cr`: the current database cursor (for database queries);
    - :attr:`uid`: the current user id (for access rights checks);
    - :attr:`context`: the current context dictionary (arbitrary metadata);
    - :attr:`su`: whether in superuser mode.

    It provides access to the registry by implementing a mapping from model
    names to models. It also holds a cache for records, and a data
    structure to manage recomputations.
    """

    cr: BaseCursor
    uid: int
    context: frozendict
    su: bool
    transaction: Transaction

    def __new__(cls, cr: BaseCursor, uid: int, context: dict, su: bool = False):
        assert isinstance(cr, BaseCursor)
        if uid == SUPERUSER_ID:
            su = True

        # determine transaction object
        transaction = cr.transaction
        if transaction is None:
            if cr._closing:
                _logger.error("The cursor is being closed, but starts a new transaction", stack_info=True)
            transaction = cr.transaction = Transaction(Registry(cr.dbname))
            transaction._check_signaling(cr)

        else:
            # if env already exists, return it
            env = transaction.lookup_env(uid, context, su)
            if env is not None:
                return env

        # otherwise create environment, and add it in the set
        self = object.__new__(cls)
        self.cr, self.uid, self.su = cr, uid, su
        self.context = frozendict(context)
        self.transaction = transaction
        transaction.add_env(self)
        return self

    def __setattr__(self, name: str, value: typing.Any) -> None:
        # once initialized, attributes are read-only
        if name in vars(self):
            raise AttributeError(f"Attribute {name!r} is read-only, call `env()` instead")
        return super().__setattr__(name, value)

    #
    # Mapping methods
    #

    def __contains__(self, model_name) -> bool:
        """ Test whether the given model exists. """
        return model_name in self.registry

    def __getitem__(self, model_name: str) -> BaseModel:
        """ Return an empty recordset from the given model. """
        return self.registry[model_name](self, (), ())

    def __iter__(self):
        """ Return an iterator on model names. """
        return iter(self.registry)

    def __len__(self):
        """ Return the size of the model registry. """
        return len(self.registry)

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other

    def __hash__(self):
        return object.__hash__(self)

    def __call__(
        self,
        cr: BaseCursor | None = None,
        user: IdType | BaseModel | None = None,
        context: dict | None = None,
        su: bool | None = None,
    ) -> Environment:
        """ Return an environment based on ``self`` with modified parameters.

        :param cr: optional database cursor to change the current cursor
        :type cursor: :class:`~odoo.orm.database.sql_db.Cursor`
        :param user: optional user/user id to change the current user
        :type user: int or :class:`res.users record<~odoo.addons.base.models.res_users.ResUsers>`
        :param dict context: optional context dictionary to change the current context
        :param bool su: optional boolean to change the superuser mode
        :returns: environment with specified args (new or existing one)
        """
        cr = self.cr if cr is None else cr
        uid = self.uid if user is None else int(user)  # type: ignore
        if context is None:
            context = clean_context(self.context) if su and not self.su else self.context
        su = (user is None and self.su) if su is None else su
        return Environment(cr, uid, context, su)

    @typing.overload
    def ref(self, xml_id: str, raise_if_not_found: typing.Literal[True] = True) -> BaseModel:
        ...

    @typing.overload
    def ref(self, xml_id: str, raise_if_not_found: typing.Literal[False]) -> BaseModel | None:
        ...

    def ref(self, xml_id: str, raise_if_not_found: bool = True) -> BaseModel | None:
        """ Return the record corresponding to the given ``xml_id``.

        :param str xml_id: record xml_id, under the format ``<module.id>``
        :param bool raise_if_not_found: whether the method should raise if record is not found
        :returns: Found record or None
        :raise ValueError: if record wasn't found and ``raise_if_not_found`` is True
        """
        res_model, res_id = self['ir.model.data']._xmlid_to_res_model_res_id(
            xml_id, raise_if_not_found=raise_if_not_found
        )

        if res_model and res_id:
            record = self[res_model].browse(res_id)
            if record.exists():
                return record
            if raise_if_not_found:
                raise ValueError('No record found for unique ID %s. It may have been deleted.' % (xml_id))
        return None

    def is_superuser(self) -> bool:
        """ Return whether the environment is in superuser mode. """
        return self.su

    def is_admin(self) -> bool:
        """ Return whether the current user has group "Access Rights", or is in
            superuser mode. """
        return self.su or self.user._is_admin()

    def is_system(self) -> bool:
        """ Return whether the current user has group "Settings", or is in
            superuser mode. """
        return self.su or self.user._is_system()

    @functools.cached_property
    def registry(self) -> Registry:
        """Return the registry associated with the transaction."""
        return self.transaction.registry

    @functools.cached_property
    def _protected(self):
        """Return the protected map of the transaction."""
        return self.transaction.protected

    @functools.cached_property
    def cache(self):
        """Return the cache object of the transaction."""
        return self.transaction.cache

    @property
    def _access_context(self) -> tuple:
        """Return the context values used by the access caches."""
        return (self.uid, *self['ir.access']._get_access_context())

    @functools.cached_property
    def _access_cache(self):
        """Get the cache for READ access (model -> ids -> bool).

        Storing True means that we have access to the record.
        We store False to avoid worst case complexity when re-checking all
        records in the prefetch: see `odoo.orm.core.access.fill_access_cache`.
        """
        return self.transaction.access_read[self._access_context]

    def _add_to_access_cache(self, records: BaseModel) -> None:
        """ Patch the read access cache so that the user has access to a record. """
        cache = self._access_cache
        cache[records._name].update(dict.fromkeys(records._ids, True))

    @functools.cached_property
    def user(self) -> BaseModel:
        """Return the current user (as an instance).

        :returns: current user - sudoed
        :rtype: :class:`res.users record<~odoo.addons.base.models.res_users.ResUsers>`"""
        return self(su=True)['res.users'].browse(self.uid)

    @functools.cached_property
    def company(self) -> BaseModel:
        """Return the current company (as an instance).

        If not specified in the context (`allowed_company_ids`),
        fallback on current user main company.

        :raise AccessError: invalid or unauthorized `allowed_company_ids` context key content.
        :return: current company (default=`self.user.company_id`), with the current environment
        :rtype: :class:`res.company record<~odoo.addons.base.models.res_company.Company>`

        .. warning::

            No sanity checks applied in sudo mode!
            When in sudo mode, a user can access any company,
            even if not in his allowed companies.

            This allows to trigger inter-company modifications,
            even if the current user doesn't have access to
            the targeted company.
        """
        company_ids = self.context.get('allowed_company_ids', [])
        if company_ids:
            if not self.su:
                user_company_ids = self.user._get_company_ids()
                if set(company_ids) - set(user_company_ids):
                    raise AccessError(self._("Access to unauthorized or invalid companies."))
            return self['res.company'].browse(company_ids[0])
        return self.user.company_id.with_env(self)

    @functools.cached_property
    def companies(self) -> BaseModel:
        """Return a recordset of the enabled companies by the user.

        If not specified in the context(`allowed_company_ids`),
        fallback on current user companies.

        :raise AccessError: invalid or unauthorized `allowed_company_ids` context key content.
        :return: current companies (default=`self.user.company_ids`), with the current environment
        :rtype: :class:`res.company recordset<~odoo.addons.base.models.res_company.Company>`

        .. warning::

            No sanity checks applied in sudo mode !
            When in sudo mode, a user can access any company,
            even if not in his allowed companies.

            This allows to trigger inter-company modifications,
            even if the current user doesn't have access to
            the targeted company.
        """
        company_ids = self.context.get('allowed_company_ids', [])
        user_company_ids = self.user._get_company_ids()
        if company_ids:
            if not self.su:
                if set(company_ids) - set(user_company_ids):
                    raise AccessError(self._("Access to unauthorized or invalid companies."))
            return self['res.company'].browse(company_ids)
        # By setting the default companies to all user companies instead of the main one
        # we save a lot of potential trouble in all "out of context" calls, such as
        # /mail/redirect or /web/image, etc. And it is not unsafe because the user does
        # have access to these other companies. The risk of exposing foreign records
        # (wrt to the context) is low because all normal RPCs will have a proper
        # allowed_company_ids.
        # Examples:
        #   - when printing a report for several records from several companies
        #   - when accessing to a record from the notification email template
        #   - when loading an binary image on a template
        return self['res.company'].browse(user_company_ids)

    @functools.cached_property
    def website(self) -> BaseModel:
        """Return the current website (as an instance).

        :returns: current website (possibly empty)
        :rtype: :class:`website record<~odoo.addons.base.models.website.Website>`
        """
        return self['website'].browse(self.context.get('website_id'))

    @functools.cached_property
    def tz(self) -> tzinfo:
        """Return the current timezone info, defaults to UTC."""
        timezone = self.context.get('tz') or self.user.tz
        if timezone:
            try:
                return ZoneInfo(timezone)
            except Exception:  # noqa: BLE001
                _logger.debug("Invalid timezone %r", timezone, exc_info=True)
        return UTC

    @functools.cached_property
    def lang(self) -> str | None:
        """Return the current language code."""
        lang = self.context.get('lang')
        if lang and lang != 'en_US' and not self['res.lang']._lang_get(lang):
            # cannot translate here because we do not have a valid language
            raise UserError(f'Invalid language code: {lang}')  # pylint: disable=missing-gettext
        return lang or None

    @functools.cached_property
    def _lang(self) -> str:
        """Return the technical language code of the current context for **model_terms** translated field
        """
        context = self.context
        lang = self.lang or 'en_US'
        if context.get('edit_translations') or context.get('check_translations'):
            lang = '_' + lang
        return lang

    def _(self, source: str | LazyGettext, *args, **kwargs) -> str:
        """Translate the term using current environment's language.

        Usage:

        ```
        self.env._("hello world")  # dynamically get module name
        self.env._("hello %s", "test")
        self.env._(LAZY_TRANSLATION)
        ```

        :param source: String to translate or lazy translation
        :param ...: args or kwargs for templating
        :return: The transalted string
        """
        lang = self.lang or 'en_US'
        if isinstance(source, str):
            assert not (args and kwargs), "Use args or kwargs, not both"
            format_args = args or kwargs
        elif isinstance(source, LazyGettext):
            # translate a lazy text evaluation
            assert not args and not kwargs, "All args should come from the lazy text"
            return source._translate(lang)
        else:
            raise TypeError(f"Cannot translate {source!r}")
        if lang == 'en_US':
            # we ignore the module as en_US is not translated
            return get_translation('base', 'en_US', source, format_args)
        try:
            module = get_translated_module(2)
            return get_translation(module, lang, source, format_args)
        except Exception:  # noqa: BLE001
            _logger.debug('translation went wrong for "%r", skipped', source, exc_info=True)
        return source

    @deprecated("Since 20.0, use transaction.clear or transaction.reset")
    def clear(self) -> None:
        """ Clear all record caches, and discard all fields to recompute.
            This may be useful when recovering from a failed ORM operation.
        """
        reset_cached_properties(self)
        self.transaction.clear()

    def invalidate_all(self, flush: bool = True) -> None:
        """ Invalidate the cache of all records.

        :param flush: whether pending updates should be flushed before invalidation.
            It is ``True`` by default, which ensures cache consistency.
            Do not use this parameter unless you know what you are doing.
        """
        if flush:
            self.flush_all()
        self.transaction.invalidate_field_data()

    def _recompute_all(self) -> None:
        """ Process all pending computations. """
        for _ in range(MAX_FIXPOINT_ITERATIONS):
            # fields to compute on real records (new records are not recomputed)
            fields_ = [field for field, ids in self.transaction.tocompute.items() if any(ids)]
            if not fields_:
                break
            for field in fields_:
                self[field.model_name]._recompute_field(field)
        else:
            _logger.warning("Too many iterations for recomputing fields!")

    def flush_all(self) -> None:
        """ Flush all pending computations and updates to the database. """
        for _ in range(MAX_FIXPOINT_ITERATIONS):
            self._recompute_all()
            model_names = OrderedSet(field.model_name for field in self._field_dirty)
            if not model_names:
                break
            for model_name in model_names:
                self[model_name].flush_model()
        else:
            _logger.warning("Too many iterations for flushing fields!")

    def is_protected(self, field: Field, record: BaseModel) -> bool:
        """ Return whether `record` is protected against invalidation or
            recomputation for `field`.
        """
        return record.id in self._protected.get(field, ())

    def protected(self, field: Field) -> BaseModel:
        """ Return the recordset for which ``field`` should not be invalidated or recomputed. """
        return self[field.model_name].browse(self._protected.get(field, ()))

    @typing.overload
    def protecting(self, what: Collection[Field], records: BaseModel) -> typing.ContextManager[None]:
        ...

    @typing.overload
    def protecting(self, what: Collection[tuple[Collection[Field], BaseModel]]) -> typing.ContextManager[None]:
        ...

    @contextmanager
    def protecting(self, what, records=None) -> Iterator[None]:
        """ Prevent the invalidation or recomputation of fields on records.
        The parameters are either:

        - ``what`` a collection of fields and ``records`` a recordset, or
        - ``what`` a collection of pairs ``(fields, records)``.
        """
        protected = self._protected
        try:
            protected.pushmap()
            if records is not None:  # convert first signature to second one
                what = [(what, records)]
            ids_by_field = defaultdict(list)
            for fields, what_records in what:
                for field in fields:
                    ids_by_field[field].extend(what_records._ids)

            for field, rec_ids in ids_by_field.items():
                ids = protected.get(field)
                protected[field] = ids.union(rec_ids) if ids else frozenset(rec_ids)
            yield
        finally:
            protected.popmap()

    def fields_to_compute(self) -> Collection[Field]:
        """ Return a view on the field to compute. """
        return self.transaction.tocompute.keys()

    def records_to_compute(self, field: Field) -> BaseModel:
        """ Return the records to compute for ``field``. """
        ids = self.transaction.tocompute.get(field, ())
        return self[field.model_name].browse(ids)

    def is_to_compute(self, field: Field, record: BaseModel) -> bool:
        """ Return whether ``field`` must be computed on ``record``. """
        return record.id in self.transaction.tocompute.get(field, ())

    def not_to_compute(self, field: Field, records: BaseModel) -> BaseModel:
        """ Return the subset of ``records`` for which ``field`` must not be computed. """
        ids = self.transaction.tocompute.get(field, ())
        return records.browse(id_ for id_ in records._ids if id_ not in ids)

    def add_to_compute(self, field: Field, records: BaseModel) -> None:
        """ Mark ``field`` to be computed on ``records``. """
        if not records:
            return
        assert field.store and field.compute, "Cannot add to recompute no-store or no-computed field"
        self.transaction.tocompute[field].update(records._ids)

    def remove_to_compute(self, field: Field, records: BaseModel) -> None:
        """ Mark ``field`` as computed on ``records``. """
        if not records:
            return
        ids = self.transaction.tocompute.get(field, None)
        if ids is None:
            return
        ids.difference_update(records._ids)
        if not ids:
            del self.transaction.tocompute[field]

    def cache_key(self, field: Field) -> typing.Any:
        """ Return the cache key of the given ``field``. """
        def get(key, get_context=self.context.get):
            if key == 'company':
                return self.company.id
            elif key == 'uid':
                return self.uid if field.compute_sudo else (self.uid, self.su)
            elif key == 'lang':
                return get_context('lang') or None
            elif key == 'active_test':
                return get_context('active_test', field.context.get('active_test', True))
            else:
                val = get_context(key)
                if type(val) is list:
                    val = tuple(val)
                try:
                    hash(val)
                except TypeError:
                    raise TypeError(
                        "Can only create cache keys from hashable values, "
                        f"got non-hashable value {val!r} at context key {key!r} "
                        f"(dependency of field {field})"
                    ) from None  # we don't need to chain the exception created 2 lines above
                else:
                    return val

        return tuple(get(key) for key in self.registry.field_depends_context[field])

    @functools.cached_property
    def _field_cache_memo(self) -> dict[Field, MutableMapping[IdType, typing.Any]]:
        """Memo for `Field._get_cache(env)`.  Do not use it."""
        return {}

    @functools.cached_property
    def _field_access_memo(self) -> set[Field]:
        """Memo for `model.has_field_access(field, 'read')`.  Do not use it."""
        return set()

    @functools.cached_property
    def _field_dirty(self):
        """ Map fields to set of dirty ids. """
        return self.transaction.field_dirty

    @functools.cached_property
    def _field_depends_context(self):
        return self.registry.field_depends_context

    def execute_query(self, query: SQL) -> list[tuple]:
        """ Execute the given query, fetch its result and return it as a list of
        tuples (or an empty list if no result to fetch). The method
        automatically flushes all the fields in the metadata of the query.
        """
        assert isinstance(query, SQL)
        _, _, fields_to_flush = query._sql_tuple
        if fields_to_flush:
            fnames_to_flush = defaultdict[str, OrderedSet[str]](OrderedSet)
            for field in fields_to_flush:
                fnames_to_flush[field.model_name].add(field.name)
            for model_name, field_names in fnames_to_flush.items():
                self[model_name].flush_model(field_names)
        self.cr.execute(query)
        return [] if self.cr.description is None else self.cr.fetchall()

    def execute_query_dict(self, query: SQL) -> list[dict]:
        """ Execute the given query, fetch its results as a list of dicts.
        The method automatically flushes fields in the metadata of the query.
        """
        rows = self.execute_query(query)
        if not rows:
            return []
        description = self.cr.description
        assert description is not None, "No cr.description, the executed query does not return a table."
        return [
            {column.name: row[index] for index, column in enumerate(description)}
            for row in rows
        ]


# imported at the end: the module of the other side imports this one
from .transaction import Transaction
