"""The errors of the assets: the compilation and the assets that are not found."""

from __future__ import annotations



class CompileError(RuntimeError): pass


class AssetError(Exception):
    pass


class AssetNotFound(AssetError):
    pass


class XMLAssetError(Exception):
    pass
