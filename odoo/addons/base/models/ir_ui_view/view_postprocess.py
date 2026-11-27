"""The post-processing of the views for a client: the access rights, the attributes, the fields and the modifiers of each tag."""

from __future__ import annotations

import collections
import functools
from lxml import etree
from markupsafe import Markup
from odoo.tools import _
from odoo.tools.view_validation import get_expression_field_names
from .helpers import VIEW_MODIFIERS
from .name_manager import NameManager


def postprocess_and_fields(self, node, model=None, **options):
    """ Return an architecture and a description of all the fields.

        The field description combines the result of fields_get() and
        postprocess().

        :param self: the view to postprocess
        :param node: the architecture as an etree
        :param model: the view's reference model name
        :return: a tuple (arch, fields) where arch is the given node as a
            string and fields is the description of all the fields.

        """
    self and self.ensure_one()      # self is at most one view

    name_manager = self._postprocess_view(node, model or self.model, **options)
    arch = etree.tostring(node, encoding="unicode").replace('\t', '')

    models = {}
    name_managers = [name_manager]
    for name_manager in name_managers:
        models.setdefault(name_manager.model._name, set()).update(name_manager.available_fields)
        name_managers.extend(name_manager.children)

    return arch, models


def _postprocess_access_rights(self, tree):
    """
        Apply group restrictions: elements with a 'groups' attribute should
        be removed from the view to people who are not members.

        Compute and set on node access rights based on view type. Specific
        views can add additional specific rights like creating columns for
        many2one-based grouping views.
        """
    group_definitions = self.env['res.groups']._get_group_definitions()

    user_group_ids = self.env.user._get_group_ids()

    # check the read/visibility access
    @functools.cache
    def has_access(groups_key):
        groups = group_definitions.from_key(groups_key)
        return groups.matches(user_group_ids)

    # check the read/visibility access
    for node in tree.xpath('//*[@__groups_key__]'):
        if not has_access(node.attrib.pop('__groups_key__')):
            tail = node.tail
            parent = node.getparent()
            previous = node.getprevious()
            parent.remove(node)
            if tail:
                if previous is not None:
                    previous.tail = (previous.tail or '') + tail
                elif parent is not None:
                    parent.text = (parent.text or '') + tail
        elif node.tag == 't' and not node.attrib:
            # Move content of <t groups=""> blocks
            # and remove the <t> node.
            # This is to keep the structure
            # <group>
            #   <field name="foo"/>
            #   <field name="bar"/>
            # <group>
            # so the web client adds the label as expected.
            # This is also to avoid having <t> nodes in list views
            # e.g.
            # <list>
            #   <field name="foo"/>
            #   <t groups="foo">
            #     <field name="bar" groups="bar"/>
            #   </t>
            # </list>
            for child in reversed(node):
                node.addnext(child)
            node.getparent().remove(node)

    # check the create and write access
    for node in tree.xpath('//*[@model_access_rights]'):
        model = self.env[node.attrib.pop('model_access_rights')]
        if node.tag == 'field':
            can_create = model.has_access('create')
            can_write = model.has_access('write')
            node.set('can_create', str(bool(can_create)))
            node.set('can_write', str(bool(can_write)))
        else:
            for action, operation in (('create', 'create'), ('delete', 'unlink'), ('edit', 'write')):
                if not node.get(action) and not model.has_access(operation):
                    node.set(action, 'False')
            if node.tag == 'kanban':
                group_by_name = node.get('default_group_by')
                group_by_field = model._fields.get(group_by_name)
                if group_by_field and group_by_field.type == 'many2one':
                    group_by_model = model.env[group_by_field.comodel_name]
                    for action, operation in (('group_create', 'create'), ('group_delete', 'unlink'), ('group_edit', 'write')):
                        if not node.get(action) and not group_by_model.has_access(operation):
                            node.set(action, 'False')

    return tree


