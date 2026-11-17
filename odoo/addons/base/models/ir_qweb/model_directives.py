"""The compilation of the attributes, the tags, the variables and the fields of the templates."""

from __future__ import annotations

from itertools import chain
from lxml import etree
from odoo import tools
from .helpers import T_CALL_SLOT, VARNAME_REGEXP, indent_code


def _compile_directive_att(self, el, compile_context, level):
    """ Compile the attributes of the given elements.

        The compiled function will create the ``attrs`` dictionary.
        Then the dictionary will be output.


        The new namespaces of the current element.

        The static attributes (not prefixed by ``t-``) are add to the
        dictionary in first.

        The dynamic attributes values will be add after. The dynamic
        attributes has different origins.

        - value from key equal to ``t-att``: python dictionary expression;
        - value from keys that start with ``t-att-``: python expression;
        - value from keys that start with ``t-attf-``: format string
            expression.
        """
    code = []
    if (not el.nsmap and el.tag == 't') or (el.nsmap and etree.QName(el.tag).localname == 't'):
        # if it's an invisible element <t>
        if not el.get('t-out') and not el.get('t-esc') and not el.get('t-raw') and el.getparent() is not None:
            # if this invisible doesn't generate content, attributes will never be consumed
            return code
        if el.attrib.get('t-consumed-options') != 'True':
            # If the content is inserted without using a widget, attributes will never be consumed
            return code

    # Compile the introduced new namespaces of the given element.
    #
    # Add the found new attributes into the `attrs` dictionary like
    # the static attributes.
    if el.nsmap:
        for ns_prefix, ns_definition in set(el.nsmap.items()) - set(compile_context['nsmap'].items()):
            key = 'xmlns'
            if ns_prefix is not None:
                key = f'xmlns:{ns_prefix}'
            code.append(indent_code(f'attrs[{key!r}] = {ns_definition!r}', level))

    self._pre_processing_att(el.attrib)

    # Compile the static attributes of the given element.
    #
    # Etree will also remove the ns prefixes indirection in the
    # attributes. As we only have the namespace definition, we'll use
    # an nsmap where the keys are the definitions and the values the
    # prefixes in order to get back the right prefix and restore it.
    if any(not key.startswith('t-') for key in el.attrib):
        nsprefixmap = {v: k for k, v in chain(compile_context['nsmap'].items(), el.nsmap.items())}
        for key in list(el.attrib):
            if not key.startswith('t-'):
                value = el.attrib.pop(key)
                name = key
                attrib_qname = etree.QName(name)
                if attrib_qname.namespace:
                    name = f'{nsprefixmap[attrib_qname.namespace]}:{attrib_qname.localname}'
                code.append(indent_code(f'attrs[{name!r}] = {value!r}', level))

    # Compile the dynamic attributes of the given element. All
    # attributes will be add to the ``attrs`` dictionary in the
    # compiled function.
    for key in list(el.attrib):
        if key.startswith('t-attf-'):
            value = el.attrib.pop(key)
            name = key[7:]
            code.append(indent_code(f"attrs[{name!r}] = {self._compile_format(value, compile_context)}", level))
        elif key.startswith('t-att-'):
            value = el.attrib.pop(key)
            code.append(indent_code(f"attrs[{key[6:]!r}] = {self._compile_expr(value, compile_context)}", level))
        elif key == 't-att':
            value = el.attrib.pop(key)
            code.append(indent_code(f"""
                    atts_value = {self._compile_expr(value, compile_context)}
                    if isinstance(atts_value, dict):
                        attrs.update(atts_value)
                    elif isinstance(atts_value, (list, tuple)) and not isinstance(atts_value[0], (list, tuple)):
                        attrs.update([atts_value])
                    elif isinstance(atts_value, (list, tuple)):
                        attrs.update(dict(atts_value))
                    """, level))

    if code:
        code = [indent_code("attrs = {}", level)] + code
        compile_context['qweb_attrs_created'] = True

    return code


