# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The checks of the fields: their indexes, names, related fields, relations, dependencies, currencies and delete actions."""

from __future__ import annotations

from odoo import models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import expr_eval
from odoo.tools.text.translate import _


def _check_index(self):
    for field in self:
        if field.state != 'manual' or not field.index:
            continue
        if not field.store or field.ttype in ('one2many', 'many2many'):
            raise ValidationError(_("Only stored fields with a database column can be indexed."))
        if field.translate and field.index != 'trigram':
            raise ValidationError(_("Translated fields only support trigram indexes."))
        if field.index == 'trigram':
            if field.ttype not in ('char', 'text', 'html') or field.company_dependent:
                raise ValidationError(_("Trigram indexes are only supported on stored Char, Text, and HTML fields."))
            if not field.env.registry.has_trigram:
                raise ValidationError(_("Trigram indexes require the PostgreSQL pg_trgm extension."))


def _check_domain(self):
    for field in self:
        try:
            expr_eval(field.domain or '[]')
        except Exception as e:  # noqa: BLE001
            raise ValidationError(
                _("An error occurred while evaluating the domain:\n%(error)s", error=e)
            ) from e


def _check_name(self):
    for field in self:
        try:
            models.check_pg_name(field.name)
        except ValidationError:
            msg = _("Field names can only contain characters, digits and underscores (up to 63).")
            raise ValidationError(msg)


def _related_field(self):
    """ Return the ``ir.model.fields`` record corresponding to ``self.related``. """
    names = self.related.split(".")
    last = len(names) - 1
    model_name = self.model or self.model_id.model
    for index, name in enumerate(names):
        field = self._get(model_name, name)
        if not field:
            raise UserError(_(
                'Unknown field name "%(field_name)s" in related field "%(related_field)s"',
                field_name=name,
                related_field=self.related,
            ))
        if index < last and not field.relation:
            raise UserError(_(
                'Non-relational field name "%(field_name)s" in related field "%(related_field)s"',
                field_name=name,
                related_field=self.related,
            ))
        if index < last and self.env.registry.ready and not (
            field.store or (
                (model := self.env.get(model_name)) is not None
                and (model_field := model._fields.get(field.name))
                and model_field._description_searchable
            )
        ):
            raise UserError(_(
                'Field "%(field_name)s" in related path "%(related_field)s" is not searchable. '
                'Non-searchable fields cannot be used in related fields.',
                field_name=name,
                related_field=self.related,
            ))
        model_name = field.relation
    return field


def _check_related(self):
    for rec in self:
        if rec.state == 'manual' and rec.related:
            field = rec._related_field()
            if field.ttype != rec.ttype:
                raise ValidationError(_(
                    'Related field "%(related_field)s" does not have type "%(type)s"',
                    related_field=rec.related,
                    type=rec.ttype,
                ))
            if field.relation != rec.relation:
                raise ValidationError(_(
                    'Related field "%(related_field)s" does not have comodel "%(comodel)s"',
                    related_field=rec.related,
                    comodel=rec.relation,
                ))


def _check_relation(self):
    for rec in self:
        if rec.state == 'manual' and rec.relation and not rec.env['ir.model']._get_id(rec.relation):
            raise ValidationError(_("Unknown model name '%s' in Related Model", rec.relation))


def _check_depends(self):
    """ Check whether all fields in dependencies are valid. """
    for record in self:
        if not record.depends:
            continue
        for seq in record.depends.split(","):
            if not seq.strip():
                raise UserError(_("Empty dependency in “%s”", record.depends))
            model = self.env[record.model]
            names = seq.strip().split(".")
            last = len(names) - 1
            for index, name in enumerate(names):
                if name == 'id':
                    raise UserError(_("Compute method cannot depend on field 'id'"))
                field = model._fields.get(name)
                if field is None:
                    raise UserError(_(
                        'Unknown field “%(field)s” in dependency “%(dependency)s”',
                        field=name,
                        dependency=seq.strip(),
                    ))
                if index < last and not field.relational:
                    raise UserError(_(
                        'Non-relational field “%(field)s” in dependency “%(dependency)s”',
                        field=name,
                        dependency=seq.strip(),
                    ))
                model = model[name]


def _check_relation_table(self):
    for rec in self:
        if rec.relation_table:
            models.check_pg_name(rec.relation_table)


def _check_relation_field(self):
    if any(
        (rec := record).state == 'manual'
        and rec.ttype == 'one2many'
        and rec.relation_field
        and not self._get(rec.relation, rec.relation_field)
        for record in self
    ):
        raise ValidationError(_(
            "Unknown field “%(field)s” on model “%(model)s” in Relation Field",
            field=rec.relation_field,
            model=rec.relation,
        ))


def _check_currency_field(self):
    for rec in self:
        if rec.state == 'manual' and rec.ttype == 'monetary':
            if not rec.currency_field:
                currency_field = self._get(rec.model, 'currency_id') or self._get(rec.model, 'x_currency_id')
                if not currency_field:
                    raise ValidationError(_("Currency field is empty and there is no fallback field in the model"))
            else:
                currency_field = self._get(rec.model, rec.currency_field)
                if not currency_field:
                    raise ValidationError(_("Unknown field specified “%s” in currency_field", rec.currency_field))

            if currency_field.ttype != 'many2one':
                raise ValidationError(_("Currency field does not have type many2one"))
            if currency_field.relation != 'res.currency':
                raise ValidationError(_("Currency field should have a res.currency relation"))


def _check_on_delete_required_m2o(self):
    for rec in self:
        if rec.ttype == 'many2one' and rec.required and rec.on_delete == 'set null':
            raise ValidationError(_(
                "The m2o field %s is required but declares its ondelete policy "
                "as being 'set null'. Only 'restrict' and 'cascade' make sense.", rec.name,
            ))
