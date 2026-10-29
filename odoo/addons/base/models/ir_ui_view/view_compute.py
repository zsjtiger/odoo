"""The computed fields of the views: the architecture, the model, the XML id and the invalid locators, and their inverses."""

from __future__ import annotations

import collections
import re
from lxml import etree
from contextlib import suppress
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.modules.module import get_resource_from_path
from odoo.tools import config
from odoo.tools.misc import file_path
from odoo.tools.xml.template_inheritance import apply_inheritance_specs
from odoo.tools.text.translate import StoredTranslations
from .helpers import get_view_arch_from_file

from .view import _logger

def _compute_arch(self):
    def resolve_external_ids(arch_fs, view_xml_id):
        def replacer(m):
            xmlid = m.group('xmlid')
            if '.' not in xmlid:
                xmlid = '%s.%s' % (view_xml_id.split('.')[0], xmlid)
            return m.group('prefix') + str(self.env['ir.model.data']._xmlid_to_res_id(xmlid))
        return re.sub(r'(?P<prefix>[^%])%\((?P<xmlid>.*?)\)[ds]', replacer, arch_fs)

    lang = self.env.lang or 'en_US'
    env_en = self.with_context(edit_translations=None, lang='en_US', check_translations=True).env
    env_lang = self.with_context(lang=lang, check_translations=True).env
    field_arch_db = self._fields['arch_db']
    for view in self:
        arch_fs = None
        read_file = self.env.context.get('read_arch_from_file') or \
            ('xml' in config['dev_mode'] and not view.arch_updated)
        if read_file and view.arch_fs and (view.xml_id or view.key):
            xml_id = view.xml_id or view.key
            try:
                # reading the file will raise an OSError if it is unreadable
                arch_fs = get_view_arch_from_file(file_path(view.arch_fs, check_exists=False), xml_id)
            except OSError:
                _logger.warning("View %s: Full path [%s] cannot be found.", xml_id, view.arch_fs)
                arch_fs = False

            # replace %(xml_id)s, %(xml_id)d, %%(xml_id)s, %%(xml_id)d by the res_id
            if arch_fs:
                arch_fs = resolve_external_ids(arch_fs, xml_id).replace('%%', '%')
                translation_dictionary = StoredTranslations._get_translation_dictionary(
                    field_arch_db, view.with_env(env_en).arch_db, {lang: view.with_env(env_lang).arch_db}
                )
                arch_fs = field_arch_db.translate(
                    lambda term: translation_dictionary[term][lang],
                    arch_fs
                )
        view.arch = arch_fs or view.arch_db


def _inverse_arch(self):
    for view in self:
        self._validate_xml_encoding(view.arch)
        data = dict(arch_db=view.arch)
        if 'install_filename' in self.env.context:
            # we store the relative path to the resource instead of the absolute path, if found
            # (it will be missing e.g. when importing data-only modules using base_import_module)
            path_info = get_resource_from_path(self.env.context['install_filename'])
            if path_info:
                data['arch_fs'] = '/'.join(path_info[0:2])
                data['arch_updated'] = False
        view.write(data)
        # the xml_translate will clean the arch_db when write (e.g. ('<div>') -> ('<div></div>'))
        # view.arch should be reassigned here
        view.arch = view.arch_db
    # the field 'arch' depends on the context and has been implicitly
    # modified in all languages; the invalidation below ensures that the
    # field does not keep an old value in another environment
    self.invalidate_recordset(['arch'])


def _compute_arch_base(self):
    # 'arch_base' is the same as 'arch' without translation
    for view, view_wo_lang in zip(self, self.with_context(lang=None)):
        view.arch_base = view_wo_lang.arch


def _inverse_arch_base(self):
    for view, view_wo_lang in zip(self, self.with_context(lang=None)):
        self._validate_xml_encoding(view.arch_base)
        view_wo_lang.arch = view.arch_base


def reset_arch(self, mode='soft'):
    """ Reset the view arch to its previous arch (soft) or its XML file arch
        if exists (hard).
        """
    for view in self:
        arch = False
        if mode == 'soft':
            arch = view.arch_prev
            write_dict = {'arch_db': arch}
        elif mode == 'hard' and view.arch_fs:
            arch = view.with_context(read_arch_from_file=True, lang=None).arch
            write_dict = {'arch_db': arch, 'arch_prev': False, 'arch_updated': False}
        if arch:
            # Don't save current arch in previous since we reset, this arch is probably broken
            view.with_context(no_save_prev=True, lang=None).write(write_dict)


def _compute_model_data_id(self):
    # get the first ir_model_data record corresponding to self
    for view in self:
        view.model_data_id = False
    domain = [('model', '=', 'ir.ui.view'), ('res_id', 'in', self.ids)]
    for data in self.env['ir.model.data'].sudo().search_read(domain, ['res_id'], order='id desc'):
        view = self.browse(data['res_id'])
        view.model_data_id = data['id']


