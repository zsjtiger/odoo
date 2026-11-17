"""The temporal fields of the QWeb engine: the dates, the times, the durations and the relative dates."""

from __future__ import annotations

from datetime import time
import babel.dates
from odoo import api, fields, models
from odoo.tools import posix_to_ldml, format_date
from odoo.tools.misc import babel_locale_parse
from odoo.tools.text.translate import _

from .helpers import TIMEDELTA_UNITS

class IrQwebFieldDate(models.AbstractModel):
    _name = 'ir.qweb.field.date'
    _description = 'Qweb Field Date'
    _inherit = ['ir.qweb.field']

    @api.model
    def get_available_options(self):
        options = super().get_available_options()
        options.update(
            format=dict(type='string', string=_('Date format'))
        )
        return options

    @api.model
    def value_to_html(self, value, options):
        return format_date(self.env, value, date_format=options.get('format'))


class IrQwebFieldDatetime(models.AbstractModel):
    _name = 'ir.qweb.field.datetime'
    _description = 'Qweb Field Datetime'
    _inherit = ['ir.qweb.field']

    @api.model
    def get_available_options(self):
        options = super().get_available_options()
        options.update(
            format=dict(type='string', string=_('Pattern to format')),
            tz_name=dict(type='char', string=_('Optional timezone name')),
            time_only=dict(type='boolean', string=_('Display only the time')),
            hide_seconds=dict(type='boolean', string=_('Hide seconds')),
            date_only=dict(type='boolean', string=_('Display only the date')),
        )
        return options

    @api.model
    def value_to_html(self, value, options):
        if not value:
            return ''

        lang = self.user_lang()
        locale = babel_locale_parse(lang.code)
        if isinstance(value, str):
            value = fields.Datetime.from_string(value)

        if options.get('tz_name'):
            self = self.with_context(tz=options['tz_name'])
            tzinfo = babel.dates.get_timezone(options['tz_name'])
        else:
            tzinfo = None

        value = fields.Datetime.context_timestamp(self, value)

        if 'format' in options:
            pattern = options['format']
        else:
            if options.get('time_only'):
                strftime_pattern = lang.time_format
            elif options.get('date_only'):
                strftime_pattern = lang.date_format
            else:
                strftime_pattern = "%s %s" % (lang.date_format, lang.time_format)

            pattern = posix_to_ldml(strftime_pattern, locale=locale)

        if options.get('hide_seconds'):
            pattern = pattern.replace(":ss", "").replace(":s", "")

        if options.get('time_only'):
            return babel.dates.format_time(value, format=pattern, tzinfo=tzinfo, locale=locale)
        elif options.get('date_only'):
            return babel.dates.format_date(value, format=pattern, locale=locale)
        else:
            return babel.dates.format_datetime(value, format=pattern, tzinfo=tzinfo, locale=locale)


class IrQwebFieldTime(models.AbstractModel):
    """ ``time`` converter, to display integer or fractional value as
    human-readable time (e.g. 1.5 as "1:30 AM"). The unit of this value
    is in hours.

    Can be used on any numerical field between: 0 <= value < 24
    """
    _name = 'ir.qweb.field.time'
    _description = 'QWeb Field Time'
    _inherit = ['ir.qweb.field']

    @api.model
    def value_to_html(self, value, options):
        if value < 0:
            raise ValueError(_("The value (%s) passed should be positive", value))
        hours, minutes = divmod(int(abs(value) * 60), 60)
        if hours > 23:
            raise ValueError(_("The hour must be between 0 and 23"))
        t = time(hour=hours, minute=minutes)

        locale = babel_locale_parse(self.user_lang().code)
        pattern = options.get('format', 'short')

        return babel.dates.format_time(t, format=pattern, tzinfo=None, locale=locale)


