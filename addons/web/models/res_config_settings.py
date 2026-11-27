# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    web_app_name = fields.Char('Web App Name', config_parameter='web.web_app_name')
    gps_amap_key = fields.Char(
        'AMap Key', config_parameter='web.gps.amap_key',
        help="Key of the AMap JS API. Without it the GPS field shows a placeholder map.")
    gps_geocoder_url = fields.Char(
        'Geocoder URL', config_parameter='web.gps.geocoder_url',
        help="Base URL of the geocoding service. Empty uses the default service.")
