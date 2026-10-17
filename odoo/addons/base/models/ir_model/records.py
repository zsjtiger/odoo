# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The records of the fields (ir.model.fields): their lookups, their creation, their writes and their deletion, and the schema updates."""

from __future__ import annotations

from odoo import models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import sql, OrderedSet, SQL
from odoo.tools.text.translate import _

from .field import IrModelFields, _logger

def _get(self, model_name, name):
    """ Return the (sudoed) `ir.model.fields` record with the given model and name.
        The result may be an empty recordset if the model is not found.
        """
    field_id = model_name and name and self._get_ids(model_name).get(name)
    return self.sudo().browse(field_id)


def _get_ids(self, model_name):
    cr = self.env.cr
    cr.execute("SELECT name, id FROM ir_model_fields WHERE model=%s", [model_name])
    return dict(cr.fetchall())


def _drop_column(self):
    from odoo.orm.models.classes import pop_field  # noqa: PLC0415

    tables_to_drop = set()

    for field in self:
        if field.name in models.MAGIC_COLUMNS:
            continue
        model = self.env.get(field.model)
        is_model = model is not None
        if field.store:
            # TODO: Refactor this brol in master
            if is_model and sql.column_exists(self.env.cr, model._table, field.name) and \
                    sql.table_kind(self.env.cr, model._table) == sql.TableKind.Regular:
                self.env.cr.execute(SQL('ALTER TABLE %s DROP COLUMN %s CASCADE',
                    SQL.identifier(model._table), SQL.identifier(field.name),
                ))
            if field.state == 'manual' and field.ttype == 'many2many':
                rel_name = field.relation_table or (is_model and model._fields[field.name].relation)
                tables_to_drop.add(rel_name)
        if field.state == 'manual' and is_model:
            model_cls = self.env.registry[model._name]
            pop_field(model_cls, field.name)

    if tables_to_drop:
        # drop the relation tables that are not used by other fields
        self.env.cr.execute("""SELECT relation_table FROM ir_model_fields
                                WHERE relation_table IN %s AND id NOT IN %s""",
                         (tuple(tables_to_drop), tuple(self.ids)))
        tables_to_keep = {row[0] for row in self.env.cr.fetchall()}
        for rel_name in tables_to_drop - tables_to_keep:
            self.env.cr.execute(SQL('DROP TABLE %s', SQL.identifier(rel_name)))

    return True


def _prepare_update(self):
    """ Check whether the fields in ``self`` may be modified or removed.
            This method prevents the modification/deletion of many2one fields
            that have an inverse one2many, for instance.
        """
    from odoo.orm.models.classes import pop_field  # noqa: PLC0415

    force_delete = self.env.context.get('force_delete')
    if not force_delete and any(record.state != 'manual' for record in self):
        raise UserError(_("This column contains module data and cannot be removed!"))

    records = self              # all the records to delete
    fields_ = OrderedSet()      # all the fields corresponding to 'records'
    failed_dependencies = []    # list of broken (field, dependent_field)

    for record in self:
        model = self.env.get(record.model)
        if model is None:
            continue
        field = model._fields.get(record.name)
        if field is None:
            continue
        fields_.add(field)
        for dep in self.pool.get_dependent_fields(field):
            if dep.manual:
                failed_dependencies.append((field, dep))
            elif dep.inherited:
                fields_.add(dep)
                records |= self._get(dep.model_name, dep.name)

    for field in fields_:
        for inverse in model.pool.field_inverses[field]:
            if inverse.manual and inverse.type == 'one2many':
                failed_dependencies.append((field, inverse))

    self = records

    if failed_dependencies:
        if not force_delete:
            field, dep = failed_dependencies[0]
            raise UserError(_(
                "The field '%(field)s' cannot be removed because the field '%(other_field)s' depends on it.",
                field=field, other_field=dep,
            ))
        else:
            self |= self.browse().union(
                self._get(dep.model_name, dep.name)
                for field, dep in failed_dependencies
            )

    records = self.filtered(lambda record: record.state == 'manual')
    if not records:
        return self

    # remove pending write of this field
    # DLE P16: if there are pending updates of the field we currently try to unlink, pop them out from the cache
    # test `test_unlink_with_dependant`
    for record in records:
        model = self.env.get(record.model)
        field = model and model._fields.get(record.name)
        if field:
            self.env._field_dirty.pop(field)
    # remove fields from registry, and check that views are not broken
    fields = [pop_field(self.env.registry[record.model], record.name) for record in records]
    domain = Domain.OR([('arch_db', 'like', record.name)] for record in records)
    views = self.env['ir.ui.view'].search(domain)
    try:
        for view in views:
            view._check_xml()
    except Exception:
        if not force_delete:
            raise UserError(_(
                "Cannot rename/delete fields that are still present in views:\nFields: %(fields)s\nView: %(view)s",
                fields=fields,
                view=view.name,
            ))
        else:
            # uninstall mode
            _logger.warning(
                "The following fields were force-deleted to prevent a registry crash %s the following view might be broken %s",
                ", ".join(str(f) for f in fields),
                view.name)
    finally:
        if not self.pool.uninstalling_modules:
            # the registry has been modified, restore it
            self.pool._setup_models__(self.env.cr)

    return self