class IrQwebFieldDuration(models.AbstractModel):
    """ ``duration`` converter, to display integral or fractional values as
    human-readable time spans (e.g. 1.5 as "1 hour 30 minutes").

    Can be used on any numerical field.

    Has an option ``unit`` which can be one of ``second``, ``minute``,
    ``hour``, ``day``, ``week`` or ``year``, used to interpret the numerical
    field value before converting it. By default use ``second``.

    Has an option ``round``. By default use ``second``.

    Has an option ``digital`` to display 01:00 instead of 1 hour

    Sub-second values will be ignored.
    """
    _name = 'ir.qweb.field.duration'
    _description = 'Qweb Field Duration'
    _inherit = ['ir.qweb.field']

    @api.model
    def get_available_options(self):
        options = super().get_available_options()
        unit = [(value, str(label)) for value, label, ratio in TIMEDELTA_UNITS]
        options.update(
            digital=dict(type="boolean", string=_('Digital formatting')),
            unit=dict(type="selection", params=unit, string=_('Date unit'), description=_('Date unit used for comparison and formatting'), default_value='second', required=True),
            round=dict(type="selection", params=unit, string=_('Rounding unit'), description=_("Date unit used for the rounding. The value must be smaller than 'hour' if you use the digital formatting."), default_value='second'),
            format=dict(
                type="selection",
                params=[
                    ('long', _('Long')),
                    ('short', _('Short')),
                    ('narrow', _('Narrow'))],
                string=_('Format'),
                description=_("Formatting: long, short, narrow (not used for digital)"),
                default_value='long'
            ),
            add_direction=dict(
                type="boolean",
                string=_("Add direction"),
                description=_("Add directional information (not used for digital)")
            ),
        )
        return options

    @api.model
    def value_to_html(self, value, options):
        units = {unit: duration for unit, label, duration in TIMEDELTA_UNITS}

        locale = babel_locale_parse(self.user_lang().code)
        factor = units[options.get('unit', 'second')]
        round_to = units[options.get('round', 'second')]

        if options.get('digital') and round_to > 3600:
            round_to = 3600

        r = round((value * factor) / round_to) * round_to

        sections = []
        sign = ''
        if value < 0:
            r = -r
            sign = '-'

        if options.get('digital'):
            for _unit, _label, secs_per_unit in TIMEDELTA_UNITS:
                if secs_per_unit > 3600:
                    continue
                v, r = divmod(r, secs_per_unit)
                if not v and (secs_per_unit > factor or secs_per_unit < round_to):
                    continue
                sections.append(u"%02.0f" % int(round(v)))
            return sign + u':'.join(sections)

        for _unit, _label, secs_per_unit in TIMEDELTA_UNITS:
            v, r = divmod(r, secs_per_unit)
            if not v:
                continue
            try:
                section = babel.dates.format_timedelta(
                    v*secs_per_unit,
                    granularity=round_to,
                    add_direction=options.get('add_direction'),
                    format=options.get('format', 'long'),
                    threshold=1,
                    locale=locale)
            except KeyError:
                # in case of wrong implementation of babel, try to fallback on en_US locale.
                # https://github.com/python-babel/babel/pull/827/files
                # Some bugs already fixed in 2.10 but ubuntu22 is 2.8
                localeUS = babel_locale_parse('en_US')
                section = babel.dates.format_timedelta(
                    v*secs_per_unit,
                    granularity=round_to,
                    add_direction=options.get('add_direction'),
                    format=options.get('format', 'long'),
                    threshold=1,
                    locale=localeUS)
            if section:
                sections.append(section)

        if sign:
            sections.insert(0, sign)
        return u' '.join(sections)


class IrQwebFieldRelative(models.AbstractModel):
    _name = 'ir.qweb.field.relative'
    _description = 'Qweb Field Relative'
    _inherit = ['ir.qweb.field']

    @api.model
    def get_available_options(self):
        options = super().get_available_options()
        options.update(
            now=dict(type='datetime', string=_('Reference date'), description=_('Date to compare with the field value, by default use the current date.'))
        )
        return options

    @api.model
    def value_to_html(self, value, options):
        locale = babel_locale_parse(self.user_lang().code)

        if isinstance(value, str):
            value = fields.Datetime.from_string(value)

        # value should be a naive datetime in UTC. So is fields.Datetime.now()
        reference = fields.Datetime.from_string(options['now'])

        return babel.dates.format_timedelta(value - reference, add_direction=True, locale=locale)

    @api.model
    def record_to_html(self, record, field_name, options):
        if 'now' not in options:
            options = dict(options, now=record._fields[field_name].now())
        return super().record_to_html(record, field_name, options)
