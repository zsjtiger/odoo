"""Access of the field values on the records: reading, writing, the descriptor protocol and the recomputation."""

from __future__ import annotations

import typing
from odoo.exceptions import AccessError, MissingError
from odoo.tools.constants import IN_MAX
from odoo.tools.misc import SENTINEL
from odoo.orm.core.utils import SUPERUSER_ID, expand_ids

if typing.TYPE_CHECKING:
    from collections.abc import Sequence
    from odoo.orm.core.types import BaseModel


def get_company_dependent_fallback(self, records):
    assert self.company_dependent
    fallback = records.env['ir.default'] \
        .with_user(SUPERUSER_ID) \
        .with_company(records.env.company) \
        ._get_model_defaults(records._name).get(self.name)
    fallback = self.convert_to_cache(fallback, records, validate=False)
    return self.convert_to_record(fallback, records)


def read(self, records: BaseModel) -> None:
    """ Read the value of ``self`` on ``records``, and store it in cache. """
    if not self.column_type:
        raise NotImplementedError("Method read() undefined on %s" % self)


def create(self, record_values: Sequence[tuple[BaseModel, typing.Any]]) -> None:
    """ Write the value of ``self`` on the given records, which have just
    been created.

    :param record_values: a list of pairs ``(record, value)``, where
        ``value`` is in the format of method :meth:`BaseModel.write`
    """
    for record, value in record_values:
        self.write(record, value)


def write(self, records: BaseModel, value: typing.Any) -> None:
    """ Write the value of ``self`` on ``records``. This method must update
    the cache and prepare database updates.

    :param records:
    :param value: a value in any format
    """
    # discard recomputation of self on records
    records.env.remove_to_compute(self, records)

    # discard the records that are not modified
    cache_value = self.convert_to_cache(value, records)
    records = self._filter_not_equal(records, cache_value)
    if not records:
        return

    # update the cache
    self._update_cache(records, cache_value, dirty=True)


def get_value[T](self, record: BaseModel, owner=None) -> T:
    """ return the value of field ``self`` on ``record`` """
    if record is None:
        return self         # the field is accessed through the owner class

    # check field access
    env = record.env
    env.su or self in env._field_access_memo or record.check_field_access(self, 'read')

    record_len = len(record._ids)
    if record_len != 1:
        if record_len:
            # let ensure_one() raise the proper exception
            record.ensure_one()
            assert False, "unreachable"
        # null record -> return the null value for this field
        value = self.convert_to_cache(False, record, validate=False)
        return self.convert_to_record(value, record)

    if self.compute and self.store and env.transaction.tocompute.get(self):
        # process pending computations
        self.recompute(record)

    try:
        field_cache = env._field_cache_memo[self]
    except KeyError:
        field_cache = self._get_cache(env)

    record_id = record._ids[0]
    try:
        value = field_cache[record_id]
        # convert to record may also throw a KeyError if the value is not
        # in cache, in that case, the fallbacks should be implemented to
        # read it correctly
        return self.convert_to_record(value, record)
    except KeyError:
        pass
    # behavior in case of cache miss:
    #
    #   on a real record:
    #       stored -> fetch from database (computation done above)
    #       not stored and computed -> compute
    #       not stored and not computed -> default
    #
    #   on a new record w/ origin:
    #       stored and not (computed and readonly) -> fetch from origin
    #       stored and computed and readonly -> compute
    #       not stored and computed -> compute
    #       not stored and not computed -> default
    #
    #   on a new record w/o origin:
    #       stored and computed -> compute
    #       stored and not computed -> new delegate or default
    #       not stored and computed -> compute
    #       not stored and not computed -> default
    #
    if self.store and record_id:
        # real record: fetch from database
        recs = self._to_prefetch(record)
        try:
            recs._fetch_field(self)
            fallback_single = False
        except AccessError:
            if len(recs) == 1:
                raise
            fallback_single = True
        if fallback_single:
            record._fetch_field(self)
        value = field_cache.get(record_id, SENTINEL)
        if value is SENTINEL:
            raise MissingError("\n".join([
                env._("Record does not exist or has been deleted."),
                env._("(Record: %(record)s, User: %(user)s)", record=record, user=env.uid),
            ])) from None

    elif self.store and record._origin and not (self.compute and self.readonly):
        # new record with origin: fetch from origin, and assign the
        # records to prefetch in cache (which is necessary for
        # relational fields to "map" prefetching ids to their value)
        recs = self._to_prefetch(record)
        try:
            for rec in recs:
                if (rec_origin := rec._origin):
                    value = self.convert_to_cache(rec_origin[self.name], rec, validate=False)
                    self._update_cache(rec, value)
            fallback_single = False
        except (AccessError, KeyError, MissingError):
            if len(recs) == 1:
                raise
            fallback_single = True
        if fallback_single:
            value = self.convert_to_cache(record._origin[self.name], record, validate=False)
            self._update_cache(record, value)
        # get the final value (see patches in x2many fields)
        value = field_cache[record_id]

    elif self.compute:
        # non-stored field or new record without origin: compute
        if env.is_protected(self, record):
            value = self.convert_to_cache(False, record, validate=False)
            self._update_cache(record, value)
        else:
            recs = record if self.recursive else self._to_prefetch(record)
            try:
                self.compute_value(recs)
                fallback_single = False
            except (AccessError, MissingError):
                fallback_single = True
            if fallback_single:
                self.compute_value(record)
                recs = record

            missing_recs_ids = tuple(self._cache_missing_ids(recs))
            if missing_recs_ids:
                missing_recs = record.browse(missing_recs_ids)
                if self.readonly and not self.store:
                    raise ValueError(f"Compute method failed to assign {missing_recs}.{self.name}")
                # fallback to null value if compute gives nothing, do it for every unset record
                false_value = self.convert_to_cache(False, record, validate=False)
                self._update_cache(missing_recs, false_value)

            # cache could have been entirely invalidated by compute
            # as some compute methods call indirectly env.invalidate_all()
            field_cache = self._get_cache(env)
            value = field_cache[record_id]

    elif self.type == 'many2one' and self.delegate and not record_id:
        # parent record of a new record: new record, with the same
        # values as record for the corresponding inherited fields
        def is_inherited_field(name):
            field = record._fields[name]
            return field.inherited and field.related.split('.')[0] == self.name

        parent = record.env[self.comodel_name].new({
            name: value
            for name, value in record._cache.items()
            if is_inherited_field(name)
        })
        # in case the delegate field has inverse one2many fields, this
        # updates the inverse fields as well
        value = self.convert_to_cache(parent, record, validate=False)
        self._update_cache(record, value)
        # set inverse fields on new records in the comodel
        # TODO move this logic to _update_cache?
        if inv_recs := parent.filtered(lambda r: not r.id):
            for invf in env.registry.field_inverses[self]:
                invf._update_inverse(inv_recs, record)

    else:
        # non-stored field or stored field on new record: default value
        value = self.convert_to_cache(False, record, validate=False)
        self._update_cache(record, value)
        defaults = record.default_get([self.name])
        if self.name in defaults:
            # The null value above is necessary to convert x2many field
            # values. For instance, converting [(Command.LINK, id)]
            # accesses the field's current value, then adds the given
            # id. Without an initial value, the conversion ends up here
            # to determine the field's value, and generates an infinite
            # recursion.
            value = self.convert_to_cache(defaults[self.name], record)
            self._update_cache(record, value)
        # get the final value (see patches in x2many fields)
        value = field_cache[record_id]

    return self.convert_to_record(value, record)


