# -*- coding: utf-8 -*-
import base64
import io
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


def _xlsx(tech, rows):
    """A file in the import layout: labels, technical names, then one row per dict."""
    wb = Workbook()
    ws = wb.active
    ws.append([t.upper() for t in tech])
    ws.append(tech)
    for row in rows:
        ws.append([row.get(t) for t in tech])
    out = io.BytesIO()
    wb.save(out)
    return base64.b64encode(out.getvalue()).decode()


@tagged('post_install', '-at_install')
class TestDataImport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = cls.env['ir.model']._get('res.partner')
        cls.Job = cls.env['ir.data.import.job']
        cls.Partner = cls.env['res.partner']

    def _job(self, tech, rows, user=None):
        Job = self.Job.with_user(user) if user else self.Job
        return Job.create({
            'model_id': self.model.id,
            'source_file': _xlsx(tech, rows),
            'source_filename': 'import.xlsx',
        })

    def _result_rows(self, job):
        wb = load_workbook(io.BytesIO(bytes(job.result_file)))
        ws = wb.worksheets[0]
        header = [c.value for c in ws[2]]
        col = header.index('validation_error') + 1
        return {r: ws.cell(row=r, column=col).value for r in range(3, ws.max_row + 1)}

    def test_template_has_action_id_and_fields(self):
        content, filename = self.env['ir.data.import.template']._build_xlsx('res.partner')
        self.assertTrue(filename.endswith('_template.xlsx'))
        wb = load_workbook(io.BytesIO(content))
        techs = [c.value for c in wb.worksheets[0][2]]
        self.assertEqual(techs[0], 'id')
        self.assertEqual(techs[-1], 'action')  # Action is the last column
        self.assertIn('name', techs)
        self.assertNotIn('child_ids', techs)  # one2many is not importable
        self.assertIn('Help', wb.sheetnames)

    def test_validate_does_not_write_then_import_applies_n_u_d(self):
        to_update = self.Partner.create({'name': 'Old name'})
        to_delete = self.Partner.create({'name': 'To delete'})
        job = self._job(['action', 'id', 'name', 'email'], [
            {'action': 'N', 'name': 'New Co', 'email': 'new@example.com'},
            {'action': 'U', 'id': to_update.id, 'name': 'Renamed'},
            {'action': 'D', 'id': to_delete.id},
        ])
        job.action_validate()
        self.assertEqual(job.state, 'validated')
        self.assertEqual(job.error_rows, 0)
        self.assertEqual(job.total_rows, 3)
        # validation must not change the database
        self.assertFalse(self.Partner.search_count([('name', '=', 'New Co')]))
        self.assertEqual(to_update.name, 'Old name')
        self.assertTrue(to_delete.exists())

        job.action_import()
        self.assertEqual(job.state, 'done')
        self.assertEqual((job.created_rows, job.updated_rows, job.deleted_rows), (1, 1, 1))
        self.assertTrue(self.Partner.search_count([('name', '=', 'New Co')]))
        self.assertEqual(to_update.name, 'Renamed')
        self.assertFalse(to_delete.exists())

    def test_errors_are_written_per_row_and_block_import(self):
        job = self._job(['action', 'id', 'name'], [
            {'action': 'N', 'name': 'Good'},
            {'action': 'X', 'name': 'Bad action'},
            {'action': 'U', 'id': 999999, 'name': 'Missing'},
            {'action': 'U', 'name': 'No id'},
        ])
        job.action_validate()
        self.assertEqual(job.error_rows, 3)
        messages = self._result_rows(job)
        self.assertFalse(messages[3])  # the good row has no message
        self.assertIn('Action must be', messages[4])
        self.assertIn('does not exist', messages[5])
        self.assertIn('ID is required', messages[6])
        with self.assertRaises(UserError):
            job.action_import()
        self.assertFalse(self.Partner.search_count([('name', '=', 'Good')]))

    def test_duplicate_id_in_file(self):
        partner = self.Partner.create({'name': 'Dup'})
        job = self._job(['action', 'id', 'name'], [
            {'action': 'U', 'id': partner.id, 'name': 'First'},
            {'action': 'U', 'id': partner.id, 'name': 'Second'},
        ])
        job.action_validate()
        self.assertIn('more than once', self._result_rows(job)[4])

    def test_many2one_boolean_and_selection_conversion(self):
        country = self.env.ref('base.be')
        job = self._job(['action', 'name', 'country_id', 'active'], [
            {'action': 'N', 'name': 'Converted', 'country_id': country.name, 'active': '否'},
        ])
        job.action_validate()
        self.assertEqual(job.error_rows, 0)
        job.action_import()
        partner = self.Partner.with_context(active_test=False).search([('name', '=', 'Converted')])
        self.assertEqual(partner.country_id, country)
        self.assertFalse(partner.active)

    def test_unknown_many2one_is_an_error(self):
        job = self._job(['action', 'name', 'country_id'], [
            {'action': 'N', 'name': 'X', 'country_id': 'Atlantis'},
        ])
        job.action_validate()
        self.assertIn('not found', self._result_rows(job)[3])

    def test_declarative_rule_reports_its_message(self):
        self.env['ir.data.import.rule'].create({
            'name': 'Email required', 'model_id': self.model.id, 'action': 'N',
            'domain': "[('email', '!=', False)]", 'message': 'Email is required',
        })
        job = self._job(['action', 'name', 'email'], [
            {'action': 'N', 'name': 'No mail'},
            {'action': 'N', 'name': 'With mail', 'email': 'ok@example.com'},
        ])
        job.action_validate()
        messages = self._result_rows(job)
        self.assertEqual(messages[3], 'Email is required')
        self.assertFalse(messages[4])

    def test_python_hook_reports_its_message(self):
        def fake_hook(record_self, action, vals, record=None):
            if record and record.name == 'Forbidden':
                raise UserError('Forbidden name')

        with patch.object(type(self.Partner), '_import_validate_row', fake_hook, create=True):
            job = self._job(['action', 'name'], [{'action': 'N', 'name': 'Forbidden'}])
            job.action_validate()
        self.assertEqual(self._result_rows(job)[3], 'Forbidden name')

    def test_invalid_file_is_rejected(self):
        job = self.Job.create({
            'model_id': self.model.id,
            'source_file': base64.b64encode(b'not an excel file').decode(),
        })
        with self.assertRaises(UserError):
            job.action_validate()

    def test_user_without_permission_cannot_import(self):
        user = self.env['res.users'].create({
            'name': 'No import', 'login': 'no_import_user',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        job = self._job(['action', 'name'], [{'action': 'N', 'name': 'Nope'}], user=user)
        with self.assertRaises(AccessError):
            job.with_user(user).action_validate()

    def test_user_with_permission_can_import(self):
        # the model's own access rights still apply: the user must be allowed to create contacts
        user = self.env['res.users'].create({
            'name': 'Importer', 'login': 'importer_user',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('base.group_partner_manager').id])],
        })
        self.env['ir.data.import.permission'].create({
            'model_id': self.model.id, 'group_id': self.env.ref('base.group_user').id,
            'allow_import': True, 'perm_template': True,
        })
        job = self._job(['action', 'name'], [{'action': 'N', 'name': 'Allowed'}], user=user)
        job.with_user(user).action_validate()
        self.assertEqual(job.error_rows, 0, self._result_rows(job))
        job.with_user(user).action_import()
        self.assertEqual(job.state, 'done')
        self.assertTrue(self.Partner.search_count([('name', '=', 'Allowed')]))
