# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMobileCustomField(TransactionCase):
    """ 自定义相关字段: 配置生成手动 related 字段与列表视图, 删除配置时一并清理 """

    def setUp(self):
        super().setUp()
        self.model = self.env['ir.model']._get('res.partner')

    def _config(self, **vals):
        values = {'name': "Company currency", 'model_id': self.model.id, 'path': 'company_id.currency_id.name'}
        values.update(vals)
        return self.env['mobile.custom.field'].create(values)

    def test_creates_related_field_and_list_view(self):
        config = self._config()
        self.assertTrue(config.field_name.startswith('x_mcf_'))
        field = self.env['ir.model.fields'].search([('model', '=', 'res.partner'), ('name', '=', config.field_name)])
        self.assertEqual(len(field), 1)
        self.assertEqual(field.related, 'company_id.currency_id.name')
        self.assertEqual(field.ttype, 'char')
        self.assertEqual(field.state, 'manual')
        self.assertFalse(field.store)
        self.assertTrue(config.view_id)
        self.assertIn(config.field_name, config.view_id.arch_db)

    def test_value_is_read_through_the_path(self):
        partner = self.env['res.partner'].create({'name': "Path partner"})
        config = self._config()
        self.assertEqual(partner.read([config.field_name])[0][config.field_name], partner.company_id.currency_id.name)

    def test_invalid_paths_are_rejected(self):
        with self.assertRaises(ValidationError):
            self._config(path='company_id.nope')
        with self.assertRaises(ValidationError):
            self._config(path='name.upper')
        with self.assertRaises(ValidationError):
            self._config(path='')

    def test_unlink_removes_the_generated_field_and_view(self):
        config = self._config()
        field_name, view = config.field_name, config.view_id
        config.unlink()
        self.assertFalse(self.env['ir.model.fields'].search_count([('model', '=', 'res.partner'), ('name', '=', field_name)]))
        self.assertFalse(view.exists())

    def test_no_list_view_means_no_view_is_created(self):
        config = self._config(list_view=False)
        self.assertFalse(config.view_id)
        self.assertTrue(config.field_id)

    def test_changing_the_path_regenerates_the_field(self):
        config = self._config()
        old_view = config.view_id
        config.path = 'company_id.name'
        self.assertEqual(config.field_id.related, 'company_id.name')
        self.assertEqual(config.field_id.ttype, 'char')
        self.assertFalse(old_view.exists())
        self.assertTrue(config.view_id)
