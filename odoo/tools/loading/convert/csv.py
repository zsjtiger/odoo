"""Import of the CSV data files."""

import csv
import io
import logging
import os.path

from .common import ConvertMode, IdRef

_logger = logging.getLogger('odoo.tools.loading.convert')


def convert_csv_import(
        env,
        module,
        fname,
        csvcontent,
        idref: IdRef | None = None,
        mode: ConvertMode = 'init',
        noupdate=False,
):
    '''Import csv file :
        quote: "
        delimiter: ,
        encoding: utf-8'''
    env = env(context=dict(env.context, lang=None))
    filename, _ext = os.path.splitext(os.path.basename(fname))
    model = filename.split('-')[0]
    reader = csv.reader(io.StringIO(csvcontent.decode()), quotechar='"', delimiter=',')
    fields = next(reader)

    if not (mode == 'init' or 'id' in fields):
        _logger.error("Import specification does not contain 'id' and we are in init mode, Cannot continue.")
        return

    translate_indexes = {i for i, field in enumerate(fields) if '@' in field}
    def remove_translations(row):
        return [cell for i, cell in enumerate(row) if i not in translate_indexes]

    fields = remove_translations(fields)
    if not fields:
        return

    # clean the data from translations (treated during translation import), then
    # filter out empty lines (any([]) == False) and lines containing only empty cells
    datas = [
        data_line for line in reader
        if any(data_line := remove_translations(line))
    ]

    context = {
        'mode': mode,
        'module': module,
        'install_mode': True,
        'install_module': module,
        'install_filename': fname,
        'noupdate': noupdate,
    }
    result = env[model].with_context(**context).load(fields, datas)
    if any(msg['type'] == 'error' for msg in result['messages']):
        # Report failed import and abort module install
        warning_msg = "\n".join(msg['message'] for msg in result['messages'])
        raise Exception(env._(
            "Module loading %(module)s failed: file %(file)s could not be processed:\n%(message)s",
            module=module,
            file=fname,
            message=warning_msg,
        ))
