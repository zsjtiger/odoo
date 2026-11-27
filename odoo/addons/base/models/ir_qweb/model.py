"""The QWeb engine (ir.qweb): the model and its entry points. The methods are split by concern in the other modules of this package."""

from __future__ import annotations

import logging
from markupsafe import Markup, escape
from collections.abc import Sized, Mapping, Sequence, Iterator
from lxml import etree
from odoo import api, models, tools
from odoo.tools.safe_eval import (
    _BUILTINS,
)
from .content import QwebContent
from .errors import QWebErrorInfo
from .helpers import VOID_ELEMENTS
from .stack import QwebCallParameters, QwebStackFrame


class IrQweb(models.AbstractModel):
    """ Base QWeb rendering engine
    * to customize ``t-field`` rendering, subclass ``ir.qweb.field`` and
      create new models called :samp:`ir.qweb.field.{widget}`
    Beware that if you need extensions or alterations which could be
    incompatible with other subsystems, you should create a local object
    inheriting from ``ir.qweb`` and customize that.
    """
    _name = 'ir.qweb'
    _description = 'Qweb'
    @api.model
    def _render(self, template: int | str | etree._Element, values: dict | None=None, **options) -> Markup:
        return _model_render._render(self, template, values, **options)
    def _render_iterall(self, view_ref, method, values, root_values, process, directive='render') -> Iterator[str]:
        return _model_render._render_iterall(self, view_ref, method, values, root_values, process, directive)
    def _get_error_info(self, error, stack: list[QwebStackFrame], frame: QwebStackFrame, process) -> QWebErrorInfo:
        return _model_render._get_error_info(self, error, stack, frame, process)
    def _get_template_cache_keys(self):
        return _model_render._get_template_cache_keys(self)
    def _get_template_info(self, template):
        return _model_render._get_template_info(self, template)
    def _compile(self, template):
        return _model_render._compile(self, template)
    @tools.conditional('xml' not in tools.config['dev_mode'], api.ormcache('ref', 'tuple(self.env.context.get(k) or False for k in self._get_template_cache_keys())', cache='templates'))
    def _generate_code_cached(self, ref: int):
        return _model_render._generate_code_cached(self, ref)
    def _generate_code_uncached(self, template: int | str | etree._Element):
        return _model_render._generate_code_uncached(self, template)
    def _generate_code(self, template: int | str | etree._Element):
        return _model_render._generate_code(self, template)
    def _get_template(self, template):
        return _model_render._get_template(self, template)
    @api.model
    def _get_preload_attribute_xmlids(self):
        return _model_render._get_preload_attribute_xmlids(self)
    def _preload_trees(self, refs: Sequence[int | str]):
        return _model_render._preload_trees(self, refs)
    def _get_converted_image_data_uri(self, raw):
        return _model_render._get_converted_image_data_uri(self, raw)
    def _prepare_environment(self, values):
        return _model_render._prepare_environment(self, values)
    def __prepare_globals(self):
        """ Prepare the global context that will sent to eval the qweb
        generated code.
        """
        return {
            '__name__': __name__,
            'Sized': Sized,
            'Mapping': Mapping,
            'Markup': Markup,
            'escape': escape,
            'VOID_ELEMENTS': VOID_ELEMENTS,
            'QwebCallParameters': QwebCallParameters,
            'QwebContent': QwebContent,
            'ValueError': ValueError,
            **_BUILTINS,
        }
    def _append_text(self, text, compile_context):
        return _model_compile._append_text(self, text, compile_context)
    def _rstrip_text(self, compile_context):
        return _model_compile._rstrip_text(self, compile_context)
    def _flush_text(self, compile_context, level, rstrip=False):
        return _model_compile._flush_text(self, compile_context, level, rstrip)
    def _is_static_node(self, el, compile_context):
        return _model_compile._is_static_node(self, el, compile_context)
    def _remove_translate_suffix(self, attrib):
        return _model_compile._remove_translate_suffix(self, attrib)
    def _pre_processing_att(self, attrib):
        return _model_compile._pre_processing_att(self, attrib)
    def _compile_format(self, expr, compile_context):
        return _model_compile._compile_format(self, expr, compile_context)
    def _compile_expr_tokens(self, tokens, allowed_keys, argument_names=None, raise_on_missing=False):
        return _model_expr._compile_expr_tokens(self, tokens, allowed_keys, argument_names, raise_on_missing)
    def _compile_expr(self, expr, compile_context, raise_on_missing=False):
        return _model_expr._compile_expr(self, expr, compile_context, raise_on_missing)
    def _compile_bool(self, attr, default=False):
        return _model_expr._compile_bool(self, attr, default)
    def _compile_to_str(self, expr):
        return _model_expr._compile_to_str(self, expr)
    def _directives_eval_order(self):
        return _model_compile._directives_eval_order(self)
    def _compile_root(self, element, compile_context):
        return _model_compile._compile_root(self, element, compile_context)
    def _compile_node(self, el, compile_context, level):
        return _model_compile._compile_node(self, el, compile_context, level)
    def _compile_static_node(self, el, compile_context, level):
        return _model_compile._compile_static_node(self, el, compile_context, level)
    def _compile_directives(self, el, compile_context, level):
        return _model_compile._compile_directives(self, el, compile_context, level)
    def _compile_directive(self, el, compile_context, directive, level):
        return _model_compile._compile_directive(self, el, compile_context, directive, level)
    def _compile_directive_debug(self, el, compile_context, level):
        return _model_compile._compile_directive_debug(self, el, compile_context, level)
    def _compile_directive_options(self, el, compile_context, level):
        return _model_compile._compile_directive_options(self, el, compile_context, level)
    def _compile_directive_consumed_options(self, el, compile_context, level):
        return _model_compile._compile_directive_consumed_options(self, el, compile_context, level)
    def _compile_directive_att(self, el, compile_context, level):
        return _model_directives._compile_directive_att(self, el, compile_context, level)
    def _compile_directive_tag_open(self, el, compile_context, level):
        return _model_directives._compile_directive_tag_open(self, el, compile_context, level)
    def _compile_directive_tag_close(self, el, compile_context, level):
        return _model_directives._compile_directive_tag_close(self, el, compile_context, level)
    def _compile_directive_set(self, el, compile_context, level):
        return _model_directives._compile_directive_set(self, el, compile_context, level)
    def _compile_directive_value(self, el, compile_context, level):
        return _model_directives._compile_directive_value(self, el, compile_context, level)
    def _compile_directive_valuef(self, el, compile_context, level):
        return _model_directives._compile_directive_valuef(self, el, compile_context, level)
    def _compile_directive_inner_content(self, el, compile_context, level):
        return _model_directives._compile_directive_inner_content(self, el, compile_context, level)
    def _compile_directive_if(self, el, compile_context, level):
        return _model_control._compile_directive_if(self, el, compile_context, level)
    def _compile_directive_elif(self, el, compile_context, level):
        return _model_control._compile_directive_elif(self, el, compile_context, level)
    def _compile_directive_else(self, el, compile_context, level):
        return _model_control._compile_directive_else(self, el, compile_context, level)
    def _compile_directive_groups(self, el, compile_context, level):
        return _model_directives._compile_directive_groups(self, el, compile_context, level)
    def _compile_directive_foreach(self, el, compile_context, level):
        return _model_control._compile_directive_foreach(self, el, compile_context, level)
    def _compile_directive_as(self, el, compile_context, level):
        return _model_directives._compile_directive_as(self, el, compile_context, level)
    def _compile_directive_out(self, el, compile_context, level):
        return _model_control._compile_directive_out(self, el, compile_context, level)
    def _compile_directive_field(self, el, compile_context, level):
        return _model_directives._compile_directive_field(self, el, compile_context, level)
    def _compile_directive_call(self, el, compile_context, level):
        return _model_control._compile_directive_call(self, el, compile_context, level)
    def _compile_directive_lang(self, el, compile_context, level):
        return _model_directives._compile_directive_lang(self, el, compile_context, level)
    def _compile_directive_call_assets(self, el, compile_context, level):
        return _model_control._compile_directive_call_assets(self, el, compile_context, level)
    def _compile_directive_log(self, el, compile_context, level):
        return _model_directives._compile_directive_log(self, el, compile_context, level)
    def _debug_trace(self, debugger, values):
        return _model_render._debug_trace(self, debugger, values)
    def _post_processing_att(self, tagName, atts):
        return _model_compile._post_processing_att(self, tagName, atts)
    def _get_field(self, record, field_name, expression, tagName, field_options, values):
        return _model_directives._get_field(self, record, field_name, expression, tagName, field_options, values)
    def _get_widget(self, value, expression, tagName, field_options, values):
        return _model_directives._get_widget(self, value, expression, tagName, field_options, values)
    def _get_asset_nodes(self, bundle, css=True, js=True, binary=False, debug=False, defer_load=False, lazy_load=False, media=None, autoprefix=False):
        return _model_assets._get_asset_nodes(self, bundle, css, js, binary, debug, defer_load, lazy_load, media, autoprefix)
    def _get_asset_links(self, bundle, css=True, js=True, binary=False, debug=None, autoprefix=False):
        return _model_assets._get_asset_links(self, bundle, css, js, binary, debug, autoprefix)
    @tools.conditional('xml' not in tools.config['dev_mode'], api.ormcache('bundle', 'css', 'js', 'binary', 'tuple(sorted(assets_params.items()))', 'rtl', 'autoprefix', cache='assets'))
    def _generate_asset_links_cache(self, bundle, css=True, js=True, binary=False, assets_params=None, rtl=False, autoprefix=False):
        return _model_assets._generate_asset_links_cache(self, bundle, css, js, binary, assets_params, rtl, autoprefix)
    def _get_asset_content(self, bundle, assets_params=None):
        return _model_assets._get_asset_content(self, bundle, assets_params)
    def _get_asset_bundle(self, bundle_name, css=True, js=True, binary=False, debug_assets=False, rtl=False, assets_params=None, autoprefix=False):
        return _model_assets._get_asset_bundle(self, bundle_name, css, js, binary, debug_assets, rtl, assets_params, autoprefix)
    def _links_to_nodes(self, paths, defer_load=False, lazy_load=False, media=None):
        return _model_assets._links_to_nodes(self, paths, defer_load, lazy_load, media)
    def _link_to_node(self, path, defer_load=False, lazy_load=False, media=None):
        return _model_assets._link_to_node(self, path, defer_load, lazy_load, media)
    def _generate_asset_links(self, bundle, css=True, js=True, binary=False, debug_assets=False, assets_params=None, rtl=False, autoprefix=False):
        return _model_assets._generate_asset_links(self, bundle, css, js, binary, debug_assets, assets_params, rtl, autoprefix)
    def _get_asset_link_urls(self, bundle, debug=False):
        return _model_assets._get_asset_link_urls(self, bundle, debug)
    def _pregenerate_assets_bundles(self):
        return _model_assets._pregenerate_assets_bundles(self)
    def _get_bundles_to_pregenarate(self):
        return _model_assets._get_bundles_to_pregenarate(self)
    def _get_bundles_from_views(self):
        return _model_assets._get_bundles_from_views(self)
    def _get_lazy_bundles_from_js(self):
        return _model_assets._get_lazy_bundles_from_js(self)


_logger = logging.getLogger('odoo.addons.base.models.ir_qweb')


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import model_render as _model_render, model_compile as _model_compile, model_expr as _model_expr, model_directives as _model_directives, model_control as _model_control, model_assets as _model_assets  # noqa: E402
