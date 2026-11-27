# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The additional identifiers of the partners: their validation, their formats, their metadata and their preferred values."""

from __future__ import annotations

import typing
from stdnum.eu import vat as eu_vat
from odoo.exceptions import ValidationError
from odoo.tools.text.translate import LazyGettext
from ..partner_identifiers import (
    ADDITIONAL_IDENTIFIERS_METADATA,
    COMPANY_CATEGORIES,
    INDIVIDUAL_CATEGORIES,
    TIN_METADATA,
    get_deduced_identifiers,
    get_tin_metadata_of_country,
    is_identifier_void,
    normalize_identifier,
    validation_error_message,
)

if typing.TYPE_CHECKING:
    pass

from .partner import _logger

def _check_additional_identifiers(self):
    """Safety guard for paths that bypass `_clean_additional_identifiers`, so malformed values
        never reach the JSON.
        """
    for partner in self:
        for key, value in (partner.additional_identifiers or {}).items():
            self.env['res.partner']._validate_identifier(key, value, validation='error')  # will raise ValidationError if invalid


def _validate_identifier(self, key, value, validation=False):
    """ Run the per-identifier-type validator (if any) and return a uniform
        `{valid, value, example}` dict.
        """
    assert validation in (False, 'error', 'setnull')
    value = normalize_identifier(value)
    if not value or self.env.context.get('no_vat_validation'):
        return {'valid': True, 'value': value, 'example': None}

    if (tin_meta := TIN_METADATA.get(key)) and (country_code := tin_meta.get('countries')[:1]):
        country = self.env['res.country'].search([('code', '=', country_code[0])], limit=1)
        tin, _country_code = self._run_vat_checks(country, value, validation=validation)
        example = tin_meta.get('examples') or tin_meta.get('placeholder')
        return {'valid': bool(tin), 'value': tin, 'example': example}

    metadata = self._get_all_identifiers_metadata().get(key) or {}
    example = metadata.get('examples') or metadata.get('placeholder')
    validation_vals = {'valid': True, 'value': value, 'example': example}
    validation_function = metadata.get('validation_function')

    # For VAT-like identifiers (that are not in `vat` field) without a dedicated validator,
    # fallback to eu_vat.validate only when the value looks like a prefixed EU VAT (starts with a 2-letter code).
    supported_countries = eu_vat.MEMBER_STATES
    if not validation_function and metadata.get('category') == 'VAT' and value[:2].lower() in supported_countries:
        validation_function = eu_vat.validate

    if validation_function:
        try:
            value_normalized = validation_function(value)
        except Exception:  # noqa: BLE001
            validation_vals['valid'] = False
        else:
            validation_vals['value'] = value_normalized

    if not validation_vals['valid'] and validation == 'error':
        identifier_label = self._get_identifier_label(key)
        raise ValidationError(validation_error_message(self.env, identifier_label, validation_vals['value'], example=validation_vals['example']))
    if not validation_vals['valid'] and validation == 'setnull':
        _logger.warning("Invalid identifier %s for key %s. Returning None.", value, key)
        validation_vals['value'] = None
    return validation_vals


def _validate_identifier_by_scheme(self, scheme, value, validation=False):
    assert validation in (False, 'error', 'setnull')
    ResPartner = self.env['res.partner']
    meta = ResPartner._get_all_identifiers_metadata_by_scheme().get(scheme)
    if not meta:
        # Needs to return True to handle `odemo` scheme
        return {'valid': True, 'scheme': scheme, 'value': value, 'key': None, 'example': None}
    validation = ResPartner._validate_identifier(meta['key'], value, validation=validation)
    return {'scheme': scheme, 'key': meta['key'], **validation}


def _format_identifier(self, identifier_type, value):
    value = normalize_identifier(value)
    if not value:
        return None
    if format_function := self._get_all_identifiers_metadata().get(identifier_type, {}).get('format'):
        return format_function(value)
    return value


def _pick_preferred_identifier(self, identifiers, filter_func=None, sort_key=None):
    """ Pick the best identifier from a candidates dict.

        :param identifiers: dict {identifier_type: value} as from `_get_all_identifiers()`
        :param filter_func: optional (key, value, metadata) -> bool
        :param sort_key: optional (key, value, metadata) -> comparable
        :return: dict `{'key': ..., 'value': ..., **metadata}` of the winner, or empty dict if no candidate.
        """
    candidates = []
    for key, value in identifiers.items():
        meta = self._get_all_identifiers_metadata().get(key) or {}
        if filter_func and not filter_func(key, value, meta):
            continue
        candidates.append((key, value, meta))
    if not candidates:
        return {}
    if sort_key:
        candidates.sort(key=lambda c: sort_key(*c))
    winner_key, winner_value, winner_meta = candidates[0]
    return {
        'key': winner_key,
        'value': winner_value,
        **self._lazy_translate_additional_identifiers_metadata(winner_meta),
    }


