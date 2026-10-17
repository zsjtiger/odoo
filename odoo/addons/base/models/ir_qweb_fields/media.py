"""The media fields of the QWeb engine: the images and the barcodes."""

from __future__ import annotations

import re
from markupsafe import Markup
from PIL import Image
from lxml import html
from odoo import api, models
from odoo.tools import BinaryBytes, BinaryValue
from odoo.tools.files.image import binary_to_image, image_data_uri
from odoo.tools.mail import safe_attrs
from odoo.tools.text.translate import _

from .helpers import nl2br

class IrQwebFieldImage(models.AbstractModel):
    """ ``image`` widget rendering, inserts a data:uri-using image tag in the
    document. May be overridden by e.g. the website module to generate links
    instead.

    .. todo:: what happens if different output need different converters? e.g.
              reports may need embedded images or FS links whereas website
              needs website-aware
    """
    _name = 'ir.qweb.field.image'
    _description = 'Qweb Field Image'
    _inherit = ['ir.qweb.field']

    @api.model
    def _get_src_data_b64(self, value, options) -> str:
        if not isinstance(value, BinaryValue):
            value = BinaryBytes(value)
        if not value:
            return ""
        mimetype = value.mimetype
        if mimetype == 'image/webp':
            return self.env["ir.qweb"]._get_converted_image_data_uri(value)
        elif mimetype != "image/svg+xml":
            try:
                image = binary_to_image(value)
                image.verify()
                mimetype = Image.MIME[image.format]
            except OSError as exc:
                raise ValueError("Non-image binary fields can not be converted to HTML") from exc
            except Exception as exc:  # noqa: BLE001
                raise ValueError("Invalid image content") from exc

        return image_data_uri(value)

    @api.model
    def value_to_html(self, value, options):
        return Markup('<img src="%s">') % self._get_src_data_b64(value, options)


class IrQwebFieldImage_Url(models.AbstractModel):
    """ ``image_url`` widget rendering, inserts an image tag in the
    document.
    """
    _name = 'ir.qweb.field.image_url'
    _description = 'Qweb Field Image'
    _inherit = ['ir.qweb.field.image']

    @api.model
    def value_to_html(self, value, options):
        return Markup('<img src="%s">') % (value)


class IrQwebFieldBarcode(models.AbstractModel):
    """ ``barcode`` widget rendering, inserts a data:uri-using image tag in the
    document. May be overridden by e.g. the website module to generate links
    instead.
    """
    _name = 'ir.qweb.field.barcode'
    _description = 'Qweb Field Barcode'
    _inherit = ['ir.qweb.field']

    @api.model
    def get_available_options(self):
        options = super().get_available_options()
        options.update(
            symbology=dict(type='string', string=_('Barcode symbology'), description=_('Barcode type, eg: UPCA, EAN13, Code128'), default_value='Code128'),
            width=dict(type='integer', string=_('Width'), default_value=600),
            height=dict(type='integer', string=_('Height'), default_value=100),
            humanreadable=dict(type='integer', string=_('Human Readable'), default_value=0),
            quiet=dict(type='integer', string='Quiet', default_value=1),
            mask=dict(type='string', string='Mask', default_value='')
        )
        return options

    @api.model
    def value_to_html(self, value, options=None):
        if not value:
            return ''
        if not bool(re.match(r'^[\x00-\x7F]+$', value)):
            return nl2br(value)
        barcode_symbology = options.get('symbology', 'Code128')
        barcode = self.env['ir.actions.report'].barcode(
            barcode_symbology,
            value,
            **{key: value for key, value in options.items() if key in ['width', 'height', 'humanreadable', 'quiet', 'mask']})

        img_element = html.Element('img')
        for k, v in options.items():
            if k.startswith('img_') and k[4:] in safe_attrs:
                img_element.set(k[4:], v)
        if not img_element.get('alt'):
            img_element.set('alt', _('Barcode %s', value))
        img_element.set('src', image_data_uri(barcode))
        return Markup(html.tostring(img_element, encoding='unicode'))