def _compile_directive_tag_open(self, el, compile_context, level):
    """ Compile the opening tag with attributes of the given element into
        a list of python code line.

        The compiled function will fill the ``attrs`` dictionary. Then the
        ``attrs`` dictionary will be output and reset the value of ``attrs``.

        The static attributes (not prefixed by ``t-``) are add to the
        ``attrs`` dictionary in first.

        The dynamic attributes values will be add after. The dynamic
        attributes has different origins.

        - value from key equal to ``t-att``: python dictionary expression;
        - value from keys that start with ``t-att-``: python expression;
        - value from keys that start with ``t-attf-``: format string
            expression.
        """

    el_tag = el.attrib.pop('t-tag-open', None)
    if not el_tag:
        return []

    # open the open tag
    self._append_text(f"<{el_tag}", compile_context)

    # Generates the part of the code that prost process and output the
    # attributes from ``attrs`` dictionary. Consumes `attrs` dictionary
    # and reset it.
    #
    # Use str(value) to change Markup into str and escape it, then use str
    # to avoid the escaping of the other html content.

    if compile_context.get('qweb_attrs_created'):
        code = self._flush_text(compile_context, level)
        code.append(indent_code(f"""
                if attrs:
                    tagName = {el.tag!r}
                    for name, value in self._post_processing_att(tagName, attrs).items():
                        if value or isinstance(value, str):
                            yield f' {{escape(str(name))}}="{{escape(str(value))}}"'
                    attrs = None
            """, level))
    else:
        code = []

    # close the open tag
    if 't-tag-close' in el.attrib:
        self._append_text('>', compile_context)
    else:
        self._append_text('/>', compile_context)

    return code


def _compile_directive_tag_close(self, el, compile_context, level):
    """ Compile the closing tag of the given element into string.
        Returns an empty list because it's use only `_append_text`.
        """
    el_tag = el.attrib.pop("t-tag-close", None)
    if el_tag:
        self._append_text(f'</{el_tag}>', compile_context)
    return []


def _compile_directive_set(self, el, compile_context, level):
    """Compile `t-set` expressions into a python code as a list of
        strings.

        There are 3 kinds of `t-set`:
        * `t-value` containing python code;
        * `t-valuef` containing strings to format;
        * `t-valuef.translate` containing translated strings to format;
        * whose value is the content of the tag (being Markup safe).

        The code will contain the assignment of the dynamically generated value.
        """

    code = self._flush_text(compile_context, level, rstrip=el.tag.lower() == 't')

    if 't-set' in el.attrib:
        varname = el.attrib.pop('t-set')
        if varname == "":
            raise KeyError('t-set')
        if varname != T_CALL_SLOT and varname[0] != '{' and not VARNAME_REGEXP.match(varname):
            raise SyntaxError('The varname can only contain alphanumeric characters and underscores.')
        if '__' in varname:
            raise SyntaxError(f"Using variable names with '__' is not allowed: {varname!r}")

        if 't-value' in el.attrib or 't-valuef' in el.attrib or 't-valuef.translate' in el.attrib or varname[0] == '{':
            el.attrib.pop('t-inner-content') # The content is considered empty.
            if varname == T_CALL_SLOT:
                raise SyntaxError('t-set="0" should not be set from t-value or t-valuef')

        if 't-value' in el.attrib:
            expr = el.attrib.pop('t-value') or 'None'
            code.append(indent_code(f"values[{varname!r}] = {self._compile_expr(expr, compile_context)}", level))
        elif 't-valuef' in el.attrib:
            exprf = el.attrib.pop('t-valuef')
            code.append(indent_code(f"values[{varname!r}] = {self._compile_format(exprf, compile_context)}", level))
        elif 't-valuef.translate' in el.attrib:
            exprf = el.attrib.pop('t-valuef.translate')
            if self.env.context.get('edit_translations'):
                code.append(indent_code(f"values[{varname!r}] = Markup({self._compile_format(exprf, compile_context)})", level))
            else:
                code.append(indent_code(f"values[{varname!r}] = {self._compile_format(exprf, compile_context)}", level))
        elif varname[0] == '{':
            code.append(indent_code(f"values.update({self._compile_expr(varname, compile_context)})", level))
        else:
            # set the content as value
            _ref, path, xml = compile_context['_qweb_error_path_xml']
            content = (
                self._compile_directive(el, dict(compile_context, qweb_attrs_created=False), 'inner-content', 1) +
                self._flush_text(compile_context, 1))
            if content:
                def_name = compile_context['make_name']('t_set')
                def_code = [f"def {def_name}(self, values, root_values, process):"]
                def_code.append(indent_code('attrs = None', 1))
                def_code.append(indent_code('if False: yield ""', 1))
                def_code.append(indent_code(f'# element: {path!r} , {xml!r}', 1))
                def_code.extend(content)
                compile_context['template_functions'][def_name] = def_code

                code.append(indent_code(f"""
                        values[{varname!r}] = QwebContent(self, QwebCallParameters(self.env.context, {compile_context['ref']!r}, {def_name!r}, values.copy(), root_values, 'root', 't-set', (template_options['ref'], {path!r}, {xml!r})), process)
                    """, level))
            else:
                code.append(indent_code(f"values[{varname!r}] = ''", level))

    return code


