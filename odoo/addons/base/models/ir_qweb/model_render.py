"""The rendering of the templates: the render, the code generation and its caches, the templates and their preloading."""

from __future__ import annotations

import math
import pprint
import re
import textwrap
import threading
import traceback
import warnings
import werkzeug
from markupsafe import Markup
from collections.abc import Sequence, Iterator
from copy import deepcopy
from itertools import count
from lxml import etree
from dateutil.relativedelta import relativedelta
from pathlib import Path
from psycopg2.extensions import TransactionRollbackError
from psycopg2.errors import ReadOnlySqlTransaction
from types import FunctionType
from odoo import models, tools
from odoo.modules import Manifest
from odoo.tools import config, safe_eval, OrderedSet, frozendict, json
from odoo.tools.constants import SUPPORTED_DEBUGGER
from odoo.tools.misc import file_open, file_path
from odoo.tools.files.image import image_data_uri
from odoo.tools.profiling.profiler import ExecutionContext
from odoo.http import request
from odoo.tools.profiling.profiler import QwebTracker
from odoo.exceptions import UserError, MissingError
from .content import QwebContent, qwebJSON
from .errors import QWebError, QWebErrorInfo
from .helpers import ETREE_TEMPLATE_REF, TO_VARNAME_REGEXP, T_CALL_SLOT, _id_or_xmlid, indent_code, keep_query, unsafe_eval
from .stack import QwebCallParameters, QwebStackFrame

from .model import IrQweb, _logger

def _render(self, template: int | str | etree._Element, values: dict | None = None, **options) -> Markup:
    """ Render the template specified by the given name.

        :param template: etree, xml_id, template name (see _get_template)
            * Call the method ``load`` is not an etree.
        :param dict values: template values to be used for rendering
        :param options: used to compile the template
            Options will be add into the IrQweb.env.context for the rendering.

            * ``lang`` (str) used language to render the template
            * ``inherit_branding`` (bool) add the tag node branding
            * ``inherit_branding_auto`` (bool) add the branding on fields
            * ``minimal_qcontext``(bool) To use the minimum context and options
              from ``_prepare_environment``

        :returns: bytes marked as markup-safe (decode to :class:`markupsafe.Markup`
                  instead of `str`)
        :rtype: MarkupSafe
        """
    # profiling code
    current_thread = threading.current_thread()
    execution_context_enabled = getattr(current_thread, 'profiler_params', {}).get('execution_context_qweb')
    qweb_hooks = getattr(current_thread, 'qweb_hooks', ())
    if execution_context_enabled or qweb_hooks:
        # To have the new compilation cached because the generated code will change.
        # Therefore 'profile' is a key to the cache.
        options['profile'] = True

    values = values.copy() if values else {}
    if T_CALL_SLOT in values:
        _logger.warning('values[0] should be unset when call the _render method and only set into the template.')
        values.pop(T_CALL_SLOT)

    irQweb = self.with_context(**options)._prepare_environment(values)
    irQweb = irQweb.with_context(
        # Reference to the last node being compiled. It is mainly used for debugging and displaying error messages.
        _qweb_error_path_xml=[None, None, None],
    )

    safe_eval.check_values(values)

    root_values = frozendict(values.copy())
    process = {
        # List of generated and/or used functions, used for optimal performance
        'qweb_loaded_functions': {},
        'qweb_loaded_options': {},
        # List of codes generated during compilation. It is mainly used for debugging and displaying error messages.
        'qweb_loaded_codes': {},
    }

    iterator = irQweb._render_iterall(template, None, values, root_values, process)
    return Markup(''.join(iterator))


