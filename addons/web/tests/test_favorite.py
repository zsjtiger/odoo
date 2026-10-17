import ast

from odoo.tests.common import HttpCase, tagged

@tagged('post_install', '-at_install')
class TestFavorite(HttpCase):
    def test_favorite_management(self):
        self.patch(self.env.registry.get("ir.module.module"), "_order", "sequence desc, id desc")
        module = self.env["ir.module.module"]._get("l10n_fr")
        if not module:
            # the tour browses a non-application module of the Account Charts
            # category, provide it when l10n_fr is not in the addons path
            module = self.env["ir.module.module"].create({
                "name": "l10n_fr",
                "shortdesc": "France - Localizations",
                "category_id": self.env.ref("base.module_category_accounting_localizations_account_charts").id,
            })
        module.sequence = 100000
        # the tour edits a rule of the favorite's domain: keep a filter applied
        # once the "Apps" one is removed, as base_import_module does with its
        # search panel when installed
        action = self.env.ref("base.open_module_tree")
        context = ast.literal_eval(action.context)
        if "searchpanel_default_module_type" not in context:
            action.context = repr({**context, "search_default_not_installed": 1})
        self.start_tour("/odoo/apps", "test_favorite_management", login="admin")
