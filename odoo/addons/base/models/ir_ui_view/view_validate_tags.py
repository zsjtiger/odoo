"""The validation of the tags of the views: the nodes of each kind of view and their attributes."""

from __future__ import annotations

import inspect
import re
from lxml import etree
from lxml.builder import E
from odoo.tools import _
from .helpers import QUARTER_PERIODS, RELATIVE_PERIODS, att_names
from .name_manager import NameManager


def _validate_view(self, node, model_name, view_type=None, editable=True, node_info=None):
    """ Validate the given architecture node, and return its corresponding
        NameManager.

        :param self: the view being validated
        :param node: the combined architecture as an etree
        :param model_name: the reference model name for the given architecture
        :param view_type:
        :param editable: whether the view is considered editable
        :param node_info:
        :return: the combined architecture's NameManager
        """
    self.ensure_one()

    view_type = view_type or self.type
    if node.tag != view_type:
        self._raise_view_error(_(
            'The root node of a %(view_type)s view should be a <%(view_type)s>, not a <%(tag)s>',
            view_type=view_type, tag=node.tag,
        ), node)

    if model_name not in self.env:
        self._raise_view_error(_('Model not found: %(model)s', model=model_name), node)

    group_definitions = self.env['res.groups']._get_group_definitions()

    # model_groups/view_groups: access groups for the model/view
    validate = node_info['validate'] if node_info else False
    model_groups = node_info['model_groups'] if node_info else group_definitions.universe
    view_groups = node_info['view_groups'] if node_info else group_definitions.universe
    parent_name_manager = node_info['name_manager'] if node_info else None

    # combine model access groups with this model's access groups
    model_groups &= self._get_access_groups(group_definitions, model_name)

    # fields_get() optimization: validation does not require translations
    model = self.env[model_name].with_context(lang=None)
    name_manager = NameManager(model, parent=parent_name_manager, model_groups=model_groups)

    view_type = node.tag
    # use a stack to recursively traverse the tree
    stack = [(node, view_groups, editable, validate)]
    while stack:
        node, view_groups, editable, validate = stack.pop()

        # compute default
        tag = node.tag
        validate = validate or node.get('__validate__')
        node_info = {
            'editable': editable and self._editable_node(node, name_manager),
            'validate': validate,
            'view_type': view_type,
            'model_groups': model_groups,
            'view_groups': view_groups,
            'name_manager': name_manager,
        }

        if groups := node.get('groups'):
            for group_name in groups.replace('!', '').split(','):
                name_manager.must_exist_group(group_name, node)
            node_info['view_groups'] &= group_definitions.parse(groups, raise_if_not_found=False)

        # tag-specific validation
        validator = getattr(self, f"_validate_tag_{tag}", None)
        if validator is not None:
            validator(node, name_manager, node_info)

        if validate:
            self._validate_attributes(node, name_manager, node_info)

        for child in reversed(node):
            stack.append((child, node_info['view_groups'], node_info['editable'], validate))

    name_manager.check(self)

    return name_manager


def _validate_tag_form(self, node, name_manager, node_info):
    pass


def _validate_tag_list(self, node, name_manager, node_info):
    # reuse form view validation
    self._validate_tag_form(node, name_manager, node_info)
    if not node_info['validate']:
        return
    # inline list views inside form views aren't rng validated, so we must validate the
    # editable attribute in python
    editable_attr = node.get("editable")
    if editable_attr and editable_attr not in ["top", "bottom"]:
        msg = _(
            'The "editable" attribute of list views must be "top" or "bottom", received %(value)s',
            value=editable_attr,
        )
        self._raise_view_error(msg, node)
    allowed_tags = ('field', 'button', 'control', 'groupby', 'widget', 'header', 'column')
    for child in node.iterchildren(tag=etree.Element):
        if child.tag not in allowed_tags and not isinstance(child, etree._Comment):
            msg = _(
                'List child can only have one of %(tags)s tag (not %(wrong_tag)s)',
                tags=', '.join(allowed_tags), wrong_tag=child.tag,
            )
            self._raise_view_error(msg, child)


