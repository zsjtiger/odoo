# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The vat numbers of the partners: the labels, the checks and formats of the countries, and the errors."""

from __future__ import annotations

import datetime
import re
import typing
import stdnum
from stdnum import luhn
from stdnum.exceptions import InvalidChecksum, InvalidFormat
from stdnum.util import clean
from odoo import _
from odoo.exceptions import ValidationError
from odoo.tools.business_data import split_vat

if typing.TYPE_CHECKING:
    pass

from .helpers import EU_EXTRA_VAT_CODES, EU_EXTRA_VAT_CODES_INV, _ref_vat


def _compute_same_vat_partner_id(self):
    for partner in self:
        # use _origin to deal with onchange()
        partner_id = partner._origin.id
        # active_test = False because if a partner has been deactivated you still want to raise the error,
        # so that you can reactivate it instead of creating a new one, which would lose its history.
        Partner = self.with_context(active_test=False).sudo()
        vats = [partner.vat]

        if partner.has_vat and partner.country_id and 'EU_PREFIX' in partner.country_id.country_group_codes:
            if partner.vat[:2].isalpha():
                vats.append(partner.vat[2:])
            else:
                vats.append(partner.country_id.code + partner.vat)
                if new_code := EU_EXTRA_VAT_CODES.get(partner.country_id.code):
                    vats.append(new_code + partner.vat)
        domain = [
            ('vat', 'in', vats),
        ]
        if partner.country_id:
            domain += [('country_id', 'in', [partner.country_id.id, False])]
        if partner.company_id:
            domain += [('company_id', 'in', [False, partner.company_id.id])]
        if partner_id:
            domain += [('id', '!=', partner_id), '!', ('id', 'child_of', partner_id)]
        # For VAT number being only one character, we will skip the check just like the regular check_vat

        partner.same_vat_partner_id = partner.has_vat and not partner.parent_id and Partner.search(domain, limit=1)


def _compute_vat_label(self):
    self.vat_label = self.env.company.country_id.vat_label or _("Tax ID")


def _onchange_vat(self):
    self._check_vat(validation=False)


def _inverse_vat(self):
    self._check_vat()
    self._deduce_additional_identifiers_from_vat()


def _check_vat(self, validation="error"):
    for partner in self:
        vat, _country_code = self._run_vat_checks(partner.commercial_partner_id.country_id, partner.vat,
                                           partner_name=partner.name, validation=validation)
        if vat != partner.vat:  # To avoid unnecessary queries (perf tested)
            partner.vat = vat


def _run_vat_checks(self, country, vat, partner_name='', validation='error'):
    """Checks a VAT number syntactically to ensure its validity upon saving.

        :param country: a country to check for
        :param vat: a string with the VAT number to check.
        :param partner_name: to put into the error message
        :param validation: if False, it will only return the formatted vat without checking if it valid.
            if 'error', an incorrect number will raise and if 'setnull' it will just return an empty vat

        :return: A two-elements tuple with:

            1. The vat number
            2. The country code of the country the VAT number was validated for, if it was validated.
               False if it could not be validated against the provided or guessed country.
        """
    if not country or not vat:
        return vat, False
    if 1 <= len(vat) <= 2:
        if not self.env['res.partner'].new({'vat': vat}).has_vat or not validation:
            return vat, False
        if validation == 'setnull':
            return '', False
        if validation == 'error':
            raise ValidationError(_("To explicitly indicate no (valid) VAT, use '/', 'na' or 'NA' instead. "))
    vat_prefix, vat_number = split_vat(vat)

    if vat_prefix == 'EU' and country not in self.env.ref('base.europe').country_ids:
        # Foreign companies that trade with non-enterprises in the EU
        # may have a VATIN starting with "EU" instead of a country code.
        return vat, False

    do_eu_check = False
    prefixed_country = ''
    eu_prefix_country_group = self.env['res.country.group'].search([('code', '=', 'EU_PREFIX')], limit=1)
    country_code = EU_EXTRA_VAT_CODES_INV.get(vat_prefix, vat_prefix)
    if country_code in eu_prefix_country_group.country_ids.mapped('code'):
        if 'EU_PREFIX' in country.country_group_codes and vat_prefix:
            vat = vat_number
            prefixed_country = vat_prefix
        else:
            do_eu_check = True

    code_to_check = prefixed_country or country.code
    vat = self._format_vat_number(code_to_check, vat)

    if prefixed_country == 'GR':
        prefixed_country = 'EL'

    vat_to_return = prefixed_country + vat

    # The context key 'no_vat_validation' allows you to store/set a VAT number without doing validations.
    # This is for API pushes from external platforms where you have no control over VAT numbers.
    if not validation or self.env.context.get('no_vat_validation'):
        return vat_to_return, code_to_check

    # Avoid validating double prefix like BEBE0477472701
    double_prefix = prefixed_country and vat_to_return.startswith(prefixed_country + prefixed_country)
    if not self._check_vat_number(code_to_check, vat) or double_prefix:
        partner_label = _("partner%s", f' [{partner_name}]' if partner_name else '')
        if do_eu_check:
            try:
                return self._run_vat_checks(self.env['res.country'].search([('code', '=', country_code)], limit=1), vat_prefix + vat_number, partner_name, validation)
            except ValidationError:
                msg = self._build_vat_error_message(code_to_check, vat_to_return, partner_label)
                raise ValidationError(msg + "\n\n" + self.env._('If you are trying to input a European number, this is the expected format: ') + _ref_vat[country_code.lower()])
        if validation == 'error':
            msg = self._build_vat_error_message(code_to_check, vat_to_return, partner_label)
            raise ValidationError(msg)
        else:
            return '', code_to_check
    return vat_to_return, code_to_check