def _postprocess_debug_to_cache(self, tree):
    """ Transform attribute groups="base.group_no_one" into a specific
        attribute "__debug__" to ease the special treatment of this case.

        This feature is temporary because the behavior will be moved and
        processed in javascript soon. The management of 'base.group_no_one' is
        not consistent from the start. It is a magic group that historically
        was added or removed depending on the url used. 'base.group_no_one'
        should not to be considered as a security group but as a display
        feature.

        Typically the templates do not match the intent when attribute 'groups'
        contains 'base.group_no_one' and other groups. In every case we could
        spot, we want an "and" and not an "or" for the condition on groups::

            <filter name="not_secured" string="Not Secured" ... groups="account.group_account_secured,base.group_no_one"/>
            or
            <menuitem ... name="Configuration" ... groups="base.group_system,base.group_no_one"/>
        """
    for node in tree.xpath("//*[@groups]"):
        if 'base.group_no_one' in node.attrib.get('groups'):
            groups = node.attrib['groups'].split(',')
            node.attrib['__debug__'] = str('base.group_no_one' in groups)
            node.attrib['groups'] = ','.join(
                group for group in groups if not group.endswith('base.group_no_one')
            )


def _postprocess_debug(self, tree):
    """ Apply debug mode by making nodes invisible. """
    is_debug = self.env.user.has_group('base.group_no_one')
    for node in tree.xpath('//*[@__debug__]'):
        debug = node.attrib.pop('__debug__') == 'True'
        if debug != is_debug:
            node.attrib['invisible'] = '1'
            node.attrib['column_invisible'] = '1'
    return tree


def _postprocess_view(self, node, model_name, editable=True, node_info=None, **options):
    """ Process the given architecture, modifying it in-place to add and
        remove stuff.

        :param self: the optional view to postprocess
        :param node: the combined architecture as an etree
        :param model_name: the view's reference model name
        :param editable: whether the view is considered editable
        :return: the processed architecture's NameManager
        """
    root = node

    if model_name not in self.env:
        self._raise_view_error(_('Model not found: %(model)s', model=model_name), root)
    model = self.env[model_name]

    group_definitions = self.env['res.groups']._get_group_definitions()

    # model_groups/view_groups: access groups for the model/view
    model_groups = node_info['model_groups'] if node_info else group_definitions.universe
    view_groups = node_info['view_groups'] if node_info else group_definitions.universe
    parent_name_manager = node_info['name_manager'] if node_info else None

    # combine model access groups with this model's access groups
    model_groups &= self._get_access_groups(group_definitions, model_name)

    name_manager = NameManager(model, parent=parent_name_manager, model_groups=model_groups)

    root_info = {
        'view_type': root.tag,
        'view_editable': editable and self._editable_node(root, name_manager),
        'mobile': options.get('mobile'),
        'model_groups': model_groups,
        'view_groups': view_groups,
        'name_manager': name_manager,
    }

    is_compute_warning_info = options.get('is_compute_warning_info')

    self._postprocess_debug_to_cache(root)

    # use a stack to recursively traverse the tree
    stack = [(root, view_groups, editable)]
    while stack:
        node, view_groups, editable = stack.pop()

        # compute default
        tag = node.tag
        had_parent = node.getparent() is not None
        node_info = dict(root_info, view_groups=view_groups, editable=editable and self._editable_node(node, name_manager))

        node_groups = node.get('groups')
        if node_groups:
            node_info['view_groups'] &= group_definitions.parse(node_groups, raise_if_not_found=False)

        # tag-specific postprocessing
        postprocessor = getattr(self, f"_postprocess_tag_{tag}", None)
        if postprocessor is not None:
            postprocessor(node, name_manager, node_info)
            if had_parent and node.getparent() is None:
                # the node has been removed, stop processing here
                continue

        # if present, iterate on node_info['children'] instead of node
        for child in reversed(node_info.get('children', node)):
            stack.append((child, node_info['view_groups'], node_info['editable']))

        if node_groups or root_info['model_groups'] != node_info['model_groups']:
            groups = node_info['model_groups'] & node_info['view_groups']
            node.set('__groups_key__', groups.key)

        self._postprocess_attributes(node, name_manager, node_info)

        if node_groups and is_compute_warning_info:
            # reset the groups attributes to display in log
            node.attrib['groups'] = node_groups

    missing_fields = self._add_missing_fields(root, name_manager)

    if is_compute_warning_info:
        for name, (missing_groups, reasons) in missing_fields.items():
            error_message = name_manager._error_message_group_inconsistency(name, missing_groups, reasons)[0]
            if error_message:
                if self.warning_info:
                    self.warning_info += Markup('<br/>\n<br/>\n')
                self.warning_info += error_message.replace('\n', Markup('<br/>\n'))

    name_manager.update_available_fields()

    root.set('model_access_rights', model._name)

    if self._onchange_able_view(root):
        self._postprocess_on_change(root, model)

    return name_manager


