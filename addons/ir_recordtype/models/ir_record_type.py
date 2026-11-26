# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

OPERATIONS = {'create': 'perm_create', 'read': 'perm_read', 'write': 'perm_write', 'unlink': 'perm_unlink'}


class IrRecordType(models.Model):
    _name = 'ir.record.type'
    _description = 'Record Type'
    _order = 'model_id, sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade', index=True)
    model_name = fields.Char(related='model_id.model', store=True, readonly=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    parent_id = fields.Many2one(
        'ir.record.type', string='Parent Type', ondelete='restrict', index=True,
        domain="[('model_id', '=', model_id)]",
        help="Parent type of the same model. Used for the view extension chain only; "
             "access is never inherited.",
    )
    child_ids = fields.One2many('ir.record.type', 'parent_id', string='Child Types')
    permission_ids = fields.One2many('ir.record.type.permission', 'record_type_id', string='Permissions', copy=True)
    default_ids = fields.One2many('ir.record.type.default', 'record_type_id', string='Default For')
    access_ids = fields.One2many('ir.access', 'record_type_id', string='Access Rows')
    view_ids = fields.One2many('ir.ui.view', 'record_type_id', string='Views')
    action_id = fields.Many2one('ir.actions.act_window', string='Action', readonly=True, copy=False, ondelete='set null')
    menu_parent_id = fields.Many2one(
        'ir.ui.menu', string='Menu Parent', ondelete='set null',
        help="Parent of the menu generated for this type. Empty means a top-level menu.",
    )
    group_ids = fields.Many2many('res.groups', compute='_compute_group_ids', string='Granted Groups')
    has_permissions = fields.Boolean(compute='_compute_group_ids')

    _code_unique = models.Constraint('UNIQUE(model_id, code)', 'The code must be unique per model.')

    @api.depends('permission_ids.group_id', 'permission_ids.perm_read')
    def _compute_group_ids(self):
        for record in self:
            record.group_ids = record.permission_ids.group_id
            record.has_permissions = bool(record.permission_ids)

    @api.constrains('parent_id')
    def _check_parent(self):
        for record in self:
            if record.parent_id and record.parent_id.model_id != record.model_id:
                raise ValidationError(self.env._("The parent type must belong to the same model."))
            seen = set()
            node = record.parent_id
            while node:
                if node == record:
                    raise ValidationError(self.env._("Record types cannot inherit from themselves."))
                if node.id in seen:
                    break
                seen.add(node.id)
                node = node.parent_id

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_action_and_menu()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.keys() & {'name', 'sequence', 'active', 'model_id', 'menu_parent_id'}:
            self._sync_action_and_menu()
        return res

    def unlink(self):
        for record in self:
            if record.model_name in self.env.registry:
                used = self.env[record.model_name].sudo().with_context(active_test=False).search_count(
                    [('record_type_id', '=', record.id)])
                if used:
                    raise UserError(self.env._(
                        "Record type %(type)s is used by %(count)s records and cannot be deleted. Deactivate it instead.",
                        type=record.display_name, count=used,
                    ))
        actions = self.action_id
        res = super().unlink()
        actions.unlink()
        return res

    def _sync_action_and_menu(self):
        """Create or update the window action and the menu of each type (generated metadata)."""
        Action = self.env['ir.actions.act_window'].sudo()
        Menu = self.env['ir.ui.menu'].sudo().with_context(active_test=False)
        for record in self:
            if not record.action_id:
                record.action_id = Action.create({
                    'name': record.name,
                    'res_model': record.model_name,
                    'view_mode': 'list,form',
                    'domain': f"[('record_type_id', '=', {record.id})]",
                    'context': f"{{'default_record_type_id': {record.id}}}",
                })
            else:
                record.action_id.name = record.name
            record._sync_action_views()
            menu = Menu.search([('record_type_id', '=', record.id)], limit=1)
            vals = {
                'name': record.name,
                'sequence': record.sequence,
                'action': f'ir.actions.act_window,{record.action_id.id}',
                'record_type_id': record.id,
                'parent_id': record.menu_parent_id.id,
            }
            if menu:
                menu.write(vals)
            else:
                Menu.create(vals | {'parent_id': False})
        self._sync_menu_groups()

    def _sync_action_views(self):
        """The action shows the type's form view (if any) instead of the model default form."""
        self.ensure_one()
        ActionView = self.env['ir.actions.act_window.view'].sudo()
        form_view = self.view_ids.filtered(lambda v: v.type == 'form')[:1]
        ActionView.search([('act_window_id', '=', self.action_id.id), ('view_mode', '=', 'form')]).unlink()
        if form_view:
            ActionView.create({
                'act_window_id': self.action_id.id,
                'view_mode': 'form',
                'view_id': form_view.id,
                'sequence': 2,
            })

    def _sync_menu_groups(self):
        """A menu is visible to the groups that can read the type, and only while the type is active."""
        admin = self.env.ref('base.group_system')
        Menu = self.env['ir.ui.menu'].sudo().with_context(active_test=False)
        for record in self:
            read_groups = record.permission_ids.filtered('perm_read').group_id | admin
            menus = Menu.search([('record_type_id', '=', record.id)])
            menus.write({
                'group_ids': [(6, 0, read_groups.ids)],
                'active': record.active and bool(record.permission_ids.filtered('perm_read')),
            })

    def _can_use(self, operation):
        """True if the current user may perform the operation on records of this type."""
        self.ensure_one()
        if self.env.user.has_group('base.group_system'):
            return True
        field = OPERATIONS[operation]
        group_ids = set(self.env.user.all_group_ids.ids)
        return any(perm.group_id.id in group_ids and perm[field] for perm in self.permission_ids)

    def _check_can_use(self, model_name, operation):
        for record in self:
            if record.model_name != model_name:
                raise AccessError(self.env._("Record type %(type)s is not a type of model %(model)s.",
                                             type=record.display_name, model=model_name))
            if not record.active:
                raise AccessError(self.env._("Record type %s is inactive.", record.display_name))
            if not record._can_use(operation):
                raise AccessError(self.env._(
                    "You are not allowed to %(operation)s records of type %(type)s.",
                    operation=operation, type=record.display_name,
                ))

    @api.model
    def _get_default_for_user(self, model_name):
        """Default type for the current user on a model: group defaults first, then the first usable type."""
        model = self.env['ir.model']._get(model_name)
        if not model:
            return self.browse()
        defaults = self.env['ir.record.type.default'].search([
            ('model_id', '=', model.id),
            ('group_id', 'in', self.env.user.all_group_ids.ids),
        ])
        for default in defaults.sorted(lambda d: (d.record_type_id.sequence, d.record_type_id.id)):
            if default.record_type_id.active and default.record_type_id._can_use('create'):
                return default.record_type_id
        for record_type in self.search([('model_id', '=', model.id), ('active', '=', True)], order='sequence, id'):
            if record_type._can_use('create'):
                return record_type
        return self.browse()
