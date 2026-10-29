"""The numeric fields of the QWeb engine: the integers, the floats, the monetary amounts and the float times."""

from __future__ import annotations

import math
from markupsafe import Markup
from odoo import api, models, tools
from odoo.tools import float_is_zero, format_duration
from odoo.tools.numeric import float_utils
from odoo.tools.text.translate import _


class IrQwebFieldInteger(models.AbstractModel):
    _name = 'ir.qweb.field.integer'
    _description = 'Qweb Field Integer'
    _inherit = ['ir.qweb.field']

    @api.model
    def get_available_options(self):
        options = super().get_available_options()
        options.update(
            format_decimalized_number=dict(type='boolean', string=_('Decimalized number')),
            precision_digits=dict(type='integer', string=_('Precision Digits')),
        )
        return options

    @api.model
    def value_to_html(self, value, options):
        if options.get('format_decimalized_number'):
            return tools.misc.format_decimalized_number(value, options.get('precision_digits', 1))
        return self.user_lang().format('%d', value, grouping=True).replace(r'-', '-\N{ZERO WIDTH NO-BREAK SPACE}')


class IrQwebFieldFloat(models.AbstractModel):
    _name = 'ir.qweb.field.float'
    _description = 'Qweb Field Float'
    _inherit = ['ir.qweb.field']

    @api.model
    def get_available_options(self):
        options = super().get_available_options()
        options.update(
            precision=dict(type='integer', string=_('Rounding precision')),
        )
        return options

    @api.model
    def value_to_html(self, value, options):
        min_precision = options.get('min_precision')
        if 'decimal_precision' in options:
            precision = self.env['decimal.precision'].precision_get(options['decimal_precision'])
        elif options.get('precision') is None:
            # We display maximum 6 decimal digits
            precision = 6
            if min_precision is None:
                min_precision = 1
        else:
            precision = options['precision']

        # We use the precision or the maximum of relevant decimal digits if it's lower
        int_digits = int(math.log10(abs(value))) + 1 if value != 0 else 1
        max_dec_digits = max(14 - int_digits, 0)
        precision = min(precision, max_dec_digits)

        fmt = f'%.{precision}f'
        if min_precision is not None and min_precision < precision:
            _, dec_part = float_utils.float_split_str(value, precision)
            digits_count = len(dec_part.rstrip('0'))
            if digits_count < min_precision:
                fmt = f'%.{min_precision}f'
            elif digits_count < precision:
                fmt = f'%.{digits_count}f'

        value = float_utils.float_round(value, precision_digits=precision)
        return self.user_lang().format(fmt, value, grouping=True).replace(r'-', '-\N{ZERO WIDTH NO-BREAK SPACE}')

    @api.model
    def record_to_html(self, record, field_name, options):
        field = record._fields[field_name]
        if 'precision' not in options and 'decimal_precision' not in options:
            _, precision = field.get_digits(record.env) or (None, None)
            options = dict(options, precision=precision)
        if 'min_precision' not in options and hasattr(field, 'get_min_display_digits'):
            min_precision = field.get_min_display_digits(record.env)
            options = dict(options, min_precision=min_precision)
        return super().record_to_html(record, field_name, options)


