# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The access to the attachments through their related records: the access rights, the searches and the serving groups."""

from __future__ import annotations

import typing
import warnings
from collections import defaultdict
from odoo import _
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.fields import Domain
from odoo.tools import OrderedSet
from odoo.tools.constants import IN_MAX
from .helpers import (
    MAX_COMODELS_FOR_DOMAIN,
    MAX_SEARCH_LIMIT,
    SECURITY_FIELDS,
    condition_values,
)

if typing.TYPE_CHECKING:
    from collections.abc import Collection

from .attachment import IrAttachment

def _compute_res_name(self):
    for attachment in self:
        if attachment.res_model and attachment.res_id:
            record = self.env[attachment.res_model].browse(attachment.res_id)
            attachment.res_name = record.display_name
        else:
            attachment.res_name = False


def get_serving_groups(self):
    """ An ir.attachment record may be used as a fallback in the
        http dispatch if its type field is set to "binary" and its url
        field is set as the request's url. Only the groups returned by
        this method are allowed to create and write on such records.
        """
    return ['base.group_system']


def _check_serving_attachments(self):
    if self.env.is_admin():
        return
    for attachment in self:
        # restrict writing on attachments that could be served by the
        # ir.http's dispatch exception handling
        # XDO note: if read on sudo, read twice, one for constraints, one for _inverse_raw as user
        if attachment.type == 'binary' and attachment.url:
            has_group = self.env.user.has_group
            if not any(has_group(g) for g in attachment.get_serving_groups()):
                raise ValidationError(_("Sorry, you are not allowed to write on this document"))


def _check_circular_attachment(self):
    for record in self.sudo():
        if record.res_model == 'ir.attachment' and record.id == record.res_id:
            raise ValidationError(_(
                "You cannot attach an attachment to itself.\n"
                "Attachment %(record)s cannot have res_id: %(res_id)s",
                record=record, res_id=record))


def check(self, mode, values=None):
    """ Restricts the access to an ir.attachment, according to referred mode """
    warnings.warn("Since 19.0, use check_access", DeprecationWarning, stacklevel=2)
    # Always require an internal user (aka, employee) to access to a attachment
    if not (self.env.is_admin() or self.env.user._is_internal()):
        raise AccessError(_("Sorry, you are not allowed to access this document."))
    self.check_access(mode)
    if values and any(self._inaccessible_comodel_records({values.get('res_model'): [values.get('res_id')]}, mode)):
        raise AccessError(_("Sorry, you are not allowed to access this document."))


def _make_access_error_message(self, operation, domain):
    if not domain.is_false():
        return AccessError(self.env._(
            "Sorry, you are not allowed to access this document. "
            "Please contact your system administrator.\n\n"
            "(Operation: %(operation)s)\n\n"
            "Records: %(records)s, User: %(user)s",
            operation=operation,
            records=self[:6],
            user=self.env.uid,
        ))
    return super(IrAttachment, self)._make_access_error_message(operation, domain)


def _compute_res_access(self, operation: str):
    """Check access for attachments.

        Rules:

        - If we have `res_model and res_id`, the attachment is accessible if the
          referenced model is accessible. Also, when `res_field != False` and
          the user is not an administrator, we check the access on the field.
        - If we don't have a referenced record, the attachment is accessible to
          the administrator and the creator of the attachment.
        """
    assert operation in ('read', 'write') and self.env.su
    field_name = f'res_access_{operation}'

    # collect the records to check (by model)
    model_ids = defaultdict(set)            # {model_name: set(ids)}
    att_model_ids = []                      # [(att_id, (res_model, res_id))]
    # DLE P173: `test_01_portal_attachment`
    self.fetch(SECURITY_FIELDS)  # fetch only these fields
    user_model = self.sudo(False)
    forbidden_ids = set()
    for attachment in self:
        att_id = attachment.id
        res_model, res_id = attachment.res_model, attachment.res_id
        if not user_model.env.is_system():
            if not res_id and attachment.create_uid.id != self.env.uid:
                forbidden_ids.add(att_id)
                continue
            if res_field := attachment.res_field:
                try:
                    field = self.env[res_model]._fields[res_field]
                except KeyError:
                    # field does not exist
                    field = None
                if field is None or not user_model.has_field_access(field, operation):
                    forbidden_ids.add(att_id)
                    continue
        if res_model and res_id:
            model_ids[res_model].add(res_id)
            att_model_ids.append((att_id, (res_model, res_id)))
    forbidden_res_model_id = set(user_model._inaccessible_comodel_records(model_ids, operation))
    forbidden_ids.update(att_id for att_id, res in att_model_ids if res in forbidden_res_model_id)

    if forbidden_ids:
        forbidden = self.browse(forbidden_ids)
        forbidden.invalidate_recordset(SECURITY_FIELDS)  # avoid cache pollution
        for attachment in self:
            attachment[field_name] = attachment.id not in forbidden_ids
    else:
        self[field_name] = True


