"""The operations on the PDF files: merging, filling, rotating, extracting a page and adding a banner."""

from __future__ import annotations

import io
from logging import getLogger
from PIL import Image
from odoo.tools.parse_version import parse_version
from odoo.tools.misc import file_open, SENTINEL, Sentinel

from .compat import ArrayObject, DictionaryObject, NameObject, PdfFileReader, pypdf
from .writer import PdfFileWriter

_logger = getLogger('odoo.tools.pdf')


def merge_pdf(pdf_data):
    ''' Merge a collection of PDF documents in one.
    Note that the attachments are not merged.
    :param list pdf_data: a list of PDF datastrings
    :return: a unique merged PDF datastring
    '''
    writer = PdfFileWriter()
    for document in pdf_data:
        reader = PdfFileReader(io.BytesIO(document), strict=False)
        writer.append_pages_from_reader(reader)

    with io.BytesIO() as _buffer:
        writer.write(_buffer)
        return _buffer.getvalue()


def fill_form_fields_pdf(writer, form_fields):
    ''' Fill in the form fields of a PDF
    :param writer: a PdfFileWriter object
    :param dict form_fields: a dictionary of form fields to update in the PDF
    :return: a filled PDF datastring
    '''
    writer.set_need_appearances_writer()

    pypdf_version = parse_version(pypdf.__version__)
    if pypdf_version >= parse_version('3.13.0'):
        catalog = writer._root_object
        acroform = catalog.get("/AcroForm").get_object()
        if "/Fields" not in acroform:
            acroform[NameObject("/Fields")] = ArrayObject()
        if "/DR" not in acroform:
            acroform[NameObject("/DR")] = DictionaryObject()

    for page in writer.pages:
        writer.update_page_form_field_values(page, form_fields)


def rotate_pdf(pdf):
    ''' Rotate clockwise PDF (90°) into a new PDF.
    Note that the attachments are not copied.
    :param pdf: a PDF to rotate
    :return: a PDF rotated
    '''
    writer = PdfFileWriter()
    reader = PdfFileReader(io.BytesIO(pdf), strict=False)
    for page in reader.pages:
        page.rotate_clockwise(90)
        writer.add_page(page)
    with io.BytesIO() as _buffer:
        writer.write(_buffer)
        return _buffer.getvalue()


def to_pdf_stream(attachment) -> io.BytesIO | None:
    """Get the byte stream of the attachment as a PDF."""
    if not attachment.raw:
        _logger.warning("%s has no raw data.", attachment)
        return None

    if attachment_raw := attachment._get_pdf_raw():
        return io.BytesIO(attachment_raw)
    stream = io.BytesIO(attachment.raw)
    if attachment.mimetype.startswith('image'):
        output_stream = io.BytesIO()
        Image.open(stream).convert("RGB").save(output_stream, format="pdf")
        return output_stream
    _logger.warning("mimetype (%s) not recognized for %s", attachment.mimetype, attachment)
    return None


def extract_page(attachment, num_page=0) -> io.BytesIO | None:
    """Exctract a specific page form an attachement pdf"""
    pdf_stream = to_pdf_stream(attachment)
    if not pdf_stream:
        return None
    pdf = PdfFileReader(pdf_stream)
    pdf_writer = PdfFileWriter()
    pdf_writer.add_page(pdf.pages[num_page])
    stream = io.BytesIO()
    pdf_writer.write(stream)
    return stream


def add_banner(pdf_stream: io.BytesIO, text: str, logo: bool = False, thickness: float | Sentinel = SENTINEL) -> io.BytesIO:
    """ Add a banner on a PDF in the upper right corner, with Odoo's logo (optionally).

    :param pdf_stream:    The PDF stream where the banner will be applied.
    :param text:              The text to be displayed.
    :param logo:             Whether to display Odoo's logo in the banner.
    :param thickness:       The thickness of the banner in pixels (default: 2cm).
    :return:              The modified PDF stream.
    """
    from reportlab.lib import colors  # noqa: PLC0415
    from reportlab.lib.utils import ImageReader  # noqa: PLC0415
    from reportlab.pdfgen import canvas  # noqa: PLC0415

    if thickness is SENTINEL:
        from reportlab.lib.units import cm  # noqa: PLC0415
        thickness = 2 * cm

    old_pdf = PdfFileReader(pdf_stream, strict=False, overwriteWarnings=False)
    packet = io.BytesIO()
    can = canvas.Canvas(packet)
    with file_open('base/static/img/main_partner-image.png', mode='rb') as f:
        odoo_logo_file = io.BytesIO(f.read())
    odoo_logo = Image.open(odoo_logo_file)
    odoo_color = colors.Color(113 / 255, 75 / 255, 103 / 255, 0.8)

    for page in old_pdf.pages:
        width = float(abs(page.mediabox.width))
        height = float(abs(page.mediabox.height))

        can.setPageSize((width, height))
        can.translate(width, height)
        can.rotate(-45)

        # Draw banner
        path = can.beginPath()
        path.moveTo(-width, -thickness)
        path.lineTo(-width, -2 * thickness)
        path.lineTo(width, -2 * thickness)
        path.lineTo(width, -thickness)
        can.setFillColor(odoo_color)
        can.drawPath(path, fill=1, stroke=False)

        # Insert text (and logo) inside the banner
        can.setFontSize(10)
        can.setFillColor(colors.white)
        can.drawRightString(0.75 * thickness, -1.45 * thickness, text)
        logo and can.drawImage(
            ImageReader(odoo_logo), 0.25 * thickness, -2.05 * thickness, 40, 40, mask='auto', preserveAspectRatio=True)

        can.showPage()

    can.save()

    # Merge the old pages with the watermark
    watermark_pdf = PdfFileReader(packet, overwriteWarnings=False)
    new_pdf = PdfFileWriter()
    for old_page, wm_page in zip(old_pdf.pages, watermark_pdf.pages):
        new_pdf.add_page(old_page)
        new_page = new_pdf.pages[-1]
        # Remove annotations (if any), to prevent errors in PyPDF2
        if '/Annots' in new_page:
            del new_page['/Annots']
        new_page.merge_page(wm_page)
        new_page.compress_content_streams()

    # Write the new pdf into a new output stream
    output = io.BytesIO()
    new_pdf.write(output)

    return output
