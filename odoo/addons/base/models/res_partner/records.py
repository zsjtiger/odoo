# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The records of the partners: their defaults, their creation, their writes and deletion, their names and the import."""

from __future__ import annotations

import collections
import typing
from odoo import models, tools, _
from odoo.exceptions import RedirectWarning, UserError, ValidationError

if typing.TYPE_CHECKING:
    pass

from .partner import ResPartner

def _default_category(self):
    return self.env['res.partner.category'].browse(self.env.context.get('category_id'))


def default_get(self, fields):
    """Add the company of the parent as default if we are creating a child partner. """
    values = super(ResPartner, self).default_get(fields)
    if 'parent_id' in fields and values.get('parent_id'):
        parent = self.browse(values.get('parent_id'))
        values['company_id'] = parent.company_id.id
    # protection for `default_type` values leaking from menu action context (e.g. for crm's email)
    if 'type' in fields and values.get('type'):
        if values['type'] not in self._fields['type'].get_values(self.env):
            values['type'] = None
    return values


def write(self, vals):
    self._clean_additional_identifiers(vals)
    if vals.get('active') is False:
        # DLE: It should not be necessary to modify this to make work the ORM. The problem was just the recompute
        # of partner.user_ids when you create a new user for this partner, see test test_70_archive_internal_partners
        # You modified it in a previous commit, see original commit of this:
        # https://github.com/odoo/odoo/commit/9d7226371730e73c296bcc68eb1f856f82b0b4ed
        #
        # RCO: when creating a user for partner, the user is automatically added in partner.user_ids.
        # This is wrong if the user is not active, as partner.user_ids only returns active users.
        # Hence this temporary hack until the ORM updates inverse fields correctly.
        self.invalidate_recordset(['user_ids'])
        users = self.env['res.users'].sudo().search([('partner_id', 'in', self.ids), ('active', '=', True)])
        if users:
            if users.sudo(False).has_access('write'):
                error_msg = _('You cannot archive contacts linked to an active user.\n'
                              'You first need to archive their associated user.\n\n'
                              'Linked active users : %(names)s', names=", ".join([u.display_name for u in users]))
                action_error = users._action_show()
                raise RedirectWarning(error_msg, action_error, _('Go to users'))
            else:
                raise ValidationError(_('You cannot archive contacts linked to an active user.\n'
                                        'Ask an administrator to archive their associated user first.\n\n'
                                        'Linked active users :\n%(names)s', names=", ".join([u.display_name for u in users])))
    if vals.get('website'):
        vals['website'] = self._clean_website(vals['website'])
    if vals.get('name'):
        for partner in self:
            for bank in partner.bank_ids:
                if bank.holder_name == partner.name:
                    bank.holder_name = vals['name']

    # filter to keep only really updated values -> field synchronize goes through
    # partner tree and we should avoid infinite loops in case same value is
    # updated due to cycles. Use case: updating a property field, which updated
    # a computed field, which has an inverse writing the same value on property
    # field. Yay.
    pre_values_list = [{fname: partner[fname] for fname in vals} for partner in self]

    # res.partner must only allow to set the company_id of a partner if it
    # is the same as the company of all users that inherit from this partner
    # (this is to allow the code from res_users to write to the partner!) or
    # if setting the company_id to False (this is compatible with any user
    # company)
    if 'company_id' in vals:
        company_id = vals['company_id']
        for partner in self:
            if company_id and partner.user_ids:
                company = self.env['res.company'].browse(company_id)
                companies = set(user.company_id for user in partner.user_ids)
                if len(companies) > 1 or company not in companies:
                    raise UserError(
                        self.env._("The selected company is not compatible with the companies of the related user(s)"))
            if partner.child_ids:
                partner.child_ids.write({'company_id': company_id})
    result = super(ResPartner, self).write(vals)
    for partner, pre_values in zip(self, pre_values_list, strict=True):
        if internal_users := partner.user_ids.filtered(lambda u: u._is_internal() and u != self.env.user):
            internal_users.check_access('write')
        updated = {fname: fvalue for fname, fvalue in vals.items() if partner[fname] != pre_values.get(fname)}
        if updated:
            partner._fields_sync(updated)
    return result


def create(self, vals_list):
    if self.env.context.get('import_file'):
        self._check_import_consistency(vals_list)
    for vals in vals_list:
        self._clean_additional_identifiers(vals)
        if vals.get('website'):
            vals['website'] = self._clean_website(vals['website'])
    partners = super(ResPartner, self).create(vals_list)
    # due to ir.default, compute is not called as there is a default value
    # hence calling the compute manually
    for partner, values in zip(partners, vals_list):
        if 'lang' not in values:
            partner._compute_lang()
        if values.get('parent_name') and not partner.parent_id:
            # Create parent company if we got 'parent_name'
            partner._create_parent_from_name(
                values.get('parent_name'),
                values.get('parent_additional_values'),
            )

    if self.env.context.get('_partners_skip_fields_sync'):
        return partners

    for partner, vals in zip(partners, vals_list):
        vals = self.env['res.partner']._add_missing_default_values(vals)
        partner._fields_sync(vals)
    return partners


