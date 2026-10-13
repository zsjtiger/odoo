"""The validation of the views: the XML of the architecture, the inheritance, the groups and the expressions."""

from __future__ import annotations

import ast
import re
from lxml import etree
from odoo.exceptions import ValidationError, UserError
from odoo.tools import _, SQL
from odoo.tools.text.translate import TRANSLATED_ATTRS
from odoo.tools.view_validation import valid_view, get_domain_value_names, get_expression_field_names, get_dict_asts
from .helpers import COMP_REGEX, TRANSLATED_ATTRS_RE, VIEW_MODIFIERS, WRONGCLASS, att_names

from .view import _logger

def _valid_inheritance(self, arch):
    """ Check whether view inheritance is based on translated attribute. """
    for node in arch.xpath('//*[@position]'):
        # inheritance may not use a translated attribute as selector
        if node.tag == 'xpath':
            match = TRANSLATED_ATTRS_RE.search(node.get('expr', ''))
            if match:
                message = "View inheritance may not use attribute %r as a selector." % match.group(1)
                self._raise_view_error(message, node)
            if WRONGCLASS.search(node.get('expr', '')):
                _logger.warning(
                    "Error-prone use of @class in view %s (%s): use the "
                    "hasclass(*classes) function to filter elements by "
                    "their classes", self.name, self.xml_id
                )
        else:
            for attr in TRANSLATED_ATTRS:
                if node.get(attr):
                    message = "View inheritance may not use attribute %r as a selector." % attr
                    self._raise_view_error(message, node)
    return True


def _check_xml(self):
    # Sanity checks: the view should not break anything upon rendering!
    # Any exception raised below will cause a transaction rollback.
    partial_validation = self.env.context.get('ir_ui_view_partial_validation')
    views = self.with_context(validate_view_ids=(self._ids if partial_validation else True))

    for view in views:
        if partial_validation and not view.arch:
            continue
        try:
            # verify the view is valid xml and that the inheritance resolves
            if view.inherit_id:
                view_arch = etree.fromstring(view.arch or '<data/>')
                view._valid_inheritance(view_arch)

            combined_arch = view._get_combined_arch()

            # check primary view that extends this current view
            # keep a way to skip this check to avoid marking too many views as failed during an upgrade
            if not self.env.context.get('_skip_primary_extensions_check') and (view.inherit_id or view.inherit_children_ids):
                root = view
                while root.inherit_id and root.mode != 'primary':
                    root = root.inherit_id
                sibling_primary_views = self.env['ir.ui.view']
                stack = [root]
                while stack:
                    root = stack.pop()
                    for child in root.inherit_children_ids:
                        if child.mode == 'primary':
                            sibling_primary_views += child
                        else:
                            stack.append(child)

                # During an upgrade, we can only use the views that have been
                # fully upgraded already.
                if not self.pool.ready and sibling_primary_views and self.pool._init_modules:
                    sql = sibling_primary_views._get_filter_xmlid_query(modules=tuple(self.pool._init_modules))
                    loaded_view_ids = {id_ for id_, in self.env.execute_query(sql)}
                    loaded_view_ids.update({
                        id
                        for id, xid in (sibling_primary_views - views.browse(loaded_view_ids)).get_external_id().items()
                        if xid in self.pool.loaded_xmlids
                    })
                    sibling_primary_views = sibling_primary_views.browse(loaded_view_ids)

                # Check if we know how to apply inheritances
                sibling_primary_views._get_combined_archs()

            if view.type == 'qweb':
                continue
        except (etree.ParseError, ValueError, TypeError) as e:
            # Note: lxml < 5.0 raises ValueError; lxml 5.0+ / libxml2 2.12+ raises TypeError
            err = ValidationError(_(
                "Error while parsing or validating view:\n\n%(error)s",
                error=e,
                view=view.key or view.id,
            )).with_traceback(e.__traceback__)
            err.context = getattr(e, 'context', None)
            raise err from None

        try:
            # verify that all fields used are valid, etc.
            view._validate_view(combined_arch, view.model)
            combined_archs = [combined_arch]

            if combined_arch.xpath('//*[@attrs]') or combined_arch.xpath('//*[@states]'):
                view_name = f'{view.name} ({view.xml_id})' if view.xml_id else view.name
                err = ValidationError(_('Since 17.0, the "attrs" and "states" attributes are no longer used.\nView: %(name)s in %(file)s',
                    name=view_name, file=view.arch_fs
                ))
                err.context = {'name': 'invalid view'}
                raise err

            if combined_archs[0].tag == 'data':
                # A <data> element is a wrapper for multiple root nodes
                combined_archs = combined_archs[0]
            for view_arch in combined_archs:
                for node in view_arch.xpath('//*[@__validate__]'):
                    del node.attrib['__validate__']
                check = valid_view(view_arch, env=self.env, model=view.model)
                if not check:
                    view_name = f'{view.name} ({view.xml_id})' if view.xml_id else view.name
                    raise ValidationError(_(
                        'Invalid view %(name)s definition in %(file)s',
                        name=view_name, file=view.arch_fs
                    ))
        except ValueError as e:
            if hasattr(e, 'context'):
                lines = etree.tostring(combined_arch, encoding='unicode').splitlines(keepends=True)
                fivelines = "".join(lines[max(0, e.context["line"]-3):e.context["line"]+2])
                err = ValidationError(_(
                    "Error while validating view near:\n\n%(fivelines)s\n%(error)s",
                    fivelines=fivelines, error=e,
                ))
                err.context = e.context
                raise err.with_traceback(e.__traceback__) from None
            elif e.__context__:
                err = ValidationError(_(
                    "Error while validating view (%(view)s):\n\n%(error)s", view=view.key or view.id, error=e.__context__,
                ))
                err.context = {'name': 'invalid view'}
                raise err.with_traceback(e.__context__.__traceback__) from None
            else:
                raise ValidationError(_(
                    "Error while validating view (%(view)s):\n\n%(error)s", view=view.key or view.id, error=e,
                ))

    return True