def unlink(self):
    if not self:
        return True

    # prevent screwing up fields that depend on these fields
    self = self._prepare_update()

    # determine registry fields corresponding to self
    fields = OrderedSet()
    for record in self:
        try:
            fields.add(self.pool[record.model]._fields[record.name])
        except KeyError:
            pass

    # clean the registry from the fields to remove
    assert self.env.registry is self.pool
    self.env.transaction.will_change_registry()
    self.pool._discard_fields(fields)

    # discard the removed fields from fields to compute
    for field in fields:
        self.env.transaction.tocompute.pop(field, None)

    model_names = self.mapped('model')
    self._drop_column()
    res = super(IrModelFields, self).unlink()

    # The field we just deleted might be inherited, and the registry is
    # inconsistent in this case; therefore we reload the registry.
    # Beware: when renaming a field, method write() calls unlink() on the
    # corresponding inherited fields with 'force_delete' in context, and
    # method write() itself is in charge of cleaning up the registry. If
    # done here, the field to be renamed regenerates an inherited field
    # below, and we end up with two records for the inherited field: one
    # with the old name, and one with the new name.
    if not (self.env.context.get('force_delete') or self.pool.uninstalling_modules):
        # setup models; this re-initializes models in registry
        self.env.flush_all()
        self.pool._setup_models__(self.env.cr, model_names)
        # update database schema of model and its descendant models
        models = self.pool.descendants(model_names, '_inherits')
        self.pool.init_models(self.env.cr, models, dict(self.env.context, update_custom_fields=True))

    return res


def create(self, vals_list):
    IrModel = self.env['ir.model']
    for vals in vals_list:
        if 'index' in vals:
            vals['index'] = 'btree' if vals['index'] is True else vals['index'] or None
        if vals.get('translate') and not isinstance(vals['translate'], str):
            _logger.warning("Deprecated since Odoo 19, ir.model.fields.translate becomes Selection, the value should be a string")
            vals['translate'] = 'html_translate' if vals.get('ttype') == 'html' else 'standard'
        if 'model_id' in vals:
            model_from_id = IrModel.browse(vals['model_id']).model
            if vals.get('model', False):
                if vals['model'] != model_from_id:
                    raise ValidationError(_(
                        "Inconsistent values: model=%(model)s does not match model_id=%(model_id)s.",
                        model=vals['model'], model_id=vals['model_id'],
                    ))
            else:
                vals['model'] = model_from_id

    # for self._get_ids() in _update_selection()
    # we need to invalidate the cache before and after creation of the field
    self.env.transaction.invalidate_ormcache('stable')
    res = super(IrModelFields, self).create(vals_list)
    self.env.transaction.invalidate_ormcache('stable')
    models = OrderedSet(res.mapped('model'))

    for vals in vals_list:
        if vals.get('state', 'manual') == 'manual':
            relation = vals.get('relation')
            if relation and not IrModel._get_id(relation):
                raise UserError(_("Model %s does not exist!", vals['relation']))

            if (
                vals.get('ttype') == 'one2many' and
                vals.get("store", True) and
                not vals.get("related") and
                not self.search_count([
                    ('ttype', '=', 'many2one'),
                    ('model', '=', vals['relation']),
                    ('name', '=', vals['relation_field']),
                ])
            ):
                raise UserError(_("Many2one %(field)s on model %(model)s does not exist!", field=vals['relation_field'], model=vals['relation']))

    if any(model in self.pool for model in models):
        # setup models; this re-initializes model in registry
        self.env.flush_all()
        self.pool._setup_models__(self.env.cr, models)
        # update database schema of models and their descendants
        models = self.pool.descendants(models, '_inherits')
        self.pool.init_models(self.env.cr, models, dict(self.env.context, update_custom_fields=True))

    return res


