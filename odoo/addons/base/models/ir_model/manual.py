# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The manual fields: their reflection in the registry and the translations and selections of the fields."""

from __future__ import annotations

from collections import defaultdict
from odoo import fields
from odoo.tools import frozendict, unique
from odoo.tools.safe_eval import expr_eval
from odoo.tools.text.translate import FIELD_TRANSLATE
from .helpers import field_xmlid, make_compute, mark_modified, select_en, upsert_en

from .field import _logger

def _reflect_field_params(self, field, model_id):
    """ Return the values to write to the database for the given field. """
    translate = next(k for k, v in FIELD_TRANSLATE.items() if v == field.translate)
    return {
        'model_id': model_id,
        'model': field.model_name,
        'name': field.name,
        'field_description': field.string,
        'help': field.help or None,
        'ttype': field.type,
        'state': 'manual' if field.manual else 'base',
        'relation': field.comodel_name if field.relational else None,
        'index': 'btree' if field.index is True else field.index or None,
        'store': bool(field.store),
        'copied': bool(field.copy),
        'on_delete': field.ondelete if field.type == 'many2one' else None,
        'related': field.related or None,
        'readonly': bool(field.readonly),
        'required': bool(field.required),
        'selectable': bool(field.search or field.store),
        'size': getattr(field, 'size', None),
        'translate': translate,
        'company_dependent': bool(field.company_dependent),
        'relation_field': field.inverse_name if field.type == 'one2many' else None,
        'relation_model_field': field.model_field if field.type == "many2one_reference" else None,
        'relation_table': field.relation if field.type == 'many2many' else None,
        'column1': field.column1 if field.type == 'many2many' else None,
        'column2': field.column2 if field.type == 'many2many' else None,
        'currency_field': field.currency_field if field.type == 'monetary' else None,
        # html sanitization attributes (useless for other fields)
        'sanitize': field.sanitize if field.type == 'html' else None,
        'sanitize_overridable': field.sanitize_overridable if field.type == 'html' else None,
        'sanitize_tags': field.sanitize_tags if field.type == 'html' else None,
        'sanitize_attributes': field.sanitize_attributes if field.type == 'html' else None,
        'sanitize_style': field.sanitize_style if field.type == 'html' else None,
        'sanitize_form': field.sanitize_form if field.type == 'html' else None,
        'strip_style': field.strip_style if field.type == 'html' else None,
        'strip_classes': field.strip_classes if field.type == 'html' else None,
    }


def _reflect_fields(self, model_names):
    """ Reflect the fields of the given models. """

    for model_name in model_names:
        model = self.env[model_name]
        by_label = {}
        for field in model._fields.values():
            if field.string in by_label:
                other = by_label[field.string]
                _logger.warning('Two fields (%s, %s) of %s have the same label: %s. [Modules: %s and %s]',
                                field.name, other.name, model, field.string, field._module, other._module)
            else:
                by_label[field.string] = field

    # determine expected and existing rows
    rows = []
    for model_name in model_names:
        model_id = self.env['ir.model']._get_id(model_name)
        for field in self.env[model_name]._fields.values():
            rows.append(self._reflect_field_params(field, model_id))
    if not rows:
        return
    cols = list(unique(['model', 'name'] + list(rows[0])))
    expected = [tuple(row[col] for col in cols) for row in rows]

    field_ids = {}
    existing = {}
    for row in select_en(self, ['id'] + cols, model_names):
        field_ids[row[1:3]] = row[0]
        existing[row[1:3]] = row[1:]

    # create or update rows
    rows = [row for row in expected if existing.get(row[:2]) != row]
    if rows:
        ids = upsert_en(self, cols, rows, ['model', 'name'])
        for row, id_ in zip(rows, ids):
            field_ids[row[:2]] = id_
        self.pool.post_init(mark_modified, self.browse(ids), cols[2:])

    # update their XML id
    module = self.env.context.get('module')
    if not module:
        return

    data_list = []
    for (field_model, field_name), field_id in field_ids.items():
        model = self.env[field_model]
        field = model._fields.get(field_name)
        if field and (
            module == model._original_module
            or module in field._modules
            or any(
                # module introduced field on model by inheritance
                field_name in self.env[parent]._fields
                for parent, parent_module in model._inherit_module.items()
                if module == parent_module
            )
        ):
            xml_id = field_xmlid(module, field_model, field_name)
            record = self.browse(field_id)
            data_list.append({'xml_id': xml_id, 'record': record})
    self.env['ir.model.data']._update_xmlids(data_list)


