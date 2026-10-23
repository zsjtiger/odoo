"""The relational fields of the QWeb engine: the many2one, many2many and one2many fields, the contacts and the QWeb templates."""

from __future__ import annotations

import logging
from markupsafe import Markup, escape
from odoo import api, models
from odoo.tools.text.translate import _

from .helpers import nl2br

_logger = logging.getLogger('odoo.addons.base.models.ir_qweb_fields')


class IrQwebFieldMany2one(models.AbstractModel):
    _name = 'ir.qweb.field.many2one'
    _description = 'Qweb Field Many to One'
    _inherit = ['ir.qweb.field']

    @api.model
    def value_to_html(self, value, options):
        if not value:
            return False
        value = value.sudo().display_name
        if not value:
            return False
        return nl2br(value)


class IrQwebFieldMany2many(models.AbstractModel):
    _name = 'ir.qweb.field.many2many'
    _description = 'Qweb field many2many'
    _inherit = ['ir.qweb.field']

    @api.model
    def value_to_html(self, value, options):
        if not value:
            return False
        text = ', '.join(value.sudo().mapped('display_name'))
        return nl2br(text)


class IrQwebFieldOne2many(models.AbstractModel):
    _name = 'ir.qweb.field.one2many'
    _description = 'Qweb field one2many'
    _inherit = ['ir.qweb.field']

    @api.model
    def value_to_html(self, value, options):
        if not value:
            return False
        text = ', '.join(value.sudo().mapped('display_name'))
        return nl2br(text)


class IrQwebFieldContact(models.AbstractModel):
    _name = 'ir.qweb.field.contact'
    _description = 'Qweb Field Contact'
    _inherit = ['ir.qweb.field.many2one']

    @api.model
    def get_available_options(self):
        options = super().get_available_options()
        contact_fields = [
            {'field_name': 'name', 'label': _('Name'), 'default': True},
            {'field_name': 'address', 'label': _('Address'), 'default': True},
            {'field_name': 'phone', 'label': _('Phone'), 'default': True},
            {'field_name': 'email', 'label': _('Email'), 'default': True},
            {'field_name': 'vat', 'label': _('VAT')},
        ]
        separator_params = dict(
            type='selection',
            selection=[[" ", _("Space")], [",", _("Comma")], ["-", _("Dash")], ["|", _("Vertical bar")], ["/", _("Slash")]],
            placeholder=_('Linebreak'),
        )
        options.update(
            fields=dict(type='array', params=dict(type='selection', params=contact_fields), string=_('Displayed fields'), description=_('List of contact fields to display in the widget'), default_value=[param.get('field_name') for param in contact_fields if param.get('default')]),
            separator=dict(type='selection', params=separator_params, string=_('Address separator'), description=_('Separator use to split the address from the display_name.'), default_value=False),
            no_marker=dict(type='boolean', string=_('Hide badges'), description=_("Don't display the font awesome marker")),
            no_tag_br=dict(type='boolean', string=_('Use comma'), description=_("Use comma instead of the <br> tag to display the address")),
            phone_icons=dict(type='boolean', string=_('Display phone icons'), description=_("Display the phone icons even if no_marker is True")),
            country_image=dict(type='boolean', string=_('Display country image'), description=_("Display the country image if the field is present on the record")),
        )
        return options

    @api.model
    def value_to_html(self, value, options):
        if not value:
            if options.get('null_text'):
                val = {
                    'options': options,
                }
                template_options = options.get('template_options', {})
                return self.env['ir.qweb']._render('base.no_contact', val, **template_options)
            return ''

        opf = options.get('fields') or ["name", "address", "phone", "email"]
        sep = options.get('separator')
        if sep:
            opsep = escape(sep)
        elif options.get('no_tag_br'):
            # escaped joiners will auto-escape joined params
            opsep = escape(', ')
        else:
            opsep = Markup('<br/>')

        value = value.sudo().with_context(show_address=True)
        display_name = value.display_name or ''
        # Avoid having something like:
        # display_name = 'Foo\n  \n' -> This is a res.partner with a name and no address
        # That would return markup('<br/>') as address. But there is no address set.
        if any(elem.strip() for elem in display_name.split("\n")[1:]):
            address = opsep.join(display_name.split("\n")[1:]).strip()
        else:
            address = ''
        val = {
            'name': display_name.split("\n")[0],
            'address': address,
            'phone': value.phone,
            'city': value.city,
            'country_id': value.country_id.display_name,
            'website': value.website,
            'email': value.email,
            'vat': value.vat,
            'vat_label': value.country_id.vat_label or _('VAT'),
            'fields': opf,
            'object': value,
            'options': options
        }
        return self.env['ir.qweb']._render('base.contact', val, minimal_qcontext=True)


class IrQwebFieldQweb(models.AbstractModel):
    _name = 'ir.qweb.field.qweb'
    _description = 'Qweb Field qweb'
    _inherit = ['ir.qweb.field.many2one']

    @api.model
    def record_to_html(self, record, field_name, options):
        view = record[field_name]
        if not view:
            return ''

        if view._name != "ir.ui.view":
            _logger.warning("%s.%s must be a 'ir.ui.view', got %r.", record, field_name, view._name)
            return ''

        return self.env['ir.qweb']._render(view.id, options.get('values', {}))
