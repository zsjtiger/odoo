# -*- coding: utf-8 -*-

from odoo import api, models


class Base(models.AbstractModel):
    _inherit = 'base'

    @api.model
    def mobile_filter_config(self):
        """ Custom filter panel of the mobile client.

        Return a list of sections; each section is a dict with:
          - ``name``, ``label``: the section title
          - ``options``: list of ``{key, label, domain, radio}``; a selected option adds
            its domain (options of one section are OR-ed, sections are AND-ed)
          - ``cards`` (optional): ``{field, subfield}``, a many2one field whose records are
            shown as selectable cards; ``subfield`` is shown under the card name

        An empty list means the mobile client uses the filters of the search view.
        """
        return []
