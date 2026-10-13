# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The computed values and the onchanges of the fields: the relations, the selections, the copies, the index types and the display names."""

from __future__ import annotations

from ast import literal_eval
from odoo import models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.text.translate import _


def _compute_relation_field_id(self):
    for rec in self:
        if rec.state == 'manual' and rec.relation_field:
            rec.relation_field_id = self._get(rec.relation, rec.relation_field)
        else:
            rec.relation_field_id = False


def _compute_related_field_id(self):
    for rec in self:
        if rec.state == 'manual' and rec.related:
            rec.related_field_id = rec._related_field()
        else:
            rec.related_field_id = False


def _compute_selection(self):
    for rec in self:
        if rec.ttype in ('selection', 'reference'):
            rec.selection = str(self.env['ir.model.fields.selection']._get_selection(rec.id))
        else:
            rec.selection = False


def _inverse_selection(self):
    for rec in self:
        selection = literal_eval(rec.selection or "[]")
        self.env['ir.model.fields.selection']._update_selection(rec.model, rec.name, selection)


def _compute_copied(self):
    for rec in self:
        rec.copied = (rec.ttype != 'one2many') and not (rec.related or rec.compute)


def _get_allowed_index_types(self):
    self.ensure_one()
    if not self.store or self.ttype in ('one2many', 'many2many'):
        return []

    allowed = [] if self.translate else ['btree', 'btree_not_null']
    if (
        self.ttype in ('char', 'text', 'html')
        and not self.company_dependent
        and self.env.registry.has_trigram
    ):
        allowed.append('trigram')
    return allowed


def _compute_allowed_index_types(self):
    for field in self:
        field.allowed_index_types = field._get_allowed_index_types()


def _onchange_index(self):
    for field in self:
        if field.index and field.index not in field._get_allowed_index_types():
            field.index = False


def _in_modules(self):
    installed_modules = self.env['ir.module.module'].search([('state', '=', 'installed')])
    installed_names = set(installed_modules.mapped('name'))
    xml_ids = models.Model._get_external_ids(self)
    for field in self:
        module_names = set(xml_id.split('.')[0] for xml_id in xml_ids[field.id])
        field.modules = ", ".join(sorted(installed_names & module_names))


def _onchange_related(self):
    if self.related:
        try:
            field = self._related_field()
        except UserError as e:
            return {'warning': {'title': _("Warning"), 'message': e}}
        self.ttype = field.ttype
        self.relation = field.relation
        self.readonly = True


def _onchange_relation(self):
    try:
        self._check_relation()
    except ValidationError as e:
        return {'warning': {'title': _("Model %s does not exist", self.relation), 'message': e}}


def _onchange_compute(self):
    if self.compute:
        self.readonly = True


def _custom_many2many_names(self, model_name, comodel_name):
    """ Return default names for the table and columns of a custom many2many field. """
    rel1 = self.env[model_name]._table
    rel2 = self.env[comodel_name]._table
    table = 'x_%s_%s_rel' % tuple(sorted([rel1, rel2]))
    if rel1 == rel2:
        return (table, 'id1', 'id2')
    else:
        return (table, '%s_id' % rel1, '%s_id' % rel2)


def _onchange_ttype(self):
    if self.ttype == 'many2many' and self.model_id and self.relation:
        if self.relation not in self.env:
            return
        names = self._custom_many2many_names(self.model_id.model, self.relation)
        self.relation_table, self.column1, self.column2 = names
    else:
        self.relation_table = False
        self.column1 = False
        self.column2 = False


def _onchange_relation_table(self):
    if self.relation_table:
        # check whether other fields use the same table
        others = self.search([('ttype', '=', 'many2many'),
                              ('relation_table', '=', self.relation_table),
                              ('id', 'not in', self.ids)])
        if others:
            for other in others:
                if (other.model, other.relation) == (self.relation, self.model):
                    # other is a candidate inverse field
                    self.column1 = other.column2
                    self.column2 = other.column1
                    return
            return {'warning': {
                'title': _("Warning"),
                'message': _("The table “%s” is used by another, possibly incompatible field(s).", self.relation_table),
            }}


def _compute_display_name(self):
    IrModel = self.env["ir.model"]
    for field in self:
        if self.env.context.get('hide_model'):
            field.display_name = field.field_description
            continue
        model_string = IrModel._get(field.model).name
        field.display_name = f'{field.field_description} ({model_string})'