def _render_iterall(self, view_ref, method, values, root_values, process, directive='render') -> Iterator[str]:
    """ Iterate over the generator method.
            Generator elements are a str
        """

    loaded_functions = process['qweb_loaded_functions']
    loaded_options = process['qweb_loaded_options']

    params = QwebCallParameters(
        context={},
        view_ref=view_ref,
        method=method,
        values=None,
        root_values=root_values,
        scope=False,
        directive=directive,
        path_xml=None,
    )
    stack = [QwebStackFrame(params, self, iter([params]), values, None)]

    try:
        while stack:
            if len(stack) > 50:
                raise RecursionError('Qweb template infinite recursion')  # noqa: TRY301

            frame = stack[-1]

            # traverse the iterator
            for item in frame.iterator:
                # To debug the rendering step by step you can log the (len(stack) * '  ', repr(item))
                if isinstance(item, str):
                    yield item
                    continue

                # use QwebContent params or return already evaluated QwebContent
                if is_content := isinstance(item, QwebContent):
                    params = item.params__
                    if params.directive == 't-log':
                        path = OrderedSet(str(info.params.path_xml) for info in stack if info.params.path_xml)
                        path.add(str(params.path_xml))
                        _logger.warning("t-log is displayed in dev mode:\n    %s\n\n%s", '\n    '.join(path), item or "--EMPTY--")
                    if item.html is not None:
                        yield item.html
                        continue

                else:  # isinstance(item, QwebCallParameters)
                    params = item

                # add new QwebStackFrame from QwebCallParameters
                values = frame.values
                irQweb = frame.irQweb

                # Use the current directive context
                if params.context:
                    irQweb = irQweb.with_context(**params.context)

                render_template = loaded_functions.get(params.method)

                # Fetch the compiled function and template options
                if not render_template:
                    template_functions, def_name, options, _code = irQweb._compile(params.view_ref)
                    loaded_functions.update(template_functions)
                    loaded_options[params.view_ref] = options
                    render_template = template_functions[params.method or def_name]
                else:
                    options = loaded_options[params.view_ref]

                # Apply a new scope if needed
                if params.scope:
                    if params.scope == 'root':
                        values = root_values
                    values = values.copy()

                # Update values with default values
                if params.values:
                    values.update(params.values)

                iterator = iter([])
                try:
                    # Create the iterator from the template
                    iterator = render_template(irQweb, values, root_values, process)
                finally:
                    if is_content and self.env.context['_qweb_error_path_xml'][1]:
                        # add a stack frame to log a complete error with the path when compile the template
                        logParams = QwebCallParameters(*(params[0:-1] + (tuple(self.env.context['_qweb_error_path_xml']),)))
                        stack.append(QwebStackFrame(logParams, irQweb, [], values, options))
                    stack.append(QwebStackFrame(params, irQweb, iterator, values, options))
                break

            else:
                stack.pop()

    except (TransactionRollbackError, ReadOnlySqlTransaction):
        raise

    except Exception as error:
        qweb_error_info = self._get_error_info(error, stack[1:], stack[-1], process)
        if qweb_error_info.template is None and qweb_error_info.ref is None:
            qweb_error_info.ref = view_ref

        if hasattr(error, 'qweb'):
            if qweb_error_info.source:
                error.qweb.source = qweb_error_info.source + error.qweb.source
            if not error.qweb.ref and frame.params.view_ref:
                error.qweb.ref = frame.params.view_ref
            qweb_error_info = error.qweb
        elif not isinstance(error, UserError):
            # If is not an odoo Exception check if the current error is raise from
            # IrQweb (models or computed code). In this case, convert it into an QWebError.
            isQweb = False

            trace = error.__traceback__
            tb_frames = [trace.tb_frame]
            while trace.tb_next is not None:
                trace = trace.tb_next
                tb_frames.append(trace.tb_frame)
            for tb_frame in tb_frames[::-1]:
                if tb_frame.f_globals.get('__name__') == __name__ or (
                    isinstance(tb_frame.f_locals.get('self'), models.AbstractModel)
                    and tb_frame.f_locals['self']._name == self._name
                ):
                    isQweb = True
                    break
                if any(path in tb_frame.f_code.co_filename for path in tools.config['addons_path']):
                    break

            if isQweb:
                raise QWebError(qweb_error_info) from error

        error.qweb = qweb_error_info
        raise


