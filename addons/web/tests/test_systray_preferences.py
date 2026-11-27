# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSystrayPreferences(TransactionCase):

    def setUp(self):
        super().setUp()
        self.user = self.env['res.users'].create({
            'name': 'Systray User',
            'login': 'systray_user',
            'group_ids': [(6, 0, self.env.ref('base.group_user').ids)],
        })

    def test_all_items_are_shown_by_default(self):
        user = self.user.with_user(self.user)
        self.assertTrue(user.systray_show_ai)
        self.assertTrue(user.systray_show_messaging)
        self.assertTrue(user.systray_show_activity)
        self.assertTrue(user.systray_show_studio)
        self.assertTrue(user.systray_show_company)

    def test_hiding_and_showing_an_item_updates_the_settings(self):
        self.user.write({'systray_show_ai': False, 'systray_show_activity': False})
        settings = self.env['res.users.settings'].sudo().search([('user_id', '=', self.user.id)])
        self.assertEqual(sorted(settings.hidden_systray_items), ['activity', 'ai'])
        self.assertFalse(self.user.systray_show_ai)
        self.assertFalse(self.user.systray_show_activity)
        self.assertTrue(self.user.systray_show_messaging)

        self.user.write({'systray_show_ai': True})
        self.assertEqual(settings.hidden_systray_items, ['activity'])
        self.assertTrue(self.user.systray_show_ai)

    def test_preferences_are_per_user(self):
        other = self.env['res.users'].create({
            'name': 'Other', 'login': 'systray_other',
            'group_ids': [(6, 0, self.env.ref('base.group_user').ids)],
        })
        self.user.write({'systray_show_company': False})
        self.assertFalse(self.user.systray_show_company)
        self.assertTrue(other.systray_show_company)
