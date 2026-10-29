"""The text fields of the QWeb engine: the texts, the selections and the HTML."""

from __future__ import annotations

from markupsafe import Markup, escape
from lxml import etree
from odoo import api, models
from odoo.tools.text.translate import _

from .helpers import nl2br

class IrQwebFieldText(models.AbstractModel):
    _name = 'ir.qweb.field.text'
    _description = 'Qweb Field Text'
    _inherit = ['ir.qweb.field']

    @api.model
    def value_to_html(self, value, options):
        """
        Escapes the value and converts newlines to br. This is bullshit.
        """
        return nl2br(value) if value else ''

    @api.model
    def attributes(self, record, field_name, options, values=None):
        attrs = super().attributes(record, field_name, options, values)
        attrs['dir'] = 'auto'
        return attrs


class IrQwebFieldSelection(models.AbstractModel):
    _name = 'ir.qweb.field.selection'
    _description = 'Qweb Field Selection'
    _inherit = ['ir.qweb.field']

    @api.model
    def get_available_options(self):
        options = super().get_available_options()
        options.update(
            selection=dict(type='selection', string=_('Selection'), description=_('By default the widget uses the field information'), required=True)
        )
        options.update(
            selection=dict(type='json', string=_('Json'), description=_('By default the widget uses the field information'), required=True)
        )
        return options

    @api.model
    def value_to_html(self, value, options):
        if not value:
            return ''
        return escape(options['selection'].get(value, value) or '')

    @api.model
    def record_to_html(self, record, field_name, options):
        if 'selection' not in options:
            options = dict(options, selection=dict(record._fields[field_name].get_description(self.env)['selection']))
        return super().record_to_html(record, field_name, options)


class IrQwebFieldHtml(models.AbstractModel):
    _name = 'ir.qweb.field.html'
    _description = 'Qweb Field HTML'
    _inherit = ['ir.qweb.field']

    def _post_processing_att(self, tag, attrib):
        self.env['ir.qweb']._remove_translate_suffix(attrib)
        return self.env['ir.qweb']._post_processing_att(tag, attrib)

    @api.model
    def value_to_html(self, value, options):
        # wrap value inside a body and parse it as HTML
        body = etree.fromstring("<body>%s</body>" % value, etree.HTMLParser(encoding='utf-8'))[0]
        # use pos processing for all nodes with attributes
        for element in body.iter():
            if element.attrib:
                attrib = dict(element.attrib)
                attrib = self._post_processing_att(element.tag, attrib)
                element.attrib.clear()
                element.attrib.update(attrib)
        return Markup(etree.tostring(body, encoding='unicode', method='html')[6:-7])