def _get_error_info(self, error, stack: list[QwebStackFrame], frame: QwebStackFrame, process) -> QWebErrorInfo:
    no_id_ref = 'etree._Element'

    path = None
    html = None
    loaded_codes = process['qweb_loaded_codes']

    # The compilation may have failed before the compilation options were loaded
    # or come from an evaluated QWebContent.
    options = frame.options or {}
    if frame.params.view_ref not in loaded_codes:
        try:
            _template_functions, _def_name, options, code = self._compile(frame.params.view_ref)
            loaded_codes[frame.params.view_ref] = code
        except Exception:  # noqa: BLE001
            pass

    if (frame.params.view_ref in loaded_codes and not isinstance(error, RecursionError)) or len(stack) <= 1:
        if 'ref' not in options:
            options = process['qweb_loaded_options'].get(frame.params.view_ref) or {}

        ref = options.get('ref') or frame.params.view_ref  # The template can have a null reference, for example for a provided etree.
        ref_name = options.get('ref_name') or None
        code = loaded_codes.get(frame.params.view_ref) or loaded_codes.get(no_id_ref)
        if ref == self.env.context['_qweb_error_path_xml'][0]:
            path = self.env.context['_qweb_error_path_xml'][1]
            html = self.env.context['_qweb_error_path_xml'][2]
    else:
        # get the previous caller (like t-call) to display erroneous xml node.
        options = stack[-2].options or {}  # The compilation may have failed before the compilation options were loaded.
        ref = options.get('ref')
        ref_name = options.get('ref_name')
        code = loaded_codes.get(ref) or loaded_codes.get(no_id_ref)
        if frame.params.path_xml:
            path = frame.params.path_xml[1]
            html = frame.params.path_xml[2]

    source_file_ref = None if ref == no_id_ref else ref
    line_nb = 0
    trace = traceback.format_exc()

    for error_line in reversed(trace.split('\n')):
        if f'File "<{source_file_ref}>"' in error_line or (ref is None and 'File "<' in error_line):
            line_function = error_line.split(', line ')[1]
            line_nb = int(line_function.split(',')[0]) - 1
            break

    source = [info.params.path_xml for info in stack if info.params.path_xml]
    code_lines = (code or '').split('\n')

    found = False
    for code_line in reversed(code_lines[:line_nb]):
        if code_line.startswith('def '):
            break
        match = re.match(r'\s*# element: (.*) , (.*)', code_line)
        if not match:
            if found:
                break
            continue

        c_path = match[1][1:-1]
        c_html = match[2][1:-1]
        if c_html == '<t/>':
            continue
        if found:
            info = (ref, c_path, c_html)
            if info not in source:
                source.append(info)
        else:
            found = True
            path = c_path
            html = c_html

    if path:
        source.append((ref, path, html))
    elif isinstance(frame.params, QwebCallParameters) and frame.params.path_xml:
        ref, path, html = frame.params.path_xml

    surrounding = None
    if self.env.context.get('dev_mode') and line_nb:
        if html and ' t-if=' in html and ' if ' in '\n'.join(code_lines[line_nb - 2:line_nb - 1]):
            line_nb -= 1
        previous_lines = '\n'.join(code_lines[max(line_nb - 25, 0):line_nb - 1])
        line = code_lines[line_nb - 1]
        next_lines = '\n'.join(code_lines[line_nb:line_nb + 5])
        indent = re.search(r"^(\s*)", line).group(0)
        surrounding = textwrap.indent(
            textwrap.dedent(
                f"{previous_lines}\n"
                f"{indent}########### Line triggering the error ############\n{line}\n"
                f"{indent}##################################################\n{next_lines}"
            ),
            ' ' * 8
        )

    return QWebErrorInfo(f'{error.__class__.__name__}: {error}', ref if ref_name is None else ref_name, ref, path, html, source, surrounding)


