# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The attachments: the model, its file storage and the lazily loaded local files. The names are re-exported here."""

# the helpers first, then the local file (imported by the model), then the model
from .helpers import CREATE_FROM_STREAM_FLAG, DIRECTORY_MODE, GC_FILE_SUFFIX, GC_GRACE_PERIOD, GC_GRACE_PERIOD_MAX, MAX_COMODELS_FOR_DOMAIN, MAX_SEARCH_LIMIT, SECURITY_FIELDS, condition_values
from .local_file import LocalBinaryFile
from .attachment import IrAttachment
