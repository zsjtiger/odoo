# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The storage of the files: the filestore, the paths, the reads and writes of the files, and their garbage collection."""

from __future__ import annotations

import io
import os
import re
import shutil
import tempfile
import typing
import uuid
from datetime import datetime
from odoo import _
from odoo.exceptions import AccessError
from odoo.fields import Domain
from odoo.tools import SQL, config, split_every
from odoo.tools.files.binary import EMPTY_BINARY, BinaryValue
from odoo.tools.constants import IN_MAX
from .helpers import (
    DIRECTORY_MODE,
    GC_FILE_SUFFIX,
    GC_GRACE_PERIOD,
    GC_GRACE_PERIOD_MAX,
)
from .local_file import LocalBinaryFile

if typing.TYPE_CHECKING:
    pass

from .attachment import IrAttachment, _logger

def _storage(self):
    return self.env['ir.config_parameter'].sudo().get_str('ir_attachment.location') or 'file'


def _filestore(self):
    return config.filestore(self.env.cr.dbname)


def _get_storage_domain(self):
    # domain to retrieve the attachments to migrate
    return {
        'db': [('store_fname', '!=', False)],
        'file': [('db_datas', '!=', False)],
    }[self._storage()]


def force_storage(self):
    """Force all attachments to be stored in the currently configured storage"""
    if not self.env.is_admin():
        raise AccessError(_('Only administrators can execute this action.'))

    # Migrate only binary attachments and bypass the res_field automatic
    # filter added in _search override
    self.search(Domain.AND([
        self._get_storage_domain(),
        ['&', ('type', '=', 'binary'), '|', ('res_field', '=', False), ('res_field', '!=', False)]
    ]))._migrate()


def _migrate(self):
    record_count = len(self)
    storage = self._storage().upper()
    for index, attach in enumerate(self):
        _logger.debug("Migrate attachment %s/%s to %s", index + 1, record_count, storage)
        # pass mimetype, to avoid recomputation
        attach.write({'raw': attach.raw, 'mimetype': attach.mimetype})


def _full_path(self, path):
    assert not path.endswith(GC_FILE_SUFFIX)
    # sanitize path
    path = re.sub(r'[.:]', '', path).strip('/\\')
    return os.path.join(self._filestore(), path)


def _file_fname(self, sha: str) -> str:
    # scatter files across 256 dirs
    # we use '/' in the db
    return sha[:2] + '/' + sha


def _file_read(self) -> BinaryValue:
    assert isinstance(self, IrAttachment) and self.store_fname
    try:
        return LocalBinaryFile(self)
    except OSError:
        full_path = self._full_path(self.store_fname)
        _logger.info("_file_read reading %s", full_path, exc_info=True)
        return EMPTY_BINARY


