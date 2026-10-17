# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The addresses of the partners: the formatting, the address fields, the display and the lookups of the addresses."""

from __future__ import annotations

import re
import typing
from collections import defaultdict
from odoo import _
from odoo.tools.business_data import street_split
from ..address_mixins import ADDRESS_FIELDS

if typing.TYPE_CHECKING:
    pass

from .partner import ResPartner

def country_name(self):
    return self.country_id.name or ''


def _get_street_split(self):
    return street_split(self.street or '')


def _compute_type_address_label(self):
    for partner in self:
        if partner.type == 'invoice':
            partner.type_address_label = _('Invoice Address')
        elif partner.type == 'delivery':
            partner.type_address_label = _('Delivery Address')
        else:
            partner.type_address_label = _('Address')


def _compute_address(self):
    for partner in self:
        partner.contact_address = partner._display_address()
        partner.address = partner._display_address(without_name=True)
        partner.contact_address_inline = partner._display_address(separator=', ')
        partner.address_inline = partner._display_address(without_name=True, separator=', ')


def _convert_fields_to_values(self, field_names):
    """ Returns dict of write() values for synchronizing ``field_names`` """
    if any(self._fields[fname].type == 'one2many' for fname in field_names):
        raise AssertionError(_('One2Many fields cannot be synchronized as part of `commercial_fields` or `address fields`'))
    return self._convert_to_write({fname: self[fname] for fname in field_names})


def _address_fields(self):
    """Returns the list of address fields that are synced from the parent."""
    return list(ADDRESS_FIELDS)


def _formatting_address_fields(self):
    """Returns the list of address fields usable to format addresses."""
    return self._address_fields()


def _get_address_values(self):
    """ Get address values from record if at least one value is set. Otherwise
        it is considered empty and nothing is returned. """
    address_fields = self._address_fields()
    if any(self[key] for key in address_fields):
        return self._convert_fields_to_values(address_fields)
    return {}


def _update_address(self, vals):
    """ Filter values from vals that are liked to address definition, and
        update recordset using super(ResPartner, self).write to avoid loops and side effects
        due to synchronization of address fields through partner hierarchy. """
    addr_vals = {key: vals[key] for key in self._address_fields() if key in vals}
    if addr_vals:
        super(ResPartner, self).write(addr_vals)


def address_get(self, adr_pref=None):
    """ Find contacts/addresses of the right type(s) by doing a depth-first-search
        through descendants within company boundaries (stop at entities flagged ``is_company``)
        then continuing the search at the ancestors that are within the same company boundaries.
        Defaults to partners of type ``'default'`` when the exact type is not found, or to the
        provided partner itself if no type ``'default'`` is found either. """
    adr_pref = set(adr_pref or [])
    if 'contact' not in adr_pref:
        adr_pref.add('contact')
    result = {}
    visited = set()
    for partner in self:
        current_partner = partner
        while current_partner:
            to_scan = [current_partner]
            # Scan descendants, DFS
            while to_scan:
                record = to_scan.pop(0)
                visited.add(record)
                if record.type in adr_pref and not result.get(record.type):
                    result[record.type] = record.id
                if len(result) == len(adr_pref):
                    return result
                record.child_ids.fetch(['type', 'child_ids', 'is_company', 'parent_id'])
                to_scan = [c for c in record.child_ids
                             if c not in visited
                             if not c.is_company] + to_scan

            # Continue scanning at ancestor if current_partner is not a commercial entity
            if current_partner.is_company or not current_partner.parent_id:
                break
            current_partner = current_partner.parent_id

    # default to type 'contact' or the partner itself
    default = result.get('contact', self.id or False)
    for adr_type in adr_pref:
        result[adr_type] = result.get(adr_type) or default
    return result


def view_header_get(self, view_id, view_type):
    if self.env.context.get('category_id'):
        return  _(
            'Partners: %(category)s',
            category=self.env['res.partner.category'].browse(self.env.context['category_id']).name,
        )
    return super(ResPartner, self).view_header_get(view_id, view_type)


def _get_default_address_format(self):
    return "%(street)s\n%(street2)s\n%(city)s %(state_code)s %(zip)s\n%(country_name)s"


def _get_address_format(self):
    return self.country_id.address_format or self._get_default_address_format()


def _prepare_display_address(self, without_name=False):
    # get the information that will be injected into the display format
    # get the address format
    address_format = self._get_address_format()
    args = defaultdict(str, {
        'state_code': self.state_id.code or '',
        'state_name': self.state_id.name or '',
        'country_code': self.country_id.code or '',
        'country_name': self.country_name,
        'parent_name': self.commercial_company_name or '',
    })
    for field in self._formatting_address_fields():
        args[field] = self[field] or ''
    if without_name:
        args['parent_name'] = ''
    elif self.parent_id:
        address_format = '%(parent_name)s\n' + address_format
    return address_format, args


def _display_address(self, without_name=False, separator='\n'):
    '''
        The purpose of this function is to build and return an address formatted accordingly to the
        standards of the country where it belongs.

        :param without_name: if address contains name
        :returns: the address formatted in a display that fit its country habits (or the default ones
            if not country is specified)
        :rtype: string
        '''
    address_format, args = self._prepare_display_address(without_name)
    address = address_format % args
    address = re.sub(r' {2,}', ' ', address)  # Remove extra space
    return separator.join(val for line in address.splitlines() if (val := line.strip()))


def _display_address_depends(self):
    # field dependencies of method _display_address()
    return self._formatting_address_fields() + [
        'country_id', 'parent_id', 'state_id',
    ]


def _get_all_addr(self):
    self.ensure_one()
    return [{
        'contact_type': self.street,
        'street': self.street,
        'street2': self.street2,
        'zip': self.zip,
        'city': self.city,
        'state': self.state_id.code,
        'country': self.country_id.code,
    }]


def _get_res_city_by_name(self, name, country_id):
    pass
