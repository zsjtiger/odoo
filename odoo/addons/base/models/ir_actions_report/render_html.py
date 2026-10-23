# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The rendering of the reports as HTML and text: the templates, the rendering context, the layouts and the barcodes."""

import lxml.html
from lxml import etree
from markupsafe import Markup
from odoo import fields
from odoo.tools import frozendict, is_html_empty
from odoo.tools.files.barcode import (
    check_barcode_encoding,
    createBarcodeDrawing,
    get_barcode_font,
)
from odoo.tools.lru import LRU
from odoo.tools.safe_eval import time


def _get_layout(self):
    return self.env.ref('web.minimal_layout', raise_if_not_found=False)


def _get_report_url(self, layout=None):
    report_url = self.env['ir.config_parameter'].sudo().get_str('report.url')
    return report_url or (layout or self._get_layout() or self).get_base_url()


def _prepare_html(self, html, report_model=False):
    '''Divide and recreate the header/footer html by merging all found in html.
        The bodies are extracted and added to a list. Then, extract the specific_paperformat_args.
        The idea is to put all headers/footers together. Then, we will use a javascript trick
        (see minimal_layout template) to set the right header/footer during the processing of wkhtmltopdf.
        This allows the computation of multiple reports in a single call to wkhtmltopdf.
        '''

    # Return empty dictionary if 'web.minimal_layout' not found.
    layout = self._get_layout()
    if not layout:
        return {}
    base_url = self._get_report_url(layout=layout)

    root = lxml.html.fromstring(html, parser=lxml.html.HTMLParser(encoding='utf-8'))
    match_klass = "//div[contains(concat(' ', normalize-space(@class), ' '), ' {} ')]"

    header_node = etree.Element('div', id='minimal_layout_report_headers')
    footer_node = etree.Element('div', id='minimal_layout_report_footers')
    bodies = []
    res_ids = []

    body_parent = root.xpath('//main')[0]
    # Retrieve headers
    for node in root.xpath(match_klass.format('header')):
        body_parent = node.getparent()
        node.getparent().remove(node)
        header_node.append(node)

    # Retrieve footers
    for node in root.xpath(match_klass.format('footer')):
        body_parent = node.getparent()
        node.getparent().remove(node)
        footer_node.append(node)

    # Retrieve bodies
    for node in root.xpath(match_klass.format('article')):
        # set context language to body language
        IrQweb = self.env['ir.qweb']
        if node.get('data-oe-lang'):
            IrQweb = IrQweb.with_context(lang=node.get('data-oe-lang'))
        body = IrQweb._render(layout.id, {
                'subst': False,
                'body': Markup(lxml.html.tostring(node, encoding='unicode')),
                'base_url': base_url,
                'report_xml_id': self.xml_id,
                'debug': self.env.context.get("debug"),
            }, raise_if_not_found=False)
        bodies.append(body)
        if node.get('data-oe-model') == report_model:
            res_ids.append(int(node.get('data-oe-id', 0)))
        else:
            res_ids.append(None)

    if not bodies:
        body = ''.join(lxml.html.tostring(c, encoding='unicode') for c in body_parent.getchildren())
        bodies.append(body)

    # Get paperformat arguments set in the root html tag. They are prioritized over
    # paperformat-record arguments.
    specific_paperformat_args = {}
    for attribute in root.items():
        if attribute[0].startswith('data-report-'):
            specific_paperformat_args[attribute[0]] = attribute[1]

    header = self.env['ir.qweb']._render(layout.id, {
        'subst': True,
        'body': Markup(lxml.html.tostring(header_node, encoding='unicode')),
        'base_url': base_url,
        'report_xml_id': self.xml_id,
        'debug': self.env.context.get("debug"),
    })
    footer = self.env['ir.qweb']._render(layout.id, {
        'subst': True,
        'body': Markup(lxml.html.tostring(footer_node, encoding='unicode')),
        'base_url': base_url,
        'report_xml_id': self.xml_id,
        'debug': self.env.context.get("debug"),
    })

    return bodies, res_ids, header, footer, specific_paperformat_args