def _check_vat_number(self, country_code, vat_number):
    ''' Low-level method directly calling stdnum or our own specific method. '''
    check_func_name = 'check_vat_' + country_code.lower()
    check_func = getattr(self, check_func_name, None) or getattr(stdnum.util.get_cc_module(country_code, 'vat'), 'is_valid', None)
    return check_func(vat_number) if check_func else True


def _build_vat_error_message(self, country_code, wrong_vat, record_label):
    if self.env.context.get('company_id'):
        company = self.env['res.company'].browse(self.env.context['company_id'])
    else:
        company = self.env.company

    vat_label = _("VAT")
    if country_code and company.country_id and country_code == company.country_id.code and company.country_id.vat_label:
        vat_label = company.country_id.vat_label

    expected_format = _ref_vat.get(country_code.lower())
    expected_note = ""
    if expected_format:
        expected_note = ' \n' + self.env._(
            'Note: the expected format is %(expected_format)s',
             expected_format=expected_format
        )

    # Catch use case where the record label is about the public user (name: False)
    if 'False' not in record_label:
        return '\n' + self.env._(
            'The %(vat_label)s number [%(wrong_vat)s] for %(record_label)s does not seem to be valid. %(expected_note)s',
            vat_label=vat_label,
            wrong_vat=wrong_vat,
            record_label=record_label,
            expected_note=expected_note
        )
    else:
        return '\n' + self.env._(
            'The %(vat_label)s number [%(wrong_vat)s] does not seem to be valid. %(expected_note)s',
            vat_label=vat_label,
            wrong_vat=wrong_vat,
            expected_note=expected_note,
        )


def _get_country_specific_vat_variants(self, normalized_vat, country_prefix):
    """
        Return additional formatted VAT values to consider during EDI partner matching.
        Should stay consistent with `_check_customer_vat_match` to ensure
        correct partner matching when importing EDI documents.
        """
    vat_variants = []
    if country_prefix.upper() == 'CH':
        normalized_vat = normalized_vat.replace('-', '')
        if (vat_formatted := self._run_vat_checks(self.env.ref('base.ch'), normalized_vat, validation='setnull')[0]):
            vat_base = re.sub(r"\s*(TVA|IVA|MWST)?$", "", vat_formatted.upper())
            vat_variants.extend([f'{vat_base} {suffix}' for suffix in ('TVA', 'IVA', 'MWST')])
    return vat_variants


def _format_vat_number(self, country_code, vat):
    """ Low-level method directly calling stdnum or our own specific method returning the formatted VAT. """
    stdnum_vat_fix_func = getattr(stdnum.util.get_cc_module(country_code, 'vat'), 'compact', None)
    # If any localization module needs to define vat fix method for its country then we give first priority to it.
    format_func_name = 'format_vat_' + country_code.lower()
    format_func = getattr(self, format_func_name, None) or stdnum_vat_fix_func
    if format_func:
        vat = format_func(vat)
    return vat


