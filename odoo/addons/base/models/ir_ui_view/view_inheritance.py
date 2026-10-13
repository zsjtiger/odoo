"""The inheritance of the views: the views that inherit from a view, the combination of their architectures and the views of a model."""

from __future__ import annotations

import collections
import pprint
from lxml import etree
from lxml.builder import E
from odoo.exceptions import AccessError
from odoo.fields import Domain
from odoo.tools import _, unique, SQL
from odoo.tools.xml.template_inheritance import apply_inheritance_specs as _apply_inheritance_specs, locate_node as _locate_node
from .helpers import ref_re

from .view import _logger

def default_view(self, model, view_type):
    """ Fetches the default view for the provided (model, view_type) pair:
         primary view with the lowest priority.

        :param str model:
        :param int view_type:
        :return: id of the default view of False if none found
        :rtype: int
        """
    return self.search(self._get_default_view_domain(model, view_type), limit=1).id


def _get_default_view_domain(self, model, view_type):
    return Domain([('model', '=', model), ('type', '=', view_type), ('mode', '=', 'primary')])


def _get_inheriting_views_domain(self):
    """ Return a domain to filter the sub-views to inherit from. """
    tree_cut_off_view = self.env.context.get("ir_ui_view_tree_cut_off_view")
    domain = Domain('active', '=', True)
    if tree_cut_off_view:
        return domain | Domain('id', '=', tree_cut_off_view.id)
    return domain


def _get_filter_xmlid_query(self, *, modules):
    """This method is meant to be overridden by other modules.
        """
    return SQL("""SELECT res_id FROM ir_model_data
                  WHERE res_id IN %(res_ids)s AND model = 'ir.ui.view' AND module IN %(modules)s
               """, res_ids=self._ids, modules=tuple(modules))


def _get_inheriting_views(self):
    """
        Determine the views that inherit from the current recordset, and return
        them as a recordset, ordered by priority then by id.
        """
    if not self.ids:
        return self.browse()
    domain = self._get_inheriting_views_domain()
    query = self._search(domain)

    field_names = [f.name for f in self._fields.values() if f.prefetch is True and not f.groups]
    aliased_names = SQL(', ').join(
        SQL("%s AS %s", query.table[name], SQL.identifier(name))
        for name in field_names
    )

    assert query.from_clause == SQL.identifier('ir_ui_view'), f"Unexpected from clause: {query.from_clause}"
    where_clause = query.where_clause

    query = SQL("""
            WITH RECURSIVE ir_ui_view_inherits AS (
                SELECT ir_ui_view.id, %(aliased_names)s
                FROM ir_ui_view
                WHERE id IN %(ids)s AND (%(where_clause)s)
            UNION
                SELECT ir_ui_view.id, %(aliased_names)s
                FROM ir_ui_view
                INNER JOIN ir_ui_view_inherits parent ON parent.id = ir_ui_view.inherit_id
                WHERE coalesce(ir_ui_view.model, '') = coalesce(parent.model, '')
                      AND ir_ui_view.mode = 'extension'
                      AND (%(where_clause)s)
            )
            SELECT
                v.id, %(field_names)s
            FROM ir_ui_view_inherits as v
            ORDER BY v.priority, v.id
        """,
        aliased_names=aliased_names,
        field_names=SQL(', ').join(SQL.identifier('v', f) for f in field_names),
        ids=tuple(self.ids), where_clause=where_clause)
    # ORDER BY v.priority, v.id:
    # 1/ sort by priority: abritrary value set by developers on some
    #    views to solve "dependency hell" problems and force a view
    #    to be combined earlier or later. e.g. all views created via
    #    studio have a priority=99 to be loaded last.
    # 2/ sort by view id: the order the views were inserted in the
    #    database. e.g. base views are placed before stock ones.

    rows = self.env.execute_query(query)
    if not rows:
        return self.browse()

    ids, *columns = zip(*rows)
    views = self.browse(ids)

    # optimization: fill in cache of retrieved fields
    for fname, column in zip(field_names, columns, strict=True):
        self._fields[fname]._insert_cache(views, column)

    return views


