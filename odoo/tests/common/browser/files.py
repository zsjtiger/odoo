# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Files written by the tests of the browser: screenshots and the logs of Chrome."""

from __future__ import annotations

import logging
import pathlib
import re
import typing
from datetime import datetime
import odoo.cli
from ..utils import _logger, get_db_name

if typing.TYPE_CHECKING:
    pass


def save_test_file(test_name, content, prefix, extension='png', logger=_logger, document_type='Screenshot', date_format="%Y%m%d_%H%M%S_%f", loglevel=logging.RUNBOT, directory=''):
    assert re.fullmatch(r'\w*_', prefix)
    assert re.fullmatch(r'[a-z]+', extension)
    assert re.fullmatch(r'\w+', test_name)
    now = datetime.now().strftime(date_format)
    dest = pathlib.Path(odoo.tools.config['screenshots']) / get_db_name() / directory
    dest.mkdir(parents=True, exist_ok=True)
    full_path = dest / f'{prefix}{now}_{test_name}.{extension}'
    full_path.write_bytes(content)
    logger.log(loglevel, "%s in: %s", document_type, full_path)