def _convert_hu_local_to_eu_vat(self, local_vat):
    if self._check_tin_hu_companies_re.match(local_vat) or self._check_tin_hu_european_re.match(local_vat):
        return f'HU{local_vat[:8]}'
    return False


def _ie_check_char(self, vat):
    vat = vat.zfill(8)
    extra = 0
    if vat[7] not in ' W':
        if vat[7].isalpha():
            extra = 9 * (ord(vat[7]) - 64)
        else:
            # invalid
            return -1
    checksum = extra + sum((8 - i) * int(x) for i, x in enumerate(vat[:7]))
    return 'WABCDEFGHIJKLMNOPQRSTUV'[checksum % 23]


def check_vat_al(self, vat):
    """Check Albania VAT number"""
    number = split_vat(vat, default_country_code='al')[1]
    return len(number) == 10 and self._check_vat_al_re.match(number)


def check_vat_br(self, vat):
    def is_cnpj_valid(vat):
        vat = clean(vat, ' -./').strip().upper()
        if vat.startswith('000000000000') or len(vat) != 14:
            return False
        if self._ResPartner__check_vat_br_re.match(vat):
            values = [ord(n) - 48 for n in vat[:12]]
            weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
            d1 = (11 - sum(w * v for w, v in zip(weights, values))) % 11 % 10
            values.append(d1)
            weights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
            d2 = (11 - sum(w * v for w, v in zip(weights, values))) % 11 % 10
            return vat[-2:] == f'{d1}{d2}'
        return False

    is_cpf_valid = stdnum.get_cc_module('br', 'cpf').is_valid
    return is_cpf_valid(vat) or is_cnpj_valid(vat)


def check_vat_ch(self, vat):
    '''
        Check Switzerland VAT number.
        '''
    # A new VAT number format in Switzerland has been introduced between 2011 and 2013
    # https://www.estv.admin.ch/estv/fr/home/mehrwertsteuer/fachinformationen/steuerpflicht/unternehmens-identifikationsnummer--uid-.html
    # The old format "TVA 123456" is not valid since 2014
    # Accepted format are: (spaces are ignored)
    #     CHE#########MWST
    #     CHE#########TVA
    #     CHE#########IVA
    #     CHE-###.###.### MWST
    #     CHE-###.###.### TVA
    #     CHE-###.###.### IVA
    #
    # /!\ The english abbreviation VAT is not valid /!\

    match = self._check_vat_ch_re.match(vat)
    if match:
        # For new TVA numbers, the last digit is a MOD11 checksum digit build with weighting pattern: 5,4,3,2,7,6,5,4
        num = [s for s in match.group(1) if s.isdigit()]        # get the digits only
        factor = (5, 4, 3, 2, 7, 6, 5, 4)
        csum = sum(int(num[i]) * factor[i] for i in range(8))
        check = (11 - (csum % 11)) % 11
        return check == int(num[8])
    return False


def check_vat_cr(self, vat):
    # CÉDULA FÍSICA: 9 digits
    # CÉDULA JURÍDICA: 10 digits
    # CÉDULA DIMEX: 11 or 12 digits
    # CÉDULA NITE: 10 digits

    return self._check_vat_cr_re.match(vat) or False


def check_vat_de(self, vat):
    is_valid_vat = stdnum.util.get_cc_module("de", "vat").is_valid
    is_valid_stnr = stdnum.util.get_cc_module("de", "stnr").is_valid
    return is_valid_vat(vat) or is_valid_stnr(vat)


def check_vat_do(self, vat):
    is_valid_vat = stdnum.util.get_cc_module("do", "vat").is_valid
    is_valid_cedula = stdnum.util.get_cc_module("do", "cedula").is_valid
    return is_valid_vat(vat) or is_valid_cedula(vat)


def check_vat_ec(self, vat):
    vat = clean(vat, ' -.').upper().strip()
    return self.is_valid_ruc_ec(vat)


def check_vat_gr(self, vat):
    """ Allows some custom test VAT number to be valid to allow testing Greece EDI. """
    gr_vat = stdnum.util.get_cc_module('gr', 'vat')
    vat = gr_vat.compact(vat)
    greece_test_vats = ('047747270', '047747210', '047747220', '117747270', '127747270')
    if vat in greece_test_vats:
        return True
    return gr_vat.is_valid(vat)