def _reflect_field_groups(self, model_names):
    """ Synchronize the groups field based on the 'groups' attribute declared
        in the model field's definitions.

        This looks up the external IDs declared in Python (e.g.
        `test_field = fields.Char(...,groups='base.group_user'))`, retrieves the
        corresponding group records, and updates the 'ir_model_fields_group_rel'
        relation.
        """
    if not model_names:
        return

    def lookup_group(field, xmlid):
        try:
            model, res_id = self.env['ir.model.data']._xmlid_lookup(xmlid)
        except ValueError:
            raise ValueError(f"{field} failed to lookup group xmlid {xmlid}")
        assert model == 'res.groups' and res_id, "In"
        return res_id

    model_ids = [self.env['ir.model']._get_id(model_name) for model_name in model_names]
    existing = {
        (field.id, group.id)
        for field in self.sudo().search([('model_id', 'in', model_ids)])
        for group in field.groups
    }

    expected = set()
    for model_name in model_names:
        field_ids = self.env['ir.model.fields']._get_ids(model_name)
        for field in self.env[model_name]._fields.values():
            if not field.groups or field.groups == fields.NO_ACCESS:
                continue
            field_id = field_ids[field.name]
            expected.update(
                (field_id, lookup_group(field, xmlid))
                for xmlid in field.groups.split(',')
                if xmlid[0] != '!'  # ignore negative group specifications
            )

    self.invalidate_model(['groups'])
    if to_add := sorted(expected - existing):
        self.env.cr.execute("""
                INSERT INTO ir_model_fields_group_rel(field_id, group_id)
                SELECT * FROM UNNEST(%s, %s)
            """, [list(array) for array in zip(*to_add)])
    if to_remove := sorted(existing - expected):
        self.env.cr.execute("""
            DELETE FROM ir_model_fields_group_rel rel
            WHERE EXISTS (
                SELECT FROM UNNEST(%s, %s) AS rm(field_id, group_id)
                WHERE rm.field_id = rel.field_id AND rm.group_id = rel.group_id
            )
            """, [list(array) for array in zip(*to_remove)])


def _all_manual_field_data(self):
    cr = self.env.cr
    # we cannot use self._fields to determine translated fields, as it has not been set up yet
    cr.execute("""
            SELECT *, field_description->>'en_US' AS field_description, help->>'en_US' AS help
            FROM ir_model_fields
            WHERE state = 'manual'
        """)
    result = defaultdict(dict)
    for row in cr.dictfetchall():
        result[row['model']][row['name']] = row
    return result


def _get_manual_field_data(self, model_name):
    """ Return the given model's manual field data. """
    return self._all_manual_field_data().get(model_name, {})


