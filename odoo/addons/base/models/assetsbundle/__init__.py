# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The assets of the bundles: the constants, the errors, the assets, the preprocessed stylesheets and the bundles. The names are re-exported here."""

from .helpers import ANY_UNIQUE, EXTENSIONS, _logger
from .errors import AssetError, AssetNotFound, CompileError, XMLAssetError
from .assets import BinaryAsset, JavascriptAsset, StylesheetAsset, WebAsset, XMLAsset
from .preprocessed import LessStylesheetAsset, PreprocessedCSS, SassStylesheetAsset, ScssStylesheetAsset
from .bundle import AssetsBundle
