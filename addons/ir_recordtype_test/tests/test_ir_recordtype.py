# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestIrRecordType(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = cls.env['ir.model']._get('ir.recordtype.test')
        if not cls.model:
            # the test model is only registered in test mode: reflect it into ir.model
            cls.env['ir.model']._reflect_models(['ir.recordtype.test'])
            cls.model = cls.env['ir.model']._get('ir.recordtype.test')
        cls.group_user = cls.env.ref('base.group_user')
        cls.group_portal = cls.env.ref('base.group_portal')
        cls.RecordType = cls.env['ir.record.type']

    def _type(self, code='t1', **vals):
        return self.RecordType.create({'name': code, 'code': code, 'model_id': self.model.id, **vals})

    def test_permission_generates_scoped_access_row(self):
        rt = self._type()
        perm = self.env['ir.record.type.permission'].create({
            'record_type_id': rt.id, 'group_id': self.group_user.id,
            'perm_read': True, 'perm_create': True,
        })
        access = perm.access_id
        self.assertTrue(access)
        self.assertEqual(access.operation, 'cr')
        self.assertEqual(access.group_id, self.group_user)
        self.assertEqual(access.record_type_id, rt)
        self.assertIn(str(rt.id), access.domain)

    def test_permission_update_changes_access_row(self):
        rt = self._type('t2')
        perm = self.env['ir.record.type.permission'].create({
            'record_type_id': rt.id, 'group_id': self.group_user.id, 'perm_read': True,
        })
        access = perm.access_id
        perm.write({'perm_write': True})
        self.assertEqual(perm.access_id, access)
        self.assertEqual(access.operation, 'ru')

    def test_permission_needs_one_operation(self):
        rt = self._type('t3')
        with self.assertRaises(ValidationError):
            self.env['ir.record.type.permission'].create({
                'record_type_id': rt.id, 'group_id': self.group_user.id, 'perm_read': False,
            })

    def test_parent_must_be_same_model(self):
        other = self.env['ir.model']._get('res.partner')
        parent = self.RecordType.create({'name': 'p', 'code': 'p', 'model_id': other.id})
        with self.assertRaises(ValidationError):
            self._type('t4', parent_id=parent.id)

    def test_parent_cycle_rejected(self):
        parent = self._type('p1')
        child = self._type('c1', parent_id=parent.id)
        with self.assertRaises(ValidationError):
            parent.write({'parent_id': child.id})

    def test_default_requires_group_granted(self):
        rt = self._type('t5')
        with self.assertRaises(ValidationError):
            self.env['ir.record.type.default'].create({
                'model_id': self.model.id, 'group_id': self.group_user.id, 'record_type_id': rt.id,
            })
        self.env['ir.record.type.permission'].create({
            'record_type_id': rt.id, 'group_id': self.group_user.id, 'perm_read': True,
        })
        self.env['ir.record.type.default'].create({
            'model_id': self.model.id, 'group_id': self.group_user.id, 'record_type_id': rt.id,
        })

    def test_menu_and_action_generated_and_hidden_without_read(self):
        rt = self._type('t6')
        self.assertTrue(rt.action_id)
        # without any read permission the menu is generated but hidden
        menu = self.env['ir.ui.menu'].with_context(active_test=False).search([('record_type_id', '=', rt.id)])
        self.assertTrue(menu)
        self.assertFalse(menu.active)
        perm = self.env['ir.record.type.permission'].create({
            'record_type_id': rt.id, 'group_id': self.group_portal.id, 'perm_read': True,
        })
        menu = self.env['ir.ui.menu'].search([('record_type_id', '=', rt.id)])
        self.assertTrue(menu.active)
        self.assertIn(self.group_portal, menu.group_ids)
        perm.write({'perm_read': False, 'perm_write': True})
        menu = self.env['ir.ui.menu'].with_context(active_test=False).search([('record_type_id', '=', rt.id)])
        self.assertFalse(menu.active)

    def test_group_grant_on_supporting_model_must_be_scoped(self):
        self.model.supports_record_type = True
        try:
            with self.assertRaises(ValidationError):
                self.env['ir.access'].create({
                    'name': 'unscoped', 'model_id': self.model.id,
                    'group_id': self.group_user.id, 'operation': 'r',
                })
            rt = self._type('t7')
            access = self.env['ir.access'].create({
                'name': 'scoped', 'model_id': self.model.id, 'group_id': self.group_user.id,
                'operation': 'r', 'record_type_id': rt.id,
            })
            self.assertTrue(access)
        finally:
            self.model.supports_record_type = False

    def test_access_row_type_must_match_model(self):
        other = self.env['ir.model']._get('res.partner')
        rt = self._type('t8')
        with self.assertRaises(ValidationError):
            self.env['ir.access'].create({
                'name': 'mismatch', 'model_id': other.id,
                'group_id': self.group_user.id, 'operation': 'r', 'record_type_id': rt.id,
            })


@tagged('post_install', '-at_install')
class TestIrRecordTypeViewsAndDefaults(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = cls.env['ir.model']._get('ir.recordtype.test')
        cls.group_user = cls.env.ref('base.group_user')

    def test_type_form_view_is_used_by_action(self):
        rt = self.env['ir.record.type'].create({'name': 'v', 'code': 'v', 'model_id': self.model.id})
        view = self.env['ir.ui.view'].create({
            'name': 'v form', 'model': 'ir.recordtype.test', 'type': 'form', 'arch': '<form><field name="name"/></form>',
            'record_type_id': rt.id,
        })
        self.assertEqual(view.record_type_id, rt)
        rt.write({'name': 'v2'})
        action_view = self.env['ir.actions.act_window.view'].search([
            ('act_window_id', '=', rt.action_id.id), ('view_mode', '=', 'form'),
        ])
        self.assertEqual(action_view.view_id, view)

    def test_type_view_must_be_form_of_same_model(self):
        rt = self.env['ir.record.type'].create({'name': 'v3', 'code': 'v3', 'model_id': self.model.id})
        with self.assertRaises(ValidationError):
            self.env['ir.ui.view'].create({
                'name': 'list', 'model': 'ir.recordtype.test', 'type': 'list', 'arch': '<list><field name="name"/></list>',
                'record_type_id': rt.id,
            })

    def test_default_for_user_follows_group_default(self):
        RecordType = self.env['ir.record.type']
        first = RecordType.create({'name': 'd1', 'code': 'd1', 'model_id': self.model.id, 'sequence': 5})
        second = RecordType.create({'name': 'd2', 'code': 'd2', 'model_id': self.model.id, 'sequence': 1})
        for rt in (first, second):
            self.env['ir.record.type.permission'].create({
                'record_type_id': rt.id, 'group_id': self.group_user.id, 'perm_read': True, 'perm_create': True,
            })
        user = self.env['res.users'].create({
            'name': 'default user', 'login': 'default_user_rt', 'group_ids': [(6, 0, self.group_user.ids)],
        })
        # no group default: the usable type with the lowest sequence wins
        self.assertEqual(RecordType.with_user(user)._get_default_for_user(self.model.model), second)
        self.env['ir.record.type.default'].create({
            'model_id': self.model.id, 'group_id': self.group_user.id, 'record_type_id': first.id,
        })
        # group default wins over sequence
        self.assertEqual(RecordType.with_user(user)._get_default_for_user(self.model.model), first)