def _validate_tag_graph(self, node, name_manager, node_info):
    if not node_info['validate']:
        return
    for child in node.iterchildren(tag=etree.Element):
        if child.tag != 'field' and not isinstance(child, etree._Comment):
            msg = _('A <graph> can only contains <field> nodes, found a <%s>', child.tag)
            self._raise_view_error(msg, child)


def _validate_tag_calendar(self, node, name_manager, node_info):
    for additional_field in ('date_start', 'date_stop', 'color', 'all_day'):
        if fnames := node.get(additional_field):
            name_manager.has_field(node, fnames.split('.', 1)[0], node_info)
    for f in node:
        if f.tag == 'filter':
            name_manager.has_field(node, f.get('name'), node_info)


def _validate_tag_search(self, node, name_manager, node_info):
    if node_info['validate'] and not node.iterdescendants(tag="field"):
        # the field of the search view may be within a group node, which is why we must check
        # for all descendants containing a node with a field tag, if this is not the case
        # then a search is not possible.
        self._log_view_warning('Search tag requires at least one field element', node)

    searchpanels = [child for child in node if child.tag == 'searchpanel']
    if searchpanels:
        if len(searchpanels) > 1:
            self._raise_view_error(_('Search tag can only contain one search panel'), node)
        node.remove(searchpanels[0])
        self._validate_view(searchpanels[0], name_manager.model._name, view_type="searchpanel",
                            node_info=node_info, editable=False)


def _validate_tag_field(self, node, name_manager, node_info):
    validate = node_info['validate']

    name = node.get('name')
    if not name:
        self._raise_view_error(_("Field tag must have a \"name\" attribute defined"), node)

    field = name_manager.model._fields.get(name)
    if field:
        if field.groups:
            group_definitions = self.env['res.groups']._get_group_definitions()
            node_info['model_groups'] &= group_definitions.parse(field.groups, raise_if_not_found=False)

        if validate and field.relational:
            domain = (
                node.get('domain')
                or node_info['editable'] and field._description_domain(self.env)
            )
            if isinstance(domain, str):
                # dynamic domain: in [('foo', '=', bar)], field 'foo' must
                # exist on the comodel and field 'bar' must be in the view
                desc = (f'domain of <field name="{name}">' if node.get('domain')
                        else f"domain of python field {name!r}")
                self._validate_domain_identifiers(node, name_manager, domain, desc, field.comodel_name, node_info)

        elif validate and node.get('domain'):
            msg = _(
                'Domain on non-relational field "%(name)s" makes no sense (domain:%(domain)s)',
                name=name, domain=node.get('domain'),
            )
            self._raise_view_error(msg, node)

        if field.type == 'properties' and node_info['view_type'] != 'search':
            name_manager.must_have_fields(node, {field._description_definition_record}, node_info, use=f"definition record of {field.name}")

        for child in node:
            if child.tag not in ('form', 'list', 'graph', 'kanban', 'calendar'):
                continue
            node.remove(child)
            self._validate_view(
                child, field.comodel_name, view_type=child.tag, editable=node_info['editable'],
                node_info=node_info,
            )

    elif validate and name not in name_manager.field_info:
        msg = _(
            'Field "%(field_name)s" does not exist in model "%(model_name)s"',
            field_name=name, model_name=name_manager.model._name,
        )
        self._raise_view_error(msg, node)

    name_manager.has_field(node, name, node_info, {'id': node.get('id'), 'select': node.get('select')})


