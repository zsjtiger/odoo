"""The writers of the PDF files: the branded writer, and the writer of the PDF/A files with their attachments and metadata."""

from __future__ import annotations

import io
from datetime import datetime
from hashlib import md5
from logging import getLogger
from zlib import compress, decompress
from odoo.tools.parse_version import parse_version
from odoo.tools.misc import file_open

from .compat import ArrayObject, BooleanObject, ByteStringObject, DEFAULT_PDF_DATETIME_FORMAT, DecodedStreamObject, DictionaryObject, IndirectObject, NameObject, NumberObject, PdfWriter, REGEX_SUBTYPE_FORMATED, REGEX_SUBTYPE_UNFORMATED, create_string_object

_logger = getLogger('odoo.tools.pdf')


class BrandedFileWriter(PdfWriter):
    def write_stream(self, *args, **kwargs):
        self.add_metadata({
            '/Creator': "Odoo",
            '/Producer': "Odoo",
        })
        super().write_stream(*args, **kwargs)


PdfFileWriter = BrandedFileWriter


class OdooPdfFileWriter(PdfFileWriter):

    def __init__(self, *args, **kwargs):
        """
        Override of the init to initialise additional variables.
        :param pdf_content: if given, will initialise the reader with the pdf content.
        """
        super().__init__(*args, **kwargs)
        self._reader = None
        self.is_pdfa = False

    def format_subtype(self, subtype):
        """
        Apply the correct format to the subtype.
        It should take the form of "/xxx#2Fxxx". E.g. for "text/xml": "/text#2Fxml"
        :param subtype: The mime-type of the attachement.
        """
        if not subtype:
            return subtype

        adapted_subtype = subtype
        if REGEX_SUBTYPE_UNFORMATED.match(subtype):
            return '/' + subtype

        if not REGEX_SUBTYPE_FORMATED.match(adapted_subtype):
            # The subtype still does not match the correct format, so we will not add it to the document
            _logger.warning("Attempt to add an attachment with the incorrect subtype '%s'. The subtype will be ignored.", subtype)
            adapted_subtype = ''
        return adapted_subtype

    def add_attachment(self, name, data, subtype=None, afrelationship='/Data'):
        """ Add an attachment to the pdf. Supports adding multiple attachment, while respecting PDF/A rules.

        :param name: The name of the attachement
        :param data: The data of the attachement
        :param subtype: The mime-type of the attachement. This is required by PDF/A, but not essential otherwise.
        :param afrelationship: The relationship between the embedded file and the PDF content. This is required by PDF/A.
        """
        # NOTE: Currently AFRelationship can only be '/Alternative' as it is coupled to the hardcoded
        # <fx:ConformanceLevel>EXTENDED</fx:ConformanceLevel> in the XMP metadata template
        # (account_invoice_pdfa_3_facturx_metadata). If support for MINIMUM/BASIC-WL is ever added,
        # both afrelationship and ConformanceLevel must change together.

        # Valid AFRelationship values per PDF 2.0 spec (ISO 32000-2, section 7.11.3)
        valid_afrelationships = {'/Source', '/Data', '/Alternative', '/Supplement', '/Unspecified', '/EncryptedPayload', '/FormData', '/Schema'}
        if afrelationship not in valid_afrelationships:
            _logger.warning(
                "Invalid AFRelationship value '%s', falling back to '/Data'. "
                "Valid values are: %s",
                afrelationship, ', '.join(sorted(valid_afrelationships))
            )
            afrelationship = '/Data'
        adapted_subtype = self.format_subtype(subtype)

        attachment = self._create_attachment_object({
            'filename': name,
            'content': data,
            'subtype': adapted_subtype,
            'afrelationship': afrelationship,
        })
        if self._root_object.get('/Names') and self._root_object['/Names'].get('/EmbeddedFiles'):
            names_array = self._root_object["/Names"]["/EmbeddedFiles"]["/Names"]
            names_array.extend([attachment.get_object()['/F'], attachment])
        else:
            names_array = ArrayObject()
            names_array.extend([attachment.get_object()['/F'], attachment])

            embedded_files_names_dictionary = DictionaryObject()
            embedded_files_names_dictionary.update({
                NameObject("/Names"): names_array
            })
            embedded_files_dictionary = DictionaryObject()
            embedded_files_dictionary.update({
                NameObject("/EmbeddedFiles"): embedded_files_names_dictionary
            })
            self._root_object.update({
                NameObject("/Names"): embedded_files_dictionary
            })

        if self._root_object.get('/AF'):
            attachment_array = self._root_object['/AF']
            attachment_array.extend([attachment])
        else:
            # Create a new object containing an array referencing embedded file
            # And reference this array in the root catalogue
            attachment_array = self._add_object(ArrayObject([attachment]))
            self._root_object.update({
                NameObject("/AF"): attachment_array
            })
    addAttachment = add_attachment

    def embed_odoo_attachment(self, attachment, subtype=None, afrelationship='/Data'):
        assert attachment, "embed_odoo_attachment cannot be called without attachment."
        self.add_attachment(attachment.name, attachment.raw, subtype=subtype or attachment.mimetype, afrelationship=afrelationship)

    def clone_reader_document_root(self, reader):
        super().clone_reader_document_root(reader)
        self._reader = reader
        # Try to read the header coming in, and reuse it in our new PDF
        # This is done in order to allows modifying PDF/A files after creating them (as PyPDF does not read it)
        stream = reader.stream
        stream.seek(0)
        header = stream.readlines(9)
        # Should always be true, the first line of a pdf should have 9 bytes (%PDF-1.x plus a newline)
        if len(header) == 1:
            # If we found a header, set it back to the new pdf
            self._header = header[0]
            # Also check the second line. If it is PDF/A, it should be a line starting by % following by four bytes + \n
            second_line = stream.readlines(1)[0]
            if second_line.decode('latin-1')[0] == '%' and len(second_line) == 6:
                self.is_pdfa = True
        # clone_reader_document_root clones reader._ID since 3.2 (py-pdf/pypdf#1520)
        if not hasattr(self, '_ID'):
            # Look if we have an ID in the incoming stream and use it.
            self._set_id(reader.trailer.get('/ID', None))

    def _set_id(self, pdf_id):
        if not pdf_id:
            return

        # property in pypdf
        if hasattr(type(self), '_ID'):
            self.trailers['/ID'] = pdf_id
        else:
            self._ID = pdf_id

    def convert_to_pdfa(self):
        """
        Transform the opened PDF file into a PDF/A compliant file
        """
        # Set the PDF version to 1.7 (as PDF/A-3 is based on version 1.7) and make it PDF/A compliant.
        # See https://github.com/veraPDF/veraPDF-validation-profiles/wiki/PDFA-Parts-2-and-3-rules#rule-612-1
        self._header = b"%PDF-1.7"

        # Add a document ID to the trailer. This is only needed when using encryption with regular PDF, but is required
        # when using PDF/A
        pdf_id = ByteStringObject(md5(self._reader.stream.getvalue()).digest())
        # The first string is based on the content at the time of creating the file, while the second is based on the
        # content of the file when it was last updated. When creating a PDF, both are set to the same value.
        self._set_id(ArrayObject((pdf_id, pdf_id)))

        with file_open('tools/data/files/sRGB2014.icc', mode='rb') as icc_profile:
            icc_profile_file_data = compress(icc_profile.read())

        icc_profile_stream_obj = DecodedStreamObject()
        icc_profile_stream_obj.set_data(icc_profile_file_data)
        icc_profile_stream_obj.update({
            NameObject("/Filter"): NameObject("/FlateDecode"),
            NameObject("/N"): NumberObject(3),
            NameObject("/Length"): NameObject(str(len(icc_profile_file_data))),
        })

        icc_profile_obj = self._add_object(icc_profile_stream_obj)

        output_intent_dict_obj = DictionaryObject()
        output_intent_dict_obj.update({
            NameObject("/S"): NameObject("/GTS_PDFA1"),
            NameObject("/OutputConditionIdentifier"): create_string_object("sRGB"),
            NameObject("/DestOutputProfile"): icc_profile_obj,
            NameObject("/Type"): NameObject("/OutputIntent"),
        })

        output_intent_obj = self._add_object(output_intent_dict_obj)
        self._root_object.update({
            NameObject("/OutputIntents"): ArrayObject([output_intent_obj]),
        })

        pages = self._root_object['/Pages']['/Kids']

        # PDF/A needs the glyphs width array embedded in the pdf to be consistent with the ones from the font file.
        # But it seems like it is not the case when exporting from wkhtmltopdf.
        try:
            import fontTools.ttLib  # noqa: PLC0415
        except ImportError:
            _logger.warning('The fonttools package is not installed. Generated PDF may not be PDF/A compliant.')
        else:
            fonts = {}
            # First browse through all the pages of the pdf file, to get a reference to all the fonts used in the PDF.
            for page in pages:
                for font in page.get_object()['/Resources']['/Font'].values():
                    for descendant in font.get_object()['/DescendantFonts']:
                        fonts[descendant.idnum] = descendant.get_object()

            # Then for each font, rewrite the width array with the information taken directly from the font file.
            # The new width are calculated such as width = round(1000 * font_glyph_width / font_units_per_em)
            # See: http://martin.hoppenheit.info/blog/2018/pdfa-validation-and-inconsistent-glyph-width-information/
            for font in fonts.values():
                font_file = font['/FontDescriptor']['/FontFile2']
                stream = io.BytesIO(decompress(font_file._data))
                ttfont = fontTools.ttLib.TTFont(stream)
                font_upm = ttfont['head'].unitsPerEm
                if parse_version(fontTools.__version__) < parse_version('4.37.2'):
                    glyphs = ttfont.getGlyphSet()._hmtx.metrics
                else:
                    glyphs = ttfont.getGlyphSet().hMetrics
                glyph_widths = []
                for key, values in glyphs.items():
                    if key[:5] == 'glyph':
                        glyph_widths.append(NumberObject(round(1000.0 * values[0] / font_upm)))

                font[NameObject('/W')] = ArrayObject([NumberObject(1), ArrayObject(glyph_widths)])
                stream.close()

        # Every annotation dictionary, except those whose subtype is Popup,
        # must contain the /F key (annotation flags), as required by PDF/A (clause 6.3.2).
        # - Print flag must be 1.
        # - Hidden, Invisible, ToggleNoView and NoView flags must be 0.
        # - For text annotations, NoZoom and NoRotate are recommended to be 1.
        PDFA_ANNOT_FLAG_INVISIBLE = 1 << 0
        PDFA_ANNOT_FLAG_HIDDEN = 1 << 1
        PDFA_ANNOT_FLAG_PRINT = 1 << 2
        PDFA_ANNOT_FLAG_NOZOOM = 1 << 3
        PDFA_ANNOT_FLAG_NOROTATE = 1 << 4
        PDFA_ANNOT_FLAG_NOVIEW = 1 << 5
        PDFA_ANNOT_FLAG_TOGGLENOVIEW = 1 << 8

        for page in pages:
            page_obj = page.get_object()
            annots = page_obj.get('/Annots', [])
            if isinstance(annots, IndirectObject):
                annots = annots.get_object()
            for annot_ref in annots:
                annot = annot_ref.get_object()
                if annot.get('/Subtype') == '/Popup':
                    continue

                flags = annot.get('/F', 0)
                flags |= PDFA_ANNOT_FLAG_PRINT
                flags &= ~(
                    PDFA_ANNOT_FLAG_HIDDEN
                    | PDFA_ANNOT_FLAG_INVISIBLE
                    | PDFA_ANNOT_FLAG_TOGGLENOVIEW
                    | PDFA_ANNOT_FLAG_NOVIEW
                )
                if annot.get('/Subtype') == '/Text':
                    flags |= PDFA_ANNOT_FLAG_NOZOOM | PDFA_ANNOT_FLAG_NOROTATE

                annot[NameObject('/F')] = NumberObject(flags)

        outlines = self._root_object['/Outlines'].get_object()
        outlines[NameObject('/Count')] = NumberObject(1)

        # [6.7.2.2-1] include a MarkInfo dictionary containing "Marked" with true value
        mark_info = DictionaryObject({NameObject("/Marked"): BooleanObject(True)})
        self._root_object[NameObject("/MarkInfo")] = mark_info

        # [6.7.3.3-1] include minimal document structure in the catalog
        struct_tree_root = DictionaryObject({NameObject("/Type"): NameObject("/StructTreeRoot")})
        self._root_object[NameObject("/StructTreeRoot")] = struct_tree_root

        # Set odoo as producer
        self.addMetadata({
            '/Creator': "Odoo",
            '/Producer': "Odoo",
        })
        self.is_pdfa = True

    def add_file_metadata(self, metadata_content):
        """
        Set the XMP metadata of the pdf, wrapping it with the necessary XMP header/footer.
        These are required for a PDF/A file to be completely compliant. Ommiting them would result in validation errors.

        :param metadata_content: bytes of the metadata to add to the pdf.
        """
        # See https://wwwimages2.adobe.com/content/dam/acom/en/devnet/xmp/pdfs/XMP%20SDK%20Release%20cc-2016-08/XMPSpecificationPart1.pdf
        # Page 10/11
        header = b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        footer = b'<?xpacket end="w"?>'
        metadata = b'%s%s%s' % (header, metadata_content, footer)
        file_entry = DecodedStreamObject()
        file_entry.set_data(metadata)
        file_entry.update({
            NameObject("/Type"): NameObject("/Metadata"),
            NameObject("/Subtype"): NameObject("/XML"),
            NameObject("/Length"): NameObject(str(len(metadata))),
        })

        # Add the new metadata to the pdf, then redirect the reference to refer to this new object.
        metadata_object = self._add_object(file_entry)
        self._root_object.update({NameObject("/Metadata"): metadata_object})

    def _create_attachment_object(self, attachment):
        ''' Create a PyPdf2.generic object representing an embedded file.

        :param attachment: A dictionary containing:
            * filename: The name of the file to embed (required)
            * content:  The bytes of the file to embed (required)
            * subtype: The mime-type of the file to embed (optional)
        :return:
        '''
        file_entry = DecodedStreamObject()
        file_entry.set_data(attachment['content'])
        file_entry.update({
            NameObject("/Type"): NameObject("/EmbeddedFile"),
            NameObject("/Params"):
                DictionaryObject({
                    NameObject('/CheckSum'): create_string_object(md5(attachment['content']).hexdigest()),
                    NameObject('/ModDate'): create_string_object(datetime.now().strftime(DEFAULT_PDF_DATETIME_FORMAT)),
                    NameObject('/Size'): NumberObject(len(attachment['content'])),
                }),
        })
        if attachment.get('subtype'):
            file_entry.update({
                NameObject("/Subtype"): NameObject(attachment['subtype']),
            })
        file_entry_object = self._add_object(file_entry)
        filename_object = create_string_object(attachment['filename'])
        filespec_object = DictionaryObject({
            NameObject("/AFRelationship"): NameObject(attachment.get('afrelationship', '/Data')),
            NameObject("/Type"): NameObject("/Filespec"),
            NameObject("/F"): filename_object,
            NameObject("/EF"):
                DictionaryObject({
                    NameObject("/F"): file_entry_object,
                    NameObject('/UF'): file_entry_object,
                }),
            NameObject("/UF"): filename_object,
        })
        if attachment.get('description'):
            filespec_object.update({NameObject("/Desc"): create_string_object(attachment['description'])})
        return self._add_object(filespec_object)