def check_vat_gt(self, vat):
    """
        Allow some custom Guatemala NIT numbers to pass the test to be used for testing the Guatemalan EDI.
        """
    guatemalan_test_vats = ('11201220K', '11201350K')
    if vat in guatemalan_test_vats or self._ResPartner__check_vat_gt_testing_infile.match(vat):
        return True
    return stdnum.util.get_cc_module('gt', 'vat').is_valid(vat)


def check_vat_hu(self, vat):
    """
            Check Hungary VAT number that can be for example 'HU12345676 or 'xxxxxxxx-y-zz' or '8xxxxxxxxy'

            - For xxxxxxxx-y-zz, 'x' can be any number, 'y' is a number between 1 and 5 depending on the person and the 'zz'
              is used for region code.
            - 8xxxxxxxxy, Tin number for individual, it has to start with an 8 and finish with the check digit
            - In case of EU format it will be the first 8 digits of the full VAT
        """
    companies = self._check_tin_hu_companies_re.match(vat)
    if companies:
        return True
    individual = self._check_tin_hu_individual_re.match(vat)
    if individual:
        return True
    european = self._check_tin_hu_european_re.match(vat)
    if european:
        return True
    # Check the vat number
    return stdnum.util.get_cc_module('hu', 'vat').is_valid(vat)


def check_vat_id(self, vat):
    """ Temporary Indonesian VAT validation to support the new format
        introduced in January 2024."""
    vat = clean(vat, ' -.').strip()

    if len(vat) not in (15, 16) or not vat.isdecimal():
        return False

    # VAT could be 15 (old numbers) or 16 digits. If there are 15 digits long, the 10th digit is a luhn checksum
    # In some cases, the 15 digits can be transformed in a 16-digit by adding a 0 in front. In such case, we
    # we can verify the luhn checksum like for the 15 digits by removing the 0.
    # However, for newly created VAT 16-digits VAT number, there is no checksum.
    if (len(vat) == 16 and vat[0] != '0'):
        return True

    try:
        luhn.validate(vat[0:9] if len(vat) == 15 else vat[1:10])
    except (InvalidFormat, InvalidChecksum):
        return False

    return True


def check_vat_ie(self, vat):
    return stdnum.util.get_cc_module('ie', 'vat').is_valid(vat)


def check_vat_il(self, vat):
    check_func = stdnum.util.get_cc_module('il', 'idnr').is_valid
    return check_func(vat)


def check_vat_in(self, vat):
    # reference from https://www.gstzen.in/a/format-of-a-gst-number-gstin.html
    if vat and len(vat) == 15:
        all_gstin_re = [
            r'[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}[Z1-9A-J]{1}[0-9A-Z]{1}',  # Normal, Composite, Casual GSTIN
            r'[0-9]{4}[A-Z]{3}[0-9]{5}[UO]{1}[N][A-Z0-9]{1}',  # UN/ON Body GSTIN
            r'[0-9]{4}[A-Z]{3}[0-9]{5}[A-Z]{3}',  # Revised NRI GSTIN
            r'[0-9]{4}[A-Z]{3}[0-9]{5}[N][R][0-9A-Z]{1}',  # NRI GSTIN
            r'[0-9]{2}[A-Z]{4}[A-Z0-9]{1}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}[DK]{1}[0-9A-Z]{1}',  # TDS GSTIN
            r'[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}[C]{1}[0-9A-Z]{1}'  # TCS GSTIN
        ]
        return any(re.compile(rx).match(vat) for rx in all_gstin_re)
    return False


def check_vat_jp(self, vat):
    if vat and vat[0] == 'T':
        vat = vat[1:]
    return stdnum.util.get_cc_module('jp', 'vat').is_valid(vat)


def check_vat_ma(self, vat):
    return vat.isdigit() and len(vat) == 8


def check_vat_mx(self, vat):
    ''' Mexican VAT verification

        Verificar RFC México
        '''
    m = self._check_vat_mx_re.fullmatch(vat)
    if not m:
        # No valid format
        return False
    ano = int(m['ano'])
    if ano > 30:
        ano = 1900 + ano
    else:
        ano = 2000 + ano
    try:
        datetime.date(ano, int(m['mes']), int(m['dia']))
    except ValueError:
        return False

    # Valid format and valid date
    return True


