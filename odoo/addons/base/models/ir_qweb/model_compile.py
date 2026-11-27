"""The compilation of the templates into code: the nodes, the directives in their order, and the text."""

from __future__ import annotations

from markupsafe import escape
from itertools import chain
from lxml import etree
from urllib.parse import unquote_plus
from odoo.tools.text.translate import FORMAT_REGEX
from .helpers import FIRST_RSTRIP_REGEXP, MALICIOUS_SCHEMES, RSTRIP_REGEXP, SPECIAL_DIRECTIVES, VOID_ELEMENTS, WHITESPACE_REGEX, indent_code

from .model import _logger

def _append_text(self, text, compile_context):
    """ Add an item (converts to a string) to the list.
            This will be concatenated and added during a call to the
            `_flush_text` method. This makes it possible to return only one
            yield containing all the parts."""
    compile_context['_text_concat'].append(self._compile_to_str(text))


def _rstrip_text(self, compile_context):
    """ The text to flush is right stripped, and the stripped content are
        returned.
        """
    text_concat = compile_context['_text_concat']
    if not text_concat:
        return ''

    result = RSTRIP_REGEXP.search(text_concat[-1])
    strip = result.group(0) if result else ''
    text_concat[-1] = RSTRIP_REGEXP.sub('', text_concat[-1])

    return strip


def _flush_text(self, compile_context, level, rstrip=False):
    """Concatenate all the textual chunks added by the `_append_text`
            method into a single yield.
            If no text to flush, return an empty list

            If rstrip the text is right stripped.

            @returns list(str)
        """
    text_concat = compile_context['_text_concat']
    if not text_concat:
        return []
    if rstrip:
        self._rstrip_text(compile_context)
    text = ''.join(text_concat)
    text_concat.clear()
    if not text:
        return []
    return [f"{'    ' * level}yield {text!r}"]


def _is_static_node(self, el, compile_context):
    """ Test whether the given element is purely static, i.e. (there
        are no t-* attributes), does not require dynamic rendering for its
        attributes.
        """
    return el.tag != 't' and 'groups' not in el.attrib and not any(
        att.startswith('t-') and att not in ('t-tag-open', 't-inner-content')
        for att in el.attrib
    )


def _remove_translate_suffix(self, attrib):
    for key in list(attrib):
        if key.endswith('.translate'):
            attrib[key.removesuffix('.translate')] = attrib.pop(key)


def _pre_processing_att(self, attrib):
    self._remove_translate_suffix(attrib)


def _compile_format(self, expr, compile_context):
    """ Parses the provided format string and compiles it to a single
        expression python, uses string with format method.
        Use format is faster to concat string and values.
        """
    # <t t-setf-name="Hello #{world} %s !"/>
    # =>
    # values['name'] = 'Hello %s %%s !' % (values['world'],)
    values = [
        f'self._compile_to_str({self._compile_expr(m.group(1) or m.group(2), compile_context)})'
        for m in FORMAT_REGEX.finditer(expr)
    ]
    if not values:
        return repr(expr)
    code = repr(FORMAT_REGEX.sub('%s', expr.replace('%', '%%')))
    code += f' % ({", ".join(values)},)'
    return code


def _directives_eval_order(self):
    """ List all supported directives in the order in which they should be
        evaluated on a given element. For instance, a node bearing both
        ``foreach`` and ``if`` should see ``foreach`` executed before ``if``
        aka

        .. code-block:: xml

            <el t-foreach="foo" t-as="bar" t-if="bar">

        should be equivalent to

        .. code-block:: xml

            <t t-foreach="foo" t-as="bar">
                <t t-if="bar">
                    <el>

        then this method should return ``['foreach', 'if']``.
        """
    return [
        'elif', # Must be the first because compiled by the previous if.
        'else', # Must be the first because compiled by the previous if.
        'debug',
        'log',
        'groups',
        'as', 'foreach',
        'if',
        'call-assets',
        'lang',
        'options',
        'call',
        'att',
        'field', 'out',
        'tag-open',
        'set',
        'inner-content',
        'tag-close',
    ]


def _compile_root(self, element, compile_context):
    element.attrib.pop('t-name', None)
    if element.text:
        element.text = FIRST_RSTRIP_REGEXP.sub(r'\2', element.text)
    return self._compile_node(element, compile_context, 1)


