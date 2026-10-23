# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The information of the modules: the descriptions, the versions, the views and the icons."""

import os
from collections import defaultdict
import lxml.html
from docutils.core import publish_string
from markupsafe import Markup
from odoo import modules, tools
from odoo.modules.module import Manifest
from odoo.tools import BinaryBytes
from odoo.tools.business_data import get_flag
from odoo.tools.misc import file_open
from .rst import MyWriter

from .module import _logger

def get_module_info(cls, name):
    if isinstance(name, str):
        # we have no info for studio_customization
        # imported modules are not found using this method
        return modules.Manifest.for_addon(name, display_warning=False) or {}
    if isinstance(name, modules.Manifest):
        return name
    return {}


def _get_desc(self):
    def _apply_description_images(doc):
        html = lxml.html.document_fromstring(doc)
        for element, _attribute, _link, _pos in html.iterlinks():
            if element.get('src') and not '//' in element.get('src') and not 'static/' in element.get('src'):
                element.set('src', "/%s/static/description/%s" % (module.name, element.get('src')))
        return tools.html_sanitize(lxml.html.tostring(html, encoding='unicode'))

    for module in self:
        if not module.name:
            module.description_html = False
            continue
        path = os.path.join(module.name, 'static/description/index.html')
        try:
            with tools.file_open(path) as desc_file:
                doc = desc_file.read()
                module.description_html = _apply_description_images(doc)
        except FileNotFoundError:
            overrides = {
                'embed_stylesheet': False,
                'doctitle_xform': False,
                'output_encoding': 'unicode',
                'xml_declaration': False,
                'file_insertion_enabled': False,
            }
            raw_description = module.description or ''

            try:
                output = publish_string(source=raw_description, source_path=module.name, settings_overrides=overrides, writer=MyWriter())
            except Exception as e:  # noqa: BLE001
                _logger.warning("Failed to render module description for %s: %s. Falling back to raw description.", module.name, e)
                output = Markup('<pre><code>%s</code></pre>') % raw_description

            module.description_html = _apply_description_images(output)


def _get_latest_version(self):
    default_version = modules.adapt_version('1.0')
    for module in self:
        module.installed_version = self.get_module_info(module.name).get('version', default_version)


def _get_views(self):
    IrModelData = self.env['ir.model.data'].with_context(active_test=True)
    dmodels = ['ir.ui.view', 'ir.actions.report', 'ir.ui.menu']

    for module in self:
        # Skip uninstalled modules below, no data to find anyway.
        if module.state not in ('installed', 'to upgrade', 'to remove'):
            module.views_by_module = ""
            module.reports_by_module = ""
            module.menus_by_module = ""
            continue

        # then, search and group ir.model.data records
        imd_models = defaultdict(list)
        imd_domain = [('module', '=', module.name), ('model', 'in', tuple(dmodels)), ('res_id', '!=', False)]
        for data in IrModelData.sudo().search(imd_domain):
            imd_models[data.model].append(data.res_id)

        def browse(model):
            # as this method is called before the module update, some xmlid
            # may be invalid at this stage; explictly filter records before
            # reading them
            return self.env[model].browse(imd_models[model]).exists()

        def format_view(v):
            return '%s%s (%s)' % (v.inherit_id and '* INHERIT ' or '', v.name, v.type)

        module.views_by_module = "\n".join(sorted(format_view(v) for v in browse('ir.ui.view')))
        module.reports_by_module = "\n".join(sorted(r.name for r in browse('ir.actions.report')))
        module.menus_by_module = "\n".join(sorted(m.complete_name for m in browse('ir.ui.menu')))


def _get_icon_image(self):
    self.icon_image = ''
    self.icon_flag = ''
    for module in self:
        if not module.id:
            continue
        manifest = self.get_module_info(module.name)
        if module.icon:
            path = module.icon or ''
        elif manifest:
            path = manifest.get('icon', '')
        else:
            path = Manifest.for_addon('base').icon
        path = path.removeprefix("/")
        if path:
            try:
                with file_open(path, 'rb', filter_ext=('.png', '.svg', '.gif', '.jpeg', '.jpg')) as f:
                    module.icon_image = BinaryBytes(f.read())
            except OSError:
                module.icon_image = False
        countries = manifest.get('countries', [])
        country_code = len(countries) == 1 and countries[0]
        module.icon_flag = get_flag(country_code.upper()) if country_code else ''