def _check_groups(self):
    for view in self:
        if (view.group_ids and
            view.inherit_id and
            view.mode != 'primary'):
            raise ValidationError(_("Inherited view cannot have '%(attr)s' defined on the record. Use '%(attr)s' attributes inside the view definition", attr='groups'))


def _check_000_inheritance(self):
    # NOTE: constraints methods are check alphabetically. Always ensure this method will be
    #       called before other constraint methods to avoid infinite loop in `_get_combined_arch`.
    if self._has_cycle('inherit_id'):
        raise ValidationError(_('You cannot create recursive inherited views.'))


def _validate_xml_encoding(self, text):
    if isinstance(text, str) and re.search(r'<\?xml[^>]*encoding=.*?\?>', text, re.IGNORECASE):
        raise UserError(_(
            "Unicode strings with encoding declaration are not supported in XML.\n"
            "Remove the encoding declaration."
        ))


def _validate_attributes(self, node, name_manager, node_info):
    """ Generic validation of node attributes. """

    # python expression used in for readonly, invisible, ...
    # and thus are only executed client side
    for attr in VIEW_MODIFIERS:
        py_expression = node.attrib.get(attr)
        if py_expression:
            self._validate_expression(node, name_manager, py_expression, f"modifier {attr!r}", node_info)

    for attr, expr in node.items():
        if attr in ('class', 't-att-class', 't-attf-class'):
            self._validate_classes(node, expr)

        elif attr == 'context':
            try:
                vnames = get_expression_field_names(expr)
            except SyntaxError as e:
                message = _('Invalid context: “%(expr)s” is not a valid Python expression \n\n %(error)s', expr=expr, error=e)
                self._raise_view_error(message)
            if vnames:
                name_manager.must_have_fields(node, vnames, node_info, f"context ({expr})")
            for key, val_ast in get_dict_asts(expr).items():
                if key == 'group_by':  # only in context
                    if not isinstance(val_ast, ast.Constant) or not isinstance(val_ast.value, str):
                        msg = _(
                            '"group_by" value must be a string %(attribute)s=“%(value)s”',
                            attribute=attr, value=expr,
                        )
                        self._raise_view_error(msg, node)
                    group_by = val_ast.value
                    fname = group_by.split(':')[0]
                    if fname not in name_manager.model._fields:
                        msg = _(
                            'Unknown field “%(field)s” in "group_by" value in %(attribute)s=“%(value)s”',
                            field=fname, attribute=attr, value=expr,
                        )
                        self._raise_view_error(msg, node)

        elif attr in ('col', 'colspan'):
            # col check is mainly there for the tag 'group', but previous
            # check was generic in view form
            if not expr.isdigit():
                self._raise_view_error(
                    _('“%(attribute)s” value must be an integer (%(value)s)',
                      attribute=attr, value=expr),
                    node,
                )

        elif attr.startswith('decoration-'):
            vnames = get_expression_field_names(expr)
            if vnames:
                name_manager.must_have_fields(node, vnames, node_info, f"{attr}={expr!r}")

        elif attr == 'data-bs-toggle' and expr == 'tab':
            if node.get('role') != 'tab':
                msg = 'tab link (data-bs-toggle="tab") must have "tab" role'
                self._log_view_warning(msg, node)
            aria_control = node.get('aria-controls') or node.get('t-att-aria-controls')
            if not aria_control and not node.get('t-attf-aria-controls'):
                msg = 'tab link (data-bs-toggle="tab") must have "aria_control" defined'
                self._log_view_warning(msg, node)
            if aria_control and '#' in aria_control:
                msg = 'aria-controls in tablink cannot contains "#"'
                self._log_view_warning(msg, node)

        elif attr == 'data-icon':
            description = 'A <%s> with data-icon attribute (%s)' % (node.tag, expr)
            self._validate_data_icon_accessibility(node, description)

        elif attr == "role" and expr in ('presentation', 'none'):
            msg = ("A role cannot be `none` or `presentation`. "
                "All your elements must be accessible with screen readers, describe it.")
            self._log_view_warning(msg, node)

        elif attr == 'group':
            msg = "attribute 'group' is not valid.  Did you mean 'groups'?"
            self._log_view_warning(msg, node)

        elif (re.match(r'^(t\-att\-|t\-attf\-)?data-tooltip(-template|-info)$', attr)):
            self._raise_view_error(_("Forbidden attribute used in arch (%s).", attr), node)

        elif (attr.startswith("t-")):
            self._validate_qweb_directive(node, attr, node_info["view_type"])
            if (re.search(COMP_REGEX, expr)):
                self._raise_view_error(_("Forbidden use of `__comp__` in arch."), node)