class IrQwebFieldMonetary(models.AbstractModel):
    """ ``monetary`` converter, has a mandatory option
    ``display_currency`` only if field is not of type Monetary.
    Otherwise, if we are in presence of a monetary field, the field definition must
    have a currency_field attribute set.

    The currency is used for formatting *and rounding* of the float value. It
    is assumed that the linked res_currency has a non-empty rounding value and
    res.currency's ``round`` method is used to perform rounding.

    .. note:: the monetary converter internally adds the qweb context to its
              options mapping, so that the context is available to callees.
              It's set under the ``_values`` key.
    """
    _name = 'ir.qweb.field.monetary'
    _description = 'Qweb Field Monetary'
    _inherit = ['ir.qweb.field']

    @api.model
    def get_available_options(self):
        options = super().get_available_options()
        options.update(
            from_currency=dict(type='model', params='res.currency', string=_('Original currency')),
            display_currency=dict(type='model', params='res.currency', string=_('Display currency'), required="value_to_html"),
            date=dict(type='date', string=_('Date'), description=_('Date used for the original currency (only used for t-out). by default use the current date.')),
            company_id=dict(type='model', params='res.company', string=_('Company'), description=_('Company used for the original currency (only used for t-out). By default use the user company')),
        )
        return options

    @api.model
    def value_to_html(self, value, options):
        display_currency = options['display_currency']

        if not isinstance(value, (int, float)):
            raise ValueError(_("The value send to monetary field is not a number."))

        # lang.format mandates a sprintf-style format. These formats are non-
        # minimal (they have a default fixed precision instead), and
        # lang.format will not set one by default. currency.round will not
        # provide one either. So we need to generate a precision value
        # (integer > 0) from the currency's rounding (a float generally < 1.0).
        fmt = "%.{0}f".format(options.get('decimal_places', display_currency.decimal_places))

        if options.get('from_currency'):
            date = options.get('date')
            company_id = options.get('company_id')
            if company_id:
                company = self.env['res.company'].browse(company_id)
            else:
                company = self.env.company
            value = options['from_currency']._convert(value, display_currency, company, date)

        if float_is_zero(value, precision_digits=display_currency.decimal_places):
            value = 0.0

        lang = self.user_lang()
        formatted_amount = lang.format(fmt, display_currency.round(value), grouping=True)\
            .replace(r' ', '\N{NO-BREAK SPACE}').replace(r'-', '-\N{ZERO WIDTH NO-BREAK SPACE}')

        pre = post = ''
        if display_currency.position == 'before':
            pre = '{symbol}\N{NO-BREAK SPACE}'.format(symbol=display_currency.symbol or '')
        else:
            post = '\N{NO-BREAK SPACE}{symbol}'.format(symbol=display_currency.symbol or '')

        if options.get('label_price') and lang.decimal_point in formatted_amount:
            sep = lang.decimal_point
            integer_part, decimal_part = formatted_amount.split(sep)
            integer_part += sep
            return Markup('{pre}<span class="oe_currency_value">{0}</span><span class="oe_currency_value" style="font-size:0.5em">{1}</span>{post}').format(integer_part, decimal_part, pre=pre, post=post)

        return Markup('{pre}<span class="oe_currency_value">{0}</span>{post}').format(formatted_amount, pre=pre, post=post)

    @api.model
    def record_to_html(self, record, field_name, options):
        options = dict(options)
        #currency should be specified by monetary field
        field = record._fields[field_name]

        if not options.get('display_currency') and field.type == 'monetary' and field.get_currency_field(record):
            options['display_currency'] = record[field.get_currency_field(record)]
        if not options.get('display_currency'):
            # search on the model if they are a res.currency field to set as default
            fields = record._fields.items()
            currency_fields = [k for k, v in fields if v.type == 'many2one' and v.comodel_name == 'res.currency']
            if currency_fields:
                options['display_currency'] = record[currency_fields[0]]
        if 'date' not in options:
            options['date'] = record.env.context.get('date')
        if 'company_id' not in options:
            options['company_id'] = record.env.context.get('company_id')

        return super().record_to_html(record, field_name, options)


class IrQwebFieldFloat_Time(models.AbstractModel):
    """ ``float_time`` converter, to display integral or fractional values as
    human-readable time spans (e.g. 1.5 as "01:30").

    Can be used on any numerical field.
    """
    _name = 'ir.qweb.field.float_time'
    _description = 'Qweb Field Float Time'
    _inherit = ['ir.qweb.field']

    @api.model
    def value_to_html(self, value, options):
        return format_duration(value)