def _compute_available_additional_identifiers_metadata(self):
    for partner in self:
        stored_identifiers = partner.additional_identifiers or {}
        vals = {
                # Resolve lazy translations now: JSON would otherwise stringify them in a frame where
                # no language can be detected.
            key: self._lazy_translate_additional_identifiers_metadata(metadata)
            for key, metadata in self._get_all_additional_identifiers_metadata().items()
            if not metadata.get('countries')
                or partner.country_code in metadata['countries']
                or key in stored_identifiers  # includes international, and any identifier already set on the record
        }
        if {key: metadata for key, metadata in vals.items() if metadata.get('category') == 'EN' and key != 'OTHER'}:
            # Pops out the default 'OTHER' only if another 'EN' identifier is available
            vals.pop('OTHER', None)
        partner.available_additional_identifiers_metadata = vals


def _lazy_translate_additional_identifiers_metadata(self, metadata):
    """Resolve lazy translation in additional identifier metadata"""
    return {
        key: self.env._(value) if isinstance(value, LazyGettext) else value  # pylint: disable=gettext-variable
        for key, value in metadata.items()
    }


def _get_additional_identifier(self, identifier_type):
    """Convenience getter for an entry of the JSON."""
    if not self:
        return None
    self.ensure_one()
    return (self.additional_identifiers or {}).get(identifier_type)


def _set_additional_identifier(self, identifier_type, value):
    """ Write helper for adding identifier in the JSON.
        It validates, normalizes, deduce siblings and inserts the value.
        """
    self.ensure_one()
    if not identifier_type:
        return
    identifiers = self.additional_identifiers or {}
    if not value:
        identifiers.pop(identifier_type, None)
        self.additional_identifiers = identifiers
        return
    validation = self.env['res.partner']._validate_identifier(identifier_type, value, validation='error')  # possibly raises ValidationError
    normalized_value = validation['value']
    identifiers[identifier_type] = normalized_value  # set the normalized value
    deduced_identifiers = get_deduced_identifiers(identifier_type, normalized_value)
    self.additional_identifiers = {**identifiers, **deduced_identifiers}  # json needs to be fully reassigned each time


def _get_all_identifiers(self, enrich=False):
    """Combined VAT + additional identifiers of the commercial partner.
        With `enrich`, also include identifiers derivable from the stored ones (e.g. FR_SIRET => FR_SIREN).
        """
    self.ensure_one()
    partner = self.commercial_partner_id
    identifiers = partner.additional_identifiers or {}
    if not is_identifier_void(partner.vat):
        key = get_tin_metadata_of_country(partner.country_code).get('key', 'TIN')
        identifiers = {key: partner.vat, **identifiers}
    enriched_identifiers = {}
    if enrich:
        for identifier_type, value in identifiers.items():
            enriched_identifiers.update(get_deduced_identifiers(identifier_type, value))
    return {**enriched_identifiers, **identifiers}


def _get_all_identifiers_metadata(self):
    """ Returns a dict with the metadata of every known identifier: the TIN ones, which
        describe the generic `vat` field, plus the additional ones.
        Only override this to register an identifier that must NOT be added in
        `additional_identifiers` (e.g. a corner case scheme); in any other case override
        `_get_all_additional_identifiers_metadata` instead.
        """
    return {**TIN_METADATA, **self._get_all_additional_identifiers_metadata()}


def _get_allowed_identifier_metadata_keys(self):
    """ Metadata keys an identifier may declare. Localizations extend it with the keys
        they read themselves, e.g. the code they report the identifier with. """
    return {
        'category', 'countries', 'display_optional', 'examples', 'format', 'help', 'label',
        'placeholder', 'scheme', 'sequence', 'synced', 'validation_function',
    }


def _get_all_identifiers_metadata_by_scheme(self):
    return {
        metadata.get('scheme'): {'key': key, **metadata}
        for key, metadata in self._get_all_identifiers_metadata().items()
        if metadata.get('scheme')
    }


def _get_all_additional_identifiers_metadata(self):
    """ Returns a dict with the metadata of the identifiers available in `additional_identifiers`.
        TO BE OVERRIDDEN by modules that want to add or modify the default
        metadata. Entries added here are automatically picked up by
        `_get_all_identifiers_metadata`, hence used for validation, labels, etc.
        """
    return {**ADDITIONAL_IDENTIFIERS_METADATA}


def _get_legal_entity_category_priority(self):
    return {'EN': 0, 'VAT': 1, 'TIN': 1, 'GST': 1, 'CN': 2}


def _get_tax_category_priority(self):
    return {'VAT': 0, 'TIN': 0, 'GST': 0}


def _get_identifier_label(self, identifier_key):
    """Return the label of an identifier given its key."""
    return self._get_all_identifiers_metadata().get(identifier_key, {}).get('label', '')


def _is_individual_identifier(self, identifier_key):
    """ Whether the identifier represents an individual (e.g. a citizen number). """
    return self._get_all_identifiers_metadata().get(identifier_key, {}).get('category') in INDIVIDUAL_CATEGORIES


def _is_company_identifier(self, identifier_key):
    """ Whether the identifier represents a company (a tax number or an enterprise number).
        Identifiers without a category fall on the company side, like `is_company` defaults to False. """
    category = self._get_all_identifiers_metadata().get(identifier_key, {}).get('category')
    return not category or category in COMPANY_CATEGORIES