def _instanciate_attrs(self, field_data):
    """ Return the parameters for a field instance for ``field_data``. """
    attrs = {
        'manual': True,
        'string': field_data['field_description'],
        'help': field_data['help'],
        'index': field_data['index'],
        'copy': bool(field_data['copied']),
        'related': field_data['related'],
        'required': bool(field_data['required']),
        'readonly': bool(field_data['readonly']),
        'store': bool(field_data['store']),
        'company_dependent': bool(field_data['company_dependent']),
    }
    if field_data['ttype'] in ('char', 'text', 'html'):
        attrs['translate'] = FIELD_TRANSLATE.get(
            field_data['translate'],
            True
        )
        if field_data['ttype'] == 'char':
            attrs['size'] = field_data['size'] or None
            if attrs['copy']:
                attrs.pop('copy')  # use the default setting for "(copy)"
        elif field_data['ttype'] == 'html':
            attrs['sanitize'] = field_data['sanitize']
            attrs['sanitize_overridable'] = field_data['sanitize_overridable']
            attrs['sanitize_tags'] = field_data['sanitize_tags']
            attrs['sanitize_attributes'] = field_data['sanitize_attributes']
            attrs['sanitize_style'] = field_data['sanitize_style']
            attrs['sanitize_form'] = field_data['sanitize_form']
            attrs['strip_style'] = field_data['strip_style']
            attrs['strip_classes'] = field_data['strip_classes']
    elif field_data['ttype'] in ('selection', 'reference'):
        if not attrs['related']:
            attrs['selection'] = self.env['ir.model.fields.selection']._get_selection_data(field_data['id'])
        if field_data['ttype'] == 'selection':
            attrs['group_expand'] = field_data['group_expand']
    elif field_data['ttype'] == 'many2one':
        if not self.pool.loaded and field_data['relation'] not in self.env:
            return
        attrs['comodel_name'] = field_data['relation']
        attrs['ondelete'] = field_data['on_delete']
        attrs['domain'] = expr_eval(field_data['domain'] or '[]')
        attrs['group_expand'] = '_read_group_expand_full' if field_data['group_expand'] else None
    elif field_data['ttype'] == 'one2many':
        if not self.pool.loaded and not (
            field_data['relation'] in self.env and (
                field_data['relation_field'] in self.env[field_data['relation']]._fields or
                field_data['relation_field'] in self._get_manual_field_data(field_data['relation'])
        )):
            return
        attrs['comodel_name'] = field_data['relation']
        attrs['inverse_name'] = field_data['relation_field']
        attrs['domain'] = expr_eval(field_data['domain'] or '[]')
    elif field_data['ttype'] == 'many2many':
        if not self.pool.loaded and field_data['relation'] not in self.env:
            return
        attrs['comodel_name'] = field_data['relation']
        rel, col1, col2 = self._custom_many2many_names(field_data['model'], field_data['relation'])
        attrs['relation'] = field_data['relation_table'] or rel
        attrs['column1'] = field_data['column1'] or col1
        attrs['column2'] = field_data['column2'] or col2
        attrs['domain'] = expr_eval(field_data['domain'] or '[]')
    elif field_data['ttype'] == 'monetary':
        # be sure that custom monetary field are always instanciated
        if not self.pool.loaded and \
            field_data['currency_field'] and not self._is_manual_name(field_data['currency_field']):
            return
        attrs['currency_field'] = field_data['currency_field']
    # add compute function if given
    if field_data['compute']:
        attrs['compute'] = make_compute(field_data['compute'], field_data['depends'])
    return attrs


def _is_manual_name(self, name):
    return name.startswith('x_')


def get_field_string(self, model_name):
    """ Return the translation of fields strings in the context's language.
        Note that the result contains the available translations only.

        :param model_name: the name of a model
        :return: the model's fields' strings as a dictionary `{field_name: field_string}`
        """
    return {
        field_name: values['field_description']
        for field_name, values in self._get_fields_cached(model_name).items()
    }


def get_field_help(self, model_name):
    """ Return the translation of fields help in the context's language.
        Note that the result contains the available translations only.

        :param model_name: the name of a model
        :return: the model's fields' help as a dictionary `{field_name: field_help}`
        """
    return {
        field_name: values['help']
        for field_name, values in self._get_fields_cached(model_name).items()
    }


def get_field_selection(self, model_name, field_name):
    """ Return the translation of a field's selection in the context's language.
        Note that the result contains the available translations only.

        :param model_name: the name of the field's model
        :param field_name: the name of the field
        :return: the fields' selection as a list
        """
    return self._get_fields_cached(model_name).get(field_name, {}).get('selection', [])


def _get_fields_cached(self, model_name):
    """ Return the translated information of all model field's in the context's language.
        Note that the result contains the available translations only.

        :param model_name: the name of the field's model
        :return: {field_name: {id, help, field_description, [selection]}}
        """
    fields = self.sudo().browse(self._get_ids(model_name).values())
    result = {
        field.name: {
            'id': field.id,
            'help': field.help,
            'field_description': field.field_description,
        }
        for field in fields
    }
    for field in fields.filtered(lambda field: field.ttype in ('selection', 'reference')):
        result[field.name]['selection'] = [
            (sel.value, sel.name) for sel in field.selection_ids
        ]
    return frozendict(result)
