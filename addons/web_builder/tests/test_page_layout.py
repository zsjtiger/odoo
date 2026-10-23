# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo.tests import tagged

from odoo.addons.web_builder.tests.test_view_editor import TestStudioController


@tagged('post_install', '-at_install')
class TestPageLayout(TestStudioController):
    def _studio_views(self, view):
        return self.env['ir.ui.view'].search([
            ('inherit_id', '=', view.id),
            ('name', '=', 'Odoo Studio: %s customization' % view.name),
        ])

    def test_page_layout_is_stored_as_studio_view(self):
        view = self.env.ref('base.view_partner_form')
        arch = """<data>
                <xpath expr="/form" position="replace">
                    <form string="Partners">
                        <sheet>
                            <group string="Main"><field name="name"/></group>
                        </sheet>
                    </form>
                </xpath>
            </data>"""
        self.assertFalse(self._studio_views(view))

        self.studio_controller.edit_page_layout(view.id, arch)
        studio_view = self._studio_views(view)
        self.assertEqual(len(studio_view), 1)
        self.assertIn('string="Main"', studio_view.arch)

        # Saving again updates the same studio view
        self.studio_controller.edit_page_layout(view.id, arch.replace('Main', 'Other'))
        self.assertEqual(self._studio_views(view), studio_view)
        self.assertIn('string="Other"', studio_view.arch)