def _filter_loaded_views(self, check_view_ids):
    """
        During the module upgrade phase it may happen that a view is
        present in the database but the fields it relies on are not
        fully loaded yet. This method only considers views that belong
        to modules whose code is already loaded. Custom views defined
        directly in the database are loaded only after the module
        initialization phase is completely finished.
        """
    # check that all found ids have a corresponding xml_id in a loaded module
    ids_to_check = [vid for vid in self.ids if vid not in check_view_ids]
    if not ids_to_check:
        return self
    loaded_modules = tuple(self.pool._init_modules) + (self.env.context.get('install_module'),)
    sql = self.browse(ids_to_check)._get_filter_xmlid_query(modules=loaded_modules)
    valid_view_ids = {id_ for id_, in self.env.execute_query(sql)} | check_view_ids
    return self.browse(vid for vid in self.ids if vid in valid_view_ids)


def _check_view_access(self):
    """ Verify that a view is accessible by the current user based on the
        groups attribute. Views with no groups are considered private.
        """
    if self.inherit_id and self.mode != 'primary':
        return self.inherit_id._check_view_access()
    if set(self.group_ids.ids) & set(self.env.user._get_group_ids()):
        return True
    if self.group_ids:
        error = _(
            "View '%(name)s' accessible only to groups %(groups)s ",
            name=self.key,
            groups=", ".join([g.name for g in self.group_ids]
        ))
    else:
        error = _("View '%(name)s' is private", name=self.key)
    raise AccessError(error)


def _raise_view_error(self, message, node=None, *, from_exception=None, from_traceback=None):
    """ Handle a view error by raising an exception.

        :param str message: message to raise or log, augmented with contextual
                            view information
        :param node: the lxml element where the error is located (if any)
        :param BaseException from_exception:
            when raising an exception, chain it to the provided one (default:
            disable chaining)
        :param types.TracebackType from_traceback:
            when raising an exception, start with this traceback (default: start
            at exception creation)
        """
    err = ValueError(message).with_traceback(from_traceback)
    err.context = {
        'view': self,
        'name': getattr(self, 'name', None),
        'xmlid': self.xml_id,
        'view.model': self.model,
        'view.parent': self.inherit_id,
        'file': self.env.context.get('install_filename'),
        'line': node.sourceline if node is not None else 1,
    }
    raise err from from_exception


def _log_view_warning(self, message, node):
    """ Handle a view issue by logging a warning.

        :param str message: message to raise or log, augmented with contextual
                            view information
        :param node: the lxml element where the error is located (if any)
        """
    error_context = {
        'view': self,
        'name': getattr(self, 'name', None),
        'xmlid': self.xml_id,
        'view.model': self.model,
        'view.parent': self.inherit_id,
        'file': self.env.context.get('install_filename'),
        'line': node.sourceline if node is not None else 1,
    }
    _logger.warning(
        "%s\nView error context:\n%s",
        message, pprint.pformat(error_context)
    )


def locate_node(self, arch, spec):
    """ Locate a node in a source (parent) architecture.

        Given a complete source (parent) architecture (i.e. the field
        `arch` in a view), and a 'spec' node (a node in an inheriting
        view that specifies the location in the source view of what
        should be changed), return (if it exists) the node in the
        source view matching the specification.

        :param arch: a parent architecture to modify
        :param spec: a modifying node in an inheriting view
        :return: a node in the source matching the spec
        """
    return _locate_node(arch, spec)


def inherit_branding(self, specs_tree):
    for node in specs_tree.iterchildren(tag=etree.Element):
        xpath = node.getroottree().getpath(node)
        if node.tag == 'data' or node.tag == 'xpath' or node.get('position'):
            self.inherit_branding(node)
        elif node.get('t-field'):
            node.set('data-oe-xpath', xpath)
            self.inherit_branding(node)
        else:
            node.set('data-oe-id', str(self.id))
            node.set('data-oe-xpath', xpath)
            node.set('data-oe-model', 'ir.ui.view')
            node.set('data-oe-field', 'arch')
    return specs_tree