def _get_access_groups(self, group_definitions, model_name):
    """ Return the group expression object that represents the users who
        can perform ``operation`` on model ``model_name``.
        """
    groups = self.env['ir.access']._get_groups_with_access(model_name, 'read')
    return group_definitions.from_ids(groups._ids)


def _add_missing_fields(self, node, name_manager):
    """ Add the fields required for evaluating expressions in the view given by ``node``. """
    root = node
    missing_fields = name_manager.get_missing_fields()
    for name, (missing_groups, reasons) in missing_fields.items():
        if name not in name_manager.field_info:
            continue

        # If the available fields have different groups then to avoid it being missing for
        # certain users, we virtually add a field with common groups.
        name_manager.available_fields[name].setdefault('info', {})
        name_manager.available_fields[name].setdefault('groups', []).append(missing_groups)
        name_manager.available_names.add(name)

        readonly = True
        if filename_reasons := [r for r in reasons if r[1][0] == "filename"]:
            node = filename_reasons[-1][2]
            if node_readonly := node.get("readonly"):
                readonly = node_readonly
            else:
                field = name_manager.model._fields[node.get("name")]
                if field.type == "binary":
                    readonly = field.readonly or False
        # If the field is not in the view without any group restriction,
        # add the field node with all mandatory groups (or without group if
        # the mandatory field does not have groups).
        attrs = {
            'name': name,
            'invisible' if root.tag != 'list' else 'column_invisible': 'True',
            'readonly': str(readonly),
            'data-used-by': '; '.join(
                f"{attr}={expr!r} ({node.tag},{node.get('name')})"
                for _groups, (attr, expr), node in reasons
            ),
        }

        if missing_groups is not False:
            subset_groups = missing_groups.invert_intersect(name_manager.model_groups)
            if subset_groups is None:
                subset_groups = missing_groups
            if not subset_groups.is_universal():
                attrs['__groups_key__'] = subset_groups.key

        item = etree.Element('field', attrs)
        item.tail = '\n'
        root.append(item)
    return missing_fields


def _postprocess_on_change(self, arch, model):
    """ Add attribute on_change="1" on fields that are dependencies of
            computed fields on the same view.
        """
    # map each field object to its corresponding nodes in arch
    field_nodes = collections.defaultdict(list)

    def collect(node, model):
        if node.tag == 'field':
            field = model._fields.get(node.get('name'))
            if field:
                field_nodes[field].append(node)
                if field.relational:
                    model = self.env[field.comodel_name]
        for child in node:
            collect(child, model)

    collect(arch, model)

    for field, nodes in field_nodes.items():
        # if field should trigger an onchange, add on_change="1" on the
        # nodes referring to field
        model = self.env[field.model_name]
        if model._has_onchange(field, field_nodes):
            for node in nodes:
                if not node.get('on_change'):
                    node.set('on_change', '1')