def _compile_directive_value(self, el, compile_context, level):
    """Compile `t-value` expressions into a python code as a list of strings.

        This method only check if this attributes is on the same node of a
         `t-set` attribute.
        """
    raise SyntaxError("t-value must be on the same node of t-set")


def _compile_directive_valuef(self, el, compile_context, level):
    """Compile `t-valuef` expressions into a python code as a list of strings.

        This method only check if this attributes is on the same node of a
         `t-set` attribute.
        """
    raise SyntaxError("t-valuef must be on the same node of t-set")


def _compile_directive_inner_content(self, el, compile_context, level):
    """Compiles the content of the element (is the technical `t-inner-content`
        directive created by QWeb) into a python code as a list of
        strings.

        The code will contains the text content of the node or the compliled
        code from the recursive call of ``_compile_node``.
        """
    el.attrib.pop('t-inner-content', None)

    if el.nsmap:
        # Update the dict of inherited namespaces before continuing the recursion. Note:
        # since `compile_context['nsmap']` is a dict (and therefore mutable) and we do **not**
        # want changes done in deeper recursion to bevisible in earlier ones, we'll pass
        # a copy before continuing the recursion and restore the original afterwards.
        compile_context = dict(compile_context, nsmap=el.nsmap)

    if el.text is not None:
        self._append_text(el.text, compile_context)
    body = []
    for item in list(el):
        if isinstance(item, etree._Comment):
            if compile_context.get('preserve_comments'):
                self._append_text(f"<!--{item.text}-->", compile_context)
        elif isinstance(item, etree._ProcessingInstruction):
            if compile_context.get('preserve_comments'):
                self._append_text(f"<?{item.target} {item.text}?>", compile_context)
        else:
            body.extend(self._compile_node(item, compile_context, level))
        # comments can also contains tail text
        if item.tail is not None:
            self._append_text(item.tail, compile_context)
    return body


def _compile_directive_groups(self, el, compile_context, level):
    """Compile `t-groups` expressions into a python code as a list of
        strings.

        The code will contain the condition `if self.env.user.has_groups(groups)`
        part that wrap the rest of the compiled code of this element.
        """
    groups = el.attrib.pop('t-groups', el.attrib.pop('groups', None))

    strip = self._rstrip_text(compile_context)
    code = self._flush_text(compile_context, level)
    code.append(indent_code(f"if self.env.user.has_groups({groups!r}):", level))
    if strip and el.tag.lower() != 't':
        self._append_text(strip, compile_context)
    code.extend([
        *self._compile_directives(el, compile_context, level + 1),
        *self._flush_text(compile_context, level + 1, rstrip=True),
    ] or [indent_code('pass', level + 1)])
    return code


def _compile_directive_as(self, el, compile_context, level):
    """Compile `t-as` expressions into a python code as a list of strings.

        This method only check if this attributes is on the same node of a
         `t-foreach` attribute.
        """
    if 't-foreach' not in el.attrib:
        raise SyntaxError("t-as must be on the same node of t-foreach")
    return []