def _add_validation_flag(self, combined_arch, view=None, arch=None):
    """ Add a validation flag on elements in ``combined_arch`` or ``arch``.
        This is part of the partial validation of views.

        :param Element combined_arch: the architecture to be modified by ``arch``
        :param view: an optional view inheriting ``self``
        :param Element arch: an optional modifying architecture from inheriting
            view ``view``
        """
    # validate_view_ids is either falsy (no validation), True (full
    # validation) or a collection of ids (partial validation)
    validate_view_ids = self.env.context.get('validate_view_ids')
    if not validate_view_ids:
        return

    if validate_view_ids is True or self.id in validate_view_ids:
        # optimization, flag the root node
        combined_arch.set('__validate__', '1')
        return

    if view is None or view.id not in validate_view_ids:
        return

    for node in arch.xpath('//*[@position]'):
        if node.get('position') in ('after', 'before', 'inside'):
            # validate the elements being inserted, except the ones that
            # specify a move, as in:
            #   <field name="foo" position="after">
            #       <field name="bar" position="move"/>
            #   </field>
            for child in node.iterchildren(tag=etree.Element):
                if not child.get('position'):
                    child.set('__validate__', '1')
        if node.get('position') == 'replace':
            # validate everything, since this impacts the whole arch
            combined_arch.set('__validate__', '1')
            break
        if node.get('position') == 'attributes':
            # validate the element being modified by adding
            # attribute "__validate__" on it:
            #   <field name="foo" position="attributes">
            #       <attribute name="readonly">1</attribute>
            #       <attribute name="__validate__">1</attribute>    <!-- add this -->
            #   </field>
            node.append(E.attribute('1', name='__validate__'))


def apply_inheritance_specs(self, source, specs_tree, pre_locate=None):
    """ Apply an inheriting view (a descendant of the base view)

        Apply to a source architecture all the spec nodes (i.e. nodes
        describing where and what changes to apply to some parent
        architecture) given by an inheriting view.

        :param Element source: a parent architecture to modify
        :param Element specs_tree: a modifying architecture in an inheriting view
        :param (optional) pre_locate: function that is execute before locating a node.
                                        This function receives an arch as argument.
        :return: a modified source where the specs are applied
        :rtype: Element
        """
    # Queue of specification nodes (i.e. nodes describing where and
    # changes to apply to some parent architecture).
    try:
        source = _apply_inheritance_specs(
            source, specs_tree,
            inherit_branding=self.env.context.get('inherit_branding'),
            pre_locate=pre_locate,
        )
    except ValueError as e:
        self._raise_view_error(str(e), specs_tree)
    return source