def _search_res_access(self, operation, domain_operator):
    assert operation in ('read', 'write') and self.env.su
    if domain_operator != 'in':
        return NotImplemented
    domain = self.env.context.get('search_domain')
    if not isinstance(domain, Domain):
        domain = Domain.TRUE
    sec_domain = Domain.FALSE
    self = self.sudo(False)  # noqa: PLW0642

    # - res_id == False needs to be system user or creator
    res_ids = condition_values(self, 'res_id', domain)
    if not res_ids or False in res_ids:
        if self.env.is_system():
            sec_domain |= Domain('res_id', '=', False)
        else:
            sec_domain |= Domain('res_id', '=', False) & Domain('create_uid', '=', self.env.uid)

    # Search by res_model and res_id, filter using permissions from res_model
    # - res_id != False needs then check access on the linked res_model record
    # - res_field != False needs to check field access on the res_model
    res_model_names = condition_values(self, 'res_model', domain)
    if 0 < len(res_model_names or ()) <= MAX_COMODELS_FOR_DOMAIN:
        env = self.with_context(active_test=False).env
        check_res_fields = not self.env.is_system() and tuple(condition_values(self, 'res_field', domain) or ()) != (False,)
        for res_model_name in res_model_names:
            comodel = env.get(res_model_name)
            if comodel is None:
                continue
            codomain = Domain('res_model', '=', comodel._name)
            comodel_res_ids = condition_values(self, 'res_id', domain.map_conditions(
                lambda cond: codomain & cond if cond.field_expr == 'res_model' else cond
            ))
            comodel_domain = Domain('id', 'in', comodel_res_ids) if comodel_res_ids else Domain.TRUE
            if operation != 'read':
                comodel_domain &= comodel._access_domain(operation).optimize_full(comodel.sudo())
            query = comodel._search(comodel_domain)
            if query.is_empty():
                continue
            if query.where_clause:
                codomain &= Domain('res_id', 'in', query)
            if check_res_fields:
                accessible_fields = [
                    field.name
                    for field in comodel._fields.values()
                    if field.type == 'binary' or (field.relational and field.comodel_name == self._name)
                    if comodel.has_field_access(field, operation)
                ]
                accessible_fields.append(False)
                codomain &= Domain('res_field', 'in', accessible_fields)
            sec_domain |= codomain

        return sec_domain

    # We do not have a small restriction on res_model. We still need to
    # support other queries such as: `('id', 'in' ...)`.
    records = self.sudo().with_context(active_test=False).search_fetch(
        domain & Domain('res_model', '!=', False) & ~sec_domain, SECURITY_FIELDS, order='id', limit=MAX_SEARCH_LIMIT).sudo(False)
    if len(records) == MAX_SEARCH_LIMIT:  # avoid out of memory
        raise ValueError(self.env._("Cannot search, too many attachments"))
    records = records._filtered_access(operation)
    # [('id', 'any!', query_with_ids)] is optimized in sec_domain
    return sec_domain | Domain('id', 'any!', records._as_query(ordered=False))


def _inaccessible_comodel_records(self, model_and_ids: dict[str, Collection[int]], operation: str):
    # check access rights on the records
    if self.env.su:
        return
    for res_model, res_ids in model_and_ids.items():
        res_ids = OrderedSet(filter(None, res_ids))
        if not res_model or not res_ids:
            # nothing to check
            continue
        # forbid access to attachments linked to removed models as we do not
        # know what persmissions should be checked
        if res_model not in self.env:
            for res_id in res_ids:
                yield res_model, res_id
            continue
        records = self.env[res_model].browse(res_ids)
        if res_model == 'res.users' and len(records) == 1 and self.env.uid == records.id:
            # by default a user cannot write on itself, despite the list of writeable fields
            # e.g. in the case of a user inserting an image into his image signature
            # we need to bypass this check which would needlessly throw us away
            continue
        try:
            records = records._filtered_access(operation)
        except MissingError:
            records = records.exists()._filtered_access(operation)
        res_ids.difference_update(records._ids)
        for res_id in res_ids:
            yield res_model, res_id


def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
    assert not self._active_name, "active name not supported on ir.attachment"
    domain = Domain(domain)
    if (
        not self.env.context.get('skip_res_field_check')
        and not any(d.field_expr in ('id', 'res_field') for d in domain.iter_conditions())
        and not bypass_access
    ):
        domain &= Domain('res_field', '=', False)

    domain = domain.optimize_full(self)
    if self.env.su or bypass_access or domain.is_false():
        return super(IrAttachment, self)._search(domain, offset, limit, order, active_test=active_test, bypass_access=bypass_access)
    if self.env.context.get('_generating_sql_for_fields'):
        raise ValueError("Cannot generate SQL for whole ir.attachment")
    if 0 < len(condition_values(self, 'res_model', domain) or ()) <= MAX_COMODELS_FOR_DOMAIN:
        return super(IrAttachment, self)._search(domain, offset, limit, order, active_test=active_test, bypass_access=bypass_access)

    self_sudo = self.sudo().with_context(active_test=False)
    ordered = bool(order)
    if limit is None:
        records = self_sudo.search_fetch(
            domain, SECURITY_FIELDS, order=order).sudo(False)
        return records._filtered_access('read')[offset:]._as_query(ordered)
    # Fetch by small batches
    sub_offset = 0
    limit += offset
    result = []
    if not ordered:
        # By default, order by model to batch access checks.
        order = 'res_model nulls first, id'
    while len(result) < limit:
        records = self_sudo.search_fetch(
            domain,
            SECURITY_FIELDS,
            offset=sub_offset,
            limit=IN_MAX,
            order=order,
        ).sudo(False)
        result.extend(records._filtered_access('read')._ids)
        if len(records) < IN_MAX:
            # There are no more records
            break
        sub_offset += IN_MAX
    return self.browse(result[offset:limit])._as_query(ordered)
