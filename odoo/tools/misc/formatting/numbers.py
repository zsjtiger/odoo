"""The formatting of the numbers and the amounts: the sizes, the decimals, the currencies and the lang formatting."""

from __future__ import annotations

import re
import typing
from odoo.tools.numeric.float_utils import float_round

if typing.TYPE_CHECKING:
    from odoo.api import Environment

from .languages import get_lang

NON_BREAKING_SPACE = u'\N{NO-BREAK SPACE}'


ROUNDING_UNIT_CHARS = {
    'thousands': 'k',
    'lakhs': 'L',
    'millions': 'M',
}


def human_size(sz: float | str) -> str | typing.Literal[False]:
    """
    Return the size in a human readable format
    """
    if not sz:
        return False
    units = ('bytes', 'Kb', 'Mb', 'Gb', 'Tb')
    if isinstance(sz, str):
        sz=len(sz)
    s, i = float(sz), 0
    while s >= 1024 and i < len(units)-1:
        s /= 1024
        i += 1
    return "%0.2f %s" % (s, units[i])


def formatLang(
    env: Environment,
    value: float | typing.Literal[''],
    digits: int = 2,
    grouping: bool = True,
    dp: str | None = None,
    currency_obj: typing.Any | None = None,
    rounding_method: typing.Literal['HALF-UP', 'HALF-DOWN', 'HALF-EVEN', "UP", "DOWN"] = 'HALF-EVEN',
    rounding_unit: typing.Literal['decimals', 'units', 'thousands', 'lakhs', 'millions'] = 'decimals',
) -> str:
    """
    This function will format a number `value` to the appropriate format of the language used.

    :param env: The environment.
    :param value: The value to be formatted.
    :param digits: The number of decimals digits.
    :param grouping: Usage of language grouping or not.
    :param dp: Name of the decimals precision to be used. This will override ``digits``
                   and ``currency_obj`` precision.
    :param currency_obj: Currency to be used. This will override ``digits`` precision.
    :param rounding_method: The rounding method to be used:
        **'HALF-UP'** will round to the closest number with ties going away from zero,
        **'HALF-DOWN'** will round to the closest number with ties going towards zero,
        **'HALF_EVEN'** will round to the closest number with ties going to the closest
        even number,
        **'UP'** will always round away from 0,
        **'DOWN'** will always round towards 0.
    :param rounding_unit: The rounding unit to be used:
        **decimals** will round to decimals with ``digits`` or ``dp`` precision,
        **units** will round to units without any decimals,
        **thousands** will round to thousands without any decimals and append 'k',
        **lakhs** will round to lakhs without any decimals and append 'L',
        **millions** will round to millions without any decimals and append 'M'.

    :returns: The value formatted.
    """
    # We don't want to return 0
    if value == '':
        return ''

    if rounding_unit == 'decimals':
        if dp:
            digits = env['decimal.precision'].precision_get(dp)
        elif currency_obj:
            digits = currency_obj.decimal_places
    else:
        digits = 0

    rounding_unit_mapping = {
        'decimals': 1,
        'thousands': 10**3,
        'lakhs': 10**5,
        'millions': 10**6,
        'units': 1,
    }

    value /= rounding_unit_mapping[rounding_unit]

    rounded_value = float_round(value, precision_digits=digits, rounding_method=rounding_method)
    lang = env['res.lang'].browse(get_lang(env).id)
    formatted_value = lang.format(f'%.{digits}f', rounded_value, grouping=grouping)

    if unit_char := ROUNDING_UNIT_CHARS.get(rounding_unit):
        formatted_value = f'{formatted_value}{unit_char}'

    if currency_obj and currency_obj.symbol:
        arguments = (formatted_value, NON_BREAKING_SPACE, currency_obj.symbol)

        return '%s%s%s' % (arguments if currency_obj.position == 'after' else arguments[::-1])

    return formatted_value


def format_decimalized_number(number: float, decimal: int = 1) -> str:
    """Format a number to display to nearest metrics unit next to it.

    Do not display digits if all visible digits are null.
    Do not display units higher then "Tera" because most people don't know what
    a "Yotta" is.

    ::

        >>> format_decimalized_number(123_456.789)
        123.5k
        >>> format_decimalized_number(123_000.789)
        123k
        >>> format_decimalized_number(-123_456.789)
        -123.5k
        >>> format_decimalized_number(0.789)
        0.8
    """
    for unit in ['', 'k', 'M', 'G']:
        if abs(number) < 1000.0:
            return "%g%s" % (round(number, decimal), unit)
        number /= 1000.0
    return "%g%s" % (round(number, decimal), 'T')


def format_decimalized_amount(amount: float, currency=None) -> str:
    """Format an amount to display the currency and also display the metric unit
    of the amount.

    ::

        >>> format_decimalized_amount(123_456.789, env.ref("base.USD"))
        $123.5k
    """
    formated_amount = format_decimalized_number(amount)

    if not currency:
        return formated_amount

    if currency.position == 'before':
        return "%s%s" % (currency.symbol or '', formated_amount)

    return "%s %s" % (formated_amount, currency.symbol or '')


def format_amount(env: Environment, amount: float, currency, lang_code: str | None = None, trailing_zeroes: bool = True) -> str:
    fmt = "%.{0}f".format(currency.decimal_places)
    lang = env['res.lang'].browse(get_lang(env, lang_code).id)

    formatted_amount = lang.format(fmt, currency.round(amount), grouping=True)\
        .replace(r' ', u'\N{NO-BREAK SPACE}').replace(r'-', u'-\N{ZERO WIDTH NO-BREAK SPACE}')

    if not trailing_zeroes and currency.decimal_places:
        formatted_amount = re.sub(fr'{re.escape(lang.decimal_point)}?0+$', '', formatted_amount)

    pre = post = u''
    if currency.position == 'before':
        pre = u'{symbol}\N{NO-BREAK SPACE}'.format(symbol=currency.symbol or '')
    else:
        post = u'\N{NO-BREAK SPACE}{symbol}'.format(symbol=currency.symbol or '')

    return u'{pre}{0}{post}'.format(formatted_amount, pre=pre, post=post)
