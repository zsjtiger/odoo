"""The formatting and parsing of the dates, the times, the datetimes and the durations."""

from __future__ import annotations

import datetime
import typing
from zoneinfo import ZoneInfo
import babel
import babel.dates

if typing.TYPE_CHECKING:
    from odoo.api import Environment

from .languages import babel_locale_parse, get_lang

DEFAULT_SERVER_DATE_FORMAT = "%Y-%m-%d"


DEFAULT_SERVER_TIME_FORMAT = "%H:%M:%S"


DEFAULT_SERVER_DATETIME_FORMAT = "%s %s" % (
    DEFAULT_SERVER_DATE_FORMAT,
    DEFAULT_SERVER_TIME_FORMAT)


DATE_LENGTH = len(datetime.date.today().strftime(DEFAULT_SERVER_DATE_FORMAT))


DATETIME_FORMATS_MAP = {
        '%C': '', # century
        '%D': '%m/%d/%Y', # modified %y->%Y
        '%e': '%d',
        '%E': '', # special modifier
        '%F': '%Y-%m-%d',
        '%g': '%Y', # modified %y->%Y
        '%G': '%Y',
        '%h': '%b',
        '%k': '%H',
        '%l': '%I',
        '%n': '\n',
        '%O': '', # special modifier
        '%P': '%p',
        '%R': '%H:%M',
        '%r': '%I:%M:%S %p',
        '%s': '', #num of seconds since epoch
        '%T': '%H:%M:%S',
        '%t': ' ', # tab
        '%u': ' %w',
        '%V': '%W',
        '%y': '%Y', # Even if %y works, it's ambiguous, so we should use %Y
        '%+': '%Y-%m-%d %H:%M:%S',

        # %Z is a special case that causes 2 problems at least:
        #  - the timezone names we use (in res_user.context_tz) come
        #    from pytz, but not all these names are recognized by
        #    strptime(), so we cannot convert in both directions
        #    when such a timezone is selected and %Z is in the format
        #  - %Z is replaced by an empty string in strftime() when
        #    there is not tzinfo in a datetime value (e.g when the user
        #    did not pick a context_tz). The resulting string does not
        #    parse back if the format requires %Z.
        # As a consequence, we strip it completely from format strings.
        # The user can always have a look at the context_tz in
        # preferences to check the timezone.
        '%z': '',
        '%Z': '',
}


POSIX_TO_LDML = {
    'a': 'E',
    'A': 'EEEE',
    'b': 'MMM',
    'B': 'MMMM',
    #'c': '',
    'd': 'dd',
    '-d': 'd',
    'H': 'HH',
    'I': 'hh',
    'j': 'DDD',
    'm': 'MM',
    '-m': 'M',
    'M': 'mm',
    'p': 'a',
    'S': 'ss',
    'U': 'w',
    'w': 'e',
    'W': 'w',
    'y': 'yy',
    'Y': 'yyyy',
    # see comments above, and babel's format_datetime assumes an UTC timezone
    # for naive datetime objects
    #'z': 'Z',
    #'Z': 'z',
}


def posix_to_ldml(fmt: str, locale: babel.Locale) -> str:
    """ Converts a posix/strftime pattern into an LDML date format pattern.

    :param fmt: non-extended C89/C90 strftime pattern
    :param locale: babel locale used for locale-specific conversions (e.g. %x and %X)
    :return: unicode
    """
    buf = []
    pc = False
    minus = False
    quoted = []

    for c in fmt:
        # LDML date format patterns uses letters, so letters must be quoted
        if not pc and c.isalpha():
            quoted.append(c if c != "'" else "''")
            continue
        if quoted:
            buf.append("'")
            buf.append(''.join(quoted))
            buf.append("'")
            quoted = []

        if pc:
            if c == '%': # escaped percent
                buf.append('%')
            elif c == 'x': # date format, short seems to match
                buf.append(locale.date_formats['short'].pattern)
            elif c == 'X': # time format, seems to include seconds. short does not
                buf.append(locale.time_formats['medium'].pattern)
            elif c == '-':
                minus = True
                continue
            else: # look up format char in static mapping
                if minus:
                    c = '-' + c
                    minus = False
                buf.append(POSIX_TO_LDML[c])
            pc = False
        elif c == '%':
            pc = True
        else:
            buf.append(c)

    # flush anything remaining in quoted buffer
    if quoted:
        buf.append("'")
        buf.append(''.join(quoted))
        buf.append("'")

    return ''.join(buf)


def format_date(
    env: Environment,
    value: datetime.datetime | datetime.date | str,
    lang_code: str | None = None,
    date_format: str | typing.Literal[False] = False,
) -> str:
    """
        Formats the date in a given format.

        :param env: an environment.
        :param date, datetime or string value: the date to format.
        :param string lang_code: the lang code, if not specified it is extracted from the
            environment context.
        :param string date_format: the format or the date (LDML format), if not specified the
            default format of the lang.
        :return: date formatted in the specified format.
        :rtype: string
    """
    if not value:
        return ''
    from odoo.fields import Datetime  # noqa: PLC0415
    if isinstance(value, str):
        if len(value) < DATE_LENGTH:
            return ''
        if len(value) > DATE_LENGTH:
            # a datetime, convert to correct timezone
            value = Datetime.from_string(value)
            value = Datetime.context_timestamp(env['res.lang'], value)
        else:
            value = Datetime.from_string(value)
    elif isinstance(value, datetime.datetime) and not value.tzinfo:
        # a datetime, convert to correct timezone
        value = Datetime.context_timestamp(env['res.lang'], value)

    lang = get_lang(env, lang_code)
    locale = babel_locale_parse(lang.code)
    if not date_format:
        date_format = posix_to_ldml(lang.date_format, locale=locale)

    assert isinstance(value, datetime.date)  # datetime is a subclass of date
    return babel.dates.format_date(value, format=date_format, locale=locale)