def _validate_classes(self, node, expr):
    """ Validate the classes present on node. """
    classes = set(expr.split(' '))
    # Be careful: not always true if it is an expression
    # example: <div t-attf-class="{{!selection_mode ? 'oe_kanban_color_' + kanban_getcolor(record.color.raw_value) : ''}} oe_kanban_card oe_kanban_global_click oe_applicant_kanban oe_semantic_html_override">
    if 'modal' in classes and node.get('role') != 'dialog':
        msg = '"modal" class should only be used with "dialog" role'
        self._log_view_warning(msg, node)

    if 'modal-header' in classes and node.tag != 'header':
        msg = '"modal-header" class should only be used in "header" tag'
        self._log_view_warning(msg, node)

    if 'modal-body' in classes and node.tag != 'main':
        msg = '"modal-body" class should only be used in "main" tag'
        self._log_view_warning(msg, node)

    if 'modal-footer' in classes and node.tag != 'footer':
        msg = '"modal-footer" class should only be used in "footer" tag'
        self._log_view_warning(msg, node)

    if 'tab-pane' in classes and node.get('role') != 'tabpanel':
        msg = '"tab-pane" class should only be used with "tabpanel" role'
        self._log_view_warning(msg, node)

    if 'nav-tabs' in classes and node.get('role') != 'tablist':
        msg = 'A tab list with class nav-tabs must have role="tablist"'
        self._log_view_warning(msg, node)

    if any(klass.startswith('alert-') for klass in classes):
        if (
            node.get('role') not in ('alert', 'alertdialog', 'status')
            and 'alert-link' not in classes
        ):
            msg = ("An alert (class alert-*) must have an alert, alertdialog or "
                    "status role or an alert-link class. Please use alert and "
                    "alertdialog only for what expects to stop any activity to "
                    "be read immediately.")
            self._log_view_warning(msg, node)

    if any(klass.startswith('btn') for klass in classes):
        if node.tag in ('a', 'button', 'select'):
            pass
        elif node.tag == 'input' and node.get('type') in ('button', 'submit', 'reset'):
            pass
        elif any(klass in classes for klass in ('btn-group', 'btn-toolbar', 'btn-addr')):
            pass
        elif node.tag == 'field' and node.get('widget') == 'url':
            pass
        else:
            msg = ("A simili button must be in tag a/button/select or tag `input` "
                    "with type button/submit/reset or have class in "
                    "btn-group/btn-toolbar/btn-addr")
            self._log_view_warning(msg, node)


