# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The content of the attachments: the data, the checksums, the mimetypes, the indexed content and the uploads."""

from __future__ import annotations

import contextlib
import hashlib
import io
import mimetypes
import os
import re
import tempfile
import typing
import warnings
from odoo import _, api
from odoo.exceptions import AccessError, UserError
from odoo.tools import OrderedSet, str2bool
from odoo.tools.files import image
from odoo.tools.files.binary import EMPTY_BINARY, BinaryBytes, BinaryValue
from odoo.tools.files.mimetypes import guess_file_mimetype, guess_mimetype
from .helpers import (
    CREATE_FROM_STREAM_FLAG,
    DIRECTORY_MODE,
)

if typing.TYPE_CHECKING:
    pass

from .attachment import IrAttachment, _logger

def _compute_raw(self):
    for attach in self:
        if attach.store_fname:
            raw = attach._file_read()
        else:
            raw = BinaryBytes(attach.db_datas, filename=attach.name)
        attach.raw = raw


def _get_pdf_raw(self):
    self.ensure_one()
    if self.type != 'binary':
        return False
    if not self.mimetype.startswith('application/pdf'):
        return False
    return self.raw


def _inverse_raw(self):
    old_fnames = OrderedSet()
    raw_map = {}

    for attach in self:
        # compute the fields that depend on raw
        bin_data = attach.raw or EMPTY_BINARY
        vals = self._get_datas_related_values(bin_data, attach.mimetype)

        # take current location in filestore to possibly garbage-collect it
        if fname := attach.store_fname:
            old_fnames.add(fname)

        # write as superuser, as user probably does not have write access
        super(IrAttachment, attach.sudo()).write(vals)
        if bin_data and (fname := attach.store_fname):
            raw_map[fname] = bin_data

    if raw_map or old_fnames:
        # before touching the filestore, prevent the GC from
        # running until the end of the transaction
        self.lock_for_update(allow_referencing=True)
    for fname in old_fnames:
        if fname not in raw_map:
            self._file_delete(fname)
    for fname, raw in raw_map.items():
        with raw.open() as f:
            self._file_write(fname, f)


def _get_datas_related_values(self, data: BinaryValue, mimetype):
    checksum = self._compute_checksum(data)
    try:
        if data:
            index_content = self._index(data, mimetype, checksum=checksum)
        else:
            index_content = False
    except TypeError:
        index_content = self._index(data, mimetype)
    values = {
        'file_size': data.size,
        'checksum': checksum,
        'index_content': index_content,
        'store_fname': False,
        'db_datas': data or False,
    }
    if data and self._storage() != 'db':
        values['store_fname'] = self._file_fname(checksum)
        values['db_datas'] = False
    return values


def _compute_checksum(self, bin_data):
    """ compute the checksum for the given bytes
            :param bin_data : data in its binary form
        """
    # an empty file has a checksum too (for caching)
    return hashlib.sha1(bin_data or b'').hexdigest()


def _same_content(self, file1: io.IOBase, file2: io.IOBase) -> bool:
    with contextlib.ExitStack() as exit_stack:
        exit_stack.callback(file1.seek, file1.tell())
        file1.seek(0)
        exit_stack.callback(file2.seek, file2.tell())
        file2.seek(0)
        while True:
            chunk1 = file1.read(io.DEFAULT_BUFFER_SIZE)
            chunk2 = file2.read(io.DEFAULT_BUFFER_SIZE)
            if chunk1 != chunk2:
                return False
            if not chunk1:
                break
    return True


def _compute_mimetype(self, values):
    """ compute the mimetype of the given values
            :param values : dict of values to create or write an ir_attachment
            :return mime : string indicating the mimetype, or application/octet-stream by default
        """
    mimetype = None
    if values.get('mimetype'):
        mimetype = values['mimetype']
    if not mimetype and values.get('name'):
        mimetype = mimetypes.guess_type(values['name'])[0]
    if not mimetype and values.get('url'):
        mimetype = mimetypes.guess_type(values['url'].split('?')[0])[0]
    if not mimetype or mimetype == 'application/octet-stream':
        if raw := values.get('raw'):
            if isinstance(raw, BinaryValue):
                if mimetype := raw.mimetype:
                    return mimetype
                raw = raw.content
            assert isinstance(raw, bytes), f"Expecting raw bytes, got {type(raw)}"
            mimetype = guess_mimetype(raw)
    return mimetype.lower() if mimetype else 'application/octet-stream'


def _postprocess_contents(self, values):
    ICP = self.env['ir.config_parameter'].sudo()
    supported_subtype = (ICP.get_str('base.image_autoresize_extensions') or 'png,jpeg,bmp,tiff').split(',')

    assert 'mimetype' in values and 'datas' not in values, '_check_contents should handle that'
    type_, subtype = values['mimetype'].split('/', 1)
    if type_ != 'image' or subtype not in supported_subtype:
        return values
    raw = values.get('raw')
    if not raw:
        return values

    # Can be set to 0 to skip the resize
    max_resolution = ICP.get_str('base.image_autoresize_max_px') or '1920x1920'
    if str2bool(max_resolution, True):
        try:
            img = image.ImageProcess(raw, verify_resolution=False)

            if not img.image:
                _logger.info('Post processing ignored : Empty source, SVG, or WEBP')
                return values

            w, h = img.image.size
            nw, nh = map(int, max_resolution.split('x'))
            if w > nw or h > nh:
                img = img.resize(nw, nh)
                if subtype == 'jpeg':  # Do not affect PNGs color palette
                    quality = ICP.get_int('base.image_autoresize_quality', 80)
                    output = img.image_quality(quality)
                else:
                    output = img.image_quality()
                values['raw'] = BinaryBytes(output, filename=raw.filename)
        except UserError as e:
            # Catch error during test where we provide fake image
            # raise UserError(_("This file could not be decoded as an image file. Please try with a different file."))
            msg = str(e)  # the exception can be lazy-translated, resolve it here
            _logger.info('Post processing ignored : %s', msg)
    return values