def _compile_node(self, el, compile_context, level):
    """ Compile the given element into python code.

            The t-* attributes (directives) will be converted to a python instruction. If there
            are no t-* attributes, the element will be considered static.

            Directives are compiled using the order provided by the
            ``_directives_eval_order`` method (an create the
            ``compile_context['iter_directives']`` iterator).
            For compilation, the directives supported are those with a
            compilation method ``_compile_directive_*``

        :return: list of string
        """
    # Internal directive used to skip a rendering.
    if 't-qweb-skip' in el.attrib:
        return []

    # if tag don't have qweb attributes don't use directives
    if self._is_static_node(el, compile_context):
        return self._compile_static_node(el, compile_context, level)

    path = compile_context['root'].getpath(el)
    xml = etree.tostring(etree.Element(el.tag, el.attrib), encoding='unicode')
    compile_context['_qweb_error_path_xml'][0] = compile_context['ref']
    compile_context['_qweb_error_path_xml'][1] = path
    compile_context['_qweb_error_path_xml'][2] = xml
    body = [indent_code(f'# element: {path!r} , {xml!r}', level)]

    # create an iterator on directives to compile in order
    compile_context['iter_directives'] = iter(self._directives_eval_order())

    # add technical directive tag-open, tag-close, inner-content and take
    # care of the namspace
    if not el.nsmap:
        unqualified_el_tag = el_tag = el.tag
    else:
        # Etree will remove the ns prefixes indirection by inlining the corresponding
        # nsmap definition into the tag attribute. Restore the tag and prefix here.
        # Note: we do not support namespace dynamic attributes, we need a default URI
        # on the root and use attribute directive t-att="{'xmlns:example': value}".
        unqualified_el_tag = etree.QName(el.tag).localname
        el_tag = unqualified_el_tag
        if el.prefix:
            el_tag = f'{el.prefix}:{el_tag}'

    if unqualified_el_tag != 't':
        el.set('t-tag-open', el_tag)
        if el_tag not in VOID_ELEMENTS:
            el.set('t-tag-close', el_tag)

    if not {'t-out', 't-field'}.intersection(el.attrib):
        el.set('t-inner-content', 'True')

    return body + self._compile_directives(el, compile_context, level)


def _compile_static_node(self, el, compile_context, level):
    """ Compile a purely static element into a list of string. """
    self._pre_processing_att(el.attrib)
    if not el.nsmap:
        unqualified_el_tag = el_tag = el.tag
        attrib = self._post_processing_att(el.tag, {**el.attrib, '__is_static_node': True})
    else:
        # Etree will remove the ns prefixes indirection by inlining the corresponding
        # nsmap definition into the tag attribute. Restore the tag and prefix here.
        unqualified_el_tag = etree.QName(el.tag).localname
        el_tag = unqualified_el_tag
        if el.prefix:
            el_tag = f'{el.prefix}:{el_tag}'

        attrib = {}
        # If `el` introduced new namespaces, write them as attribute by using the
        # `attrib` dict.
        for ns_prefix, ns_definition in set(el.nsmap.items()) - set(compile_context['nsmap'].items()):
            if ns_prefix is None:
                attrib['xmlns'] = ns_definition
            else:
                attrib[f'xmlns:{ns_prefix}'] = ns_definition

        # Etree will also remove the ns prefixes indirection in the attributes. As we only have
        # the namespace definition, we'll use an nsmap where the keys are the definitions and
        # the values the prefixes in order to get back the right prefix and restore it.
        ns = chain(compile_context['nsmap'].items(), el.nsmap.items())
        nsprefixmap = {v: k for k, v in ns}
        for key, value in el.attrib.items():
            attrib_qname = etree.QName(key)
            if attrib_qname.namespace:
                attrib[f'{nsprefixmap[attrib_qname.namespace]}:{attrib_qname.localname}'] = value
            else:
                attrib[key] = value

        attrib = self._post_processing_att(el.tag, {**attrib, '__is_static_node': True})

        # Update the dict of inherited namespaces before continuing the recursion. Note:
        # since `compile_context['nsmap']` is a dict (and therefore mutable) and we do **not**
        # want changes done in deeper recursion to bevisible in earlier ones, we'll pass
        # a copy before continuing the recursion and restore the original afterwards.
        original_nsmap = dict(compile_context['nsmap'])

    if unqualified_el_tag != 't':
        attributes = ''.join(f' {name}="{escape(str(value))}"'
                            for name, value in attrib.items() if value or isinstance(value, str))
        self._append_text(f'<{el_tag}{"".join(attributes)}', compile_context)
        if el_tag in VOID_ELEMENTS:
            self._append_text('/>', compile_context)
        else:
            self._append_text('>', compile_context)

    el.attrib.clear()

    if el.nsmap:
        compile_context['nsmap'].update(el.nsmap)
        body = self._compile_directive(el, compile_context, 'inner-content', level)
        compile_context['nsmap'] = original_nsmap
    else:
        body = self._compile_directive(el, compile_context, 'inner-content', level)

    if unqualified_el_tag != 't':
        if el_tag not in VOID_ELEMENTS:
            self._append_text(f'</{el_tag}>', compile_context)

    return body


