# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The update of the modules from their manifests: the values, the dependencies, the countries, the exclusions, the categories and the translations."""

from textwrap import dedent
from odoo import modules
from odoo.tools.misc import topological_sort
from odoo.tools.parse_version import parse_version

from .module import IrModuleModule, _logger

def get_values_from_terp(terp):
    return {
        'description': dedent(terp.get('description', '')),
        'shortdesc': terp.get('name', ''),
        'author': terp.get('author', 'Unknown'),
        'maintainer': terp.get('maintainer', False),
        'contributors': ', '.join(terp.get('contributors', [])) or False,
        'website': terp.get('website', ''),
        'license': terp.get('license', 'LGPL-3'),
        'sequence': terp.get('sequence', 100),
        'application': terp.get('application', False),
        'auto_install': terp.get('auto_install', False) is not False,
        'icon': terp.get('icon', False),
        'summary': terp.get('summary', ''),
        'url': terp.get('url') or terp.get('live_test_url', ''),
        'to_buy': False,
        'iap_paid_service': terp.get('iap_paid_service', False),
    }


def create(self, vals_list):
    modules = super(IrModuleModule, self).create(vals_list)
    module_metadata_list = [{
        'name': 'module_%s' % module.name,
        'model': 'ir.module.module',
        'module': 'base',
        'res_id': module.id,
        'noupdate': True,
    } for module in modules]
    self.env['ir.model.data'].create(module_metadata_list)
    return modules


def update_list(self):
    res = [0, 0]    # [update, add]

    default_version = modules.adapt_version('1.0')
    known_mods = self.with_context(lang=None, module_memo_category={}, module_memo_country={}).search([])
    known_mods_names = {mod.name: mod for mod in known_mods}

    # iterate through detected modules and update/create them in db
    for manifest in modules.Manifest.all_addon_manifests():
        mod = known_mods_names.get(manifest.name)
        terp = self.get_module_info(manifest)
        values = self.get_values_from_terp(terp)

        if mod:
            updated_values = {}
            for key in values:
                old = getattr(mod, key)
                if (old or values[key]) and values[key] != old:
                    updated_values[key] = values[key]
            if terp.get('installable', True) and mod.state == 'uninstallable':
                updated_values['state'] = 'uninstalled'
            if parse_version(terp.get('version', default_version)) > parse_version(mod.latest_version or default_version):
                res[0] += 1
            if updated_values:
                mod.write(updated_values)
        elif not manifest or not terp:
            continue
        else:
            state = "uninstalled" if terp.get('installable', True) else "uninstallable"
            mod = self.create(dict(name=manifest.name, state=state, **values))
            res[1] += 1

        mod._update_from_terp(terp)

    return res


def _update_from_terp(self, terp):
    self._update_dependencies(terp.get('depends', []), terp.get('auto_install'))
    self._update_countries(terp.get('countries', []))
    self._update_exclusions(terp.get('excludes', []))
    self._update_category(terp.get('category', 'Uncategorized'))


def _update_dependencies(self, depends=None, auto_install_requirements=()):
    self.ensure_one()
    deps = self.dependencies_id
    existing = {dep.name for dep in deps}
    needed = set(depends or [])
    to_delete = []
    auto_install_requirements = set(auto_install_requirements or ())
    for dep in deps:
        if dep.name not in needed:
            to_delete.append(dep.id)
        else:
            dep.auto_install_required = dep.name in auto_install_requirements
    if to_create := needed - existing:
        deps.create([{'module_id': self.id, 'name': name, 'auto_install_required': name in auto_install_requirements} for name in to_create])
    if to_delete:
        deps.browse(to_delete).unlink()


def _update_countries(self, countries=()):
    self.ensure_one()
    self.country_ids  # put countries in cache (otherwise they are read one by one when writing)
    if (cache := self.env.context.get('module_memo_country')) is not None:
        if not cache:
            cache.update({c.code: c.id for c in self.env['res.country'].search([])})
        country_recs = self.env['res.country'].browse(c_id for c in countries if (c_id := cache.get(c.upper())))
    else:
        country_recs = self.env['res.country'].search([('code', 'in', [c.upper() for c in countries])])
    self.country_ids = country_recs
    self.env['res.company'].invalidate_model(['uninstalled_l10n_module_ids'])


def _update_exclusions(self, excludes=None):
    self.ensure_one()
    exclusions = self.exclusion_ids
    existing = {excl.name for excl in exclusions}
    needed = set(excludes or [])
    if to_create := needed - existing:
        exclusions.create([{'module_id': self.id, 'name': name} for name in to_create])
    exclusions.filtered(lambda e: e.name not in needed).unlink()


def _update_category(self, category='Uncategorized'):
    self.ensure_one()
    current_category = self.category_id
    seen = set()
    current_category_path = []
    while current_category:
        current_category_path.insert(0, current_category.name)
        seen.add(current_category.id)
        if current_category.parent_id.id in seen:
            current_category.parent_id = False
            _logger.warning('category %r ancestry loop has been detected and fixed', current_category)
        current_category = current_category.parent_id

    categs = category.split('/')
    if categs != current_category_path:
        cat_id = modules.db.create_categories(self.env.cr, categs, self.env.context.get('module_memo_category'))
        self.write({'category_id': cat_id})


def _update_translations(self, filter_lang=None, overwrite=False):
    if not filter_lang:
        langs = self.env['res.lang'].get_installed()
        filter_lang = [code for code, _ in langs]
    elif not isinstance(filter_lang, (list, tuple)):
        filter_lang = [filter_lang]

    update_mods = self.filtered(lambda r: r.state in ('installed', 'to install', 'to upgrade'))
    mod_dict = {
        mod.name: mod.dependencies_id.mapped('name')
        for mod in update_mods
    }
    mod_names = topological_sort(mod_dict)
    self.env['ir.module.module']._load_module_terms(mod_names, filter_lang, overwrite)