def _get_x2many_missing_view_archs(self, field, field_node, node_info):
    """
        For x2many fields that require to have some multi-record arch (kanban or list) to display the records
        be available, this function fetches all arch that are needed and return them.
        The caller function is responsible to do what it needs with them.
        """
    current_view_types = [el.tag for el in field_node.xpath("./*[descendant::field]")]
    missing_view_types = []
    if not any(view_type in current_view_types for view_type in field_node.get('mode', 'kanban,list').split(',')):
        missing_view_types.append(
            field_node.get('mode', 'kanban' if node_info.get('mobile') else 'list').split(',')[0]
        )

    if not missing_view_types:
        return []

    comodel = self.env[field.comodel_name].sudo(False)
    refs = self._get_view_refs(field_node)
    # Do not propagate <view_type>_view_ref of parent call to `_get_view`
    comodel = comodel.with_context(**{
        f'{view_type}_view_ref': refs.get(f'{view_type}_view_ref')
        for view_type in missing_view_types
    })

    return [comodel._get_view(view_type=view_type) for view_type in missing_view_types]


def _postprocess_attributes(self, node, name_manager, node_info):
    # get mandatory fields
    for attr, expr in node.items():
        if attr in VIEW_MODIFIERS or attr.startswith('decoration-'):
            vnames = get_expression_field_names(expr)
            name_manager.must_have_fields(node, vnames, node_info, (attr, expr))
        elif attr == 'groups':
            node.attrib.pop('groups')


def _postprocess_tag_calendar(self, node, name_manager, node_info):
    for additional_field in ('date_start', 'date_stop', 'color', 'all_day'):
        if fname := node.get(additional_field):
            name_manager.has_field(node, fname, node_info)
    if fname := node.get('aggregate'):
        name_manager.has_field(node, fname.split(':')[0], node_info)
    for f in node:
        if f.tag == 'filter':
            name_manager.has_field(node, f.get('name'), node_info)


def _postprocess_tag_field(self, node, name_manager, node_info):
    name = node.get('name')
    if not name:
        return

    attrs = {'id': node.get('id'), 'select': node.get('select')}
    field = name_manager.model._fields.get(name)

    if field:
        if field.groups:
            group_definitions = self.env['res.groups']._get_group_definitions()
            node_info['model_groups'] &= group_definitions.parse(field.groups, raise_if_not_found=False)
        if (
            node_info.get('view_type') == 'form'
            and field.type in ('one2many', 'many2many')
            and not node.get('widget')
            and node.get('invisible') not in ('1', 'True')
            and not name_manager.parent
        ):
            # Embed kanban/list/form views for visible x2many fields in form views
            # if no widget or the widget requires it.
            # So the web client doesn't have to call `get_views` for x2many fields not embedding their view
            # in the main form view.
            for arch, _view in self._get_x2many_missing_view_archs(field, node, node_info):
                node.append(arch)

        if field.relational:
            domain = (
                node.get('domain')
                or node_info['editable'] and field._description_domain(self.env)
            )
            if isinstance(domain, str):
                vnames = get_expression_field_names(domain)
                name_manager.must_have_fields(node, vnames, node_info, ('domain', domain))
        if field.type == 'properties':
            name_manager.must_have_fields(node, [field.definition_record], node_info, ('fieldname', field.name))
        context = node.get('context')
        if context:
            vnames = get_expression_field_names(context)
            name_manager.must_have_fields(node, vnames, node_info, ('context', context))
        if field.type == "binary" and (field_filename := node.get("filename")):
            name_manager.must_have_fields(node, [field_filename], node_info, ("filename", field_filename))

        for child in node:
            if child.tag in ('form', 'list', 'graph', 'kanban', 'calendar'):
                node_info['children'] = []
                self._postprocess_view(child, field.comodel_name, editable=node_info['editable'], node_info=node_info)

        if node_info['editable'] and field.type in ('many2one', 'many2many'):
            node.set('model_access_rights', field.comodel_name)

    name_manager.has_field(node, name, node_info, attrs)


