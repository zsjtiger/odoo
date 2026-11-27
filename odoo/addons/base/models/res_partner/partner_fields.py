# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The computed fields and the onchanges of the partners: the statistics, the languages, the users, the vat presence, the names, the parents and the checks."""

from __future__ import annotations

import datetime
import re
import typing
from collections import defaultdict
from zoneinfo import ZoneInfo
from werkzeug import urls
from odoo import api, tools, _
from odoo.exceptions import ValidationError
from odoo.tools import SQL

if typing.TYPE_CHECKING:
    pass


def _compute_application_statistics(self):
    result = self._compute_application_statistics_hook()
    for p in self:
        p.application_statistics = result.get(p.id, [])


def _compute_application_statistics_hook(self):
    """ Hook for override, as overriding compute method does not update
        cache accordingly. All overrides receive False instead of previously
        assigned value. """
    return defaultdict(list)


def _get_complete_name(self):
    self.ensure_one()

    displayed_types = self._complete_name_displayed_types
    type_description = dict(self._fields['type']._description_selection(self.env))

    name = self.name or ''
    if self.parent_id:
        if not name and self.type in displayed_types:
            name = type_description[self.type]
        if not self.is_company and not self.env.context.get('partner_display_name_hide_company'):
            name = f"{self.commercial_company_name or self.sudo().parent_id.name}, {name}"
    return name.strip()


def _compute_complete_name(self):
    for partner in self:
        partner.complete_name = partner.with_context({})._get_complete_name()


def _compute_lang(self):
    """ While creating / updating child contact, take the parent lang by
        default if any. 0therwise, fallback to default context / DB lang """
    for partner in self:
        if partner.parent_id:
            partner.lang = partner.parent_id.lang or partner.default_get(['lang']).get('lang') or partner.env.lang
        elif not partner.lang:
            partner.lang = partner.default_get(['lang']).get('lang') or partner.env.lang


def _compute_active_lang_count(self):
    lang_count = len(self.env['res.lang'].get_installed())
    for partner in self:
        partner.active_lang_count = lang_count


def _compute_tz_offset(self):
    for partner in self:
        partner.tz_offset = datetime.datetime.now(ZoneInfo(partner.tz or 'UTC')).strftime('%z')


def _compute_user_id(self):
    """ Synchronize sales rep with parent if partner is a person """
    for partner in self.filtered(lambda partner: not partner.user_id and not partner.is_company and partner.parent_id.user_id):
        partner.user_id = partner.parent_id.user_id


def _compute_main_user_id(self):
    partners = self
    if partner := partners & self.env.user.partner_id:
        partner.main_user_id = self.env.user
        partners -= partner
    active_users = partners.user_ids.filtered('active')
    for partner in partners:
        users = partner.user_ids & active_users
        # Special case for OdooBot as its user might be archived.
        if not users and partner.id == self.env["ir.model.data"]._xmlid_to_res_id("base.partner_root"):
            partner.main_user_id = self.env["ir.model.data"]._xmlid_to_res_id("base.user_root")
            continue
        partner.main_user_id = users.sorted(
            lambda u: (not u.share, -u.id), reverse=True,
        )[:1]


def _compute_partner_share(self):
    super_partner = self.env['res.users'].browse(api.SUPERUSER_ID).partner_id
    if super_partner in self:
        super_partner.partner_share = False
    for partner in self - super_partner:
        partner.partner_share = not partner.user_ids or not any(not user.share for user in partner.user_ids)


def _compute_get_ids(self):
    for partner in self:
        partner.self = partner.id


def _compute_commercial_partner(self):
    for partner in self:
        if not partner.parent_id:
            partner.commercial_partner_id = partner
        else:
            partner.commercial_partner_id = partner.parent_id.commercial_partner_id


def _check_parent_id(self):
    if self._has_cycle():
        raise ValidationError(_('You cannot create recursive Partner hierarchies.'))


def _check_partner_company(self):
    """
        Check that for every partner which has a company,
        if there exists a company linked to that partner,
        the company_id set on the partner is that company
        """
    partners = self.filtered(lambda p: p.is_company and p.company_id)
    companies = self.env['res.company'].search_fetch([('partner_id', 'in', partners.ids)], ['partner_id'])
    for company in companies:
        if company != company.partner_id.company_id:
            raise ValidationError(_('The company assigned to this partner does not match the company this partner represents.'))