def _validate_data_icon_accessibility(self, node, description):
    valid_aria_attrs = {
        *att_names('title'), *att_names('aria-label'), *att_names('aria-labelledby'),
    }
    valid_t_attrs = {'t-value', 't-field', 't-out'}

    ## Following or preceding text
    if (node.tail or '').strip() or (node.getparent().text or '').strip():
        # text<i class="oi" data-icon="..."/> or <i class="oi" data-icon="..."/>text or
        return

    ## Following or preceding text in span
    def has_text(elem):
        if elem is None:
            return False
        if elem.tag == 'span' and elem.text:
            return True
        if elem.tag in ['field', 'label'] and elem.get('string'):
            return True
        return elem.tag == 't' and elem.get('t-out')

    if has_text(node.getnext()) or has_text(node.getprevious()):
        return

    def has_title_or_aria_label(node):
        return any(node.get(attr) for attr in valid_aria_attrs)

    ## Aria label can be on ancestors
    if any(map(has_title_or_aria_label, node.iterancestors())):
        return

    if node.get('string'):
        return

    ## And we ignore all elements with describing in children
    def contains_description(node, depth=0):
        if depth > 2:
            _logger.warning('excessive depth in data-icon')
        if any(node.get(attr) for attr in valid_t_attrs):
            return True
        if has_title_or_aria_label(node):
            return True
        if node.tag in ('label', 'field'):
            return True
        if node.text:  # not sure, does it match *[text()]
            return True
        return any(contains_description(child, depth+1) for child in node)

    if contains_description(node):
        return

    msg = '%s must have title in its tag, parents, descendants or have text'
    self._log_view_warning(msg % description, node)


def _validate_qweb_directive(self, node, directive, view_type):
    """Some views (e.g. kanban, form) generate owl templates from the archs.
        However, we don't want to see owl directives directly written in archs.
        There are exceptions though, e.g. the kanban arch defines qweb templates.
        We thus here validate that the given directive is allowed, according to the view_type.
        """
    allowed_directives = ["t-translation"]
    if self._is_qweb_based_view(view_type):
        allowed_directives.extend([
            "t-name",
            "t-out",
            "t-set",
            "t-value",
            "t-if",
            "t-else",
            "t-elif",
            "t-foreach",
            "t-as",
            "t-key",
            "t-att.*",
            "t-call",
            "t-debug",
        ])
    if (not next(filter(lambda regex: re.match(regex, directive), allowed_directives), None)):
        self._raise_view_error(_("Forbidden owl directive used in arch (%s).", directive), node)


