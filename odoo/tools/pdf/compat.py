"""The compatibility layer over pypdf: the loading of the pypdf implementation, its fixes, and the aliases of the names of PyPDF2."""

from __future__ import annotations

import importlib
import re
import typing
from zlib import decompressobj
from PIL import PdfImagePlugin


try:
    import zlib

    def _decompress(data):
        zobj = zlib.decompressobj()
        return zobj.decompress(data)

    import PyPDF2.filters  # needed after PyPDF2 2.0.0 and before 2.11.0
    PyPDF2.filters.decompress = _decompress
except ImportError:
    pass  # no fix required


if typing.TYPE_CHECKING:
    # for type checking, default to the newest version
    from . import _pypdf as pypdf
else:
    errors = []
    # keep pypdf2 2.x first so noble uses that rather than pypdf 4.0
    for SUBMOD in ['._pypdf2_2', '._pypdf']:
        try:
            pypdf = importlib.import_module(SUBMOD, __package__)
            break
        except ImportError as e:
            errors.append(e)
    else:
        raise ImportError("pypdf implementation not found") from errors[0]
    del errors


PageObject, PdfReaderBase, PdfWriter, filters, generic, errors, create_string_object =\
    pypdf.PageObject, pypdf.PdfReader, pypdf.PdfWriter, pypdf.filters, pypdf.generic, pypdf.errors, pypdf.create_string_object


(ArrayObject, BooleanObject, ByteStringObject, DecodedStreamObject, DictionaryObject,
 IndirectObject, NameObject, NumberObject, PdfObject, NullObject, RectangleObject, TextStringObject) =\
    (generic.ArrayObject, generic.BooleanObject, generic.ByteStringObject, generic.DecodedStreamObject, generic.DictionaryObject, generic.IndirectObject,
     generic.NameObject, generic.NumberObject, generic.PdfObject, generic.NullObject, generic.RectangleObject, generic.TextStringObject)


PdfReadError = errors.PdfReadError  # moved in 2.0


PdfStreamError = errors.PdfStreamError  # moved in 2.0


DependencyError = errors.DependencyError


createStringObject = create_string_object  # deprecated in 2.0, removed in 5.0


pypdf.filters.decompress = lambda data: decompressobj().decompress(data)


class PdfReader(PdfReaderBase):
    def __init__(self, stream, strict=True, *args, **kwargs):
        super().__init__(stream, strict)


PdfFileReader = pypdf.PdfFileReader = PdfReader


pypdf.PdfFileWriter = PdfWriter


DEFAULT_PDF_DATETIME_FORMAT = "D:%Y%m%d%H%M%S+00'00'"


REGEX_SUBTYPE_UNFORMATED = re.compile(r'^\w+/[\w-]+$')


REGEX_SUBTYPE_FORMATED = re.compile(r'^/\w+#2F[\w-]+$')


PdfImagePlugin.__name__


def _unwrapping_get(self, key, default=None):
    try:
        return self[key]
    except KeyError:
        return default


DictionaryObject.get = _unwrapping_get


if hasattr(NameObject, 'renumber_table'):
    # Make sure all the correct delimiters are included
    # We will make this change only if pypdf has the renumber_table attribute
    # https://github.com/py-pdf/pypdf/commit/8c542f331828c5839fda48442d89b8ac5d3984ac
    NameObject.renumber_table.update({
        **{chr(i): f"#{i:02X}".encode() for i in b"#()<>[]{}/%"},
        **{chr(i): f"#{i:02X}".encode() for i in range(33)},
    })