def _combine(self, hierarchy: dict):
    """
        Return self's arch combined with its inherited views archs.

        :param hierarchy: mapping from parent views to their child views
        :return: combined architecture
        :rtype: Element
        """
    self.ensure_one()
    assert self.mode == 'primary'

    # We achieve a pre-order depth-first hierarchy traversal where
    # primary views (and their children) are traversed after all the
    # extensions for the current primary view have been visited.
    #
    # https://en.wikipedia.org/wiki/Tree_traversal#Depth-first_search_of_binary_tree
    #
    # Example:                  hierarchy = {
    #                               1: [2, 3],  # primary view
    #             1*                2: [4, 5],
    #            / \                3: [],
    #           2   3               4: [6],     # primary view
    #          / \                  5: [7, 8],
    #         4*  5                 6: [],
    #        /   / \                7: [],
    #       6   7   8               8: [],
    #                           }
    #
    # Tree traversal order (`view` and `queue` at the `while` stmt):
    #   1 [2, 3]
    #   2 [5, 3, 4]
    #   5 [7, 8, 3, 4]
    #   7 [8, 3, 4]
    #   8 [3, 4]
    #   3 [4]
    #   4 [6]
    #   6 []
    combined_arch = etree.fromstring(self.arch)
    if self.env.context.get('inherit_branding'):
        combined_arch.attrib.update({
            'data-oe-model': 'ir.ui.view',
            'data-oe-id': str(self.id),
            'data-oe-field': 'arch',
        })
    self._add_validation_flag(combined_arch)

    # The depth-first traversal is implemented with a double-ended queue.
    # The queue is traversed from left to right, and after each view in the
    # queue is processed, its children are pushed at the left of the queue,
    # so that they are traversed in order.  The queue is therefore mostly
    # used as a stack.  An exception is made for primary views, which are
    # pushed at the other end of the queue, so that they are applied after
    # all extensions have been applied.
    queue = collections.deque(sorted(hierarchy[self], key=lambda v: v.mode))
    tree_cut_off_view = self.env.context.get("ir_ui_view_tree_cut_off_view")
    while queue:
        view = queue.popleft()
        if view == tree_cut_off_view:
            break
        arch = etree.fromstring(view.arch or '<data/>')
        if view.env.context.get('inherit_branding'):
            view.inherit_branding(arch)
        self._add_validation_flag(combined_arch, view, arch)
        combined_arch = view.apply_inheritance_specs(combined_arch, arch)

        for child_view in reversed(hierarchy[view]):
            if child_view.mode == 'primary':
                queue.append(child_view)
            else:
                queue.appendleft(child_view)

    return combined_arch


def get_combined_arch(self):
    """ Return the arch of ``self`` (as a string) combined with its inherited views. """
    return etree.tostring(self._get_combined_arch(), encoding='unicode')


def _get_combined_arch(self):
    self.ensure_one()
    return self._get_combined_archs()[0]


def _get_combined_archs(self):
    """ Return the arch of ``self`` (as an etree) combined with its inherited views. """
    parented = []
    roots = self.env['ir.ui.view']
    for root in self:
        parented.append(view_ids := [])
        while True:
            view_ids.append(root.id)
            if not root.inherit_id:
                roots += root
                break
            root = root.inherit_id
    views = self.env['ir.ui.view'].browse(unique(view_id for view_ids in parented for view_id in view_ids))

    # Add inherited views to the list of loading forced views
    # Otherwise, inherited views could not find elements created in
    # their direct parents if that parent is defined in the same module
    # introduce check_view_ids in context
    if 'check_view_ids' not in views.env.context:
        views = views.with_context(check_view_ids=[])
    views.env.context['check_view_ids'].extend(views.ids)

    # Map each node to its children nodes. Note that all children nodes are
    # part of a single prefetch set, which is all views to combine.
    all_tree_views = views._get_inheriting_views()

    # During an upgrade, we can only use the views that have been
    # fully upgraded already.
    if not self.pool.ready and not self.env.context.get('load_all_views'):
        all_tree_views = all_tree_views._filter_loaded_views(set(views.env.context['check_view_ids']))

    # get the global children views then get hierarchy for each views
    children_views = collections.defaultdict(list)
    for view in all_tree_views:
        children_views[view.inherit_id].append(view)

    def get_hierarchy(root, parented_ids, _hierarchy=None):
        if _hierarchy is None:
            _hierarchy = collections.defaultdict(list)
        _hierarchy[root.inherit_id].append(root)
        for child in children_views[root]:
            if child.id in parented_ids or child.mode != 'primary':
                get_hierarchy(child, parented_ids, _hierarchy)
        return _hierarchy

    roots = roots.with_prefetch(all_tree_views._prefetch_ids)

    return [
        root._combine(get_hierarchy(root, parented_ids))
        for root, parented_ids in zip(roots, parented)
    ]


def _get_view_refs(self, node):
    """ Extract the `[view_type]_view_ref` keys and values from the node context attribute,
        giving the views to use for a field node.

        :param node: the field node as an etree
        :return: a dictonary mapping the `[view_type]_view_ref` key to the xmlid of the view to use for that view type.
        """
    if not node.get('context'):
        return {}
    return {
        m.group('view_type'): m.group('view_id')
        for m in ref_re.finditer(node.get('context'))
    }