def check_vat_no(self, vat):
    """
        Check Norway VAT number.See http://www.brreg.no/english/coordination/number.html
        """
    if len(vat) == 12 and vat.upper().endswith('MVA'):
        vat = vat[:-3]  # Strictly speaking we should enforce the suffix MVA but...

    if len(vat) != 9:
        return False
    try:
        int(vat)
    except ValueError:
        return False

    sum = (3 * int(vat[0])) + (2 * int(vat[1])) + \
        (7 * int(vat[2])) + (6 * int(vat[3])) + \
        (5 * int(vat[4])) + (4 * int(vat[5])) + \
        (3 * int(vat[6])) + (2 * int(vat[7]))

    check = 11 - (sum % 11)
    if check == 11:
        check = 0
    if check == 10:
        # 10 is not a valid check digit for an organization number
        return False
    return check == int(vat[8])


def check_vat_pe(self, vat):
    if len(vat) != 11 or not vat.isdigit():
        return False
    dig_check = 11 - (sum(int('5432765432'[f]) * int(vat[f]) for f in range(0, 10)) % 11)
    if dig_check == 10:
        dig_check = 0
    elif dig_check == 11:
        dig_check = 1
    return int(vat[10]) == dig_check


def check_vat_ph(self, vat):
    return len(vat) >= 11 and len(vat) <= 17 and self._check_vat_ph_re.match(vat)


def check_vat_pk(self, vat):
    # NTN (7 digits, or 7 + 1 check digit) or CNIC (13 digits): 1234567, 1234567-8, 12345-1234567-8.
    return bool(re.fullmatch(r'\d{7}|\d{8}|\d{13}', (vat or '').replace('-', '').replace(' ', '')))


def check_vat_ro(self, vat):
    """
            Check Romanian VAT number that can be for example 'RO1234567897 or 'xyyzzaabbxxxx' or '9000xxxxxxxx'.

            - For xyyzzaabbxxxx, 'x' can be any number, 'y' is the two last digit of a year (in the range 00…99),
              'a' is a month, b is a day of the month, the number 8 and 9 are Country or district code
              (For those twos digits, we decided to let some flexibility  to avoid complexifying the regex and also
              for maintainability)
            - 9000xxxxxxxx, start with 9000 and then is filled by number In the range 0...9

            Also stdum also checks the CUI or CIF (Romanian company identifier). So a number like '123456897' will pass.
        """
    tin1 = self._check_tin1_ro_natural_persons.match(vat)
    if tin1:
        return True
    tin2 = self._check_tin2_ro_natural_persons.match(vat)
    if tin2:
        return True
    # Check the vat number
    return stdnum.util.get_cc_module('ro', 'vat').is_valid(vat)


def check_vat_rs(self, vat):
    vat = vat.removeprefix('RS')
    return stdnum.util.get_cc_module('rs', 'vat').is_valid(vat)


def check_vat_sa(self, vat):
    """
            Check company VAT TIN according to ZATCA specifications: The VAT number should start and begin with a '3'
            and be 15 digits long
        """
    return self._check_vat_sa_re.match(vat) or False


def check_vat_th(self, vat):
    check_func = stdnum.util.get_cc_module('th', 'tin').is_valid
    return check_func(vat)


def check_vat_tr(self, vat):
    return stdnum.util.get_cc_module('tr', 'tckimlik').is_valid(vat) or stdnum.util.get_cc_module('tr', 'vkn').is_valid(vat)