def _get_template_cache_keys(self):
    """ Return the list of context keys to use for caching ``_compile``. """
    return ['lang', 'inherit_branding', 'inherit_branding_auto', 'edit_translations', 'profile', 'preserve_comments']


def _get_template_info(self, template):
    return self.env['ir.ui.view']._get_cached_template_info(template)


def _compile(self, template):
    ref = None
    if isinstance(template, str) and template.endswith('.xml'):
        module_path = Manifest.for_addon(Path(template).parts[0]).path
        if 'templates' not in Path(file_path(template)).relative_to(module_path).parts:
            raise ValueError("The templates file %s must be under a subfolder 'templates' of a module", template)
        else:
            with file_open(template, 'rb', filter_ext=('.xml',)) as file:
                template = etree.fromstring(file.read())
    elif not isinstance(template, etree._Element):
        ref = self._get_template_info(template)['id']

    if ref:
        template_functions, def_name, options, code = self._generate_code_cached(ref)
    else:
        template_functions, def_name, options, code = self._generate_code_uncached(template)

    render_template = template_functions[def_name]
    if options.get('profile') and render_template.__name__ != 'profiled_method_compile':
        ref = options.get('ref')
        ref_xml = str(val) if (val := options.get('ref_xml')) else None

        def wrap(function):
            def profiled_method_compile(self, values, root_values, process):
                qweb_tracker = QwebTracker(ref, ref_xml, self.env.cr)
                self = self.with_context(qweb_tracker=qweb_tracker)
                if qweb_tracker.execution_context_enabled:
                    with ExecutionContext(template=ref):
                        return function(self, values, root_values, process)
                return function(self, values, root_values, process)

            return profiled_method_compile

        for key, function in template_functions.items():
            if isinstance(function, FunctionType):
                template_functions[key] = wrap(function)

    return (template_functions, def_name, options, code)


def _generate_code_cached(self, ref: int):
    # The method preloads templates to put information into the transaction
    # cache in addition to browse records. It also loads in batch the
    # template from directives (like: t-call and t-snippet).
    try:
        document = self._get_template(ref)[1]
    except Exception:  # noqa: BLE001
        return self._generate_code_uncached(ref)

    view_hash = hash(document)
    cache_key = tuple(self.env.context.get(k) or False for k in self._get_template_cache_keys())

    if 'xml' in tools.config['dev_mode']:
        return self._generate_code_uncached(ref)
    memo_key = (ref, view_hash, cache_key)
    cache = self.env.registry._template_code__
    code = cache.get(memo_key)
    if code is None:
        code = self._generate_code_uncached(ref)
        cache[memo_key] = code
    return code


def _generate_code_uncached(self, template: int | str | etree._Element):
    assert isinstance(self, IrQweb)
    ref = self._get_template_info(template)['id'] if isinstance(template, (int, str)) else None

    code, options, def_name, error = self._generate_code(template)

    if error:
        Error, message, stack = error

        def not_found_template(self, values, root_values, process):
            if tools.config['dev_mode']:
                _logger.info(stack)
            if self.env.context.get('raise_if_not_found', True):
                raise Error(message)
            _logger.warning('Cannot load template %s: %s', template, message)
            return ''

        return {'not_found_template': not_found_template}, 'not_found_template', frozendict(options), ''

    wrap_code = '\n'.join([
        "def generate_functions():",
        indent_code(code, 1),
        f"    code = {code!r}",
        "    return template_functions, code",
    ])
    compiled = compile(wrap_code, f"<{ref}>", 'exec')
    globals_dict = self._IrQweb__prepare_globals()
    globals_dict['__builtins__'] = globals_dict  # So that unknown/unsafe builtins are never added.
    unsafe_eval(compiled, globals_dict)

    template_functions, code = globals_dict['generate_functions']()
    return template_functions, def_name, frozendict(options), code