def _search_model_data_id(self, operator, value):
    if operator in Domain.NEGATIVE_OPERATORS:
        return NotImplemented
    name = 'name' if isinstance(value, str) else 'id'
    domain = [('model', '=', 'ir.ui.view'), (name, operator, value)]
    query = self.env['ir.model.data'].sudo()._search(domain)
    return [('id', 'in', query.subselect(query.table.res_id))]


def _compute_model_id(self):
    for record in self:
        record.model_id = self.env['ir.model']._get(record.model)


def _inverse_compute_model_id(self):
    for record in self:
        record.model = record.model_id.model


def _compute_invalid_locators(self):
    def assess_locator(source, spec):
        node = None
        with suppress(ValidationError):  # Syntax error
            # If locate_node returns None here:
            # Invalid expression: Ok Syntax, but cannot be anchored to the parent view.
            node = self.locate_node(source, spec)

        if node is None:
            return {
                "tag": spec.tag,
                "attrib": dict(spec.attrib),
                "sourceline": spec.sourceline,
            }
        return None

    self.invalid_locators = []
    for view in self:
        if not view.inherit_id or not view.arch:
            continue
        try:
            # When an arch above the current one is invalid, we don't want to raise
            # instead, we want to continue using the form view.
            # This can happen when an invalid xpath has been forcibly written without checking
            # Via SQL or during the upgrade process
            source = view.with_context(ir_ui_view_tree_cut_off_view=view)._get_combined_arch()
        except (ValidationError, ValueError):  # Xpath syntax Invalid , Xpath element unfound
            # Flagging The field as not empty and with custom information.
            # We don't do anything with the object, but the information
            # may give some clues for debugging.
            # Also, for display purposes in Form view, the field needs not be falsy.
            view.invalid_locators = [{"broken_hierarchy": True}]
            continue

        invalid_locators = []
        specs = collections.deque([etree.fromstring(view.arch)])
        while specs:
            spec = specs.popleft()
            if isinstance(spec, etree._Comment):
                continue
            if spec.tag == 'data':
                specs.extend(spec)
                continue

            if invalid_locator := assess_locator(source, spec):
                invalid_locators.append(invalid_locator)
            else:
                position, mode = spec.get("position"), spec.get("mode")
                for sub_spec in spec:
                    sub_position = sub_spec.get("position")
                    if sub_position == "move" and (position != "replace" or mode != "inner"):
                        if invalid_move := assess_locator(source, sub_spec):
                            invalid_locators.append(invalid_move)
                    elif sub_position:
                        invalid_locators.append({
                            "tag": sub_spec.tag,
                            "attrib": dict(sub_spec.attrib),
                            "sourceline": sub_spec.sourceline,
                        })

                try:
                    # Since subsequent xpaths may be dependent on previous xpaths, we apply the spec.
                    source = apply_inheritance_specs(source, spec)
                except ValueError as e:
                    # This function is only interested in locating invalid locators.
                    # Here, ValueError is raised for:
                    #   Invalid mode attribute
                    #   Invalid attributes attribute
                    #   Invalid position
                    #   Element <attribute> with 'add' or 'remove' cannot contain text
                    #   Invalid separator for python expressions in attributes
                    pass
        view.invalid_locators = invalid_locators


def _compute_xml_id(self):
    xml_ids = collections.defaultdict(list)
    domain = [('model', '=', 'ir.ui.view'), ('res_id', 'in', self.ids)]
    for data in self.env['ir.model.data'].sudo().search_read(domain, ['module', 'name', 'res_id']):
        xml_ids[data['res_id']].append("%s.%s" % (data['module'], data['name']))
    for view in self:
        view.xml_id = xml_ids.get(view.id, [''])[0]


def _compute_defaults(self, values):
    if 'inherit_id' in values:
        # Do not automatically change the mode if the view already has an inherit_id,
        # and the user change it to another.
        if not values['inherit_id'] or all(not view.inherit_id for view in self):
            values.setdefault('mode', 'extension' if values['inherit_id'] else 'primary')
    return values


def _compute_warning_info(self):
    for view in self:
        view.warning_info = ''
        try:
            if view.inherit_id:
                view_arch = etree.fromstring(view.arch)
                view._valid_inheritance(view_arch)
            combined_arch = view._get_combined_arch()
            if view.type != 'qweb':
                view._postprocess_view(combined_arch, view.model, is_compute_warning_info=True)
        except (etree.ParseError, ValueError, TypeError) as e:
            # Note: lxml < 5.0 raises ValueError; lxml 5.0+ / libxml2 2.12+ raises TypeError
            view.warning_info = str(e)
