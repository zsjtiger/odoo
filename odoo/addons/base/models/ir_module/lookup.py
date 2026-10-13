# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The lookups of the modules: the checks, the records and the installed modules."""

from collections import OrderedDict
from odoo.fields import Domain

from .module import IrModuleModule, _logger

def _check(self):
    for module in self:
        if not module.description_html:
            _logger.warning('module %s: description is empty!', module.name)


def _get(self, name):
    """ Return the (sudoed) `ir.module.module` record with the given name.
        The result may be an empty recordset if the module is not found.
        """
    model_id = self._get_id(name) if name else False
    return self.browse(model_id).sudo()


def _get_id(self, name):
    self.flush_model(['name'])
    self.env.cr.execute("SELECT id FROM ir_module_module WHERE name=%s", (name,))
    result = self.env.cr.fetchone()
    return result and result[0]


def _installed(self):
    """ Return the set of installed modules as a dictionary {name: id} """
    return {
        module.name: module.id
        for module in self.sudo().search([('state', '=', 'installed')])
    }


def search_panel_select_range(self, field_name, **kwargs):
    if field_name == 'category_id':
        enable_counters = kwargs.get('enable_counters', False)
        domain = Domain([
            ('parent_id', '=', False),
            '|',
            ('module_ids.application', '!=', False),
            ('child_ids.module_ids', '!=', False),
        ])

        excluded_xmlids = [
            'base.module_category_website_theme',
            'base.module_category_theme',
        ]
        if not self.env.user.has_group('base.group_no_one'):
            excluded_xmlids.append('base.module_category_hidden')

        excluded_category_ids = []
        for excluded_xmlid in excluded_xmlids:
            categ = self.env.ref(excluded_xmlid, False)
            if not categ:
                continue
            excluded_category_ids.append(categ.id)

        if excluded_category_ids:
            domain &= Domain('id', 'not in', excluded_category_ids)

        records = self.env['ir.module.category'].search_read(domain, ['display_name'], order="sequence")

        values_range = OrderedDict()
        for record in records:
            record_id = record['id']
            if enable_counters:
                model_domain = Domain.AND([
                    kwargs.get('search_domain', []),
                    kwargs.get('category_domain', []),
                    kwargs.get('filter_domain', []),
                    [('category_id', 'child_of', record_id), ('category_id', 'not in', excluded_category_ids)]
                ])
                record['__count'] = self.env['ir.module.module'].search_count(model_domain)
            values_range[record_id] = record

        return {
            'parent_field': 'parent_id',
            'values': list(values_range.values()),
        }

    return super(IrModuleModule, self).search_panel_select_range(field_name, **kwargs)
