"""The compilation of the control-flow directives of the templates: the conditions, the loops and the calls."""

from __future__ import annotations

from lxml import etree
from .helpers import LSTRIP_REGEXP, T_CALL_SLOT, VARNAME_REGEXP, indent_code


def _compile_directive_if(self, el, compile_context, level):
    """Compile `t-if` expressions into a python code as a list of strings.

        The code will contain the condition `if`, `else` and `elif` part that
        wrap the rest of the compiled code of this element.
        """
    expr = el.attrib.pop('t-if', el.attrib.pop('t-elif', None))

    assert not expr.isspace(), 't-if or t-elif expression should not be empty.'

    strip = self._rstrip_text(compile_context)  # the withspaces is visible only when display a content
    if el.tag.lower() == 't' and el.text and LSTRIP_REGEXP.search(el.text):
        strip = ''  # remove technical spaces
    code = self._flush_text(compile_context, level)

    _ref, path, xml = compile_context['_qweb_error_path_xml']
    code.append(indent_code(f"if {self._compile_expr(expr, compile_context)}:", level))
    code.append(indent_code(f'# element: {path!r} , {xml!r}', level + 1))
    body = []
    if strip:
        self._append_text(strip, compile_context)
    body.extend(
        self._compile_directives(el, compile_context, level + 1) +
        self._flush_text(compile_context, level + 1, rstrip=True))
    code.extend(body or [indent_code('pass', level + 1)])

    # Look for the else or elif conditions
    next_el = el.getnext()
    comments_to_remove = []
    while isinstance(next_el, etree._Comment):
        comments_to_remove.append(next_el)
        next_el = next_el.getnext()

    # If there is a t-else directive, the comment nodes are deleted
    # and the t-else or t-elif is validated.
    if next_el is not None and {'t-else', 't-elif'} & set(next_el.attrib):
        # Insert a flag to allow t-else or t-elif rendering.
        next_el.attrib['t-else-valid'] = 'True'

        # remove comment node
        parent = el.getparent()
        for comment in comments_to_remove:
            parent.remove(comment)
        if el.tail and not el.tail.isspace():
            raise SyntaxError("Unexpected non-whitespace characters between t-if and t-else directives")
        el.tail = None

        # You have to render the `t-else` and `t-elif` here in order
        # to be able to put the log. Otherwise, the parent's
        # `t-inner-content`` directive will render the different
        # nodes without taking indentation into account such as:
        #    if (if_expression):
        #         content_if
        #    log ['last_path_node'] = path
        #    else:
        #       content_else

        code.append(indent_code("else:", level))
        body = []
        if strip:
            self._append_text(strip, compile_context)
        body.extend(
            self._compile_node(next_el, compile_context, level + 1)+
            self._flush_text(compile_context, level + 1, rstrip=True))
        code.extend(body or [indent_code('pass', level + 1)])

        # Insert a flag to avoid the t-else or t-elif rendering when
        # the parent t-inner-content dirrective compile his
        # children.
        next_el.attrib['t-qweb-skip'] = 'True'

    return code


def _compile_directive_elif(self, el, compile_context, level):
    """Compile `t-elif` expressions into a python code as a list of
        strings. This method is linked with the `t-if` directive.

        Check if this directive is valide, the t-qweb-skip flag and call
        `t-if` directive
        """
    if not el.attrib.pop('t-else-valid', None):
        raise SyntaxError("t-elif directive must be preceded by t-if or t-elif directive")

    return self._compile_directive_if(el, compile_context, level)


def _compile_directive_else(self, el, compile_context, level):
    """Compile `t-else` expressions into a python code as a list of strings.
        This method is linked with the `t-if` directive.

        Check if this directive is valide and add the t-qweb-skip flag.
        """
    if not el.attrib.pop('t-else-valid', None):
        raise SyntaxError("t-elif directive must be preceded by t-if or t-elif directive")
    el.attrib.pop('t-else')
    return []


