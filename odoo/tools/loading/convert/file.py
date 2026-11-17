"""Import of a data file, whatever its format."""

import os.path
import warnings
from odoo.tools.misc import file_open

from .common import ConvertMode, IdRef
from .csv import convert_csv_import
from .xml import convert_xml_import

def convert_file(
        env,
        module,
        filename,
        idref: IdRef | None,
        mode: ConvertMode = 'update',
        noupdate=False,
        kind=None,
        pathname=None,
):
    if kind is not None:
        warnings.warn(
            "The `kind` argument is deprecated in Odoo 19.",
            DeprecationWarning,
            stacklevel=2,
        )
    if pathname is None:
        pathname = os.path.join(module, filename)
    ext = os.path.splitext(filename)[1].lower()

    with file_open(pathname, 'rb', env=env) as fp:
        if ext == '.csv':
            convert_csv_import(env, module, pathname, fp.read(), idref, mode, noupdate)
        elif ext == '.sql':
            env.cr.execute(fp.read())  # pylint: disable=sql-injection
        elif ext == '.xml':
            convert_xml_import(env, module, fp, idref, mode, noupdate)
        elif ext == '.js':
            pass # .js files are valid but ignored here.
        else:
            raise ValueError("Can't load unknown file type %s.", filename)