def _unlink_except_user(self):
    users = self.env['res.users'].sudo().search([('partner_id', 'in', self.ids)])
    if not users:
        return  # no linked user, operation is allowed
    if self.env['res.users'].sudo(False).has_access('write'):
        error_msg = _('You cannot delete contacts linked to an active user.\n'
                      'You should rather archive them after archiving their associated user.\n\n'
                      'Linked active users : %(names)s', names=", ".join([u.display_name for u in users]))
        action_error = users._action_show()
        raise RedirectWarning(error_msg, action_error, _('Go to users'))
    else:
        raise ValidationError(_('You cannot delete contacts linked to an active user.\n'
                                'Ask an administrator to archive their associated user first.\n\n'
                                'Linked active users :\n%(names)s', names=", ".join([u.display_name for u in users])))


def _load_records_create(self, vals_list):
    partners = super(ResPartner, self.with_context(_partners_skip_fields_sync=True))._load_records_create(vals_list)

    # batch up first part of _fields_sync
    # group partners by commercial_partner_id (if not self) and parent_id (if type == contact)
    groups = collections.defaultdict(list)
    for partner, vals in zip(partners, vals_list):
        cp_id = None
        if vals.get('parent_id') and partner.commercial_partner_id != partner:
            cp_id = partner.commercial_partner_id.id

        add_id = None
        if partner.parent_id and partner.type == 'contact':
            add_id = partner.parent_id.id
        groups[(cp_id, add_id)].append(partner.id)

    for (cp_id, add_id), children in groups.items():
        # values from parents (commercial, regular) written to their common children
        to_write = {}
        # commercial fields from commercial partner
        if cp_id:
            to_write = self.sudo().browse(cp_id)._convert_fields_to_values(self._commercial_fields())
        # address fields from parent
        if add_id:
            parent = self.browse(add_id)
            for f in self._address_fields():
                v = parent[f]
                if v:
                    to_write[f] = v.id if isinstance(v, models.BaseModel) else v
        if to_write:
            self.sudo().browse(children).write(to_write)

    # do the second half of _fields_sync the "normal" way
    for partner, vals in zip(partners, vals_list):
        partner._children_sync(vals)
        partner._handle_first_contact_creation()
    return partners


def name_create(self, name):
    """ Override of orm's name_create method for partners. The purpose is
            to handle some basic formats to create partners using the
            name_create.
            If only an email address is received and that the regex cannot find
            a name, the name will have the email value.
            If 'force_email' key in context: must find the email address. """
    default_type = self.env.context.get('default_type')
    if default_type and default_type not in self._fields['type'].get_values(self.env):
        context = dict(self.env.context)
        context.pop('default_type')
        self = self.with_context(context)
    name, email_normalized = tools.parse_contact_from_email(name)
    if self.env.context.get('force_email') and not email_normalized:
        raise ValidationError(_("Couldn't create contact without email address!"))

    create_values = {self._rec_name: name or email_normalized}
    if email_normalized:  # keep default_email in context
        create_values['email'] = email_normalized
    partner = self.create(create_values)
    return partner.id, partner.display_name


def find_or_create(self, email, assert_valid_email=False):
    """ Find a partner with the given ``email`` or use :meth:`name_create`
        to create a new one.

        :param str email: email-like string, which should contain at least one email,
            e.g. ``"Raoul Grosbedon <r.g@grosbedon.fr>"``
        :param bool assert_valid_email: raise if no valid email is found
        :return: newly created record
        """
    if not email:
        raise ValueError(_('An email is required for find_or_create to work'))

    parsed_name, parsed_email_normalized = tools.parse_contact_from_email(email)
    if not parsed_email_normalized and assert_valid_email:
        raise ValueError(_('A valid email is required for find_or_create to work properly.'))

    if parsed_email_normalized:
        partners = self.search([('email', '=ilike', parsed_email_normalized)], limit=1)
        if partners:
            return partners

    create_values = {self._rec_name: parsed_name or parsed_email_normalized}
    if parsed_email_normalized:  # keep default_email in context
        create_values['email'] = parsed_email_normalized
    return self.create(create_values)


def get_import_templates(self):
    return [{
        'label': _('Template for Contacts'),
        'template': '/base/static/xls/contacts_import_template.xlsx',
    }]


def _check_import_consistency(self, vals_list):
    """
        The values created by an import are generated by a name search, field by field.
        As a result there is no check that the field values are consistent with each others.
        We check that if the state is given a value, it does belong to the given country, or we remove it.
        """
    States = self.env['res.country.state']
    states_ids = {vals['state_id'] for vals in vals_list if vals.get('state_id')}
    state_to_country = States.search_read([('id', 'in', list(states_ids))], ['country_id'])
    for vals in vals_list:
        if vals.get('state_id'):
            country_id = next(c['country_id'][0] for c in state_to_country if c['id'] == vals.get('state_id'))
            state = States.browse(vals['state_id'])
            if state.country_id.id != country_id:
                state_domain = [('code', '=', state.code),
                                ('country_id', '=', country_id)]
                state = States.search(state_domain, limit=1)
                vals['state_id'] = state.id  # replace state or remove it if not found