def _compile_directives(self, el, compile_context, level):
    """ Compile the given element, following the directives given in the
        iterator ``compile_context['iter_directives']`` create by
        `_compile_node`` method.

        :return: list of code lines
        """
    if self._is_static_node(el, compile_context):
        el.attrib.pop('t-tag-open', None)
        el.attrib.pop('t-inner-content', None)
        el.attrib.pop('t-tag-close', None)
        return self._compile_static_node(el, compile_context, level)

    ref, path, xml = compile_context['_qweb_error_path_xml']

    code = []

    # compile the directives still present on the element
    for directive in compile_context['iter_directives']:
        if ('t-' + directive) in el.attrib:
            code.extend(self._compile_directive(el, compile_context, directive, level))
        elif directive == 'groups':
            if directive in el.attrib:
                code.extend(self._compile_directive(el, compile_context, directive, level))
        elif directive == 'att':
            code.extend(self._compile_directive(el, compile_context, directive, level))
        elif directive == 'options':
            if any(name.startswith('t-options-') for name in el.attrib):
                code.extend(self._compile_directive(el, compile_context, directive, level))

    # compile unordered directives still present on the element
    for att in el.attrib:
        if att not in SPECIAL_DIRECTIVES and att.startswith('t-') and getattr(self, f"_compile_directive_{att[2:].replace('-', '_')}", None):
            code.extend(self._compile_directive(el, compile_context, directive, level))

    remaining = set(el.attrib) - SPECIAL_DIRECTIVES
    if remaining:
        _logger.warning('Unknown directives or unused attributes: %s from %s\nPath: %s\nTemplate: %s', remaining, xml, path, compile_context['ref_name'] or ref)

    return code


def _compile_directive(self, el, compile_context, directive, level):
    compile_handler = getattr(self, f"_compile_directive_{directive.replace('-', '_')}", None)
    if compile_context.get('profile') and directive not in ('inner-content', 'tag-open', 'tag-close'):
        enter = f"{' ' * 4 * level}self.env.context['qweb_tracker'].enter_directive({directive!r}, {el.attrib!r}, {compile_context['_qweb_error_path_xml'][1]!r})"
        leave = f"{' ' * 4 * level}self.env.context['qweb_tracker'].leave_directive({directive!r}, {el.attrib!r}, {compile_context['_qweb_error_path_xml'][1]!r})"
        code_directive = compile_handler(el, compile_context, level)
        if code_directive:
            code_directive = [enter, *code_directive, leave]
    else:
        code_directive = compile_handler(el, compile_context, level)
    return code_directive


def _compile_directive_debug(self, el, compile_context, level):
    """Compile `t-debug` expressions into a python code as a list of
        strings.

        The code will contains the call to the debugger chosen from the valid
        list.
        """
    debugger = el.attrib.pop('t-debug')
    code = []
    if compile_context.get('dev_mode'):
        code.append(indent_code(f"self._debug_trace({debugger!r}, values)", level))
    else:
        _logger.warning("@t-debug in template is only available in qweb dev mode")
    return code


def _compile_directive_options(self, el, compile_context, level):
    """
        compile t-options and add to the dict the t-options-xxx. Will create
        the dictionary ``values['__qweb_options__']`` in compiled code.
        """
    code = []
    dict_options = []
    for key in list(el.attrib):
        if key.startswith('t-options-'):
            value = el.attrib.pop(key)
            option_name = key[10:]
            dict_options.append(f'{option_name!r}:{self._compile_expr(value, compile_context)}')

    t_options = el.attrib.pop('t-options', None)
    if t_options and dict_options:
        code.append(indent_code(f"values['__qweb_options__'] = {{**{self._compile_expr(t_options, compile_context)}, {', '.join(dict_options)}}}", level))
    elif dict_options:
        code.append(indent_code(f"values['__qweb_options__'] = {{{', '.join(dict_options)}}}", level))
    elif t_options:
        code.append(indent_code(f"values['__qweb_options__'] = {self._compile_expr(t_options, compile_context)}", level))
    else:
        code.append(indent_code("values['__qweb_options__'] = {}", level))

    el.set('t-consumed-options', str(bool(code)))

    return code


def _compile_directive_consumed_options(self, el, compile_context, level):
    raise SyntaxError('the t-options must be on the same tag as a directive that consumes it (for example: t-out, t-field, t-call)')


def _post_processing_att(self, tagName, atts):
    """ Method called at compile time for the static node and called at
            runing time for the dynamic attributes.

            This method may be overwrited to filter or modify the attributes
            (during compilation for static node or after they compilation in
            the case of dynamic elements).

            @returns dict
        """
    if atts.pop('__is_static_node', False):
        return atts
    href = str(atts.get('href') or '')
    if MALICIOUS_SCHEMES(WHITESPACE_REGEX.sub('', unquote_plus(href))):
        atts['href'] = ""
    return atts
