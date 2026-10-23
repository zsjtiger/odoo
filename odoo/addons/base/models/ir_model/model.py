"""The models of the registry (ir.model): their definition, their access and their deletion."""

from __future__ import annotations

import logging
from inspect import cleandoc
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tools import sql, unique, SQL
from odoo.tools.text.translate import _

from .helpers import RE_ORDER_FIELDS, mark_modified, model_xmlid, select_en, upsert_en

_logger = logging.getLogger('odoo.addons.base.models.ir_model')


class IrModel(models.Model):
    _name = 'ir.model'
    _description = "Model"
    _order = 'model'
    _rec_names_search = ('name', 'model')
    _allow_sudo_commands = False

    def _default_field_id(self):
        if self.env.context.get('install_mode'):
            return []                   # no default field when importing
        return [Command.create({'name': 'x_name', 'field_description': 'Name', 'ttype': 'char', 'copied': True})]

    name = fields.Char(string='Model Description', translate=True, required=True)
    model = fields.Char(default='x_', required=True)
    order = fields.Char(string='Order', default='id', required=True,
                        help='SQL expression for ordering records in the model; e.g. "x_sequence asc, id desc"')
    info = fields.Text(string='Information')
    explanation = fields.Text(string='Explanation', help='Verbose description of what is this model for')
    field_id = fields.One2many('ir.model.fields', 'model_id', string='Fields', required=True, copy=True,
                               default=_default_field_id)
    inherited_model_ids = fields.Many2many('ir.model', compute='_inherited_models', string="Inherited models",
                                           help="The list of models that extends the current model.")
    state = fields.Selection([('manual', 'Custom'), ('base', 'Base')], string='Type', default='manual', readonly=True)
    access_ids = fields.One2many('ir.access', 'model_id', string='Access')
    abstract = fields.Boolean(string="Abstract Model")
    transient = fields.Boolean(string="Transient Model")
    modules = fields.Char(compute='_in_modules', string='In Apps', help='List of modules in which the object is defined or inherited')
    view_ids = fields.One2many('ir.ui.view', compute='_view_ids', string='Views')
    count = fields.Integer(compute='_compute_count', string="Count (Incl. Archived)",
                           help="Total number of records in this model")
    fold_name = fields.Char(string="Fold Field", help="In a Kanban view where columns are records of this model, the value "
        "of this (boolean) field determines which column should be folded by default.")

    @api.depends()
    def _inherited_models(self):
        self.inherited_model_ids = False
        for model in self:
            records = self.env.get(model.model)
            if records is not None:
                model.inherited_model_ids = self.search([('model', 'in', list(records._inherits))])

    @api.depends()
    def _in_modules(self):
        installed_modules = self.env['ir.module.module'].search([('state', '=', 'installed')])
        installed_names = set(installed_modules.mapped('name'))
        xml_ids = models.Model._get_external_ids(self)
        for model in self:
            module_names = set(xml_id.split('.')[0] for xml_id in xml_ids[model.id])
            model.modules = ", ".join(sorted(installed_names & module_names))

    @api.depends()
    def _view_ids(self):
        for model in self:
            model.view_ids = self.env['ir.ui.view'].search([('model', '=', model.model)])

    @api.depends()
    def _compute_count(self):
        self.count = 0
        for model in self:
            records = self.env.get(model.model)
            if records is not None and not records._abstract and records._auto:
                [[count]] = self.env.execute_query(SQL("SELECT COUNT(*) FROM %s", SQL.identifier(records._table)))
                model.count = count

    @api.constrains('model')
    def _check_model_name(self):
        for model in self:
            if model.state == 'manual':
                self._check_manual_name(model.model)
            if not models.check_object_name(model.model):
                raise ValidationError(_("The model name can only contain lowercase characters, digits, underscores and dots."))

    @api.constrains('order', 'field_id')
    def _check_order(self):
        for model in self:
            try:
                model._check_qorder(model.order)  # regex check for the whole clause ('is it valid sql?')
            except UserError as e:
                raise ValidationError(str(e))
            # add MAGIC_COLUMNS to 'stored_fields' in case 'model' has not been
            # initialized yet, or 'field_id' is not up-to-date in cache
            stored_fields = set(
                model.field_id.filtered('store').mapped('name') + models.MAGIC_COLUMNS
            )
            if model.model in self.env:
                # add fields inherited from models specified via code if they are already loaded
                stored_fields.update(
                    fname
                    for fname, fval in self.env[model.model]._fields.items()
                    if fval.inherited and fval.base_field.store
                )

            order_fields = RE_ORDER_FIELDS.findall(model.order)
            for field in order_fields:
                if field not in stored_fields:
                    raise ValidationError(_("Unable to order by %s: fields used for ordering must be present on the model and stored.", field))

    @api.constrains('fold_name')
    def _check_fold_name(self):
        for model in self:
            if model.fold_name and model.fold_name not in model.field_id.mapped('name'):
                raise ValidationError(_("The value of 'Fold Field' should be a field name of the model."))

    _obj_name_uniq = models.Constraint('UNIQUE (model)', 'Each model must have a unique name.')

    def _get(self, name):
        """ Return the (sudoed) `ir.model` record with the given name.
        The result may be an empty recordset if the model is not found.
        """
        model_id = self._get_id(name) if name else False
        return self.sudo().browse(model_id)

    @api.ormcache('name', cache='stable')
    def _get_id(self, name):
        self.env.cr.execute("SELECT id FROM ir_model WHERE model=%s", (name,))
        result = self.env.cr.fetchone()
        return result and result[0]

    def _drop_table(self):
        for model in self:
            current_model = self.env.get(model.model)
            if current_model is not None:
                if current_model._abstract:
                    continue

                table = current_model._table
                kind = sql.table_kind(self.env.cr, table)
                if kind == sql.TableKind.View:
                    self.env.cr.execute(SQL('DROP VIEW %s', SQL.identifier(table)))
                elif kind == sql.TableKind.Regular:
                    self.env.cr.execute(SQL('DROP TABLE %s CASCADE', SQL.identifier(table)))
                elif kind is not None:
                    _logger.warning(
                        "Unable to drop table %r of model %r: unmanaged or unknown tabe type %r",
                        table, model.model, kind
                    )
            else:
                _logger.runbot('The model %s could not be dropped because it did not exist in the registry.', model.model)
        return True

    @api.ondelete(at_uninstall=False)
    def _unlink_if_manual(self):
        if self.env.context.get('force_delete'):
            return
        # Prevent manual deletion of module tables
        for model in self:
            if model.state != 'manual':
                raise UserError(_("Model “%s” contains module data and cannot be removed.", model.name))

    @api.ondelete(at_uninstall=False)
    def _unlink_related_attachments(self):
        """ Delete attachment associated with the models being deleted. """
        models = tuple(self.mapped('model'))

        # Get files attached solely to the models being deleted (and none other)
        fname_rows = self.env.execute_query(SQL(
            """
            SELECT DISTINCT store_fname
            FROM ir_attachment
            WHERE res_model IN %s AND store_fname IS NOT NULL
            EXCEPT
            SELECT store_fname
            FROM ir_attachment
            WHERE res_model NOT IN %s
            """,
            models, models,
        ))

        self.env.execute_query(SQL(
            "DELETE FROM ir_attachment WHERE res_model IN %s",
            models,
        ))

        for (fname,) in fname_rows:
            self.env['ir.attachment']._file_delete(fname)

    def unlink(self):
        # prevent screwing up fields that depend on these models' fields
        manual_models = self.filtered(lambda model: model.state == 'manual')
        manual_models.field_id.filtered(lambda f: f.state == 'manual')._prepare_update()
        (self - manual_models).field_id._prepare_update()

        # delete fields whose comodel is being removed
        self.env['ir.model.fields'].search([('relation', 'in', self.mapped('model'))]).unlink()

        # delete ir_crons created by user
        crons = self.env['ir.cron'].with_context(active_test=False).search([('model_id', 'in', self.ids)])
        if crons:
            crons.unlink()

        # delete related ir_model_data
        model_data = self.env['ir.model.data'].search([('model', 'in', self.mapped('model'))])
        if model_data:
            model_data.unlink()

        self._drop_table()
        res = super().unlink()

        # Reload registry for normal unlink only. For module uninstall, the
        # reload is done independently in odoo.modules.loading.
        if not self.pool.uninstalling_modules:
            # setup models; this automatically removes custom model from registry
            self.env.flush_all()
            self.pool._setup_models__(self.env.cr)

        return res

    def write(self, vals):
        for unmodifiable_field in ('model', 'state', 'abstract', 'transient'):
            if unmodifiable_field in vals and any(rec[unmodifiable_field] != vals[unmodifiable_field] for rec in self):
                raise UserError(_('Field %s cannot be modified on models.', self._fields[unmodifiable_field]._description_string(self.env)))
        # Filter out operations 4 from field id, because the web client always
        # writes (4,id,False) even for non dirty items.
        if 'field_id' in vals:
            vals['field_id'] = [op for op in vals['field_id'] if op[0] != 4]
        res = super().write(vals)
        if not any(self._ids):
            return res
        # ordering has been changed, reload registry to reflect update + signaling
        if 'order' in vals or 'fold_name' in vals:
            self.env.flush_all()  # _setup_models__ need to fetch the updated values from the db
            # incremental setup will reload custom models
            self.pool._setup_models__(self.env.cr, [])
        if 'rule_ids' in vals or 'access_ids' in vals:
            # for env['ir.access']._get_all_access
            self.env.transaction.invalidate_ormcache('stable')
        return res

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        manual_models = [
            vals['model'] for vals in vals_list if vals.get('state', 'manual') == 'manual'
        ]
        if manual_models:
            # setup models; this automatically adds model in registry
            self.env.flush_all()
            # incremental setup will reload custom models
            self.pool._setup_models__(self.env.cr, [])
            # update database schema
            self.pool.init_models(self.env.cr, manual_models, dict(self.env.context, update_custom_fields=True))
        if res:
            # for env['ir.access']._get_all_access
            self.env.transaction.invalidate_ormcache('stable')
        return res

    @api.model
    def name_create(self, name):
        """ Infer the model from the name. E.g.: 'My New Model' should become 'x_my_new_model'. """
        ir_model = self.create({
            'name': name,
            'model': 'x_' + '_'.join(name.lower().split(' ')),
        })
        return ir_model.id, ir_model.display_name

    def _reflect_model_params(self, model):
        """ Return the values to write to the database for the given model. """
        explanations = []
        for cls in reversed(type(model).mro()):
            # Use __dict__ to only capture explanations explicitly defined on this class.
            explanation = cls.__dict__.get('_explanation')
            # Only include if it matches the target model's name (ignores mixins).
            if explanation and getattr(cls, '_name', None) == model._name:
                explanations.append(cleandoc(explanation or ''))

        return {
            'model': model._name,
            'name': model._description,
            'explanation': "\n\n".join(explanations) if explanations else False,
            'order': model._order,
            'info': next(cls.__doc__ for cls in self.env.registry[model._name].mro() if cls.__doc__),
            'state': 'manual' if model._custom else 'base',
            'abstract': model._abstract,
            'transient': model._transient,
            'fold_name': model._fold_name,
        }

    def _reflect_models(self, model_names):
        """ Reflect the given models. """
        # determine expected and existing rows
        rows = [
            self._reflect_model_params(self.env[model_name])
            for model_name in model_names
        ]
        cols = list(unique(['model'] + list(rows[0])))
        expected = [tuple(row[col] for col in cols) for row in rows]

        model_ids = {}
        existing = {}
        for row in select_en(self, ['id'] + cols, model_names):
            model_ids[row[1]] = row[0]
            existing[row[1]] = row[1:]

        # create or update rows
        rows = [row for row in expected if existing.get(row[0]) != row]
        if rows:
            ids = upsert_en(self, cols, rows, ['model'])
            for row, id_ in zip(rows, ids):
                model_ids[row[0]] = id_
            self.pool.post_init(mark_modified, self.browse(ids), cols[1:])

        # update their XML id
        module = self.env.context.get('module')
        if not module:
            return

        data_list = []
        for model_name, model_id in model_ids.items():
            model = self.env[model_name]
            if model._module == module:
                # model._module is the name of the module that last extended model
                xml_id = model_xmlid(module, model_name)
                record = self.browse(model_id)
                data_list.append({'xml_id': xml_id, 'record': record})
        self.env['ir.model.data']._update_xmlids(data_list)

    @api.model
    def _instanciate_attrs(self, model_data):
        """ Return the attributes to instanciate a custom model definition class
            corresponding to ``model_data``.
        """
        return {
            '_name': model_data['model'],
            '_description': model_data['name'],
            '_module': False,
            '_custom': True,
            '_abstract': bool(model_data['abstract']),
            '_transient': bool(model_data['transient']),
            '_order': model_data['order'],
            '_fold_name': model_data['fold_name'],
            '__doc__': model_data['info'],
        }

    @api.model
    def _is_manual_name(self, name):
        return name.startswith('x_')

    @api.model
    def _check_manual_name(self, name):
        if not self._is_manual_name(name):
            raise ValidationError(_("The model name must start with 'x_'."))
