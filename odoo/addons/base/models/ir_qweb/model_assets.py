"""The assets of the templates: the bundles, their links and their pregeneration."""

from __future__ import annotations

import glob
import re
import time
from lxml import etree
from os.path import join as opj
from odoo.modules import Manifest
from odoo.tools.constants import EXTERNAL_ASSET
from odoo.tools.misc import str2bool, file_open
from odoo.addons.base.models.assetsbundle import AssetsBundle
from odoo.tools.constants import SCRIPT_EXTENSIONS, STYLE_EXTENSIONS, TEMPLATE_EXTENSIONS, FONT_EXTENSIONS

from .model import _logger

def _get_asset_nodes(self, bundle, css=True, js=True, binary=False, debug=False, defer_load=False, lazy_load=False, media=None, autoprefix=False):
    """Generates asset nodes.
        If debug=assets, the assets will be regenerated when a file which composes them has been modified.
        Else, the assets will be generated only once and then stored in cache.
        """
    media = css and media or None
    links = self._get_asset_links(bundle, css=css, js=js, binary=binary, debug=debug, autoprefix=autoprefix)
    return self._links_to_nodes([links[0]] if binary else links, defer_load=defer_load, lazy_load=lazy_load, media=media)


def _get_asset_links(self, bundle, css=True, js=True, binary=False, debug=None, autoprefix=False):
    """Generates asset nodes.
        If debug=assets, the assets will be regenerated when a file which composes them has been modified.
        Else, the assets will be generated only once and then stored in cache.
        """
    rtl = self.env['res.lang'].sudo()._lang_get(code=(self.env.lang or self.env.user.lang)).direction == 'rtl'
    assets_params = self.env['ir.asset']._get_asset_params() # website_id
    debug_assets = debug and 'assets' in debug

    if debug_assets:
        return self._generate_asset_links(bundle, css=css, js=js, binary=binary, debug_assets=True, assets_params=assets_params, rtl=rtl, autoprefix=autoprefix)
    else:
        return self._generate_asset_links_cache(bundle, css=css, js=js, binary=binary, assets_params=assets_params, rtl=rtl, autoprefix=autoprefix)


def _generate_asset_links_cache(self, bundle, css=True, js=True, binary=False, assets_params=None, rtl=False, autoprefix=False):
    return self._generate_asset_links(bundle, css, js, binary, False, assets_params, rtl, autoprefix=autoprefix)


def _get_asset_content(self, bundle, assets_params=None):
    if assets_params is None:
        assets_params = self.env['ir.asset']._get_asset_params()  # website_id
    asset_paths = self.env['ir.asset']._get_asset_paths(bundle=bundle, assets_params=assets_params)
    files = []
    external_asset = []
    for path, full_path, definition_bundle, last_modified in asset_paths:
        if full_path is not EXTERNAL_ASSET:
            files.append({
                'url': path,
                'filename': full_path,
                'content': '',
                'last_modified': last_modified,
                'definition_bundle': definition_bundle,
            })
        else:
            external_asset.append(path)
    return (files, external_asset)


def _get_asset_bundle(self, bundle_name, css=True, js=True, binary=False, debug_assets=False, rtl=False, assets_params=None, autoprefix=False):
    if assets_params is None:
        assets_params = self.env['ir.asset']._get_asset_params()
    files, external_assets = self._get_asset_content(bundle_name, assets_params)
    return AssetsBundle(bundle_name, files, external_assets, env=self.env, css=css, js=js, binary=binary, debug_assets=debug_assets, rtl=rtl, assets_params=assets_params, autoprefix=autoprefix)


def _links_to_nodes(self, paths, defer_load=False, lazy_load=False, media=None):
    return [self._link_to_node(path, defer_load=defer_load, lazy_load=lazy_load, media=media) for path in paths]


def _link_to_node(self, path, defer_load=False, lazy_load=False, media=None):
    ext = path.rsplit('.', maxsplit=1)[-1] if path else 'js'
    is_js = ext in SCRIPT_EXTENSIONS
    is_xml = ext in TEMPLATE_EXTENSIONS
    is_css = ext in STYLE_EXTENSIONS
    is_font = ext in FONT_EXTENSIONS

    if is_js:
        is_asset_bundle = path and path.startswith('/web/assets/')
        attributes = {
            'type': 'text/javascript',
        }

        if defer_load:
            # Note that "lazy_load" will lead to "defer" being added in JS,
            # not here, otherwise this is not W3C valid (defer is probably
            # not even needed there anyways). See LAZY_LOAD_DEFER.
            attributes['defer'] = 'defer'
        if path:
            if lazy_load:
                attributes['data-src'] = path
            else:
                attributes['src'] = path

        if is_asset_bundle:
            attributes['onerror'] = "__odooAssetError=1"

        return ('script', attributes)

    if is_css:
        attributes = {
            'type': f'text/{ext}',  # we don't really expect to have anything else than pure css here
            'rel': 'stylesheet',
            'href': path,
            'media': media,
        }
        return ('link', attributes)

    if is_xml:
        attributes = {
            'type': 'text/xml',
            'async': 'async',
            'rel': 'prefetch',
            'data-src': path,
            }
        return ('script', attributes)

    if is_font:
        attributes = {
            'rel': 'preload',
            'href': path,
            'as': 'font',
            'crossorigin': '',
        }
        return ('link', attributes)

    return None