def _generate_code(self, template: int | str | etree._Element):
    """ Compile the given template into a rendering function (generator)::

            render_template(qweb, values)

        This method can be called only by :meth:`_render` method or by
        the compiled code of t-call from an other template.

        An ``options`` dictionary is created and attached to the function.
        It contains rendering options that are part of the cache key in
        addition to template references.

        where ``qweb`` is a QWeb instance and ``values`` are the values to
        render.

        :returns: tuple containing code, options and main method name
        """
    if not isinstance(template, (int, str, etree._Element)):
        template = str(template)
    # The `compile_context`` dictionary includes the elements used for the
    # cache key to which are added the template references as well as
    # technical information useful for generating the function. This
    # dictionary is only used when compiling the template.
    compile_context = self.env.context.copy()

    try:
        element, document, ref = self._get_template(template)
    except (ValueError, UserError) as e:
        # return the error information if the template is not found or fail
        options = {k: compile_context.get(k, False) for k in self._get_template_cache_keys()}
        message = str(e)
        if hasattr(e, 'context') and e.context.get('view'):
            message = f"{message} (view: {e.context['view'].key})"
        error = (e.__class__, message, traceback.format_exc())
        return (None, options, 'not_found_template', error)

    compile_context.pop('raise_if_not_found', None)

    ref_name = element.attrib.get('t-name')
    if isinstance(ref, int) or (isinstance(template, str) and '<' not in template):
        ref_name = self._get_template_info(ref)['key'] or ref_name

    # reference to get xml and etree (usually the template ID)
    compile_context['ref'] = ref
    # reference name or key to get xml and etree (usually the template XML ID)
    compile_context['ref_name'] = ref_name
    # str xml of the reference template used for compilation. Useful for debugging, dev mode and profiling.
    compile_context['ref_xml'] = str(document) if document else None
    # Identifier used to call `_compile`
    compile_context['template'] = template
    # Root of the etree which will be processed during compilation.
    compile_context['root'] = element.getroottree()
    # Reference to the last node being compiled. It is mainly used for debugging and displaying error messages.
    compile_context['_qweb_error_path_xml'] = compile_context.get('_qweb_error_path_xml', [None, None, None])

    compile_context['nsmap'] = {
        ns_prefix: str(ns_definition)
        for ns_prefix, ns_definition in compile_context.get('nsmap', {}).items()
    }

    # The options dictionary includes cache key elements and template
    # references. It will be attached to the generated function. This
    # dictionary is only there for logs, performance or test information.
    # The values of these `options` cannot be changed and must always be
    # identical in `context` and `self.env.context`.
    options = {
        key: compile_context.get(key, False)
        for key in self._get_template_cache_keys() + ['ref', 'ref_name']
    }

    # generate code
    ref_name = compile_context['ref_name'] or ''
    if isinstance(template, etree._Element):
        def_name = TO_VARNAME_REGEXP.sub(r'_', f'template_etree_{next(ETREE_TEMPLATE_REF)}')
    else:
        def_name = TO_VARNAME_REGEXP.sub(r'_', f'template_{ref_name if "<" not in ref_name else ""}_{ref}')

    name_gen = count()
    compile_context['make_name'] = lambda prefix: f"{def_name}_{prefix}_{next(name_gen)}"

    compile_context['template_functions'] = {}

    compile_context['_text_concat'] = []
    self._append_text("", compile_context)  # To ensure the template function is a generator and doesn't become a regular function
    compile_context['template_functions'][f'{def_name}_content'] = (
        [f"def {def_name}_content(self, values, root_values, process):"]
        + [indent_code('attrs = None', 1)]
        + [indent_code('if False: yield ""', 1)]
        + self._compile_root(element, compile_context)
        + self._flush_text(compile_context, 1, rstrip=True))

    compile_context['template_functions'][def_name] = [indent_code(f"""
            def {def_name}(self, values, root_values, process):
                attrs = None
                if 'xmlid' not in values:
                    values['xmlid'] = {options['ref_name']!r}
                    values['viewid'] = {options['ref']!r}
                process['qweb_loaded_functions'].update(template_functions)
                process['qweb_loaded_options'][{options['ref']!r}] = process['qweb_loaded_options'][{options['ref_name']!r}] = template_options
                process['qweb_loaded_codes'][{options['ref']!r}] = process['qweb_loaded_codes'][{options['ref_name']!r}] = code
                yield from {def_name}_content(self, values, root_values, process)
                """, 0)]

    code_lines = []
    json_options = json.scriptsafe.loads(json.scriptsafe.dumps(options, default=str))
    code_lines.append(f'template_options = {pprint.pformat(json_options, indent=4)}')
    code_lines.append('code = None')
    code_lines.append('template_functions = {}')

    for lines in compile_context['template_functions'].values():
        code_lines.extend(lines)

    for name in compile_context['template_functions']:
        code_lines.append(f'template_functions[{name!r}] = {name}')

    code = '\n'.join(code_lines)

    if options.get('profile'):
        options['ref_xml'] = compile_context['ref_xml']

    # The compilation did not fail.
    compile_context['_qweb_error_path_xml'][1] = None
    compile_context['_qweb_error_path_xml'][2] = None

    return (code, options, def_name, None)