def check_vat_tw(self, vat):
    """
        Since Feb. 2025, due to the imminent exhaustion of the UBN numbers, the validation logic was changed from using
        a division by 10 for the final check to using a division by 5, making numbers that were previously invalid now
        valid.

        The stdnum implementation of the VAT validation is not up to date with this latest update, so we implement our
        own validation to support these new valid UBNs.
        """
    vat = stdnum.util.get_cc_module("tw", "vat").compact(vat)
    if len(vat) != 8 or not vat.isdigit():
        return False  # The length is fixed, and we will expect it to be 8 in the following checks.

    logic_multiplier = [1, 2, 1, 2, 1, 2, 4, 1]  # This multiplier is set by the official validation logic.
    # Multiply each of the 8 digits of the VAT number by the corresponding digit of the logic multiplier.
    # For the next steps, we will need to sum the results.
    # For a two-digit product like 20, you would add its digits (2 + 0) to the total sum, so we convert the sums here
    # to strings in order to make it easier later on.
    products = [str(a * int(b)) for a, b in zip(logic_multiplier, vat)]
    if vat[6] != '7':
        # If the 7th number is not 7, we simply sum everything and check that the result is divisible by 5.
        checksum = sum(int(d) for d in ''.join(products))
        return checksum % 5 == 0
    else:
        # If the 7th number is 7, we calculate two sums:
        # z1: Calculate the total sum where the 7th position's contribution is taken as 1.
        # z2: Calculate the total sum where the 7th position's contribution is taken as 0.
        # The VAT number is valid if either Z1 or Z2 (or both) is evenly divisible by 5.
        base_checksum = sum(int(d) for d in "".join(products[0:6] + products[7:]))
        return (base_checksum + 1) % 5 == 0 or base_checksum % 5 == 0


def check_vat_ua(self, vat):
    return len(vat[2:] if vat.startswith('UA') else vat) in {8, 10, 12}