def barcode(self, barcode_type, value, **kwargs):
    defaults = {
        'width': (600, int),
        'height': (100, int),
        'humanreadable': (False, lambda x: bool(int(x))),
        'quiet': (True, lambda x: bool(int(x))),
        'mask': (None, lambda x: x),
        'barBorder': (4, int),
        # The QR code can have different layouts depending on the Error Correction Level
        # See: https://en.wikipedia.org/wiki/QR_code#Error_correction
        # Level 'L' – up to 7% damage   (default)
        # Level 'M' – up to 15% damage  (i.e. required by l10n_ch QR bill)
        # Level 'Q' – up to 25% damage
        # Level 'H' – up to 30% damage
        'barLevel': ('L', lambda x: x in ('L', 'M', 'Q', 'H') and x or 'L'),
    }
    kwargs = {k: validator(kwargs.get(k, v)) for k, (v, validator) in defaults.items()}
    kwargs['humanReadable'] = kwargs.pop('humanreadable')
    if kwargs['humanReadable']:
        kwargs['fontName'] = get_barcode_font()

    if kwargs['width'] * kwargs['height'] > 1200000 or max(kwargs['width'], kwargs['height']) > 10000:
        raise ValueError("Barcode too large")

    if barcode_type == 'UPCA' and len(value) in (11, 12, 13):
        barcode_type = 'EAN13'
        if len(value) in (11, 12):
            value = '0%s' % value
    elif barcode_type == 'auto':
        symbology_guess = {8: 'EAN8', 13: 'EAN13'}
        barcode_type = symbology_guess.get(len(value), 'Code128')
    elif barcode_type == 'QR':
        # for `QR` type, `quiet` is not supported. And is simply ignored.
        # But we can use `barBorder` to get a similar behaviour.
        # quiet=True & barBorder=4 by default cf above, remove border only if quiet=False
        if not kwargs['quiet']:
            kwargs['barBorder'] = 0

    if barcode_type in ('EAN8', 'EAN13') and not check_barcode_encoding(value, barcode_type):
        # If the barcode does not respect the encoding specifications, convert its type into Code128.
        # Otherwise, the report-lab method may return a barcode different from its value. For instance,
        # if the barcode type is EAN-8 and the value 11111111, the report-lab method will take the first
        # seven digits and will compute the check digit, which gives: 11111115 -> the barcode does not
        # match the expected value.
        barcode_type = 'Code128'

    try:
        mask_to_apply = None
        if kwargs['mask']:
            available_masks = self.get_available_barcode_masks()
            mask_to_apply = available_masks.get(kwargs['mask'])
        frozen_kwargs = frozendict(kwargs)
        cache = self.env.cr.cache.setdefault('ir_actions_report_barcode', LRU(256))
        cache_key = (barcode_type, value, frozen_kwargs, mask_to_apply)
        if cache_key not in cache:
            barcode = createBarcodeDrawing(barcode_type, value=value, format='png', **frozen_kwargs)
            if mask_to_apply:
                mask_to_apply(frozen_kwargs['width'], frozen_kwargs['height'], barcode)
            cache[cache_key] = barcode.asString('png')
        return cache[cache_key]
    except (ValueError, AttributeError):
        if barcode_type == 'Code128':
            raise ValueError("Cannot convert into barcode.")
        elif barcode_type == 'QR':
            raise ValueError("Cannot convert into QR code.")
        else:
            return self.barcode('Code128', value, **kwargs)


def get_available_barcode_masks(self):
    """ Hook for extension.

        This function returns the available QR-code masks, in the form of a
        list of (code, mask_function) elements, where code is a string identifying
        the mask uniquely, and mask_function is a function returning a reportlab
        Drawing object with the result of the mask, and taking as parameters:

            - width of the QR-code, in pixels
            - height of the QR-code, in pixels
            - reportlab Drawing object containing the barcode to apply the mask on
        """
    return {}


def _render_template(self, template, values=None):
    """Allow to render a QWeb template python-side. This function returns the 'ir.ui.view'
        render but embellish it with some variables/methods used in reports.
        :param values: additional methods/variables used in the rendering
        :returns: html representation of the template
        :rtype: bytes
        """
    if values is None:
        values = {}

    # Browse the user instead of using the sudo self.env.user
    user = self.env['res.users'].browse(self.env.uid)
    view_obj = self.env['ir.ui.view'].with_context(inherit_branding=False)
    values.update(
        time=time,
        context_timestamp=lambda t: fields.Datetime.context_timestamp(self.with_context(tz=user.tz), t),
        user=user,
        res_company=self.env.company,
        web_base_url=self.env['ir.config_parameter'].sudo().get_str('web.base.url'),
    )
    return view_obj._render_template(template, values).encode()


def _render_qweb_text(self, report_ref, docids, data=None):
    if not data:
        data = {}
    data.setdefault('report_type', 'text')
    report = self._get_report(report_ref)
    data = self._get_rendering_context(report, docids, data)
    return self._render_template(report.report_name, data), 'text'


def _render_qweb_html(self, report_ref, docids, data=None):
    if not data:
        data = {}
    data.setdefault('report_type', 'html')
    report = self._get_report(report_ref)
    data = self._get_rendering_context(report, docids, data)
    return self._render_template(report.report_name, data), 'html'


def _get_rendering_context_model(self, report):
    report_model_name = 'report.%s' % report.report_name
    return self.env.get(report_model_name)


def _get_rendering_context(self, report, docids, data):
    # If the report is using a custom model to render its html, we must use it.
    # Otherwise, fallback on the generic html rendering.
    report_model = self._get_rendering_context_model(report)

    data = data and dict(data) or {}

    if report_model is not None:
        data.update(report_model._get_report_values(docids, data=data))
    else:
        docs = self.env[report.model].browse(docids)
        data.update({
            'doc_ids': docids,
            'doc_model': report.model,
            'docs': docs,
        })
    data['is_html_empty'] = is_html_empty
    return data