def _postprocess_tag_form(self, node, name_manager, node_info):
    result = name_manager.model.view_header_get(False, node.tag)
    if result:
        node.set('string', result)


def _postprocess_tag_groupby(self, node, name_manager, node_info):
    # groupby nodes should be considered as nested view because they may
    # contain fields on the comodel
    name = node.get('name')
    field = name_manager.model._fields.get(name)
    if not field or not field.relational:
        return
    # post-process the node as a nested view, and associate it to the field
    node_info['children'] = []
    self._postprocess_view(node, field.comodel_name, editable=False, node_info=node_info)
    name_manager.has_field(node, name, node_info)


def _postprocess_tag_card(self, node, name_manager, node_info):
    # When this is called as the root of the recursive sub-view call below,
    # view_type is 'card' and children should be processed normally by the
    # inner stack — returning here lets that happen without re-entering.
    if node_info.get('view_type') == 'card':
        return
    # card nodes are processed as nested sub-views on the same model so that
    # fields auto-added for expression evaluation land inside <card> rather
    # than being appended to the parent view root.
    node_info['children'] = []
    self._postprocess_view(node, name_manager.model._name, editable=False, node_info=node_info)


def _postprocess_tag_label(self, node, name_manager, node_info):
    if not node.get('for'):
        return
    field = name_manager.model._fields.get(node.get('for'))
    if field and field.groups:
        group_definitions = self.env['res.groups']._get_group_definitions()
        node_info['model_groups'] &= group_definitions.parse(field.groups, raise_if_not_found=False)


def _postprocess_tag_filter(self, node, name_manager, node_info):
    for attribute in ('date', 'end_date'):
        field = name_manager.model._fields.get(node.get(attribute))
        if field and field.groups:
            group_definitions = self.env['res.groups']._get_group_definitions()
            node_info['model_groups'] &= group_definitions.parse(field.groups, raise_if_not_found=False)


def _postprocess_tag_search(self, node, name_manager, node_info):
    searchpanel = [child for child in node if child.tag == 'searchpanel']
    if searchpanel:
        self._postprocess_view(searchpanel[0], name_manager.model._name, editable=False, node_info=node_info)
        node_info['children'] = [child for child in node if child.tag != 'searchpanel']


def _postprocess_tag_kanban(self, node, name_manager, node_info):
    # Inline the card view if the kanban node references one via the 'card_id' attribute.
    if card_id := node.get('card_id'):
        card_arch, _card_view = self._get_view(view_id=int(card_id), view_type='card')
        node.append(card_arch)


def _postprocess_tag_list(self, node, name_manager, node_info):
    # reuse form view post-processing
    self._postprocess_tag_form(node, name_manager, node_info)


def _editable_node(self, node, name_manager):
    """ Return whether the given node must be considered editable. """
    func = getattr(self, f"_editable_tag_{node.tag}", None)
    if func is not None:
        return func(node, name_manager)
    # by default views are non-editable
    return node.tag not in (item[0] for item in self._fields['type'].selection)


def _editable_tag_form(self, node, name_manager):
    return True


def _editable_tag_list(self, node, name_manager):
    return node.get('editable') or node.get('multi_edit')


def _editable_tag_field(self, node, name_manager):
    field = name_manager.model._fields.get(node.get('name'))
    return field is None or field.is_editable() and node.get('readonly') not in ('1', 'True')


def _onchange_able_view(self, node):
    func = getattr(self, f"_onchange_able_view_{node.tag}", None)
    if func is not None:
        return func(node)


def _onchange_able_view_form(self, node):
    return True


def _onchange_able_view_list(self, node):
    return True


def _onchange_able_view_kanban(self, node):
    return True


def _modifiers_from_model(self, node):
    modifier_names = []
    if node.tag in ('kanban', 'list', 'form'):
        modifier_names += ['readonly', 'required']
    return modifier_names