def _get_template(self, template):
    """ Retrieve the given template, and return it as a tuple ``(etree,
        xml, ref)``, where ``element`` is an etree, ``document`` is the
        string document that contains ``element``, and ``ref`` if the uniq
        reference of the template (id, t-name or template).

        :param template: template identifier or etree
        """
    assert template not in (False, None, ""), "template is required"

    # template is an xml etree already
    if isinstance(template, etree._Element):
        element = template
        document = etree.tostring(template, encoding='unicode')

        # <templates>
        #   <template t-name=... /> <!-- return ONLY this element -->
        #   <template t-name=... />
        # </templates>
        for node in element.iter():
            ref = node.get('t-name')
            if ref:
                return (node, document, _id_or_xmlid(ref))

        return (element, document, 'etree._Element')

    # template is xml as string
    if isinstance(template, str) and '<' in template:
        raise ValueError('Inline templates must be passed as `etree` documents')

    # template is (id or ref) to a database stored template
    id_or_xmlid = _id_or_xmlid(template)  # e.g. <t t-call="33"/> or <t t-call="web.layout"/>

    if self._get_template_info(id_or_xmlid).get('type') not in (None, 'qweb'):
        raise ValueError('This is not a QWeb view')

    value = self._preload_trees([id_or_xmlid]).get(id_or_xmlid)
    if value.get('error'):
        raise value['error']

    # The compiled template cache can evict entries during a render, causing
    # the same preloaded tree to be processed several times.
    value_tree = deepcopy(value['tree'])
    # return etree, document and ref
    return (value_tree, value['template'], value['ref'])


def _get_preload_attribute_xmlids(self):
    return ['t-call']


