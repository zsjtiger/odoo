# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PharaccountPicklist(models.Model):
    """A dropdown definition, e.g. ``pharmacy_level``. Mirrors vrux ``picklists``."""
    _name = 'pharaccount.picklist'
    _description = 'Pharmacy Picklist'
    _order = 'name'

    name = fields.Char(required=True)
    label = fields.Char(required=True)
    description = fields.Text()
    value_ids = fields.One2many('pharaccount.picklist.value', 'picklist_id', string='Values')

    _name_unique = models.Constraint('UNIQUE(name)', 'The picklist name must be unique.')


class PharaccountPicklistValue(models.Model):
    """An option of a picklist. Mirrors vrux ``picklist_values`` and ``role_to_picklist_values``.

    ``group_ids`` limits who can select the option. Empty means every user can select it.
    ``depends_on`` is reserved for cascading picklists and is not implemented in the first version.
    """
    _name = 'pharaccount.picklist.value'
    _description = 'Pharmacy Picklist Value'
    _order = 'picklist_id, sequence, id'

    picklist_id = fields.Many2one('pharaccount.picklist', required=True, ondelete='cascade')
    name = fields.Char(required=True, help='Technical code, e.g. A')
    label = fields.Char(required=True, help='Shown to users, e.g. A级')
    sequence = fields.Integer(default=10)
    is_disabled = fields.Boolean(string='Disabled', help='A disabled option is not offered for selection.')
    value = fields.Char(help='The stored value. Only primitive types are supported.')
    group_ids = fields.Many2many(
        'res.groups', 'pharaccount_picklist_value_group_rel', 'value_id', 'group_id',
        string='Allowed groups',
        help='Groups that can select this option. Empty means everyone can select it.',
    )
    depends_on = fields.Char(string='Depends on', help='Reserved for cascading picklists.')

    _picklist_name_unique = models.Constraint(
        'UNIQUE(picklist_id, name)', 'The option code must be unique in a picklist.',
    )

    @api.model
    def get_selectable(self, picklist_name, record_type=None):
        """Return the options of a picklist the current user can select.

        :param picklist_name: the picklist ``name``, e.g. ``pharmacy_level``
        :param record_type: optional ``pharaccount.record.type``. When it has configured
            options (including its parents'), only those options are returned.
        """
        domain = [
            ('picklist_id.name', '=', picklist_name),
            ('is_disabled', '=', False),
        ]
        values = self.search(domain)
        user_group_ids = set(self.env.user.all_group_ids.ids)
        # Users cannot read res.groups, so the groups of each option are read with sudo.
        values = values.filtered(
            lambda v: not v.sudo().group_ids or bool(set(v.sudo().group_ids.ids) & user_group_ids),
        )
        if record_type and record_type.allowed_picklist_value_ids:
            values &= record_type.allowed_picklist_value_ids
        return values
