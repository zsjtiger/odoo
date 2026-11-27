"""The reader of the PDF files, with the embedded attachments."""

from __future__ import annotations

import warnings

from .compat import PdfFileReader

class OdooPdfFileReader(PdfFileReader):
    # OVERRIDE of PdfFileReader to add the management of multiple embedded files.

    ''' Returns the files inside the PDF.
    :raises NotImplementedError: if document is encrypted and uses an unsupported encryption method.
    '''
    def get_attachments(self):
        if self.is_encrypted:
            # If the PDF is owner-encrypted, try to unwrap it by giving it an empty user password.
            self.decrypt('')

        def _traverse_nodes(obj):
            file_path = obj.get("/Names", [])
            for p in file_path[1::2]:
                attachment = p.get_object()
                try:
                    yield (attachment["/F"], attachment["/EF"]["/F"].get_object().get_data())
                except (KeyError, AttributeError):
                    continue
            for kid in obj.get("/Kids", []):
                if id(kid) not in visited_nodes:
                    visited_nodes.add(id(kid))
                    yield from _traverse_nodes(kid.get_object())

        try:
            file_path = self.trailer["/Root"].get("/Names", {}).get("/EmbeddedFiles", {})
            if not file_path:
                return []
            visited_nodes = set()
            yield from _traverse_nodes(file_path)
        except Exception:  # noqa: BLE001
            # malformed pdf (i.e. invalid xref page)
            return []

    def getAttachments(self):
        warnings.warn("getAttachments() is deprecated, use get_attachments()", category=DeprecationWarning, stacklevel=2)
        self.get_attachments()
