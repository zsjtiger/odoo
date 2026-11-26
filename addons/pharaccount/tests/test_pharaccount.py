# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPharaccount(TransactionCase):

    def setUp(self):
        super().setUp()
        self.RecordType = self.env['pharaccount.record.type']
        self.Picklist = self.env['pharaccount.picklist.value']
        self.group_a = self.env['res.groups'].create({'name': 'Pharma test group A'})
        self.group_b = self.env['res.groups'].create({'name': 'Pharma test group B'})

    def _ir_type(self, code, groups=()):
        """A framework record type on pharaccount.account, readable/writable by the given groups."""
        model = self.env['ir.model']._get('pharaccount.account')
        record_type = self.env['ir.record.type'].create({'name': code, 'code': code, 'model_id': model.id})
        for group in groups:
            self.env['ir.record.type.permission'].create({
                'record_type_id': record_type.id, 'group_id': group.id,
                'perm_read': True, 'perm_write': True, 'perm_create': True,
            })
        return record_type

    def _user(self, groups, login):
        return self.env['res.users'].create({
            'name': login,
            'login': login,
            'group_ids': [(6, 0, [self.env.ref('pharaccount.group_user').id] + [g.id for g in groups])],
        })

    def test_child_inherits_parent_groups_as_union(self):
        parent = self.RecordType.create({'name': 'parent_t', 'label': 'Parent', 'group_ids': [(6, 0, [self.group_a.id])]})
        child = self.RecordType.create({'name': 'child_t', 'label': 'Child', 'parent_id': parent.id,
                                        'group_ids': [(6, 0, [self.group_b.id])]})
        self.assertEqual(child.allowed_group_ids, self.group_a | self.group_b)
        self.assertEqual(parent.allowed_group_ids, self.group_a)

    def test_parent_change_propagates_to_children(self):
        parent = self.RecordType.create({'name': 'parent_p', 'label': 'Parent'})
        child = self.RecordType.create({'name': 'child_p', 'label': 'Child', 'parent_id': parent.id})
        parent.group_ids = [(4, self.group_a.id)]
        self.assertIn(self.group_a, child.allowed_group_ids)

    def test_cycle_is_rejected(self):
        parent = self.RecordType.create({'name': 'parent_c', 'label': 'Parent'})
        child = self.RecordType.create({'name': 'child_c', 'label': 'Child', 'parent_id': parent.id})
        with self.assertRaises(ValidationError):
            parent.parent_id = child

    def test_picklist_value_visible_only_to_allowed_groups(self):
        picklist = self.env['pharaccount.picklist'].create({'name': 'test_level', 'label': 'Test level'})
        open_value = self.Picklist.create({'picklist_id': picklist.id, 'name': 'O', 'label': 'Open'})
        restricted = self.Picklist.create({'picklist_id': picklist.id, 'name': 'R', 'label': 'Restricted',
                                           'group_ids': [(6, 0, [self.group_a.id])]})
        outsider = self._user([self.group_b], 'pharma_outsider')
        insider = self._user([self.group_a], 'pharma_insider')
        seen_outsider = self.Picklist.with_user(outsider).get_selectable('test_level')
        seen_insider = self.Picklist.with_user(insider).get_selectable('test_level')
        self.assertEqual(seen_outsider, open_value)
        self.assertEqual(seen_insider, open_value | restricted)

    def test_record_type_limits_picklist_values(self):
        picklist = self.env['pharaccount.picklist'].create({'name': 'test_limit', 'label': 'Test limit'})
        first = self.Picklist.create({'picklist_id': picklist.id, 'name': 'X', 'label': 'X'})
        second = self.Picklist.create({'picklist_id': picklist.id, 'name': 'Y', 'label': 'Y'})
        record_type = self.RecordType.create({'name': 'limited_t', 'label': 'Limited',
                                              'picklist_value_ids': [(6, 0, [first.id])]})
        self.assertEqual(self.Picklist.get_selectable('test_limit', record_type), first)
        self.assertEqual(self.Picklist.get_selectable('test_limit'), first | second)

    def test_account_hidden_when_record_type_not_allowed_for_user(self):
        restricted_group = self.group_a
        record_type = self._ir_type('rule_t', [restricted_group])
        account = self.env['pharaccount.account'].create({'name': 'Rule pharmacy', 'record_type_id': record_type.id})
        outsider = self._user([self.group_b], 'pharma_rule_outsider')
        insider = self._user([restricted_group], 'pharma_rule_insider')
        # no grant matches the outsider: the framework answers with an access error, not an empty result
        with self.assertRaises(AccessError):
            self.env['pharaccount.account'].with_user(outsider).search([('id', '=', account.id)])
        self.assertEqual(self.env['pharaccount.account'].with_user(insider).search([('id', '=', account.id)]), account)

    def test_account_hidden_when_record_type_has_no_groups(self):
        # a type without any permission is invisible to non-admin users
        record_type = self._ir_type('open_t')
        account = self.env['pharaccount.account'].create({'name': 'Open pharmacy', 'record_type_id': record_type.id})
        outsider = self._user([self.group_b], 'pharma_open_outsider')
        with self.assertRaises(AccessError):
            self.env['pharaccount.account'].with_user(outsider).search([('id', '=', account.id)])

    def test_pc_and_mobile_views_load(self):
        # Every PC and mobile view must load for its model (validates fields and arch).
        expected = {
            'pharaccount.account': [
                ('pharaccount.view_pharaccount_account_list', 'list'),
                ('pharaccount.view_pharaccount_account_form', 'form'),
                ('pharaccount.view_pharaccount_account_form_mobile', 'form'),
                ('pharaccount.view_pharaccount_account_kanban_mobile', 'kanban'),
                ('pharaccount.view_pharaccount_account_search', 'search'),
            ],
            'pharaccount.record.type': [
                ('pharaccount.view_pharaccount_record_type_list', 'list'),
                ('pharaccount.view_pharaccount_record_type_form', 'form'),
                ('pharaccount.view_pharaccount_record_type_kanban_mobile', 'kanban'),
            ],
            'pharaccount.picklist': [
                ('pharaccount.view_pharaccount_picklist_list', 'list'),
                ('pharaccount.view_pharaccount_picklist_form', 'form'),
                ('pharaccount.view_pharaccount_picklist_kanban_mobile', 'kanban'),
            ],
            'pharaccount.account.state': [
                ('pharaccount.view_pharaccount_account_state_list', 'list'),
                ('pharaccount.view_pharaccount_account_state_form', 'form'),
                ('pharaccount.view_pharaccount_account_state_kanban_mobile', 'kanban'),
            ],
        }
        for model, views in expected.items():
            for xmlid, view_type in views:
                view = self.env.ref(xmlid)
                self.assertEqual(view.model, model)
                self.assertEqual(view.type, view_type)
                self.env[model].with_context(lang='en_US').get_views([(view.id, view_type)])

    def test_mobile_actions_use_kanban_and_simplified_form(self):
        action = self.env.ref('pharaccount.action_pharaccount_account_mobile')
        self.assertEqual(action.view_mode, 'kanban,form')
        mapped = {v.view_mode: v.view_id for v in action.view_ids}
        self.assertEqual(mapped['kanban'], self.env.ref('pharaccount.view_pharaccount_account_kanban_mobile'))
        self.assertEqual(mapped['form'], self.env.ref('pharaccount.view_pharaccount_account_form_mobile'))
        self.assertEqual(self.env.ref('pharaccount.action_pharaccount_account').view_mode, 'list,form')

    def test_account_extended_fields(self):
        record_type = self._ir_type('ext_t')
        state = self.env['pharaccount.account.state'].create({'name': 'ext_state', 'label': 'Ext state'})
        account = self.env['pharaccount.account'].create({
            'name': 'Extended pharmacy',
            'record_type_id': record_type.id,
            'state_id': state.id,
            'geo_province': 'Beijing',
            'geo_city': 'Beijing',
            'geo_district': 'Chaoyang',
            'sales': 1200.5,
            'is_important': True,
        })
        self.assertTrue(account.creation_time)
        self.assertEqual(account.state_id, state)
        self.assertEqual(account.geo_district, 'Chaoyang')
        self.assertTrue(account.is_important)
        self.assertFalse(account.is_public)

    def test_widget_options_follow_record_type(self):
        picklist = self.env['pharaccount.picklist'].create({'name': 'test_widget', 'label': 'Widget'})
        first = self.Picklist.create({'picklist_id': picklist.id, 'name': 'W1', 'label': 'W1', 'sequence': 1})
        second = self.Picklist.create({'picklist_id': picklist.id, 'name': 'W2', 'label': 'W2', 'sequence': 2})
        legacy = self.RecordType.create({'name': 'widget_t', 'label': 'Widget type',
                                         'picklist_value_ids': [(6, 0, [second.id])]})
        limited = self._ir_type('widget_t')
        legacy.ir_record_type_id = limited
        self.assertEqual(
            [o['id'] for o in self.Picklist.get_widget_options('test_widget')],
            [first.id, second.id],
        )
        self.assertEqual(
            [o['id'] for o in self.Picklist.get_widget_options('test_widget', limited.id)],
            [second.id],
        )

    def test_child_tables_cascade_with_pharmacy(self):
        record_type = self._ir_type('child_t')
        Account = self.env['pharaccount.account']
        pharmacy = Account.create({'name': 'Parent pharmacy', 'record_type_id': record_type.id})
        staff = self.env['pharaccount.pharmacy.staff'].create({'name': 'Zhang', 'pharmacy_id': pharmacy.id})
        link = self.env['pharaccount.hospital.link'].create({
            'pharmacy_id': pharmacy.id,
            'hospital_id': Account.create({'name': 'Hospital', 'record_type_id': record_type.id}).id,
            'package': 'P1',
        })
        inventory = self.env['pharaccount.package.inventory'].create({'pharmacy_id': pharmacy.id, 'stock': 5})
        competitor = self.env['pharaccount.competitive.product'].create({
            'pharmacy_id': pharmacy.id, 'product': 'Ours', 'competitive_product': 'Theirs',
        })
        self.assertEqual(pharmacy.staff_ids, staff)
        self.assertEqual(pharmacy.hospital_link_ids, link)
        self.assertEqual(pharmacy.package_inventory_ids, inventory)
        self.assertEqual(pharmacy.competitive_product_ids, competitor)
        children = {
            'pharaccount.pharmacy.staff': staff.id,
            'pharaccount.hospital.link': link.id,
            'pharaccount.package.inventory': inventory.id,
            'pharaccount.competitive.product': competitor.id,
        }
        pharmacy.unlink()
        for model, record_id in children.items():
            self.assertFalse(self.env[model].browse(record_id).exists(), model)

    def test_child_rows_follow_record_type_permission(self):
        restricted_group = self.group_a
        record_type = self._ir_type('child_rule_t', [restricted_group])
        pharmacy = self.env['pharaccount.account'].create({'name': 'Hidden pharmacy',
                                                           'record_type_id': record_type.id})
        staff = self.env['pharaccount.pharmacy.staff'].create({'name': 'Li', 'pharmacy_id': pharmacy.id})
        outsider = self._user([self.group_b], 'pharma_child_outsider')
        insider = self._user([restricted_group], 'pharma_child_insider')
        Staff = self.env['pharaccount.pharmacy.staff']
        self.assertFalse(Staff.with_user(outsider).search([('id', '=', staff.id)]))
        self.assertEqual(Staff.with_user(insider).search([('id', '=', staff.id)]), staff)
