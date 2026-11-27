# Part of Odoo. See LICENSE file for full copyright and licensing details.
from __future__ import annotations

import logging
import os
import stat
import typing

from odoo.tools.files.binary import BinaryValue
from odoo.tools.files.mimetypes import guess_file_mimetype

if typing.TYPE_CHECKING:
    from .attachment import IrAttachment


_logger = logging.getLogger('odoo.addons.base.models.ir_attachment')


class LocalBinaryFile(BinaryValue):
    """Lazily loaded file."""
    __slots__ = ('__checksum', '__content', '__mimetype', '__path', '__stat', 'filename')

    def __init__(self, record: IrAttachment):
        """ Open a file as a binary value.

        :param path: absolute path to the file
        :param model: model to check the path
        :raise OSError: if the file cannot be opened
        """
        path = record._full_path(record.store_fname)
        self.__path = path
        self.__stat = os.stat(path)  # checks that the file exists
        if not stat.S_ISREG(self.__stat.st_mode):
            raise FileNotFoundError(f"Path is not a regular file: {path}")
        self.__checksum: str = record.checksum
        self.__content: bytes | None = None
        self.__mimetype: str | None = None
        self.filename = record.name

    def open(self):
        assert isinstance(self, LocalBinaryFile)
        if self.__content is not None:
            return super().open()
        # open the file
        return open(self.__path, 'rb')

    @property
    def content(self) -> bytes:
        if self.__content is None:
            with self.open() as f:
                self.__content = f.read()
        return self.__content

    @property
    def mimetype(self):
        if self.__mimetype is None:
            self.__mimetype = guess_file_mimetype(self.__path)
        return self.__mimetype

    @property
    def size(self):
        return self.__stat.st_size

    @property
    def checksum(self):
        return self.__checksum

    def __repr__(self):
        return f"LocalBinaryFile({self.__path!r})"