def _generate_asset_links(self, bundle, css=True, js=True, binary=False, debug_assets=False, assets_params=None, rtl=False, autoprefix=False):
    asset_bundle = self._get_asset_bundle(bundle, css=css, js=js, binary=binary, debug_assets=debug_assets, rtl=rtl, assets_params=assets_params, autoprefix=autoprefix)
    return asset_bundle.get_links()


def _get_asset_link_urls(self, bundle, debug=False):
    asset_nodes = self._get_asset_nodes(bundle, js=False, debug=debug)
    return [node[1]['href'] for node in asset_nodes if node[0] == 'link']


def _pregenerate_assets_bundles(self):
    """
        Pregenerates all assets that may be used in web pages to speedup first loading.
        This may is mainly usefull for tests.

        The current version is looking for all t-call-assets in view to generate the minimal
        set of bundles to generate.

        Current version only generate assets without extra, not taking care of rtl.
        """
    _logger.runbot('Pregenerating assets bundles')

    js_bundles, css_bundles, bin_bundles = self._get_bundles_to_pregenarate()

    links = []
    start = time.time()
    for bundle in sorted(js_bundles):
        links += self._get_asset_bundle(bundle, css=False, js=True).js()
    _logger.info('JS Assets bundles generated in %s seconds', time.time()-start)
    start = time.time()
    for bundle in sorted(bin_bundles):
        binary_bundle = self._get_asset_bundle(bundle, binary=True)
        for bin in binary_bundle.binaries:
            links.extend(binary_bundle.bin(bin.extension))
    _logger.info('Binary Assets bundles generated in %s seconds', time.time() - start)
    start = time.time()
    for bundle in sorted(css_bundles):
        links += self._get_asset_bundle(bundle, css=True, js=False).css()
    _logger.info('CSS Assets bundles generated in %s seconds', time.time()-start)
    return links


def _get_bundles_to_pregenarate(self):
    """
        Returns the list of bundles to pregenerate.
        """
    js_views_bundles, css_views_bundles, bin_views_bundles = self._get_bundles_from_views()
    lazy_bundles = self._get_lazy_bundles_from_js()
    return (js_views_bundles | lazy_bundles, css_views_bundles | lazy_bundles, bin_views_bundles)


def _get_bundles_from_views(self):
    views = self.env['ir.ui.view'].search([('type', '=', 'qweb'), ('arch_db', 'like', 't-call-assets')])
    js_bundles = set()
    css_bundles = set()
    bin_bundles = set()
    for view in views:
        for call_asset in etree.fromstring(view.arch_db).xpath("//*[@t-call-assets]"):
            asset = call_asset.get('t-call-assets')
            js = str2bool(call_asset.get('t-js', 'True'))
            css = str2bool(call_asset.get('t-css', 'True'))
            binary = str2bool(call_asset.get('t-binary', 'False'))
            if js:
                js_bundles.add(asset)
            if css:
                css_bundles.add(asset)
            if binary:
                bin_bundles.add(asset)
    return (js_bundles, css_bundles, bin_bundles)


def _get_lazy_bundles_from_js(self):
    modules = self.env['ir.module.module'].search([('state', '=', 'installed')]).mapped('name')
    lazy_bundle_regex = re.compile(r'\bloadBundle\((["\'`])([\w\.-]+)\1\)', flags=re.ASCII)
    bundles = set()
    for module in modules:
        manifest = Manifest.for_addon(module, display_warning=False)
        if not (manifest and manifest.static_path):
            continue
        for fname in glob.iglob('**/src/**/*.js', root_dir=manifest.static_path, recursive=True):
            with file_open(opj(manifest.static_path, fname)) as f:
                fcontent = f.read()
                if match := lazy_bundle_regex.search(fcontent):
                    bundles.add(match[2])
    return bundles