def _validate_expression(self, node, name_manager, py_expression, use, node_info):
    try:
        if py_expression.lower() in ("0", "false", "1", "true"):
            # most (~95%) elements are 1/True/0/False
            return
        fnames = get_expression_field_names(py_expression)
    except (SyntaxError, ValueError, AttributeError) as e:
        msg = _("Invalid %(use)s: “%(expr)s”\n%(error)s", use=use, expr=py_expression, error=e)
        self._raise_view_error(msg, node, from_exception=e)
    name_manager.must_have_fields(node, fnames, node_info, f"{use} ({py_expression})")


def _validate_domain_identifiers(self, node, name_manager, domain, use, target_model, node_info):
    try:
        fnames, vnames = get_domain_value_names(domain)
    except (SyntaxError, ValueError, AttributeError) as e:
        msg = _("Invalid %(use)s: “%(expr)s”\n%(error)s", use=use, expr=domain, error=e)
        self._raise_view_error(msg, node, from_exception=e)

    self._check_field_paths(node, fnames, target_model, f"{use} ({domain})")
    name_manager.must_have_fields(node, vnames, node_info, f"{use} ({domain})")


def _check_field_paths(self, node, field_paths, model_name, use):
    """ Check whether the given field paths (dot-separated field names)
        correspond to actual sequences of fields on the given model.
        """
    for field_path in field_paths:
        names = field_path.split('.')
        Model = self.pool[model_name]
        if names[0] == 'parent':
            continue
        for index, name in enumerate(names):
            if Model is None:
                msg = _(
                    'Non-relational field “%(field)s” in path “%(field_path)s” in %(use)s)',
                    field=names[index - 1], field_path=field_path, use=use,
                )
                self._raise_view_error(msg, node)
            try:
                field = Model._fields[name]
            except KeyError:
                msg = _(
                    'Unknown field "%(model)s.%(field)s" in %(use)s)',
                    model=Model._name, field=name, use=use,
                )
                self._raise_view_error(msg, node)
            if not field._description_searchable:
                msg = _(
                    'Unsearchable field “%(field)s” in path “%(field_path)s” in %(use)s)',
                    field=name, field_path=field_path, use=use,
                )
                self._raise_view_error(msg, node)
            Model = self.pool.get(field.comodel_name) if field.relational else None


def _validate_custom_views(self, model):
    """Validate architecture of custom views (= without xml id) for a given model.
            This method is called at the end of registry update.
        """
    rec = self.browse(id_ for id_, in self.env.execute_query(SQL("""
                   SELECT max(v.id)
                     FROM ir_ui_view v
                LEFT JOIN ir_model_data md ON (md.model = 'ir.ui.view' AND md.res_id = v.id)
                    WHERE md.module IN (SELECT name FROM ir_module_module) IS NOT TRUE
                      AND v.model = %s
                      AND v.active = true
                 GROUP BY coalesce(v.inherit_id, v.id)
                 """, model)))
    return rec.with_context({'load_all_views': True})._check_xml()


def _validate_module_views(self, module):
    """ Validate the architecture of all the views of a given module that
            are impacted by view updates, but have not been checked yet.
        """
    assert not self.pool.ready

    # only validate the views that still exist...
    prefix = module + '.'
    prefix_len = len(prefix)
    names = tuple(
        xmlid[prefix_len:]
        for xmlid in self.pool.loaded_xmlids
        if xmlid.startswith(prefix)
    )
    if not names:
        return

    # retrieve the views with an XML id that has not been checked yet, i.e.,
    # the views with noupdate=True on their xml id
    views = self.browse(id_ for id_, in self.env.execute_query(SQL("""
            SELECT v.id
            FROM ir_ui_view v
            JOIN ir_model_data md ON (md.model = 'ir.ui.view' AND md.res_id = v.id)
            WHERE md.module = %s AND md.name IN %s AND md.noupdate
        """, module, names)))

    views._check_xml()
