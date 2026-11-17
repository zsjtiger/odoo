# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The commercial partners: the synchronisation of the commercial fields with the parents, the descendants and the companies, and the contacts."""

from __future__ import annotations

import typing
from odoo import tools, _, Command
from ..partner_identifiers import (
    INDIVIDUAL_CATEGORIES,
)

if typing.TYPE_CHECKING:
    pass


def _commercial_fields(self):
    """ Returns the list of fields that are managed by the commercial entity
        to which a partner belongs. These fields are meant to be hidden on
        partners that aren't `commercial entities` themselves, or synchronized
        at update (if present in _synced_commercial_fields), and will be
        delegated to the parent `commercial entity`. The list is meant to be
        extended by inheriting classes. """
    return self._synced_commercial_fields() + ['industry_id']


def _synced_commercial_fields(self):
    """ Returns the list of fields that are managed by the commercial entity
        to which a partner belongs. When modified on a children, update is
        propagated until the commercial entity. """
    return ['vat', 'additional_identifiers']


def _get_commercial_values(self):
    """ Get commercial values from record. Return only set values, as they
        are considered individually, and only set values should be taken into
        account. """
    set_commercial_fields = [fname for fname in self._commercial_fields() if self[fname]]
    if set_commercial_fields:
        return self._convert_fields_to_values(set_commercial_fields)
    return {}


def _get_synced_commercial_values(self):
    """ Get synchronized commercial values from ercord. Return only set values
        as for other commercial values. """
    set_synced_fields = [fname for fname in self._synced_commercial_fields() if self[fname]]
    if set_synced_fields:
        return self._convert_fields_to_values(set_synced_fields)
    return {}


def _apply_synced_identifiers(self, source_identifiers):
    """ Mirror the *synced* identifiers of ``source_identifiers`` onto every record
        in ``self``, while keeping per-contact identifiers untouched.
        Per-contact identifiers are those flagged ``synced=False`` in their metadata, and
        individual identifiers, which stay on their own record.
        """
    all_metadata = self._get_all_identifiers_metadata()

    def is_shared(key):
        metadata = all_metadata.get(key, {})
        return metadata.get('synced', True) and metadata.get('category') not in INDIVIDUAL_CATEGORIES

    synced = {
        key: value
        for key, value in (source_identifiers or {}).items()
        if is_shared(key)
    }
    for record in self:
        existing = record.additional_identifiers or {}
        own = {key: value for key, value in existing.items() if not is_shared(key)}
        merged = own if any(record._is_individual_identifier(key) for key in own) else own | synced
        if merged != existing:
            record.write({'additional_identifiers': merged})


def _write_commercial_sync(self, sync_vals):
    """ Apply commercial-fields ``sync_vals`` to ``self``.
        ``additional_identifiers`` is special-cased so only its flagged synced keys
        are propagated; the remaining fields are written as-is.
        """
    if 'additional_identifiers' in sync_vals:
        sync_vals = dict(sync_vals)
        self._apply_synced_identifiers(sync_vals.pop('additional_identifiers'))
    if 'vat' in sync_vals:
        individuals = self.filtered(lambda p: any(
            p._is_individual_identifier(key) for key in (p.additional_identifiers or {})
        ))
        individuals.write({key: value for key, value in sync_vals.items() if key != 'vat'})
        (self - individuals).write(sync_vals)
    else:
        self.write(sync_vals)


def _company_dependent_commercial_fields(self):
    return [
        fname for fname in self._commercial_fields()
        if self._fields[fname].company_dependent
    ]


def _commercial_sync_from_company(self):
    """ Handle sync of commercial fields when a new parent commercial entity is set,
        as if they were related fields """
    commercial_partner = self.commercial_partner_id
    if commercial_partner != self:
        sync_vals = commercial_partner._get_commercial_values()
        if sync_vals:
            self._write_commercial_sync(sync_vals)
            self._commercial_sync_to_descendants()
        self._company_dependent_commercial_sync()


def _company_dependent_commercial_sync(self):
    """ Propagate sync of company dependant commercial fields to other
        commpanies. """
    if not (fields_to_sync := self._company_dependent_commercial_fields()):
        return

    for company_sudo in self.env['res.company'].sudo().search([]):
        if company_sudo == self.env.company:
            continue  # already handled by _commercial_sync_from_company
        self_in_company = self.with_company(company_sudo)
        self_in_company.write(
            self_in_company.commercial_partner_id._convert_fields_to_values(fields_to_sync)
        )


def _commercial_sync_to_descendants(self, fields_to_sync=None):
    """ Handle sync of commercial fields to descendants """
    commercial_partner = self.commercial_partner_id
    if fields_to_sync is None:
        fields_to_sync = self._commercial_fields()
    sync_vals = commercial_partner._convert_fields_to_values(fields_to_sync)
    sync_children = self.child_ids.filtered(lambda c: not c.is_company)
    children_ids_to_sync = tools.OrderedSet()
    for child in sync_children:
        if any(
            self.env['res.partner']._fields[fname].convert_to_write(child[fname], self) != sync_vals[fname]
            for fname in fields_to_sync
        ):
            children_ids_to_sync.add(child.id)
        child._commercial_sync_to_descendants(fields_to_sync)
    if children_ids_to_sync:
        children_to_sync = self.env['res.partner'].browse(children_ids_to_sync)
        children_to_sync._write_commercial_sync(sync_vals)


