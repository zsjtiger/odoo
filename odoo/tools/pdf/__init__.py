# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The PDF tools: the operations on the PDF files, the readers and writers, and the pypdf compatibility layer. The names are re-exported here."""

# the compatibility layer comes first: it installs the fixes of pypdf
from .compat import ArrayObject, BooleanObject, ByteStringObject, DEFAULT_PDF_DATETIME_FORMAT, DecodedStreamObject, DependencyError, DictionaryObject, IndirectObject, NameObject, NullObject, NumberObject, PageObject, PdfFileReader, PdfObject, PdfReadError, PdfReader, PdfReaderBase, PdfStreamError, PdfWriter, REGEX_SUBTYPE_FORMATED, REGEX_SUBTYPE_UNFORMATED, RectangleObject, TextStringObject, _unwrapping_get, createStringObject, create_string_object, errors, filters, generic, pypdf
from .writer import BrandedFileWriter, OdooPdfFileWriter, PdfFileWriter
from .reader import OdooPdfFileReader
from .operations import add_banner, extract_page, fill_form_fields_pdf, merge_pdf, rotate_pdf, to_pdf_stream
from .text import reshape_text
