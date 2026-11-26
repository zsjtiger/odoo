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
