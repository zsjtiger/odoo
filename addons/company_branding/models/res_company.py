# -*- coding: utf-8 -*-
from urllib.parse import urlparse

from odoo import api, fields, models
from odoo.exceptions import ValidationError

URL_FIELDS = (
    'web_title', 'web_icon_url', 'web_logo_url',
    'mobile_title', 'mobile_icon_url', 'mobile_logo_url',
    'login_background_url',
)
TITLE_FIELDS = ('web_title', 'mobile_title')


def _is_safe_url(url):
    """Only http(s) URLs with a host are accepted; they end up in ``src`` and ``url()``."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc)


class ResCompany(models.Model):
    _inherit = 'res.company'

    web_title = fields.Char(string='Web Title', help="Browser tab title of the web client.")
    web_icon_url = fields.Char(string='Web Icon URL', help="URL of the browser tab icon (http or https).")
    web_logo_url = fields.Char(string='Web Logo URL', help="URL of the logo shown on the web login page.")
    mobile_title = fields.Char(string='Mobile Title', help="Browser tab title of the mobile web client.")
    mobile_icon_url = fields.Char(string='Mobile Icon URL', help="URL of the browser tab icon of the mobile client.")
    mobile_logo_url = fields.Char(string='Mobile Logo URL', help="URL of the logo shown on the mobile login page.")
    login_background_url = fields.Char(
        string='Login Background URL',
        help="URL of the background image of the web and mobile login pages.",
    )

    @api.constrains(*URL_FIELDS)
    def _check_branding_values(self):
        for company in self:
            for fname in URL_FIELDS:
                value = company[fname]
                if not value or fname in TITLE_FIELDS:
                    continue
                if not _is_safe_url(value.strip()):
                    raise ValidationError(self.env._(
                        "%(field)s must be an http or https URL: %(value)s",
                        field=company._fields[fname].string, value=value,
                    ))

    @api.model
    def _get_branding(self):
        """Return the branding of the current company, with empty strings for unset values."""
        company = self.env.company.sudo()
        return {fname: (company[fname] or '').strip() for fname in URL_FIELDS}
