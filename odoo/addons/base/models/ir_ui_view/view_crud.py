"""The creation, the writing, the copy and the deletion of the views, and their specific views."""

from __future__ import annotations

import uuid
from lxml import etree
from odoo.exceptions import ValidationError
from odoo.modules.module import get_resource_from_path
from odoo.tools import _

from .view import IrUiView

def create(self, vals_list):
    valid_types = self._fields['type']._selection
    for values in vals_list:
        if 'arch_db' in values and not values['arch_db']:
            # delete empty arch_db to avoid triggering _check_xml before _inverse_arch_base is called
            del values['arch_db']

        if not values.get('type'):
            if values.get('inherit_id'):
                values['type'] = self.browse(values['inherit_id']).type
            else:

                try:
                    if not values.get('arch') and not values.get('arch_base'):
                        raise ValidationError(_('Missing view architecture.'))
                    values['type'] = etree.fromstring(values.get('arch') or values.get('arch_base')).tag
                    if values['type'] not in valid_types:
                        raise ValidationError(_(
                            "Invalid view type: '%(view_type)s'.\n"
                            "You might have used an invalid starting tag in the architecture.\n"
                            "Allowed types are: %(valid_types)s",
                            view_type=values['type'], valid_types=', '.join(valid_types)
                        ))
                except (etree.ParseError, ValueError, TypeError):
                    # Note: lxml < 5.0 raises ValueError; lxml 5.0+ / libxml2 2.12+ raises TypeError
                    # don't raise here, the constraint that runs `self._check_xml` will
                    # do the job properly.
                    pass
        if not values.get('key') and values.get('type') == 'qweb':
            values['key'] = "gen_key.%s" % str(uuid.uuid4())[:6]
        if not values.get('name'):
            values['name'] = "%s %s" % (values.get('model'), values['type'])
        # Create might be called with either `arch` (xml files), `arch_base` (form view) or `arch_db`.
        values['arch_prev'] = values.get('arch_base') or values.get('arch_db') or values.get('arch')
        # write on arch: bypass _inverse_arch()
        if 'arch' in values:
            values['arch_db'] = values.pop('arch')
            if 'install_filename' in self.env.context:
                # we store the relative path to the resource instead of the absolute path, if found
                # (it will be missing e.g. when importing data-only modules using base_import_module)
                path_info = get_resource_from_path(self.env.context['install_filename'])
                if path_info:
                    values['arch_fs'] = '/'.join(path_info[0:2])
                    values['arch_updated'] = False
        values.update(self._compute_defaults(values))

    result = super(IrUiView, self).create(vals_list)
    result.with_context(ir_ui_view_partial_validation=True)._check_xml()
    return result


def write(self, vals):
    # Keep track if view was modified. That will be useful for the --dev mode
    # to prefer modified arch over file arch.
    if 'arch_updated' not in vals and ('arch' in vals or 'arch_base' in vals) and 'install_filename' not in self.env.context:
        vals['arch_updated'] = True

    # drop the corresponding view customizations (used for dashboards for example), otherwise
    # not all users would see the updated views
    custom_view = self.env['ir.ui.view.custom'].sudo().search([('ref_id', 'in', self.ids)])
    if custom_view:
        custom_view.unlink()

    if 'arch_db' in vals and not self.env.context.get('no_save_prev'):
        vals['arch_prev'] = self.arch_db

    res = super(IrUiView, self).write(self._compute_defaults(vals))

    # Check the xml of the view if it gets re-activated or changed.
    if 'active' in vals or 'arch_db' in vals or 'inherit_id' in vals:
        self._check_xml()

    return res


def unlink(self):
    # if in uninstall mode and has children views, emulate an ondelete cascade
    if self.env.context.get('force_delete') and self.inherit_children_ids:
        self.inherit_children_ids.unlink()
    return super(IrUiView, self).unlink()


def _update_field_translations(self, field_name, translations, digest=None, source_lang=''):
    return super(IrUiView, self.with_context(no_save_prev=True))._update_field_translations(field_name, translations, digest=digest, source_lang=source_lang)


def copy_data(self, default=None):
    has_default_without_key = default and 'key' not in default
    default = dict(default or {})
    vals_list = super(IrUiView, self).copy_data(default=default)
    for view, vals in zip(self, vals_list):
        if view.key and has_default_without_key:
            vals['key'] = default.get('key', view.key + '_%s' % str(uuid.uuid4())[:6])
    return vals_list


def _create_all_specific_views(self, processed_modules):
    """To be overriden and have specific view behaviour on create"""
    pass


def _get_specific_views(self):
    """ Given a view, return a record set containing all the specific views
            for that view's key.
        """
    self.ensure_one()
    # Only qweb views have a specific conterpart
    if self.type != 'qweb':
        return self.env['ir.ui.view']
    # A specific view can have a xml_id if exported/imported but it will not be equals to it's key (only generic view will).
    return self.with_context(active_test=False).search([('key', '=', self.key)]).filtered(lambda r: not r.xml_id == r.key)


def _load_records_write(self, values):
    """ During module update, when updating a generic view, we should also
            update its specific views (COW'd).
            Note that we will only update unmodified fields. That will mimic the
            noupdate behavior on views having an ir.model.data.
        """
    if self.type == 'qweb':
        for cow_view in self._get_specific_views():
            authorized_vals = {}
            for key in values:
                if key != 'inherit_id' and cow_view[key] == self[key]:
                    authorized_vals[key] = values[key]
            # if inherit_id update, replicate change on cow view but
            # only if that cow view inherit_id wasn't manually changed
            inherit_id = values.get('inherit_id')
            if inherit_id and self.inherit_id.id != inherit_id and \
               cow_view.inherit_id.key == self.inherit_id.key:
                self._load_records_write_on_cow(cow_view, inherit_id, authorized_vals)
            else:
                cow_view.with_context(no_cow=True).write(authorized_vals)
    super(IrUiView, self)._load_records_write(values)


def _load_records_write_on_cow(self, cow_view, inherit_id, values):
    # for modules updated before `website`, we need to
    # store the change to replay later on cow views
    if not hasattr(self.pool, 'website_views_to_adapt'):
        self.pool.website_views_to_adapt = []
    self.pool.website_views_to_adapt.append((
        cow_view.id,
        inherit_id,
        values,
    ))