def _fields_sync(self, values):
    """ Sync commercial fields and address fields from company and to children.
        Also synchronize address to parent. This somehow mimics related fields
        to the parent, with more control. This method should be called after
        updating values in cache e.g. self should contain new values.

        :param dict values: updated values, triggering sync
        """
    self.fetch(['parent_id', 'type', 'commercial_partner_id'])
    # 1. From UPSTREAM: sync from parent
    if values.get('parent_id') or values.get('type') == 'contact':
        # 1a. Commercial fields: sync if parent changed
        if values.get('parent_id'):
            address = self._get_address_values()
            parent_address = self.parent_id._get_address_values()
            if self.type == 'contact' and bool(address) and bool(parent_address) and address != parent_address:
                # If current partner has a different address set, change it's type so we don't lost it
                self.type = 'other'
            self.sudo()._commercial_sync_from_company()
        # 1b. Address fields: sync if parent or use_parent changed *and* both are now set
        if self.parent_id and self.type == 'contact':
            if address_values := self.parent_id._get_address_values():
                self._update_address(address_values)

    # 2. To UPSTREAM: sync parent address, as well as editable synchronized commercial fields
    address_to_upstream = (
        # parent is set, potential address update as contact address = parent address
        bool(self.parent_id) and bool(self.type == 'contact') and
        # address updated, or parent updated
        (any(field in values for field in self._address_fields()) or 'parent_id' in values) and
        # something is actually updated
        any(self[fname] != self.parent_id[fname] for fname in self._address_fields())
    )
    if address_to_upstream:
        new_address = self._get_address_values()
        self.parent_id.write(new_address)  # is going to trigger _fields_sync again
    commercial_to_upstream = (
        # has a parent and is not a commercial entity itself
        bool(self.parent_id) and (self.commercial_partner_id != self) and
        # actually updated, or parent updated
        (any(field in values for field in self._synced_commercial_fields()) or 'parent_id' in values) and
        # something is actually updated
        any(self[fname] != self.parent_id[fname] for fname in self._synced_commercial_fields())
    )
    if commercial_to_upstream:
        new_synced_commercials = self._get_synced_commercial_values()
        self.parent_id._write_commercial_sync(new_synced_commercials)

    # 3. To DOWNSTREAM: sync children
    self._children_sync(values)


def _children_sync(self, values):
    if not self.child_ids:
        return
    # 2a. Commercial Fields: sync if commercial entity
    if self.commercial_partner_id == self:
        fields_to_sync = values.keys() & self._commercial_fields()
        self.sudo()._commercial_sync_to_descendants(fields_to_sync)
    # 2b. Address fields: sync if address changed
    address_fields = self._address_fields()
    if any(field in values for field in address_fields):
        contacts = self.child_ids.filtered(lambda c: c.type == 'contact')
        contacts._update_address(values)


def _handle_first_contact_creation(self):
    """ On creation of first contact for a company (or root) that has no address, assume contact address
        was meant to be company address """
    parent = self.parent_id
    address_fields = self._address_fields()
    if (
        (parent.is_company or not parent.parent_id)
        and any(self[f] for f in address_fields)
        and not any(parent[f] for f in address_fields)
        and len(parent.child_ids) == 1
    ):
        addr_vals = self._convert_fields_to_values(address_fields)
        parent._update_address(addr_vals)


def _create_parent_from_name(self, parent_name, additional_values=None):
    """ Creates a parent form a name, used mainly when creating new partners with
        a parent (often a company) consisting in a name only, not yet a record. """
    self.ensure_one()
    if not parent_name:
        raise ValueError(_('Parent Name is required at this point'))
    parent_values = dict(name=parent_name, vat=self.vat, lang=self.lang)
    parent_values.update(self._convert_fields_to_values(self._address_fields()))
    if additional_values:
        parent_values.update(**additional_values)
    parent_company = self._create_contact_parent_company(parent_values)
    # Set new company as parent
    self.write({
        'parent_id': parent_company.id,
        'child_ids': [
            Command.update(partner_id, dict(parent_id=parent_company.id))
            for partner_id in self.child_ids.ids
        ],
    })
    return parent_company


def _create_contact_parent_company(self, values):
    """ Need to avoid recomputation of vies_valid """
    self.ensure_one()
    return self.create(values)


def open_commercial_entity(self):
    """ Utility method used to add an "Open Company" button in partner views """
    self.ensure_one()
    return {'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'view_mode': 'form',
            'res_id': self.commercial_partner_id.id,
            'target': 'current',
            }