def _compile_directive_foreach(self, el, compile_context, level):
    """Compile ``t-foreach`` expressions into a python code as a list of
        strings.

        * ``t-as`` is used to define the key name.
        * ``t-foreach`` compiled value can be an iterable, an dictionary or a
          number.

        The code will contain loop ``for`` that wrap the rest of the compiled
        code of this element.

        Some key into values dictionary are create automatically::

            *_size, *_index, *_value, *_first, *_last, *_odd, *_even, *_parity
        """
    expr_foreach = el.attrib.pop('t-foreach')
    expr_as = el.attrib.pop('t-as')

    if not expr_as:
        raise KeyError('t-as')

    if not VARNAME_REGEXP.match(expr_as):
        raise ValueError(f'The varname {expr_as!r} can only contain alphanumeric characters and underscores.')

    if el.tag.lower() == 't':
        self._rstrip_text(compile_context)

    code = self._flush_text(compile_context, level)

    content_foreach = (
        self._compile_directives(el, compile_context, level + 1) +
        self._flush_text(compile_context, level + 1, rstrip=True))

    t_foreach = compile_context['make_name']('t_foreach')
    size = compile_context['make_name']('size')
    has_value = compile_context['make_name']('has_value')

    if expr_foreach.isdigit():
        code.append(indent_code(f"""
                values[{expr_as + '_size'!r}] = {size} = {int(expr_foreach)}
                {t_foreach} = range({size})
                {has_value} = False
            """, level))
    else:
        code.append(indent_code(f"""
                {t_foreach} = {self._compile_expr(expr_foreach, compile_context)} or []
                if isinstance({t_foreach}, Sized):
                    values[{expr_as + '_size'!r}] = {size} = len({t_foreach})
                elif ({t_foreach}).__class__ == int:
                    values[{expr_as + '_size'!r}] = {size} = {t_foreach}
                    {t_foreach} = range({size})
                else:
                    {size} = None
                {has_value} = False
                if isinstance({t_foreach}, Mapping):
                    {t_foreach} = {t_foreach}.items()
                    {has_value} = True
            """, level))

    code.append(indent_code(f"""
                foreach_attrs = attrs
                for index, item in enumerate({t_foreach}):
                    attrs = foreach_attrs
                    values[{expr_as + '_index'!r}] = index
                    if {has_value}:
                        values[{expr_as!r}], values[{expr_as + '_value'!r}] = item
                    else:
                        values[{expr_as!r}] = values[{expr_as + '_value'!r}] = item
                    values[{expr_as + '_first'!r}] = values[{expr_as + '_index'!r}] == 0
                    if {size} is not None:
                        values[{expr_as + '_last'!r}] = index + 1 == {size}
                    values[{expr_as + '_odd'!r}] = index % 2
                    values[{expr_as + '_even'!r}] = not values[{expr_as + '_odd'!r}]
                    values[{expr_as + '_parity'!r}] = 'odd' if values[{expr_as + '_odd'!r}] else 'even'
            """, level))

    code.extend(content_foreach or [indent_code('continue', level + 1)])
    code.append(indent_code("attrs = None", level + 1))

    return code