def _check_contents(self, values):
    # get raw and remove db_datas
    if 'datas' in values:
        warnings.warn("Use raw, datas has beeen removed")
        values.pop('datas')  # ignoring
    raw = values.pop('db_datas', None)
    raw = values.get('raw', raw) or b''
    # make sure we have a BinaryValue in raw (if we have data)
    raw = self._fields['raw'].convert_to_cache(raw, self) or EMPTY_BINARY
    if raw or 'raw' in values:
        values['raw'] = raw

    if 'name' not in values and (filename := raw.filename or values.get('res_field')):
        values['name'] = filename
    mimetype = values['mimetype'] = self._compute_mimetype(values)
    xml_like = 'ht' in mimetype or ( # hta, html, xhtml, etc.
            'xml' in mimetype and    # other xml (svg, text/xml, etc)
            not mimetype.startswith('application/vnd.openxmlformats'))  # exception for Office formats
    force_text = xml_like and (
        self.env.context.get('attachments_mime_plainxml')
        or not self.env['ir.ui.view'].sudo(False).has_access('write')
    )
    if force_text:
        values['mimetype'] = 'text/plain'
    if not self.env.context.get('image_no_postprocess'):
        values = self._postprocess_contents(values)
    return values


def _index(self, bin_data: BinaryValue, file_type: str, checksum=None) -> str | None:
    """ compute the index content of the given binary data.
        This is a python implementation of the unix command 'strings'.
        """
    # compute index_content only for text type
    if file_type and file_type.startswith('text/'):
        word_re = re.compile(rb'[\x20-\x7E]{4,}')
        with bin_data.open() as file:
            # Use readline() with a size limit to avoid unbounded
            # reads on files which may not contain newlines.
            # Note that this could split the indexed content
            # of such files due to the buffer max size.
            return '\n'.join(
                match.group().decode('ascii')
                for line in iter(lambda: file.readline(io.DEFAULT_BUFFER_SIZE), b'')
                for match in word_re.finditer(line)
            )
    return None


def _upload_file(self, file: io.IOBase, create_vals: api.ValuesType) -> typing.Self:
    """
        Create an attachment out of a file.

        The file is read in chunks to compute the checksum, file size,
        and destination path. When it doesn't exist on the file-system
        yet or is not seekable, it is saved in a temporary file in the
        ``path/to/filestore/<dbname>/upload/`` folder. In all cases, the
        file is hard-linked/copied to the correct place in the filestore
        and a new attachment is created for that file.
        """
    if 'raw' in create_vals or 'db_datas' in create_vals:
        e = "Cannot use neither 'raw' nor 'db_datas' with _upload_file."
        raise ValueError(e)

    if self._storage() == 'db':
        return self.create(dict(create_vals, raw=BinaryBytes(file.read())))

    # Check permissions first, so we don't read the entire file if
    # it is gonna fail.
    if any(self._inaccessible_comodel_records(
        model_and_ids={create_vals.get('res_model'): [create_vals.get('res_id')]},
        operation='write',
    )):
        raise AccessError(_("Sorry, you are not allowed to access this document."))

    with contextlib.ExitStack() as exit_stack:

        # For os.link and _same_content, we need the file to be seekable and
        # accessible on the file-system.
        # When it is not, we save it in a named temporary file.
        src_path = getattr(file, 'name', None)
        try:
            if not isinstance(src_path, (str, bytes, os.PathLike)):
                raise FileNotFoundError(f"not a path: {src_path}")
            open(src_path, 'rb').close()  # check we can read it
            file.seek(0)
        except OSError:  # not accessible/seekable
            upload_dir = self._full_path('upload')
            try:  # noqa: SIM105
                os.mkdir(upload_dir, DIRECTORY_MODE)
            except FileExistsError:
                pass
            file_upload = exit_stack.enter_context(
                tempfile.NamedTemporaryFile(
                    dir=upload_dir,
                    prefix="{model}-{id}-{uid}-".format(
                        model=create_vals.get('res_model', ''),
                        id=create_vals.get('res_id', ''),
                        uid=self.env.uid,
                    ),
                    suffix='.part',
                ),
            )
            src_path = file_upload.name
        else:
            file_upload = None

        # Read the file's content in chunks to compute its checksum,
        # size and destination file name. Save it in the temporary
        # file if necessary.
        # Similar to `_compute_checksum`.
        computed_fields = {'file_size': 0}
        sha = hashlib.sha1()
        while chunk := file.read(io.DEFAULT_BUFFER_SIZE):  # 16kiB
            sha.update(chunk)
            computed_fields['file_size'] += len(chunk)
            if file_upload:
                file_upload.write(chunk)
        if file_upload:
            file_upload.flush()
        else:
            # reset the position to the beginning to save the data
            file.seek(0)
        computed_fields['checksum'] = sha.hexdigest()
        computed_fields['store_fname'] = self._file_fname(computed_fields['checksum'])
        if 'mimetype' not in create_vals:
            computed_fields['mimetype'] = guess_file_mimetype(src_path)

        # The order of the next lines matters for _gc_file_store. It
        # MUST be create => _mark_for_gc => link => commit/rollback.
        # Similar to `_file_write`.
        attach = (
            self.with_context(ir_attachment_from_stream=CREATE_FROM_STREAM_FLAG)
                .create(create_vals | computed_fields)
                .with_env(self.env)
        )
        self._file_write(computed_fields['store_fname'], file_upload or file)

    attach.index_content = attach._index(attach.raw, attach.mimetype, attach.checksum)
    return attach