def _validate_tag_filter(self, node, name_manager, node_info):
    if not node_info['validate']:
        return
    domain = node.get('domain')
    if domain:
        name = node.get('name')
        desc = f'domain of <filter name="{name}">' if name else 'domain of <filter>'
        self._validate_domain_identifiers(node, name_manager, domain, desc, name_manager.model._name, node_info)
    if node.get("end_date") and not node.get("date"):
        self._raise_view_error(_('Attribute "end_date" requires a "date" attribute'), node)
    for attribute in ("date", "end_date"):
        field_name = node.get(attribute)
        if not field_name:
            continue
        field = name_manager.model._fields.get(field_name)
        if field:
            if field.type not in ('date', 'datetime'):
                msg = _(
                    'Field "%(field_name)s" in attribute "%(attribute)s" must be a date or datetime field',
                    field_name=field_name, attribute=attribute,
                )
                self._raise_view_error(msg, node)
            if not field._description_searchable:
                msg = _(
                    'Unsearchable field "%(field_name)s" in attribute "%(attribute)s"',
                    field_name=field_name, attribute=attribute,
                )
                self._raise_view_error(msg, node)
        else:
            msg = _(
                'Field "%(field_name)s" does not exist in model "%(model_name)s"',
                field_name=field_name, model_name=name_manager.model._name,
            )
            self._raise_view_error(msg, node)
    if node.get("date") and (default_periods := node.get("default_period")):
        custom_options = {f'custom_{child.attrib["name"]}' for child in node.getchildren()}
        for default_period in default_periods.split(","):
            if not re.fullmatch(r"(year|month)((-|\+)[1-9]\d*)?", default_period)\
                and default_period not in custom_options | QUARTER_PERIODS | RELATIVE_PERIODS:
                msg = _(
                    "Invalid default period %(default_period)s for date filter",
                    default_period=default_period,
                )
                self._raise_view_error(msg, node)


def _validate_tag_button(self, node, name_manager, node_info):
    if not node_info['validate']:
        return
    name = node.get('name')
    special = node.get('special')
    type_ = node.get('type')
    if special:
        if special not in ('cancel', 'save', 'add'):
            self._raise_view_error(_("Invalid special '%(value)s' in button", value=special), node)
    elif type_:
        if type_ != 'action' and type_ != 'object':
            return
        elif not name:
            return
        elif type_ == 'object':
            func = getattr(name_manager.model, name, None)
            if not func:
                msg = _(
                    "%(action_name)s is not a valid action on %(model_name)s",
                    action_name=name, model_name=name_manager.model._name,
                )
                self._raise_view_error(msg, node)
            # get_public_method(name_manager.model, name) is too slow for this validation, a more naive check is acceptable.
            if name.startswith('_') or (hasattr(func, '_api_private') and func._api_private):
                msg = _(
                    "%(method)s on %(model)s is private and cannot be called from a button",
                    method=name, model=name_manager.model._name,
                )
                self._raise_view_error(msg, node)
            try:
                inspect.signature(func).bind()
            except TypeError:
                msg = "%s on %s has parameters and cannot be called from a button"
                self._log_view_warning(msg % (name, name_manager.model._name), node)
        elif type_ == 'action':
            name_manager.must_exist_action(name, node)

        name_manager.has_action(name)

    if node.get('icon'):
        description = 'A button with icon attribute (%s)' % node.get('icon')
        self._validate_data_icon_accessibility(node, description)


def _validate_tag_groupby(self, node, name_manager, node_info):
    # groupby nodes should be considered as nested view because they may
    # contain fields on the comodel
    name = node.get('name')
    if not name:
        return
    field = name_manager.model._fields.get(name)
    if field:
        if node_info['validate']:
            if field.type != 'many2one':
                msg = _(
                    "Field '%(name)s' found in 'groupby' node can only be of type many2one, found %(type)s",
                    name=field.name, type=field.type,
                )
                self._raise_view_error(msg, node)
            domain = node_info['editable'] and field._description_domain(self.env)
            if isinstance(domain, str):
                desc = f"domain of python field '{name}'"
                self._validate_domain_identifiers(node, name_manager, domain, desc, field.comodel_name, node_info)

        # move all children nodes into a new node <groupby>
        groupby_node = E.groupby(*node)
        # validate the node as a nested view
        self._validate_view(
            groupby_node, field.comodel_name, view_type="groupby", editable=False,
            node_info=node_info,
        )
        name_manager.has_field(node, name, node_info)

    elif node_info['validate']:
        msg = _(
            "Field '%(field)s' found in 'groupby' node does not exist in model %(model)s",
            field=name, model=name_manager.model._name,
        )
        self._raise_view_error(msg, node)