def _is_geolocalized(self):
    self.ensure_one()
    return self.partner_latitude and self.partner_longitude


def _get_preferred_legal_entity_identifier_vals(self):
    """Return a dict {'scheme': scheme, 'value': value, ...metadata} of the preferred legal entity identifier for the given partner.
        The selection is based on the following rules:
        1. It must be a legal entity identifier (e.g. company number, Tax ID, citizen card number).
        2. Among those, it picks the one with the lowest sequence, THEN the "best" category (see _get_legal_entity_category_priority).
        3. If no such identifier is found, an empty dict is returned.
        """
    self.ensure_one()
    partner = self.commercial_partner_id
    priorities = self._get_legal_entity_category_priority()
    identifier_vals = self._pick_preferred_identifier(
        partner._get_all_identifiers(enrich=True),
        filter_func=lambda k, v, m: m.get('category') in priorities or k == 'TIN',
        sort_key=lambda k, v, m: (m.get('sequence', 100), priorities.get(m.get('category'), 100)),
    )
    return identifier_vals or {}


def _get_preferred_tax_identifier_vals(self):
    """Return a dict {'scheme': scheme, 'value': value, ...metadata} of the preferred tax identifier for the given partner.
        The selection is based on the following rules:
        1. It must be a valid tax identifier (e.g. company number, Tax ID).
        2. Among those, it picks the one with the "best" category (see _get_tax_category_priority), THEN ties with the sequence.
        3. If no such identifier is found, an empty dict is returned.
        """
    self.ensure_one()
    partner = self.commercial_partner_id
    priorities = self._get_tax_category_priority()
    identifier_vals = self._pick_preferred_identifier(
        partner._get_all_identifiers(enrich=True),
        filter_func=lambda k, v, m: m.get('category') in priorities or k == 'TIN',
        sort_key=lambda k, v, m: (priorities.get(m.get('category'), 100), m.get('sequence', 100)),
    )
    return identifier_vals or {}


def _deduce_additional_identifiers_from_vat(self):
    """Populate identifiers derivable from the VAT (e.g. BE_VAT => BE_EN, AT_VAT => AT_EN)."""
    for partner in self:
        if not partner.vat or not partner.country_code:
            continue
        vat_key = get_tin_metadata_of_country(partner.country_code).get('key')
        if not vat_key:
            continue
        deduced_identifiers = get_deduced_identifiers(vat_key, partner.vat)
        if not deduced_identifiers:
            continue
        identifiers = partner.additional_identifiers or {}
        # Only keep deduced identifiers that are actually valid: a VAT does not always map to a
        # well-formed companion id (e.g. a 13-digit RO fiscal code is not a valid 10-digit CUI).
        to_update = {
            k: v for k, v in deduced_identifiers.items()
            if identifiers.get(k) != v and self.env['res.partner']._validate_identifier(k, v)['valid']
        }
        if not to_update:
            continue
        try:
            # Use mail_notrack to avoid triggering mail tracking, which would
            # recompute tracked computed fields (e.g. vies_valid) mid-inverse.
            partner.with_context(mail_notrack=True).additional_identifiers = {**identifiers, **to_update}
        except ValidationError:
            _logger.info("Skipped %s: deduced identifier from %s could not be validated.", deduced_identifiers, vat_key)
            continue


def _clean_additional_identifiers(self, vals):
    """ Pre-write filter on a `vals` dict:
        - drop unknown keys (with a warning log)
        - reject malformed values (raises ValidationError)
        - normalize
        - add deduced identifiers.
        Mutates `vals` in place.
        """
    if 'additional_identifiers' not in vals or not isinstance(vals['additional_identifiers'], dict):
        return vals
    cleaned = {}
    for key, value in vals['additional_identifiers'].items():
        if not self._get_all_additional_identifiers_metadata().get(key):
            _logger.warning(" Skipped %s: identifier %s is not in supported identifiers.", value, key)
            continue
        if not value:
            continue
        result = self.env['res.partner']._validate_identifier(key, value, validation='error')  # possibly raises ValidationError
        cleaned[key] = result['value']
    # Compute deduced identifiers (e.g. FR_SIRET => FR_SIREN). Only keep the well-formed ones.
    for key, value in list(cleaned.items()):
        for deduced_key, deduced_value in get_deduced_identifiers(key, value).items():
            if deduced_key not in cleaned and self.env['res.partner']._validate_identifier(deduced_key, deduced_value)['valid']:
                cleaned[deduced_key] = deduced_value
    vals['additional_identifiers'] = cleaned


def _deduce_country_code(self):
    """ deduce the country code based on the information available.
        we have three cases:
        - country_code is BE but the VAT number starts with FR, the country code is FR, not BE
        - if a country-specific field is set (e.g. the codice_fiscale), that country is used for the country code
        - if the VAT number has no ISO country code, use the country_code in that case.
        """
    self.ensure_one()
    _vat, country_code = self._run_vat_checks(self.country_id, self.vat, validation=False)
    return country_code or self.country_code


def _get_identifier_fields(self):
    # To be extended by localization, used for the partner_autocomplete
    return ['vat']