def _get_writable_properties(self):
    return [fname for fname in self._fields if self._fields[fname].translate]


def write(self, vals):
    if not self:
        return True

    # if set, *one* column can be renamed here
    column_rename = None

    # names of the models to patch
    patched_models = set()

    writable_properties = self._get_writable_properties()
    writable_properties_only = all(field_name in writable_properties for field_name in vals)
    if vals and self and not writable_properties_only:
        for item in self:
            if item.state != 'manual':
                raise UserError(_('Properties of base fields cannot be altered in this manner! '
                                  'Please modify them through Python code, '
                                  'preferably through a custom addon!'))

            if vals.get('model_id', item.model_id.id) != item.model_id.id:
                raise UserError(_("Changing the model of a field is forbidden!"))

            if vals.get('ttype', item.ttype) != item.ttype:
                raise UserError(_("Changing the type of a field is not yet supported. "
                                  "Please drop it and create it again!"))

            obj = self.pool.get(item.model)
            field = getattr(obj, '_fields', {}).get(item.name)

            if vals.get('name', item.name) != item.name:
                # We need to rename the field
                item._prepare_update()
                if item.ttype in ('one2many', 'many2many', 'binary'):
                    # those field names are not explicit in the database!
                    pass
                else:
                    if column_rename:
                        raise UserError(_('Can only rename one field at a time!'))
                    column_rename = (obj._table, item.name, vals['name'], item.index, item.store)

            # We don't check the 'state', because it might come from the context
            # (thus be set for multiple fields) and will be ignored anyway.
            if obj is not None and field is not None:
                patched_models.add(obj._name)

    # These shall never be written (modified)
    for column_name in ('model_id', 'model', 'state'):
        if column_name in vals:
            del vals[column_name]

    if 'index' in vals:
        index = vals['index']
        vals['index'] = 'btree' if index is True or index == 'True' else index or None

    if vals.get('translate') and not isinstance(vals['translate'], str):
        _logger.warning("Deprecated since Odoo 19, ir.model.fields.translate becomes Selection, the value should be a string")
        vals['translate'] = 'html_translate' if vals.get('ttype') == 'html' else 'standard'

    if column_rename and self.state == 'manual':
        # renaming a studio field, remove inherits fields
        # we need to set the uninstall flag to allow removing them
        (self._prepare_update() - self).with_context(force_delete=True).unlink()

    res = super(IrModelFields, self).write(vals)

    self.env.flush_all()

    if column_rename:
        # rename column in database, and its corresponding index if present
        table, oldname, newname, index, stored = column_rename
        if stored:
            self.env.cr.execute(SQL(
                'ALTER TABLE %s RENAME COLUMN %s TO %s',
                SQL.identifier(table),
                SQL.identifier(oldname),
                SQL.identifier(newname)
            ))
            if index:
                self.env.cr.execute(SQL(
                    'ALTER INDEX %s RENAME TO %s',
                    SQL.identifier(f'{table}_{oldname}_index'),
                    SQL.identifier(f'{table}_{newname}_index'),
                ))

    if column_rename or patched_models or writable_properties_only:
        # setup models, this will reload all manual fields in registry
        self.env.flush_all()
        model_names = OrderedSet(self.mapped('model'))
        self.pool._setup_models__(self.env.cr, model_names)

    if patched_models:
        # update the database schema of the models to patch
        models = self.pool.descendants(patched_models, '_inherits')
        self.pool.init_models(self.env.cr, models, dict(self.env.context, update_custom_fields=True))

    return res
