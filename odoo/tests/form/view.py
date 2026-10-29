"""The form view: the parsing of the view architecture and the one2many edition views."""

from __future__ import annotations

import ast
from lxml import etree
from .utils import MODIFIER_ALIASES, get_static_context


def _process_view(self, tree, model, level=2):
    """ Post-processes to augment the view_get with:
    * an id field (may not be present if not in the view but needed)
    * pre-processed modifiers
    * pre-processed onchanges list
    """
    fields = {'id': {'type': 'id'}}
    fields_spec = {}
    modifiers = {'id': {'required': 'False', 'readonly': 'True'}}
    contexts = {}
    # retrieve <field> nodes at the current level
    flevel = tree.xpath('count(ancestor::field)')
    daterange_field_names = {}
    field_infos = self._models_info.get(model._name, {}).get("fields", {})

    for node in tree.xpath(f'.//field[count(ancestor::field) = {flevel}]'):
        field_name = node.get('name')

        # add field_info into fields
        field_info = field_infos.get(field_name) or {'type': None}
        fields[field_name] = field_info
        fields_spec[field_name] = field_spec = {}

        # determine modifiers
        field_modifiers = {}
        for attr in ('required', 'readonly', 'invisible', 'column_invisible'):
            # use python field attribute as default value
            default = attr in ('required', 'readonly') and field_info.get(attr, False)
            expr = node.get(attr) or str(default)
            field_modifiers[attr] = MODIFIER_ALIASES.get(expr, expr)

        # Combine the field modifiers with its ancestor modifiers with an
        # OR: A field is invisible if its own invisible modifier is True OR
        # if one of its ancestor invisible modifier is True
        for ancestor in node.xpath(f'ancestor::*[@invisible][count(ancestor::field) = {flevel}]'):
            modifier = 'invisible'
            expr = ancestor.get(modifier)
            if expr == 'True' or field_modifiers[modifier] == 'True':
                field_modifiers[modifier] = 'True'
            if expr == 'False':
                field_modifiers[modifier] = field_modifiers[modifier]
            elif field_modifiers[modifier] == 'False':
                field_modifiers[modifier] = expr
            else:
                field_modifiers[modifier] = f'({expr}) or ({field_modifiers[modifier]})'

        # merge field_modifiers into modifiers[field_name]
        if field_name in modifiers:
            # The field is several times in the view, combine the modifier
            # expression with an AND: a field is X if all occurences of the
            # field in the view are X.
            for modifier, expr in modifiers[field_name].items():
                if expr == 'False' or field_modifiers[modifier] == 'False':
                    field_modifiers[modifier] = 'False'
                if expr == 'True':
                    field_modifiers[modifier] = field_modifiers[modifier]
                elif field_modifiers[modifier] == 'True':
                    field_modifiers[modifier] = expr
                else:
                    field_modifiers[modifier] = f'({expr}) and ({field_modifiers[modifier]})'

        modifiers[field_name] = field_modifiers

        # determine context
        ctx = node.get('context')
        if ctx:
            contexts[field_name] = ctx
            field_spec['context'] = get_static_context(ctx)

        # FIXME: better widgets support
        # NOTE: selection breaks because of m2o widget=selection
        if node.get('widget') in ['many2many']:
            field_info['type'] = node.get('widget')
        elif node.get('widget') == 'daterange':
            options = ast.literal_eval(node.get('options', '{}'))
            related_field = options.get('start_date_field') or options.get('end_date_field')
            daterange_field_names[related_field] = field_name

        # determine subview to use for edition
        if field_info['type'] == 'one2many':
            if level:
                field_info['invisible'] = field_modifiers.get('invisible')
                edition_view = self._get_one2many_edition_view(field_info, node, level)
                field_info['edition_view'] = edition_view
                field_spec['fields'] = edition_view['fields_spec']
            else:
                # this trick enables the following invariant: every one2many
                # field has some 'edition_view' in its info dict
                field_info['type'] = 'many2many'

    for related_field, start_field in daterange_field_names.items():
        # If the field doesn't exist in the view add it implicitly
        if related_field not in modifiers:
            field_info = field_infos.get(related_field) or {'type': None}
            fields[related_field] = field_info
            fields_spec[related_field] = {}
            modifiers[related_field] = {
                'required': field_info.get('required', False),
                'readonly': field_info.get('readonly', False),
            }
        modifiers[related_field]['invisible'] = modifiers[start_field].get('invisible', False)

    return {
        'tree': tree,
        'fields': fields,
        'fields_spec': fields_spec,
        'modifiers': modifiers,
        'contexts': contexts,
        'onchange': model._onchange_spec({'arch': etree.tostring(tree)}),
    }


def _get_one2many_edition_view(self, field_info, node, level):
    """ Return a suitable view for editing records into a one2many field. """
    submodel = self._env[field_info['relation']]

    # by simplicity, ensure we always have tree and form views
    views = {
        view.tag: view for view in node.xpath('./*[descendant::field]')
    }
    for view_type in ['list', 'form']:
        if view_type in views:
            continue
        if field_info['invisible'] == 'True':
            # add an empty view
            views[view_type] = etree.Element(view_type)
            continue
        refs = self._env['ir.ui.view']._get_view_refs(node)
        subviews = submodel.with_context(**refs).get_views([(None, view_type)])
        subnode = etree.fromstring(subviews['views'][view_type]['arch'])
        views[view_type] = subnode
        node.append(subnode)
        for model_name, value in subviews['models'].items():
            model_info = self._models_info.setdefault(model_name, {})
            if "fields" not in model_info:
                model_info["fields"] = {}
            model_info["fields"].update(value["fields"])

    # pick the first editable subview
    view_type = next(
        vtype for vtype in node.get('mode', 'list').split(',') if vtype != 'form'
    )
    if not (view_type == 'list' and views['list'].get('editable')):
        view_type = 'form'

    # don't recursively process o2ms in o2ms
    return self._process_view(views[view_type], submodel, level=level-1)