def _compile_directive_out(self, el, compile_context, level):
    """Compile `t-out` expressions into a python code as a list of
        strings.

        The code will contain evalution and rendering of the compiled value. If
        the compiled value is None or False, the tag is not added to the render
        (Except if the widget forces rendering or there is default content).
        (eg: `<t t-out="my_value">Default content if falsy</t>`)

        The output can have some rendering option with `t-options-widget` or
        `t-options={'widget': ...}. At rendering time, The compiled code will
        call ``_get_widget`` method or ``_get_field`` method for `t-field`.

        A `t-field` will necessarily be linked to the value of a record field
        (eg: `<span t-field="record.field_name"/>`), a t-out` can be applied
        to any value (eg: `<span t-out="10" t-options-widget="'float'"/>`).
        """
    ttype = 't-out'
    expr = el.attrib.pop('t-out', None)
    if expr is None:
        ttype = 't-field'
        expr = el.attrib.pop('t-field', None)

    flush = self._flush_text(compile_context, level)

    _ref, path, xml = compile_context['_qweb_error_path_xml']

    code_options = el.attrib.pop('t-consumed-options', 'None')

    # The generated code will set the values of the content, attrs (used to
    # output attributes) and the force_display (if the widget or field
    # mark force_display as True, the tag will be inserted in the output
    # even the value of content is None and without default value)

    is_slot = expr == T_CALL_SLOT and code_options != 'True'

    if is_slot:
        code = [indent_code(f"""
                self.env.context['_qweb_error_path_xml'][0] = template_options['ref']
                self.env.context['_qweb_error_path_xml'][1] = {path!r}
                self.env.context['_qweb_error_path_xml'][2] = {xml!r}
                yield values.get({T_CALL_SLOT}, '')
            """, level)]
    elif ttype == 't-field':
        code = []
        record, field_name = expr.rsplit('.', 1)
        attr_name = 'field_attrs' if compile_context.get('qweb_attrs_created') else 'attrs'
        code.append(indent_code(f"""{attr_name}, content, force_display = self._get_field({self._compile_expr(record, compile_context, raise_on_missing=True)}, {field_name!r}, {expr!r}, {el.tag!r}, values.pop('__qweb_options__', {{}}), values)""", level))
        if compile_context.get('qweb_attrs_created'):
            code.append(indent_code("""
                    if attrs is None:
                        attrs = field_attrs
                    else:
                        attrs.update(field_attrs)
                    """, level))
        else:
            compile_context['qweb_attrs_created'] = True
        code.append(indent_code("""
                if content is not None and content is not False:
                    content = self._compile_to_str(content)
                """, level))
        force_display_dependent = True
    else:
        code = []
        if expr == T_CALL_SLOT:
            code.append(indent_code(f"content = values.get({T_CALL_SLOT}, '')", level))
        else:
            code.append(indent_code(f"content = {self._compile_expr(expr, compile_context)}", level))

        if code_options == 'True':
            attr_name = 'widget_attrs' if compile_context.get('qweb_attrs_created') else 'attrs'
            code.append(indent_code(f"""{attr_name}, content, force_display = self._get_widget(content, {expr!r}, {el.tag!r}, values.pop('__qweb_options__', {{}}), values)""", level))
            if compile_context.get('qweb_attrs_created'):
                code.append(indent_code("""
                        if attrs is None:
                            attrs = widget_attrs
                        else:
                            attrs.update(widget_attrs)
                        """, level))
            else:
                compile_context['qweb_attrs_created'] = True
            code.append(indent_code("content = self._compile_to_str(content)", level))
            force_display_dependent = True
        else:
            force_display_dependent = False

    level_tag = level + (0 if is_slot else 1)
    tag_open = (
        self._compile_directive(el, compile_context, 'tag-open', level_tag) +
        self._flush_text(compile_context, level_tag))
    tag_close = (
        self._compile_directive(el, compile_context, 'tag-close', level_tag) +
        self._flush_text(compile_context, level_tag))
    default_body = (
        self._compile_directive(el, compile_context, 'inner-content', level_tag) +
        self._flush_text(compile_context, level_tag))

    if is_slot:
        return flush + tag_open + code + tag_close

    code = flush + code

    # The generated code will create the output tag with all attribute.
    # If the value is not falsy or if there is default content or if it's
    # in force_display mode, the tag is add into the output.

    el.attrib.pop('t-tag', None) # code generating the output is done here

    # generate code to display the tag if the value is not Falsy

    code.append(indent_code("if content is not None and content is not False:", level))
    code.extend(tag_open)
    # Use str to avoid the escaping of the other html content because the
    # yield generator MarkupSafe values will be join into an string in
    # `_render`.
    code.append(indent_code(f"""
            if isinstance(content, QwebContent):
                self.env.context['_qweb_error_path_xml'][0] = template_options['ref']
                self.env.context['_qweb_error_path_xml'][1] = {path!r}
                self.env.context['_qweb_error_path_xml'][2] = {xml!r}
                yield content
            else:
                yield str(escape(content))
        """, level + 1))
    code.extend(tag_close)

    # generate code to display the tag with default content if the value is
    # Falsy

    if default_body or compile_context['_text_concat']:
        _text_concat = list(compile_context['_text_concat'])
        compile_context['_text_concat'].clear()
        code.append(indent_code("else:", level))
        code.extend(tag_open)
        code.extend(default_body)
        compile_context['_text_concat'].extend(_text_concat)
        code.extend(tag_close)
    elif force_display_dependent:

        # generate code to display the tag if it's the force_diplay mode.

        if tag_open + tag_close:
            code.append(indent_code("elif force_display:", level))
            code.extend(tag_open + tag_close)

        code.append(indent_code("""else: attrs = None""", level))

    return code