def _file_write(self, fname: str, bin_value: io.IOBase) -> None:
    """ Persist the data for the given fname. """
    assert isinstance(self, IrAttachment)
    assert hasattr(bin_value, 'read') and hasattr(bin_value, 'seek'), f'expecting a seekable IO object, got {bin_value}'
    full_path = self._full_path(fname)
    try:
        # add fname to checklist, in case the transaction aborts
        self._mark_for_gc(fname)

        # check if file exists and prevent sha-1 collision
        try:
            with open(full_path, 'rb') as existing_file:
                if self._same_content(bin_value, existing_file):
                    return
                e = f"The attachment {fname} collides with an existing file."
                raise RuntimeError(e)
        except FileNotFoundError:
            pass

        # Copy ``bin_value`` in the upload folder, prevent changing
        # the copy's content (as this would corrupt the checksum and
        # filename) and then move (i.e. "commit") it to it right
        # place in the filestore.
        upload_dir = self._full_path('upload')
        prefix = os.path.basename(fname) + '-'
        try:  # noqa: SIM105
            os.mkdir(upload_dir, DIRECTORY_MODE)
        except FileExistsError:
            pass
        tmp_path = os.path.join(upload_dir, prefix + uuid.uuid4().hex[:16])
        try:
            try:
                # Fast hardlink, works for io.FileIO when it's on the same filesystem
                if not (hasattr(bin_value, 'name') and isinstance(bin_value, (tempfile._TemporaryFileWrapper, io.IOBase))):
                    raise OSError("Cannot hardlink in _file_write")  # noqa: TRY301
                os.link(bin_value.name, tmp_path)
            except OSError:
                # Copy, works for all io.IOBase
                with open(tmp_path, 'wb') as tmp_file:
                    shutil.copyfileobj(bin_value, tmp_file)
                    tmp_file.flush()
                    if hasattr(os, 'fchmod'):
                        os.fchmod(tmp_file.fileno(), 0o444)  # r--r--r--
                    else:
                        os.chmod(tmp_path, 0o444)  # r--r--r--
            else:
                os.chmod(tmp_path, 0o444)  # r--r--r--

            # "commit" the file by moving it to its right place
            try:
                os.replace(tmp_path, full_path)
                tmp_path = None
            except FileNotFoundError:  # missing directory
                os.makedirs(os.path.dirname(full_path), DIRECTORY_MODE, exist_ok=True)
                os.replace(tmp_path, full_path)
                tmp_path = None
        finally:
            # Clean-up the temporary file
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    _logger.debug("Failed to remove temporary file: %s", tmp_path, exc_info=True)

    except OSError as e:
        e.add_note(f"_file_write writing {full_path}")
        raise


def _file_delete(self, fname: str) -> None:
    """ Add ``fname`` to checklist of files to delete. """
    # Deletion may not be done immediately, because this is called within
    # the transaction that could fail later.
    self._mark_for_gc(fname)


def _mark_for_gc(self, fname: str) -> None:
    """ Add ``fname`` in a checklist for the filestore garbage collection. """
    assert isinstance(self, IrAttachment)
    fname = re.sub(r'[.:]', '', fname).strip('/\\')
    assert not fname.endswith(GC_FILE_SUFFIX)
    # we use a spooldir: add an empty file in the subdirectory 'checklist'
    full_path = os.path.join(self._full_path('checklist'), fname)
    # touch the full_path
    try:
        open(full_path, 'wb').close()
    except FileNotFoundError:  # missing directory
        os.makedirs(os.path.dirname(full_path), DIRECTORY_MODE, exist_ok=True)
        open(full_path, 'wb').close()


def _gc_file_store(self):
    """ Perform the garbage collection of the filestore. """
    assert isinstance(self, IrAttachment)
    if self._storage() != 'file':
        return
    # Fetch the timeouts from the database.
    # GC_GRACE_PERIOD is set to a sensible default, if the DB is configured
    # with a larger value respect it.
    [[grace_db]] = self.env.execute_query(SQL("""
            SELECT EXTRACT(epoch FROM GREATEST(
                NULLIF(current_setting('idle_in_transaction_session_timeout', true), '0')::interval,
                NULLIF(current_setting('transaction_timeout', true), '0')::interval
            ))::int
        """))
    self._gc_file_store_unsafe(grace_period=max(GC_GRACE_PERIOD, min((grace_db or 0) * 2, GC_GRACE_PERIOD_MAX)))


