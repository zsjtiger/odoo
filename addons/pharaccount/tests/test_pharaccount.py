# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


def load_workbook_bytes(result_file):
    """All text of the first sheet of a result file, joined (for simple assertions)."""
    import io
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(bytes(result_file))).worksheets[0]
    return ' '.join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)

@tagged('post_install', '-at_install')
class TestPharaccount(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Picklist = self.env['pharaccount.picklist.value']
        self.group_a = self.env['res.groups'].create({'name': 'Pharma test group A'})
        self.group_b = self.env['res.groups'].create({'name': 'Pharma test group B'})

    def _ir_type(self, code, groups=(), picklist=None, parent=None):
        """A framework record type on pharaccount.account, usable by the given groups."""
        model = self.env['ir.model']._get('pharaccount.account')
        vals = {'name': code, 'code': code, 'model_id': model.id, 'parent_id': parent and parent.id}
        if picklist is not None:
            vals['picklist_value_ids'] = [(6, 0, picklist.ids)]
        record_type = self.env['ir.record.type'].create(vals)
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

    def _picklist(self, name):
        return self.env['pharaccount.picklist'].create({'name': name, 'label': name})

    def test_picklist_value_visible_only_to_allowed_groups(self):
        picklist = self._picklist('test_level')
        open_value = self.Picklist.create({'picklist_id': picklist.id, 'name': 'O', 'label': 'Open'})
        restricted = self.Picklist.create({'picklist_id': picklist.id, 'name': 'R', 'label': 'Restricted',
                                           'group_ids': [(6, 0, [self.group_a.id])]})
        outsider = self._user([self.group_b], 'pharma_outsider')
        insider = self._user([self.group_a], 'pharma_insider')
        self.assertEqual(self.Picklist.with_user(outsider).get_selectable('test_level'), open_value)
        self.assertEqual(self.Picklist.with_user(insider).get_selectable('test_level'), open_value | restricted)

    def test_record_type_limits_picklist_values(self):
        picklist = self._picklist('test_limit')
        first = self.Picklist.create({'picklist_id': picklist.id, 'name': 'X', 'label': 'X'})
        second = self.Picklist.create({'picklist_id': picklist.id, 'name': 'Y', 'label': 'Y'})
        record_type = self._ir_type('limited_t', picklist=first)
        self.assertEqual(self.Picklist.get_selectable('test_limit', record_type), first)
        self.assertEqual(self.Picklist.get_selectable('test_limit'), first | second)

    def test_child_type_adds_parent_picklist_values(self):
        picklist = self._picklist('test_union')
        first = self.Picklist.create({'picklist_id': picklist.id, 'name': 'P1', 'label': 'P1'})
        second = self.Picklist.create({'picklist_id': picklist.id, 'name': 'P2', 'label': 'P2'})
        parent = self._ir_type('parent_union', picklist=first)
        child = self._ir_type('child_union', picklist=second, parent=parent)
        self.assertEqual(child.allowed_picklist_value_ids, first | second)
        self.assertEqual(parent.allowed_picklist_value_ids, first)
        parent.picklist_value_ids = [(6, 0, [first.id, second.id])]
        self.assertEqual(child.allowed_picklist_value_ids, first | second)

    def test_account_hidden_when_record_type_not_allowed_for_user(self):
        record_type = self._ir_type('rule_t', [self.group_a])
        account = self.env['pharaccount.account'].create({'name': 'Rule pharmacy', 'record_type_id': record_type.id})
        outsider = self._user([self.group_b], 'pharma_rule_outsider')
        insider = self._user([self.group_a], 'pharma_rule_insider')
        # the outsider's groups match no type of this account: nothing is returned
        self.assertFalse(self.env['pharaccount.account'].with_user(outsider).search([('id', '=', account.id)]))
        self.assertEqual(self.env['pharaccount.account'].with_user(insider).search([('id', '=', account.id)]), account)

    def test_account_hidden_when_record_type_has_no_groups(self):
        # a type without any permission is invisible to non-admin users
        record_type = self._ir_type('open_t')
        account = self.env['pharaccount.account'].create({'name': 'Open pharmacy', 'record_type_id': record_type.id})
        outsider = self._user([self.group_b], 'pharma_open_outsider')
        self.assertFalse(self.env['pharaccount.account'].with_user(outsider).search([('id', '=', account.id)]))

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
        picklist = self._picklist('test_widget')
        first = self.Picklist.create({'picklist_id': picklist.id, 'name': 'W1', 'label': 'W1', 'sequence': 1})
        second = self.Picklist.create({'picklist_id': picklist.id, 'name': 'W2', 'label': 'W2', 'sequence': 2})
        limited = self._ir_type('widget_t', picklist=second)
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
        record_type = self._ir_type('child_rule_t', [self.group_a])
        pharmacy = self.env['pharaccount.account'].create({'name': 'Hidden pharmacy',
                                                           'record_type_id': record_type.id})
        staff = self.env['pharaccount.pharmacy.staff'].create({'name': 'Li', 'pharmacy_id': pharmacy.id})
        outsider = self._user([self.group_b], 'pharma_child_outsider')
        insider = self._user([self.group_a], 'pharma_child_insider')
        Staff = self.env['pharaccount.pharmacy.staff']
        # child rows are filtered through the pharmacy's type, so the outsider just gets nothing
        self.assertFalse(Staff.with_user(outsider).search([('id', '=', staff.id)]))
        self.assertEqual(Staff.with_user(insider).search([('id', '=', staff.id)]), staff)

    def test_new_dcr_action_copies_pharmacy_info(self):
        pharmacy = self.env['pharaccount.account'].create({
            'name': 'DCR Pharmacy', 'telephone': '0100', 'mobile': '13800000000',
            'geo_city': 'Beijing', 'is_important': True,
        })
        action = pharmacy.action_new_dcr()
        self.assertEqual(action['res_model'], 'pharaccount.dcr')
        self.assertEqual(action['view_mode'], 'form')
        defaults = self.env['pharaccount.dcr'].with_context(action['context']).default_get(
            ['name', 'pharmacy_id', 'telephone', 'mobile', 'geo_city', 'is_important'])
        self.assertEqual(defaults['name'], 'DCR Pharmacy')
        self.assertEqual(defaults['pharmacy_id'], pharmacy.id)
        self.assertEqual(defaults['telephone'], '0100')
        self.assertEqual(defaults['mobile'], '13800000000')
        self.assertEqual(defaults['geo_city'], 'Beijing')
        self.assertTrue(defaults['is_important'])

    def test_import_creates_pharmacies_with_record_type(self):
        Job = self.env['ir.data.import.job']
        model = self.env['ir.model']._get('pharaccount.account')
        content = self._xlsx_bytes(['action', 'name', 'record_type', 'telephone'], [
            {'action': 'N', 'name': 'Imported Hospital', 'record_type': 'hospital', 'telephone': '010-1'},
            {'action': 'N', 'name': 'Imported Pharma', 'record_type': 'pharma'},
            {'action': 'N', 'name': 'Bad type', 'record_type': 'no_such_type'},
        ])
        job = Job.create({'model_id': model.id, 'source_file': content, 'source_filename': 'pa.xlsx'})
        job.action_validate()
        self.assertEqual(job.error_rows, 1)
        with self.assertRaises(UserError):
            job.action_import()
        # without the bad row the import goes through
        content = self._xlsx_bytes(['action', 'name', 'record_type', 'telephone'], [
            {'action': 'N', 'name': 'Imported Hospital', 'record_type': 'hospital', 'telephone': '010-1'},
            {'action': 'N', 'name': 'Imported Pharma', 'record_type': 'pharma'},
        ])
        job = Job.create({'model_id': model.id, 'source_file': content, 'source_filename': 'pa.xlsx'})
        job.action_validate()
        job.action_import()
        self.assertEqual(job.state, 'done')
        hospital = self.env['pharaccount.account'].search([('name', '=', 'Imported Hospital')])
        self.assertEqual(hospital.record_type_id.code, 'hospital')
        self.assertEqual(hospital.telephone, '010-1')

    def test_import_button_opens_wizard(self):
        account = self.env['pharaccount.account'].create({'name': 'Button check'})
        action = account.action_open_data_import()
        self.assertEqual(action['res_model'], 'ir.data.import.wizard')
        self.assertEqual(action['context']['default_model_id'], self.env['ir.model']._get('pharaccount.account').id)

    @staticmethod
    def _xlsx_bytes(tech, rows):
        import base64
        import io
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append([t.upper() for t in tech])
        ws.append(tech)
        for row in rows:
            ws.append([row.get(t) for t in tech])
        out = io.BytesIO()
        wb.save(out)
        return base64.b64encode(out.getvalue()).decode()

    def test_import_record_type_support(self):
        import io
        from openpyxl import load_workbook
        Account = self.env['pharaccount.account']
        hospital = self.env['ir.record.type'].search([('code', '=', 'hospital')])
        model = self.env['ir.model']._get('pharaccount.account')

        # the template of a record type: its code in the Help sheet and in the record type dropdown
        content, filename = self.env['ir.data.import.template']._build_xlsx('pharaccount.account', hospital)
        self.assertIn('hospital', filename)
        wb = load_workbook(io.BytesIO(content))
        help_values = [c.value for row in wb['Help'].iter_rows() for c in row]
        self.assertIn('hospital', help_values)
        formulas = [dv.formula1 for dv in wb.worksheets[0].data_validations.dataValidation]
        self.assertTrue(any('hospital' in (f or '') for f in formulas))

        # the wizard's record type is the default for new rows that name no type
        wizard = self.env['ir.data.import.wizard'].create({
            'model_id': model.id, 'record_type_id': hospital.id,
            'file': self._xlsx_bytes(['action', 'name'], [{'action': 'N', 'name': 'Default typed'}]),
            'filename': 'typed.xlsx',
        })
        wizard.action_validate()
        self.assertEqual(wizard.job_id.record_type_id, hospital)
        wizard.action_import()
        self.assertEqual(Account.search([('name', '=', 'Default typed')]).record_type_id, hospital)

    def test_delete_needs_unlink_on_record_type(self):
        hospital = self.env['ir.record.type'].search([('code', '=', 'hospital')])
        model = self.env['ir.model']._get('pharaccount.account')
        record = self.env['pharaccount.account'].create({'name': 'Protected', 'record_type_id': hospital.id})
        # the pharmacy user may read, write and create hospitals, but not delete them
        user = self.env['res.users'].create({
            'name': 'Pharmacy user', 'login': 'pharmacy_import_user',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('pharaccount.group_user').id])],
        })
        job = self.env['ir.data.import.job'].with_user(user).create({
            'model_id': model.id,
            'source_file': self._xlsx_bytes(['action', 'id'], [{'action': 'D', 'id': record.id}]),
        })
        job.with_user(user).action_validate()
        self.assertEqual(job.error_rows, 1)
        wb = load_workbook_bytes(job.result_file)
        self.assertIn('not allowed to unlink', wb)
        self.assertTrue(record.exists())

    def test_pharmacy_user_can_download_template_and_import(self):
        user = self.env['res.users'].create({
            'name': 'Pharmacy staff', 'login': 'pharmacy_staff_perm',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('pharaccount.group_user').id])],
        })
        model = self.env['ir.model']._get('pharaccount.account')
        wizard = self.env['ir.data.import.wizard'].with_user(user).create({'model_id': model.id})
        action = wizard.action_download_template()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        # the configured template requires the name: a new row without one is an error
        job = self.env['ir.data.import.job'].with_user(user).create({
            'model_id': model.id,
            'source_file': self._xlsx_bytes(['action', 'telephone'], [{'action': 'N', 'telephone': '010-9'}]),
        })
        job.with_user(user).action_validate()
        self.assertEqual(job.error_rows, 1)
        self.assertIn('is required', load_workbook_bytes(job.result_file))

    def test_allow_import_on_record_type_and_group(self):
        hospital = self.env['ir.record.type'].search([('code', '=', 'hospital')])
        model = self.env['ir.model']._get('pharaccount.account')
        Job = self.env['ir.data.import.job']
        content = self._xlsx_bytes(['action', 'name', 'record_type'], [
            {'action': 'N', 'name': 'Switch row', 'record_type': 'hospital'},
        ])
        # the type switch closes the type for everyone (the administrator included)
        hospital.allow_import = False
        job = Job.create({'model_id': model.id, 'source_file': content})
        job.action_validate()
        self.assertEqual(job.error_rows, 1)
        self.assertIn('does not allow import', load_workbook_bytes(job.result_file))
        hospital.allow_import = True

        # a group switch closes the type for that group only
        user = self.env['res.users'].create({
            'name': 'Switch user', 'login': 'switch_import_user',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('pharaccount.group_user').id])],
        })
        perm = self.env['ir.record.type.permission'].search([
            ('record_type_id', '=', hospital.id), ('group_id', '=', self.env.ref('pharaccount.group_user').id),
        ])
        self.assertTrue(perm.allow_import)  # new permission rows allow import by default
        perm.allow_import = False
        job = Job.with_user(user).create({'model_id': model.id, 'source_file': content})
        job.with_user(user).action_validate()
        self.assertEqual(job.error_rows, 1)
        self.assertIn('not allowed to import records of type', load_workbook_bytes(job.result_file))
        perm.allow_import = True
        job = Job.with_user(user).create({'model_id': model.id, 'source_file': content})
        job.with_user(user).action_validate()
        self.assertEqual(job.error_rows, 0)

