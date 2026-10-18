# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

from ast import literal_eval

from odoo import http, _
from odoo.http import request
from odoo.exceptions import UserError
from odoo.tools import sql

_logger = logging.getLogger(__name__)


class StudioFieldsMixin:
    """ Studio field operations: create, edit, rename, aliases, defaults. """

    def create_new_field(self, values):
        """ Create a new field with given values.
            In some cases we have to convert "id" to "name" or "name" to "id"
            - "model" is the current model we are working on. In js, we only have his name.
              but we need his id to create the field of this model.
            - The relational widget doesn't provide any name, we only have the id of the record.
              This is why we need to search the name depending of the given id.
        """
        # Get current model
        model_name = values.pop('model_name')
        Model = request.env[model_name]
        # If the model is backed by a sql view
        # it doesn't make sense to add field, and won't work
        table_kind = sql.table_kind(request.env.cr, Model._table)
        if table_kind != sql.TableKind.Regular:
            raise UserError(_('The model %s doesn\'t support adding fields.', Model._name))

        values['model_id'] = request.env['ir.model']._get_id(model_name)

        # Field type is called ttype in the database
        if type_ := values.pop('type', None):
            values['ttype'] = type_

        # For related fields
        if (string := values.get("string")) and values.get('related'):
            if request.env['ir.model.fields'].search_count([("model", "=", model_name), ("field_description", "=", string)]):
                values["field_description"] = _('%s (Copy)', string)
            else:
                values["field_description"] = string

        # For many2one and many2many fields
        if rel_id := values.pop('relation_id', None):
            values['relation'] = request.env['ir.model'].browse(rel_id).model
        # For related one2many fields
        if related := values.get('related') if values.get('ttype') == 'one2many' else "":
            field_name = related.rsplit('.', 1)[-1]
            field = request.env['ir.model.fields'].search([
                ('name', '=', field_name),
                ('model', '=', values.pop('relational_model')),
            ])
            field.ensure_one()
            values.update(
                relation=field.relation,
                relation_field=field.relation_field,
            )
            if values.get("store", True) is False:
                values["relation_field"] = False
        # For one2many fields
        if rel := values.pop('relation_field_id', None):
            field = request.env['ir.model.fields'].browse(rel)
            values.update(
                relation=field.model_id.model,
                relation_field=field.name,
            )
        # For selection fields
        if sel := values.get('selection'):
            values['selection'] = str(sel)

        if values.get('ttype') == 'many2many':
            # check for existing relation to avoid re-use
            values['relation_table'] = request.env['ir.model.fields']._get_next_relation(model_name, values.get('relation'))
        # Optional default value at creation
        default_value = values.pop('default_value', False)

        # Filter out invalid field names and create new field
        values = {
            k: v
            for k, v in values.items()
            if k in request.env['ir.model.fields']._fields
        }
        new_field = request.env['ir.model.fields'].with_context(studio=True).create(values)

        if default_value:
            if new_field.ttype == 'selection':
                if default_value is True:
                    # take the first selection value as default one in this case
                    default_value = new_field.selection_ids[:1].value
            self.set_default_value(new_field.model, new_field.name, default_value)

        return new_field

    @http.route('/web_studio/rename_field', type='jsonrpc', auth='user')
    def rename_field(self, studio_view_id, studio_view_arch, model, old_name, new_name, new_label=None):
        studio_view = request.env['ir.ui.view'].browse(studio_view_id)

        # a field cannot be renamed if it appears in a view ; we thus reset the
        # studio view before all operations to be able to rename the field
        studio_view.arch_db = studio_view_arch

        field_id = request.env['ir.model.fields']._get(model, old_name).with_context(lang=None)
        to_write = {'name': new_name}
        if new_label is not None:
            to_write["field_description"] = new_label
        field_id.write(to_write)

        if field_id.ttype == 'binary' and not field_id.related:
            # during the binary field creation, another char field containing
            # the filename has been created (see @edit_view). To avoid creating
            # the field twice, it is also renamed
            filename_field_id = request.env['ir.model.fields']._get(model, old_name + '_filename')
            if filename_field_id:
                filename_field_id.write({'name': new_name + '_filename'})

    @http.route('/web_studio/edit_field', type='jsonrpc', auth='user')
    def edit_field(self, model_name, field_name, values, force_edit=False):
        field = request.env['ir.model.fields'].search([('model', '=', model_name), ('name', '=', field_name)])

        if field.ttype == 'selection' and 'selection' in values:
            selection_values = [False] + [x[0] for x in literal_eval(values['selection'])]
            records = request.env[model_name].search([(field_name, 'not in', selection_values)])
            if records and not force_edit:
                message = _("""There are %s records that use the values you are trying to remove.
Are you sure you want to get rid of them?""", len(records))
                return {'records_linked': len(records), 'message': message}
            records.write({field_name: False})

        field.write(values)

        # remove default value if the value is not acceptable anymore
        if field.ttype == 'selection':
            current_default = request.env['ir.default']._get(model_name, field_name, company_id=True)
            if current_default:
                selection_values = literal_eval(field.selection)
                if current_default not in [x[0] for x in selection_values]:
                    request.env['ir.default'].discard_values(model_name, field_name, [current_default])

    @http.route('/web_studio/get_email_alias', type='jsonrpc', auth='user')
    def get_email_alias(self, model_name):
        """ Returns the email alias associated to the model @model_name. Only
        free aliases (not owned by a document using 'parent_*' fields')
        creating new documents (void 'alias_force_thread_id') are considered. """
        current_alias_domain = request.env.company.alias_domain_id
        result = {'alias_domain': current_alias_domain.name}

        model = request.env['ir.model']._get(model_name)
        if not model:
            return result

        request.env[model_name].check_access('read')
        email_alias = request.env['mail.alias'].search([
            ('alias_domain_id', '=', current_alias_domain.id),
            ('alias_force_thread_id', '=', False),
            ('alias_model_id', '=', model.id),
            ('alias_parent_model_id', '=', False),
            ('alias_parent_thread_id', '=', False)
        ], limit=1)
        result['email_alias'] = email_alias.alias_name
        return result

    @http.route('/web_studio/set_email_alias', type='jsonrpc', auth='user')
    def set_email_alias(self, model_name, value):
        """ Set the email alias associated to the model @model_name. Only
        free aliases (not owned by a document using 'parent_*' fields')
        creating new documents (void 'alias_force_thread_id') are taken into
        account; otherwise a new alias is created. When voiding, just keep a
        void alias, do not unlink aliases as it may have unwanted side effects).
        """
        model_id = request.env['ir.model']._get_id(model_name)
        if not model_id:
            return

        request.env[model_name].check_access('read')
        current_alias_domain = request.env.company.alias_domain_id
        alias_name = request.env['mail.alias']._sanitize_alias_name(value)
        existing_alias = request.env['mail.alias'].search([
            ('alias_domain_id', '=', current_alias_domain.id),
            ('alias_force_thread_id', '=', False),
            ('alias_model_id', '=', model_id),
            ('alias_parent_model_id', '=', False),
            ('alias_parent_thread_id', '=', False)
        ], limit=1)
        if existing_alias:
            existing_alias.alias_name = alias_name
        elif alias_name:
            request.env['mail.alias'].with_context(studio=True).create({
                'alias_domain_id': current_alias_domain.id,
                'alias_model_id': model_id,
                'alias_name': alias_name,
            })

    @http.route('/web_studio/get_field_infos', type='jsonrpc', auth='user')
    def get_field_infos(self, model_name, field_name, company_id=False):
        """Return default value AND tracking info for a field."""
        # ---- Default Value ----
        context = {}
        if company_id:
            context["allowed_company_ids"] = [company_id]
        default_value = self.env['ir.default'].with_context(context)._get(model_name, field_name, company_id=True)

        # ---- Tracking ----
        field = self.env[model_name]._fields.get(field_name)
        tracking = False
        if field and hasattr(field, "tracking"):
            tracking = bool(field.tracking)

        return {
            "default_value": default_value,
            "tracking": tracking,
        }

    @http.route('/web_studio/set_default_value', type='jsonrpc', auth='user')
    def set_default_value(self, model_name, field_name, value, company_id=False):
        """ Set the default value associated to the given field. """
        context = { "studio": True }
        if company_id:
            context["allowed_company_ids"] = [company_id]
        request.env['ir.default'].with_context(context).set(model_name, field_name, value, company_id=True)

    @http.route('/web_studio/set_field_tracking', type='jsonrpc', auth='user')
    def set_field_tracking(self, model_name, field_name, tracking_value):
        """Set or unset tracking for the given field."""
        return self.env['ir.model.fields']._get(model_name, field_name).with_context(studio=True).write({'tracking': tracking_value})

    @http.route('/web_studio/set_currency', type='jsonrpc', auth='user')
    def set_currency(self, model_name, field_name, value):
        """ Set the currency value associated to the given monetary field. """
        return request.env['ir.model.fields'].with_context(studio=True).search([["model", "=", model_name], ["name", "=", field_name]]).write({'currency_field': value})