def onchange_parent_id(self):
    # return values in result, as this method is used by _fields_sync()
    if not self.parent_id:
        return
    result = {}
    partner = self._origin
    parent_address = self.parent_id._get_address_values()
    if (partner.type or self.type) == 'contact' and bool(parent_address):
        # for contacts: copy the parent address, if set (aka, at least one
        # value is set in the address: otherwise, keep the one from the
        # contact)
        result['value'] = parent_address
    return result


def _onchange_country_id(self):
    if self.country_id and self.country_id != self.state_id.country_id:
        self.state_id = False


def _onchange_state(self):
    if self.state_id.country_id and self.country_id != self.state_id.country_id:
        self.country_id = self.state_id.country_id


def _onchange_company_id(self):
    if self.parent_id:
        self.company_id = self.parent_id.company_id.id


def _compute_email_formatted(self):
    """ Compute formatted email for partner, using formataddr. Be defensive
        in computation, notably

          * double format: if email already holds a formatted email like
            'Name' <email@domain.com> we should not use it as it to compute
            email formatted like "Name <'Name' <email@domain.com>>";
          * multi emails: sometimes this field is used to hold several addresses
            like email1@domain.com, email2@domain.com. We currently let this value
            untouched, but remove any formatting from multi emails;
          * invalid email: if something is wrong, keep it in email_formatted as
            this eases management and understanding of failures at mail.mail,
            mail.notification and mailing.trace level;
          * void email: email_formatted is False, as we cannot do anything with
            it;
        """
    self.email_formatted = False
    for partner in self:
        emails_normalized = tools.email_normalize_all(partner.email)
        if emails_normalized:
            # note: multi-email input leads to invalid email like "Name" <email1, email2>
            # but this is current behavior in Odoo 14+ and some servers allow it
            partner.email_formatted = tools.formataddr((
                partner.name or u"False",
                ','.join(emails_normalized)
            ))
        elif partner.email:
            partner.email_formatted = tools.formataddr((
                partner.name or u"False",
                partner.email
            ))


def _check_barcode_unicity(self):
    for partner in self:
        if partner.barcode and self.env['res.partner'].search_count([('barcode', '=', partner.barcode)]) > 1:
            raise ValidationError(_('Another partner already has this barcode'))


def _clean_website(self, website):
    url = urls.url_parse(website)
    if not url.scheme:
        if not url.netloc:
            url = url.replace(netloc=url.path, path='')
        website = url.replace(scheme='http').to_url()
    return website


def _compute_has_vat(self):
    for partner in self:
        vat = partner.vat
        partner.has_vat = vat and vat not in ('/', 'na', 'NA')


def _compute_sql_has_vat(self, table):
    return SQL("%s NOT IN ('/', 'na', 'NA', '')", table.vat)


def _compute_is_company(self):
    """ By default, a partner is considered as a company if they are their own
        commercial entity (see computed field), and if their VAT is considered as being
        valid, based on a default heuristic (not void, '/', 'na' or 'NA').

        Each localization can then further refine this definition according to legal
        definition of what is a company (e.g. more strict VAT, specific field usage,
        ...) """
    for partner in self:
        partner.is_company = partner.commercial_partner_id == partner and partner.has_vat


def _compute_is_public(self):
    for partner in self.with_context(active_test=False):
        users = partner.user_ids
        partner.is_public = users and any(user._is_public() for user in users)


def _compute_display_name(self):
    type_description = dict(self._fields['type']._description_selection(self.env))
    for partner in self:
        if partner.env.context.get("formatted_display_name"):
            name = partner.name or ''
            if partner.parent_id:
                name = (f"{partner.parent_id.name} \t "
                        f"--{partner.name or type_description.get(partner.type, '')}--")

            if partner.env.context.get('show_email') and partner.email:
                name = f"{name} \t --{partner.email}--"
            elif partner.env.context.get('partner_show_db_id'):
                name = f"{name} \t --{partner.id}--"

        else:
            name = partner.with_context(lang=self.env.lang)._get_complete_name()
            if partner.env.context.get('partner_show_db_id'):
                name = f"{name} ({partner.id})"
            if partner.env.context.get('show_email') and partner.email:
                name = f"{name} <{partner.email}>"
            if partner.env.context.get('show_address'):
                name = name + "\n" + partner.address

            if partner.env.context.get('show_identifier'):
                identifier = partner.vat or partner._get_preferred_legal_entity_identifier_vals().get('value')
                if identifier:
                    if partner.env.context.get('show_address'):
                        name = f"{name} \n {identifier}"
                    else:
                        name = f"{name} - {identifier}"

        # Remove extra empty lines
        name = re.sub(r'\s+\n', '\n', name)
        partner.display_name = name.strip()