def _validate_tag_searchpanel(self, node, name_manager, node_info):
    if not node_info['validate']:
        return
    for child in node.iterchildren(tag=etree.Element):
        if child.get('domain') and child.get('select') != 'multi':
            msg = _('Searchpanel item with select multi cannot have a domain.')
            self._raise_view_error(msg, child)


def _validate_tag_label(self, node, name_manager, node_info):
    if not node_info['validate']:
        return
    # replace return not arch.xpath('//label[not(@for) and not(descendant::input)]')
    for_ = node.get('for')
    if not for_:
        msg = _('Label tag must contain a "for". To match label style '
                'without corresponding field or button, use \'class="o_form_label"\'.')
        self._raise_view_error(msg, node)
    else:
        name_manager.must_have_name(for_, '<label for="...">')


def _validate_tag_page(self, node, name_manager, node_info):
    if not node_info['validate']:
        return
    if node.getparent() is None or node.getparent().tag != 'notebook':
        self._raise_view_error(_('Page direct ancestor must be notebook'), node)


def _validate_tag_img(self, node, name_manager, node_info):
    if node_info['validate'] and not any(node.get(alt) for alt in att_names('alt')):
        self._log_view_warning('<img> tag must contain an alt attribute', node)


def _validate_tag_a(self, node, name_manager, node_info):
    # ('calendar', 'form', 'graph', 'kanban', 'pivot', 'search', 'list', 'activity')
    if node_info['validate'] and any('btn' in node.get(cl, '') for cl in att_names('class')):
        if node.get('role') != 'button':
            msg = '"<a>" tag with "btn" class must have "button" role'
            self._log_view_warning(msg, node)


def _validate_tag_ul(self, node, name_manager, node_info):
    if node_info['validate']:
        # was applied to all nodes, but in practice only used on div and ul
        self._check_dropdown_menu(node)


def _validate_tag_div(self, node, name_manager, node_info):
    if node_info['validate']:
        self._check_dropdown_menu(node)
        self._check_progress_bar(node)


def _check_dropdown_menu(self, node):
    # ('calendar', 'form', 'graph', 'kanban', 'pivot', 'search', 'list', 'activity')
    if any('dropdown-menu' in node.get(cl, '') for cl in att_names('class')):
        if node.get('role') != 'menu':
            msg = 'dropdown-menu class must have menu role'
            self._log_view_warning(msg, node)


def _check_progress_bar(self, node):
    if any('o_progressbar' in node.get(cl, '') for cl in att_names('class')):
        if node.get('role') != 'progressbar':
            msg = 'o_progressbar class must have progressbar role'
            self._log_view_warning(msg, node)
        if not any(node.get(at) for at in att_names('aria-valuenow')):
            msg = 'o_progressbar class must have aria-valuenow attribute'
            self._log_view_warning(msg, node)
        if not any(node.get(at) for at in att_names('aria-valuemin')):
            msg = 'o_progressbar class must have aria-valuemin attribute'
            self._log_view_warning(msg, node)
        if not any(node.get(at) for at in att_names('aria-valuemax')):
            msg = 'o_progressbar class must have aria-valuemaxattribute'
            self._log_view_warning(msg, node)


def _is_qweb_based_view(self, view_type):
    return view_type == 'kanban' or view_type == 'card' or view_type == 'calendar'