def _compile_directive_field(self, el, compile_context, level):
    """Compile ``t-field`` expressions into a python code as a list of
        strings.

        The compiled code will call ``_get_field`` method at rendering time
        using the type of value supplied by the field. This behavior can be
        changed with ``t-options-widget`` or ``t-options={'widget': ...}``.

        The code will contain evalution and rendering of the compiled value
        value from the record field. If the compiled value is None or False,
        the tag is not added to the render
        (Except if the widget forces rendering or there is default content.).
        """
    tagName = el.tag
    assert tagName not in ("table", "tbody", "thead", "tfoot", "tr", "td",
                             "li", "ul", "ol", "dl", "dt", "dd"),\
        "QWeb widgets do not work correctly on %r elements" % tagName
    assert tagName != 't',\
        "t-field can not be used on a t element, provide an actual HTML node"
    assert "." in el.get('t-field'),\
        "t-field must have at least a dot like 'record.field_name'"

    return self._compile_directive_out(el, compile_context, level)


def _compile_directive_lang(self, el, compile_context, level):
    if 't-call' not in el.attrib:
        raise SyntaxError("t-lang is an alias of t-options-lang but only available on the same node of t-call")
    el.attrib['t-options-lang'] = el.attrib.pop('t-lang')
    return self._compile_node(el, compile_context, level)


def _compile_directive_log(self, el, compile_context, level):
    if 'qweb' not in tools.config['dev_mode']:
        return []

    el.attrib.pop('t-log')

    code = self._flush_text(compile_context, level, rstrip=el.tag.lower() == 't')

    # set the content as value
    ref, path, xml = compile_context['_qweb_error_path_xml']

    def_name = compile_context['make_name']('t_log')
    def_code = [f"def {def_name}(self, values, root_values, process):"]
    def_code.append(indent_code('attrs = None', 1))
    def_code.append(indent_code('if False: yield ""', 1))
    def_code.append(indent_code(f'# element: {path!r} , {xml!r}', 1))
    def_code.extend(self._compile_directives(el, dict(compile_context, qweb_attrs_created=False), 1))
    def_code.extend(self._flush_text(compile_context, 1) or [indent_code('yield ""', 1)])
    compile_context['template_functions'][def_name] = def_code

    code.append(indent_code(f"""
            yield QwebContent(self, QwebCallParameters(self.env.context, {ref!r}, {def_name!r}, values, root_values, False, 't-log', ({ref!r}, {path!r}, {xml!r})), process)
        """, level))

    return code


def _get_field(self, record, field_name, expression, tagName, field_options, values):
    """Method called at compile time to return the field value.

        :returns: tuple:
            * dict: attributes
            * string or None: content
            * boolean: force_display display the tag if the content and default_content are None
        """
    field = record._fields[field_name]

    # adds generic field options
    field_options['tagName'] = tagName
    field_options['expression'] = expression
    field_options['type'] = field_options.get('widget', field.type)
    inherit_branding = (
            self.env.context['inherit_branding']
            if 'inherit_branding' in self.env.context
            else self.env.context.get('inherit_branding_auto') and record.has_access('write'))
    field_options['inherit_branding'] = inherit_branding
    translate = self.env.context.get('edit_translations') and values.get('translatable') and field.translate
    field_options['translate'] = translate

    # field converter
    model = 'ir.qweb.field.' + field_options['type']
    converter = self.env[model] if model in self.env else self.env['ir.qweb.field']

    # get content (the return values from fields are considered to be markup safe)
    content = converter.record_to_html(record, field_name, field_options)
    attributes = converter.attributes(record, field_name, field_options, values)

    return (attributes, content, inherit_branding or translate)


def _get_widget(self, value, expression, tagName, field_options, values):
    """Method called at compile time to return the widget value.

        :returns: tuple:
            * dict: attributes
            * string or None: content
            * boolean: force_display display the tag if the content and default_content are None
        """
    field_options['type'] = field_options['widget']
    field_options['tagName'] = tagName
    field_options['expression'] = expression
    inherit_branding = self.env.context.get('inherit_branding')
    field_options['inherit_branding'] = inherit_branding

    # field converter
    model = 'ir.qweb.field.' + field_options['type']
    converter = self.env[model] if model in self.env else self.env['ir.qweb.field']

    # get content (the return values from widget are considered to be markup safe)
    content = converter.value_to_html(value, field_options)
    attributes = {}
    attributes['data-oe-type'] = field_options['type']
    attributes['data-oe-expression'] = field_options['expression']

    return (attributes, content, inherit_branding)