def check_vat_uy(self, vat):
    """ Taken from python-stdnum's master branch, as the release doesn't handle RUT numbers starting with 22.
        origin https://github.com/arthurdejong/python-stdnum/blob/master/stdnum/uy/rut.py
        FIXME Can be removed when python-stdnum does a new release. """

    def calc_check_digit(number):
        """Calculate the check digit."""
        weights = (4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
        total = sum(int(n) * w for w, n in zip(weights, number))
        return str(-total % 11)

    vat = split_vat(vat, default_country_code='UY')[1]

    return (
        vat.isdigit()  # InvalidFormat
        and len(vat) == 12  # InvalidLength
        and '01' <= vat[:2] <= '22'  # InvalidComponent
        and vat[2:8] != '000000'
        and vat[8:11] == '001'
        and vat[-1] == calc_check_digit(vat)  # Invalid Check Digit
    )


def check_vat_uz(self, vat):
    return vat.isdigit() and len(vat) in (9, 14)


def check_vat_ve(self, vat):
    # https://tin-check.com/en/venezuela/
    # https://techdocs.broadcom.com/us/en/symantec-security-software/information-security/data-loss-prevention/15-7/About-content-packs/What-s-included-in-Content-Pack-2021-02/Updated-data-identifiers-in-Content-Pack-2021-02/venezuela-national-identification-number-v115451096-d327e108002-CP2021-02.html
    # Sources last visited on 2022-12-09

    # VAT format: (kind - 1 letter)(identifier number - 8-digit number)(check digit - 1 digit)
    vat_regex = re.compile(r"""
            ([vecjpg])                          # group 1 - kind
            (
                (?P<optional_1>-)?                      # optional '-' (1)
                [0-9]{2}
                (?(optional_1)(?P<optional_2>[.])?)     # optional '.' (2) only if (1)
                [0-9]{3}
                (?(optional_2)[.])                      # mandatory '.' if (2)
                [0-9]{3}
                (?(optional_1)-)                        # mandatory '-' if (1)
            )                                   # group 2 - identifier number
            ([0-9]{1})                          # group X - check digit
        """, re.VERBOSE | re.IGNORECASE)

    matches = re.fullmatch(vat_regex, vat)
    if not matches:
        return False

    kind, identifier_number, *_, check_digit = matches.groups()
    kind = kind.lower()
    identifier_number = identifier_number.replace("-", "").replace(".", "")
    check_digit = int(check_digit)

    if kind == 'v':                   # Venezuela citizenship
        kind_digit = 1
    elif kind == 'e':                 # Foreigner
        kind_digit = 2
    elif kind == 'c' or kind == 'j':  # Township/Communal Council or Legal entity
        kind_digit = 3
    elif kind == 'p':                 # Passport
        kind_digit = 4
    else:                             # Government ('g')
        kind_digit = 5

    # === Checksum validation ===
    multipliers = [3, 2, 7, 6, 5, 4, 3, 2]
    checksum = kind_digit * 4
    checksum += sum(map(lambda n, m: int(n) * m, identifier_number, multipliers))

    checksum_digit = 11 - checksum % 11
    if checksum_digit > 9:
        checksum_digit = 0

    return check_digit == checksum_digit


def check_vat_vn(self, vat):
    """
        VAT format validator for Vietnam.
        Supported formats:
        - 10-digit format (Enterprise tax ID): e.g., 0101243150
        - 13-digit format with branch suffix: e.g., 0101243150-001
        - 12-digit format (Personal ID / Citizen ID - CCCD): e.g., 079123456789
        (used as tax ID for individuals from July 1st, 2025)

        Note:
        - stdnum.vn.mst.validate() currently only supports 10- and 13-digit VAT numbers
        - and does not accept the 12-digit personal tax ID (CCCD) format introduced from 01/07/2025.
        - This helper provides a lightweight format-level validator for use in the meantime.
        - Can be removed once stdnum.vn.mst adds CCCD support.
        """
    vat = vat.strip()
    return bool(self._ResPartner__check_vat_vn_re.match(vat))


def format_vat_al(self, vat):
    vat_prefix, vat_number = split_vat(vat)
    stdnum_vat_format = stdnum.util.get_cc_module('al', 'nipt').compact
    vat_number = stdnum_vat_format(vat_number)
    return f'{vat_prefix}{vat_number}'


def format_vat_ca(self, vat):
    """Normalize the case of a Canadian Business Number (BN).

        Two forms are accepted:
          9 digits, the business number itself, for example 123456782
          9 digits followed by a 2 letter program identifier and a 4 digit
          reference number, for example 123456782RT0001

        The program identifier tells which account the number refers to.
        RT is goods and services tax, RP is payroll, RC is corporate income
        tax and RM is import and export. It is always written in upper case,
        but stdnum keeps the case as it was typed and then rejects a lower
        case identifier, so upper case the number before compacting it.
        """
    return stdnum.get_cc_module('ca', 'bn').compact(vat.upper())


def format_vat_ch(self, vat):
    stdnum_vat_format = stdnum.util.get_cc_module('ch', 'vat').format
    return stdnum_vat_format('CH' + vat)[2:]


def format_vat_cl(self, vat):
    """ It is better to always have the -"""
    vat = vat.replace('.', '').replace('CL', '').replace(' ', '').replace('-', '').upper()
    if len(vat) > 2:
        return vat[:-1] + '-' + vat[-1]
    return vat


def format_vat_co(self, vat):
    """ It is better to always have the -"""
    stdnum_vat_format = stdnum.util.get_cc_module('co', 'vat').format
    vat = stdnum_vat_format(vat).replace('.', '').replace('-', '')
    if len(vat) > 2:
        return vat[:-1] + '-' + vat[-1]
    return vat


def format_vat_eu(self, vat):
    # Foreign companies that trade with non-enterprises in the EU
    # may have a VATIN starting with "EU" instead of a country code.
    return vat


def format_vat_hu(self, vat):
    """ We put the - back as we require it for the EDI and the different parts will make it clear to the user"""
    vat = split_vat(vat, default_country_code='hu')[1]
    if self._check_tin_hu_companies_re.match(vat):
        vat = vat[:8] + '-' + vat[8] + '-' + vat[9] + vat[10]
    return vat


def format_vat_is(self, vat):
    vat_prefix, vat_number = split_vat(vat)
    stdnum_vat_format = stdnum.util.get_cc_module('is_', 'vsk').compact
    vat_number = stdnum_vat_format(vat_number)
    return f'{vat_prefix}{vat_number}'


def format_vat_pk(self, vat):
    vat = (vat or '').replace('-', '').replace(' ', '')
    if len(vat) == 8:
        return f'{vat[:-1]}-{vat[-1]}'
    if len(vat) == 13:
        return f'{vat[:5]}-{vat[5:12]}-{vat[12]}'
    return vat


def format_vat_sm(self, vat):
    stdnum_vat_format = stdnum.util.get_cc_module('sm', 'vat').compact
    return stdnum_vat_format('SM' + vat)[2:]


def format_vat_vn(self, vat):
    """ It is better to always have the -"""
    stdnum_vat_format = stdnum.util.get_cc_module('vn', 'vat').format
    if self._ResPartner__check_vat_vn_companies_re.match(vat):
        return stdnum_vat_format(vat)
    else:
        return vat


def is_valid_ruc_ec(self, vat):
    return len(vat) in (10, 13) and vat.isdecimal()