def parse_date(env: Environment, value: str, lang_code: str | None = None) -> datetime.date | str:
    """
        Parse the date from a given format. If it is not a valid format for the
        localization, return the original string.

        :param env: an environment.
        :param string value: the date to parse.
        :param string lang_code: the lang code, if not specified it is extracted from the
            environment context.
        :return: date object from the localized string
        :rtype: datetime.date
    """
    lang = get_lang(env, lang_code)
    locale = babel_locale_parse(lang.code)
    try:
        return babel.dates.parse_date(value, locale=locale)
    except:
        return value


def format_datetime(
    env: Environment,
    value: datetime.datetime | str,
    tz: str | typing.Literal[False] = False,
    dt_format: str = 'medium',
    lang_code: str | None = None,
) -> str:
    """ Formats the datetime in a given format.

    :param env:
    :param str|datetime value: naive datetime to format either in string or in datetime
    :param str tz: name of the timezone  in which the given datetime should be localized
    :param str dt_format: “medium”, or “short” to use res.lang format with or without the
        seconds. Or a custom date/time pattern compatible with `babel` lib
    :param str lang_code: ISO code of the language to use to render the given datetime
    :rtype: str
    """
    if not value:
        return ''
    if isinstance(value, str):
        from odoo.fields import Datetime  # noqa: PLC0415
        timestamp = Datetime.from_string(value)
    else:
        timestamp = value

    tz_name = tz or env.user.tz or 'UTC'
    utc_datetime = timestamp.replace(tzinfo=datetime.UTC)
    try:
        context_tz = ZoneInfo(tz_name)
        localized_datetime = utc_datetime.astimezone(context_tz)
    except Exception:
        localized_datetime = utc_datetime

    lang = get_lang(env, lang_code)

    locale = babel_locale_parse(lang.code or lang_code)  # lang can be inactive, so `lang`is empty
    if not dt_format or dt_format == 'medium':
        date_format = posix_to_ldml(lang.date_format, locale=locale)
        time_format = posix_to_ldml(lang.time_format, locale=locale)
        dt_format = '%s %s' % (date_format, time_format)
    elif dt_format == 'short':
        date_format = posix_to_ldml(lang.date_format, locale=locale)
        time_format = posix_to_ldml(lang.time_format.replace(':%S', ''), locale=locale)
        dt_format = '%s %s' % (date_format, time_format)

    # Babel allows to format datetime in a specific language without change locale
    # So month 1 = January in English, and janvier in French
    # Formatting available here : http://babel.pocoo.org/en/latest/dates.html#date-fields
    return babel.dates.format_datetime(localized_datetime, dt_format, locale=locale)


def format_time(
    env: Environment,
    value: datetime.time | datetime.datetime | str,
    tz: str | typing.Literal[False] = False,
    time_format: str = 'medium',
    lang_code: str | None = None,
) -> str:
    """ Format the given time (hour, minute and second) with the current user preference (language, format, ...)

        :param env:
        :param value: the time to format
        :type value: `datetime.time` instance. Could be timezoned to display tzinfo according to format
        :param tz: name of the timezone  in which the given datetime should be localized
        :param str time_format: “medium”, or “short” to use res.lang format with or without the
            seconds. Or a custom time pattern compatible with `babel` lib
        :param lang_code: ISO

        :rtype str
    """
    if not value:
        return ''

    if isinstance(value, datetime.time):
        localized_time = value
    else:
        if isinstance(value, str):
            from odoo.fields import Datetime  # noqa: PLC0415
            value = Datetime.from_string(value)
        assert isinstance(value, datetime.datetime)
        tz_name = tz or env.user.tz or 'UTC'
        utc_datetime = value.replace(tzinfo=datetime.UTC)
        try:
            context_tz = ZoneInfo(tz_name)
            localized_time = utc_datetime.astimezone(context_tz).timetz()
        except Exception:
            localized_time = utc_datetime.timetz()

    lang = get_lang(env, lang_code)
    locale = babel_locale_parse(lang.code)
    if not time_format or time_format == 'medium':
        time_format = posix_to_ldml(lang.time_format, locale=locale)
    elif time_format == 'short':
        time_format = posix_to_ldml(lang.time_format.replace(':%S', ''), locale=locale)

    return babel.dates.format_time(localized_time, format=time_format, locale=locale)


def _format_time_ago(
    env: Environment,
    time_delta: datetime.timedelta,
    lang_code: str | None = None,
    add_direction: bool = True,
) -> str:
    if not lang_code:
        langs: list[str] = [code for code, _ in env['res.lang'].get_installed()]
        if (ctx_lang := env.context.get('lang')) in langs:
            lang_code = ctx_lang
        else:
            lang_code = env.user.company_id.partner_id.lang or langs[0]
        assert isinstance(lang_code, str)
    locale = babel_locale_parse(lang_code)
    return babel.dates.format_timedelta(-time_delta, add_direction=add_direction, locale=locale)


def format_duration(value: float) -> str:
    """ Format a float: used to display integral or fractional values as
        human-readable time spans (e.g. 1.5 as "01:30").
    """
    hours, minutes = divmod(abs(value) * 60, 60)
    minutes = round(minutes)
    if minutes == 60:
        minutes = 0
        hours += 1
    if value < 0:
        return '-%02d:%02d' % (hours, minutes)
    return '%02d:%02d' % (hours, minutes)