def _gc_file_store_unsafe(self, grace_period):
    # Generate the file names to check
    limit_time = datetime.now().timestamp() - grace_period

    # Clean up old uploaded files
    upload_dir = self._full_path('upload')
    if os.path.isdir(upload_dir):
        for dirpath, _subdirs, filenames in os.walk(upload_dir):
            for filename in filenames:
                path = os.path.join(dirpath, filename)
                if os.path.getmtime(path) < limit_time:
                    _logger.debug("filestore gc removing old uploaded file %s", path)
                    os.unlink(path)

    def files_to_gc():
        for dirpath, _subdirs, filenames in os.walk(self._full_path('checklist')):
            dirname = os.path.basename(dirpath)
            filenames.sort(reverse=True)  # start with files with suffix
            for filename in filenames:
                check_file = os.path.join(dirpath, filename)
                fname = f"{dirname}/{filename}"
                if check_file.endswith(GC_FILE_SUFFIX):
                    # leftover from a previous GC
                    # move the file back if it exists
                    try:
                        full_path = self._full_path(fname)
                        os.replace(full_path + GC_FILE_SUFFIX, full_path)
                    except OSError:
                        _logger.info("filestore gc was interrupted, moving back %s", filename, exc_info=True)
                    else:
                        _logger.info("filestore gc was interrupted, moved back %s", filename)
                    # move the check file back, ignore if file already exists
                    original_check_file = check_file.removesuffix(GC_FILE_SUFFIX)
                    try:
                        if not os.path.exists(original_check_file):
                            os.rename(check_file, original_check_file)
                    except OSError:
                        os.unlink(check_file)
                elif os.path.getmtime(check_file) < limit_time:
                    # we can collect the file
                    yield (fname, check_file)

    # Clean up the checklist. The checklist is split in chunks and files are garbage-collected
    # for each chunk.
    checked = 0
    removed = 0
    for name_pairs in split_every(IN_MAX, files_to_gc()):
        # start a new transaction (see latest data) and release locks of
        # previous loop which we don't want modified during processing
        self.env.cr.commit()
        # determine which files to keep among the checklist
        referenced_fnames = {fname for fname, in self.env.execute_query(SQL("""
                SELECT store_fname
                FROM ir_attachment
                WHERE store_fname IN %s
                FOR UPDATE""", tuple(p[0] for p in name_pairs)
        ))}
        checked += len(name_pairs)

        # remove files, and clean up checklist
        for fname, check_file in name_pairs:
            # If a file is written during the clean up process, we must
            # ensure that it remains on disk. To achieve this on the file
            # system, we are first moving the files and then deleting them
            # after checking if a checkfile did not appear in the meantime.
            full_path = self._full_path(fname)
            del_check_file = check_file + GC_FILE_SUFFIX
            del_full_path = full_path + GC_FILE_SUFFIX
            # 1. Move the check file
            try:
                if fname in referenced_fnames:
                    os.unlink(check_file)
                    continue
                else:
                    os.replace(check_file, del_check_file)
            except OSError:
                _logger.debug("_file_gc could not move %s", check_file, exc_info=True)
                continue
            # 2. Check the mtime of the moved check file
            if not (os.path.getmtime(del_check_file) < limit_time):
                _logger.debug("_file_gc concurrent write for %s", full_path)
                os.replace(del_check_file, check_file)  # restore the check file
                continue
            # 3. Move the file
            try:
                os.replace(full_path, del_full_path)
            except FileNotFoundError:
                pass  # check file created but the whole file does not exist
            except OSError:
                _logger.info("_file_gc could not move %s", full_path, exc_info=True)
                continue
            # 4. Check if a check file was created in the meantime
            if os.path.exists(check_file):
                _logger.debug("_file_gc concurrent write during move for %s", full_path)
                try:  # noqa: SIM105
                    os.replace(del_full_path, full_path)
                except OSError:
                    _logger.warning("_file_gc failed to move files back, ignore for %s", full_path)
                os.unlink(del_check_file)
                continue
            # 5. Remove moved files
            try:
                os.unlink(del_full_path)
            except FileNotFoundError:
                pass
            except OSError:
                _logger.info("_file_gc could not unlink %s", full_path, exc_info=True)
            else:
                removed += 1
                _logger.debug("_file_gc unlinked %s", full_path)
            os.unlink(del_check_file)
    if checked:
        # release locks
        self.env.cr.commit()

    _logger.info("filestore gc %d checked, %d removed", checked, removed)