def set_value(self, records: BaseModel, value) -> None:
    """ set the value of field ``self`` on ``records`` """
    protected_ids = []
    new_ids = []
    other_ids = []
    for record_id in records._ids:
        if record_id in records.env._protected.get(self, ()):
            protected_ids.append(record_id)
        elif not record_id:
            new_ids.append(record_id)
        else:
            other_ids.append(record_id)

    if protected_ids:
        # records being computed: no business logic, no recomputation
        protected_records = records.__class__(records.env, tuple(protected_ids), records._prefetch_ids)
        self.write(protected_records, value)

    if new_ids:
        # new records: no business logic
        new_records = records.__class__(records.env, tuple(new_ids), records._prefetch_ids)
        with records.env.protecting(records.pool.field_computed.get(self, [self]), new_records):
            if self.relational:
                new_records.modified([self.name], before=True)
            self.write(new_records, value)
            new_records.modified([self.name])

        if self.inherited:
            # special case: also assign parent records if they are new
            parents = new_records[self.related.split('.')[0]]
            parents.filtered(lambda r: not r.id)[self.name] = value

    if other_ids:
        # base case: full business logic
        records = records.__class__(records.env, tuple(other_ids), records._prefetch_ids)
        write_value = self.convert_to_write(value, records)
        records.write({self.name: write_value})


def recompute(self, records: BaseModel) -> None:
    """ Process the pending computations of ``self`` on ``records``. This
    should be called only if ``self`` is computed and stored.
    """
    to_compute_ids = records.env.transaction.tocompute.get(self)
    if not to_compute_ids:
        return

    def apply_except_missing(func, records):
        """ Apply `func` on `records`, with a fallback ignoring non-existent records. """
        try:
            func(records)
            return
        except MissingError:
            pass

        existing = records.exists()
        if existing:
            func(existing)
        # mark the field as computed on missing records, otherwise they
        # remain to compute forever, which may lead to an infinite loop
        missing = records - existing
        for f in records.pool.field_computed[self]:
            records.env.remove_to_compute(f, missing)

    if self.recursive:
        # recursive computed fields are computed record by record, in order
        # to recursively handle dependencies inside records
        def recursive_compute(records):
            for record in records:
                if record.id in to_compute_ids:
                    self.compute_value(record)

        apply_except_missing(recursive_compute, records)
        return

    for record in records:
        if record.id in to_compute_ids:
            ids = tuple(expand_ids(record.id, to_compute_ids))
            recs = record.browse(ids[:IN_MAX]).with_prefetch(ids)
            try:
                apply_except_missing(self.compute_value, recs)
                continue
            except AccessError:
                pass
            self.compute_value(record)


def compute_value(self, records: BaseModel) -> None:
    """ Invoke the compute method on ``records``; the results are in cache. """
    env = records.env
    if self.compute_sudo:
        records = records.sudo()
    fields = records.pool.field_computed[self]

    # Just in case the compute method does not assign a value, we already
    # mark the computation as done. This is also necessary if the compute
    # method accesses the old value of the field: the field will be fetched
    # with _read(), which will flush() it. If the field is still to compute,
    # the latter flush() will recursively compute this field!
    for field in fields:
        if field.store:
            env.remove_to_compute(field, records)

    try:
        with records.env.protecting(fields, records):
            records._compute_field_value(self)
    except Exception:
        for field in fields:
            if field.store:
                env.add_to_compute(field, records)
        raise