def _preload_trees(self, refs: Sequence[int | str]):
    """ Preload all tree and subtree (from t-call and other '_get_preload_attribute_xmlids' values).

            Returns::

                {
                    id or xmlId/key: {
                        'xmlid': str | None,
                        'ref': int | None,
                        'tree': etree | None,
                        'template': str | None,
                        'error': None | MissingError
                    }
                }
        """
    compile_batch = self.env['ir.ui.view']._preload_views(refs)

    refs = list(map(_id_or_xmlid, refs))
    missing_refs = {ref: compile_batch[ref] for ref in refs if 'template' not in compile_batch[ref] and not compile_batch[ref]['error']}
    if not missing_refs:
        return compile_batch

    xmlids = list(missing_refs)
    missing_refs_values = list(missing_refs.values())
    views = self.env['ir.ui.view'].sudo().union(data['view'] for data in missing_refs_values)

    trees = views._get_view_etrees()

    # add in cache
    for xmlid, view, tree in zip(xmlids, views, trees):
        data = {
            'tree': tree,
            'template': etree.tostring(tree, encoding='unicode'),
        }
        compile_batch[view.id].update(data)
        compile_batch[xmlid].update(data)

    # preload sub template
    ref_names = self._get_preload_attribute_xmlids()
    sub_refs = OrderedSet()
    for tree in trees:
        sub_refs.update(
            el.get(ref_name)
            for ref_name in ref_names
            for el in tree.xpath(f'//*[@{ref_name}]')
            if not any(att.startswith('t-options-') or att == 't-options' or att == 't-lang' for att in el.attrib)
            if '{' not in el.get(ref_name) and '<' not in el.get(ref_name) and '/' not in el.get(ref_name)
        )
    assert not any(not f for f in sub_refs), "template is required"
    self._preload_trees(list(sub_refs))

    # not found template
    for ref in missing_refs:
        if ref not in compile_batch:
            compile_batch[ref] = {
                'xmlid': ref,
                'ref': ref,
                'error': MissingError(self.env._("External ID can not be loaded: %s", ref)),
            }

    return compile_batch


def _get_converted_image_data_uri(self, raw):
    if self.env.context.get('webp_as_jpg'):
        mimetype = raw.mimetype
        if 'webp' in mimetype:
            # Use converted image so that is recognized by wkhtmltopdf.
            Attachment = self.env['ir.attachment']
            checksum = Attachment._compute_checksum(raw)
            origins = Attachment.sudo().search([
                ['id', '!=', False],  # No implicit condition on res_field.
                ['checksum', '=', checksum],
            ])
            if origins:
                converted_domain = [
                    ['id', '!=', False],  # No implicit condition on res_field.
                    ['res_model', '=', 'ir.attachment'],
                    ['res_id', 'in', origins.ids],
                    ['mimetype', '=', 'image/jpeg'],
                ]
                converted = Attachment.sudo().search(converted_domain, limit=1)
                if converted:
                    raw = converted.raw
    return image_data_uri(raw)


def _prepare_environment(self, values):
    """ Prepare the values and context that will sent to the
        compiled and evaluated function.

        :param values: template values to be used for rendering

        :returns self (with new context)
        """
    debug = request and request.session.debug or ''
    values.update(
        true=True,
        false=False,
    )
    if not self.env.context.get('minimal_qcontext'):
        values.setdefault('debug', debug)
        values.setdefault('user_id', self.env.user.with_env(self.env))
        values.setdefault('res_company', self.env.company.sudo())  # TODO: remove and use company
        values.setdefault('company', self.env.company.sudo())
        values.update(
            request=request,  # might be unbound if we're not in an httprequest context, TODO: remove
            test_mode_enabled=config['test_enable'],
            json=qwebJSON,
            quote_plus=werkzeug.urls.url_quote_plus,
            time=safe_eval.time,
            datetime=safe_eval.datetime,
            relativedelta=relativedelta,
            image_data_uri=self._get_converted_image_data_uri,
            # specific 'math' functions to ease rounding in templates and lessen controller marshmalling
            floor=math.floor,
            ceil=math.ceil,
            env=self.env,
            lang=self.env.context.get('lang'),
            keep_query=keep_query,
        )

    context = {'dev_mode': 'qweb' in tools.config['dev_mode']}
    return self.with_context(**context)


def _debug_trace(self, debugger, values):
    """Method called at running time to load debugger."""
    if not debugger:
        breakpoint()
    elif debugger in SUPPORTED_DEBUGGER:
        warnings.warn(
            "Using t-debug with an explicit debugger is deprecated "
            "since Odoo 17.0, keep the value empty and configure the "
            "``breakpoint`` builtin instead.",
            category=DeprecationWarning,
            stacklevel=2,
        )
        __import__(debugger).set_trace()
    else:
        raise ValueError(f"unsupported t-debug value: {debugger}")