def _compile_directive_call(self, el, compile_context, level):
    """Compile `t-call` expressions into a python code as a list of
        strings.

        `t-call` allow formating string dynamic at rendering time.
        Can use `t-options` used to call and render the sub-template at
        rendering time.
        The sub-template is called with a copy of the rendering values
        dictionary. The dictionary contains the key 0 coming from the
        compilation of the contents of this element

        The code will contain the call of the template and a function from the
        compilation of the content of this element.
        """
    expr = el.attrib.pop('t-call')

    el_tag = etree.QName(el.tag).localname if el.nsmap else el.tag
    if el_tag != 't':
        raise SyntaxError(f"t-call must be on a <t> element (actually on <{el_tag}>).")

    nsmap = compile_context.get('nsmap')

    code = self._flush_text(compile_context, level, rstrip=el.tag.lower() == 't')
    _ref, path, xml = compile_context['_qweb_error_path_xml']

    # options
    el.attrib.pop('t-consumed-options', None)
    code.append(indent_code("t_call_options = values.pop('__qweb_options__', {})", level))
    if nsmap:
        # update this dict with the current nsmap so that the callee know
        # if he outputting the xmlns attributes is relevenat or not
        nsmap = []
        for key, value in compile_context['nsmap'].items():
            if isinstance(key, str):
                nsmap.append(f'{key!r}:{value!r}')
            else:
                nsmap.append(f'None:{value!r}')
        code.append(indent_code(f"t_call_options.update(nsmap={{{', '.join(nsmap)}}})", level))

    # values from content (t-out="0")
    if bool(list(el) or el.text):
        def_name = compile_context['make_name']('t_call')
        code_content = [f"def {def_name}(self, values, root_values, process):"]
        code_content.append(indent_code('attrs = None', 1))
        code_content.append(indent_code('if False: yield ""', 1))
        code_content.append(indent_code(f'# element: {path!r} , {xml!r}', 1))
        code_content.extend(self._compile_directive(el, dict(compile_context, qweb_attrs_created=False), 'inner-content', 1))
        self._append_text('', compile_context)  # To ensure the template function is a generator and doesn't become a regular function
        code_content.extend(self._flush_text(compile_context, 1, rstrip=True))

        compile_context['template_functions'][def_name] = code_content

        code.append(indent_code(f"""
                t_call_content_values = values.copy()
                qwebContent = QwebContent(self, QwebCallParameters(self.env.context, {compile_context['ref']!r}, {def_name!r}, t_call_content_values, root_values, 'root', 't-call-content', (template_options['ref'], {path!r}, {xml!r})), process)
                t_call_values = {{ {T_CALL_SLOT}: qwebContent}}
            """, level))
    else:
        code.append(indent_code(f"t_call_values = {{ {T_CALL_SLOT}: '' }}", level))

    # args to values
    for key in list(el.attrib):
        if key.endswith('.f'):
            name = key.removesuffix(".f")
            value = el.attrib.pop(key)
            code.append(indent_code(f"t_call_values[{name!r}] = {self._compile_format(value, compile_context)}", level))
        elif key.endswith('.translate'):
            name = key.removesuffix(".f").removesuffix(".translate")
            value = el.attrib.pop(key)
            if self.env.context.get('edit_translations'):
                code.append(indent_code(f"t_call_values[{name!r}] = Markup({self._compile_format(value, compile_context)})", level))
            else:
                code.append(indent_code(f"t_call_values[{name!r}] = {self._compile_format(value, compile_context)}", level))
        elif not key.startswith('t-'):
            value = el.attrib.pop(key)
            code.append(indent_code(f"t_call_values[{key!r}] = {self._compile_expr(value, compile_context)}", level))
        elif key == 't-args':
            value = el.attrib.pop(key)
            code.append(indent_code(f"""
                    atts_value = {self._compile_expr(value, compile_context)}
                    if isinstance(atts_value, dict):
                        t_call_values.update(atts_value)
                    elif isinstance(atts_value, (list, tuple)) and not isinstance(atts_value[0], (list, tuple)):
                        t_call_values.update([atts_value])
                    elif isinstance(atts_value, (list, tuple)):
                        t_call_values.update(dict(atts_value))
                    """, level))

    template = expr if expr.isnumeric() else self._compile_format(expr, compile_context)

    # call
    code.append(indent_code(f"""
            template = {template}
            """, level))
    if '%' in template:
        code.append(indent_code("""
                if template.isnumeric():
                    template = int(template)
                """, level))

    code.append(indent_code(f"yield QwebCallParameters(t_call_options, template, None, t_call_values, root_values, True, 't-call', (template_options['ref'], {path!r}, {xml!r}))", level))

    return code


def _compile_directive_call_assets(self, el, compile_context, level):
    """ This special 't-call-assets' tag can be used in order to aggregate/minify javascript and css assets"""
    if len(el) > 0:
        raise SyntaxError("t-call-assets cannot contain children nodes")

    code = self._flush_text(compile_context, level)
    xmlid = el.attrib.pop('t-call-assets')
    css = self._compile_bool(el.attrib.pop('t-css', True))
    js = self._compile_bool(el.attrib.pop('t-js', True))
    binary = self._compile_bool(el.attrib.pop('t-binary', False))
    # async_load support was removed
    defer_load = self._compile_bool(el.attrib.pop('defer_load', False))
    lazy_load = self._compile_bool(el.attrib.pop('lazy_load', False))
    media = el.attrib.pop('media', False)
    autoprefix = self._compile_bool(el.attrib.pop('t-autoprefix', False))
    code.append(indent_code(f"""
            t_call_assets_nodes = self._get_asset_nodes(
                {xmlid!r},
                css={css},
                js={js},
                binary={binary},
                debug=values.get("debug"),
                defer_load={defer_load},
                lazy_load={lazy_load},
                media={media!r},
                autoprefix={autoprefix}
            )
        """.strip(), level))

    code.append(indent_code("""
            for index, (tagName, asset_attrs) in enumerate(t_call_assets_nodes):
                if index:
                    yield '\\n        '
                yield '<'
                yield tagName

                for name, value in self._post_processing_att(tagName, asset_attrs).items():
                    if value or isinstance(value, str):
                        yield f' {escape(str(name))}="{escape(str(value))}"'

                if tagName in VOID_ELEMENTS:
                    yield '/>'
                else:
                    yield '>'
                    yield '</'
                    yield tagName
                    yield '>'
                """, level))

    return code
