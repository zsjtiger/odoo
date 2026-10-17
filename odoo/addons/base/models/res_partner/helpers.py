# Part of Odoo. See LICENSE file for full copyright and licensing details.

from __future__ import annotations
import typing
from odoo import api
from odoo.tools import LazyTranslate
from odoo.tools.date_utils import all_timezones

if typing.TYPE_CHECKING:
    pass

EU_EXTRA_VAT_CODES = {
    'GR': 'EL',
    'GB': 'XI',
}
EU_EXTRA_VAT_CODES_INV = {v: k for k, v in EU_EXTRA_VAT_CODES.items()}


_lt = LazyTranslate('odoo.addons.base.models.res_partner')
_ref_vat = {
    'al': 'ALJ91402501L',
    'ar': '20055361682',
    'at': 'ATU12345675',
    'au': '83 914 571 673',
    'be': 'BE0477472701',
    'bg': 'BG1234567892',
    'br': _lt('either 11 digits for CPF or 14 characters for CNPJ'),
    'ca': _lt('123456782 or 123456782RT0001'),
    'cr': '3101012009',
    'ch': _lt('CHE-123.456.788 TVA or CHE-123.456.788 MWST or CHE-123.456.788 IVA'),  # Swiss by Yannick Vaucher @ Camptocamp
    'cl': '76086428-5',
    'co': '213123432-1',
    'cy': 'CY10259033P',
    'cz': 'CZ12345679',
    'de': _lt('DE123456788 or 12/345/67890'),
    'dk': 'DK12345674',
    'do': _lt('1-01-85004-3 or 101850043'),
    'ec': _lt('1792060346001 or 1792060346'),
    'ee': 'EE123456780',
    'es': 'ESA12345674',
    'fi': 'FI12345671',
    'fr': 'FR23334175221',
    'gb': _lt('GB123456782 or XI123456782'),
    'gr': 'EL123456783',
    'hu': _lt('HU12345676 or 12345678-1-11 or 8071592153'),
    'hr': 'HR01234567896',  # Croatia, contributed by Milan Tribuson
    'id': '1234567890123456',
    'ie': 'IE1234567FA',
    'il': _lt('XXXXXXXXX [9 digits] and it should respect the Luhn algorithm checksum'),
    'in': "12AAAAA1234AAZA",
    'is': 'IS062199',
    'it': 'IT12345670017',
    'jp': 'T7000012050002',
    'kr': '123-45-67890 or 1234567890',
    'lt': 'LT123456715',
    'lu': 'LU12345613',
    'lv': 'LV41234567891',
    'ma': '12345678',
    'mc': 'FR53000004605',
    'mt': 'MT12345634',
    'mx': _lt('GODE561231GR8'),
    'nl': 'NL123456782B90',
    'no': 'NO123456785',
    'nz': _lt('49-098-576 or 49098576'),
    'pe': _lt('10XXXXXXXXY or 20XXXXXXXXY or 15XXXXXXXXY or 16XXXXXXXXY or 17XXXXXXXXY'),
    'ph': '123-456-789-123',
    'pk': _lt('1234567 or 1234567-8 or 12345-1234567-8'),
    'pl': 'PL1234567883',
    'pt': 'PT123456789',
    'ro': 'RO1234567897 or 8001011234567 or 9000123456789',
    'rs': 'RS101134702',
    'ru': '123456789047',
    'se': 'SE123456789701',
    'si': 'SI12345679',
    'sk': 'SK2022749619',
    'sm': 'SM24165',
    'th': _lt('0123456789016 or 1234545678781 [13 digits]'),
    'tr': _lt('11111111111 (NIN) or 2222222222 (VKN)'),
    'ua': _lt('12345678 or UA12345678 (EDRPOU), 1234567890 (RNOPP) or 123456789012 (IPN)'),
    'uy': _lt("Example: '219999830019' (format: 12 digits, all numbers, valid check digit)"),
    'uz': _lt('123456789 (TIN) or 12345678901234 (PINFL)'),
    've': 'V-12345678-1, V123456781, V-12.345.678-1',
    'xi': 'XI123456782',
    'sa': _lt('310175397400003 [Fifteen digits, first and last digits should be "3"]'),
}


@api.model
def _lang_get(self):
    return self.env['res.lang'].get_installed()


# put POSIX 'Etc/*' entries at the end to avoid confusing users - see bug 1086728
_tzs = [(tz, tz) for tz in sorted(all_timezones, key=lambda tz: tz if not tz.startswith('Etc/') else '_')]
def _tz_get(self):
    return _tzs
