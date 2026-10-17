"""The loading of the modules: the import of their Python package and the execution of their scripts."""

from __future__ import annotations

import importlib
import logging
import os
import re
import sys
import traceback
import typing
import odoo.tools as tools

if typing.TYPE_CHECKING:
    pass

from .manifest import Manifest

_logger = logging.getLogger('odoo.modules.module')


TYPED_FIELD_DEFINITION_RE = re.compile(r'''
    \b (?P<field_name>\w+) \s*
    (:\s*(?P<field_type>[^ ]*))? \s*
    = \s*
    fields\.(?P<field_class>Many2one|One2many|Many2many)
    (\[(?P<type_param>[^\]]+)\])?
''', re.VERBOSE)


def load_openerp_module(module_name: str) -> None:
    """ Load an OpenERP module, if not already loaded.

    This loads the module and register all of its models, thanks to either
    the MetaModel metaclass, or the explicit instantiation of the model.
    This is also used to load server-wide module (i.e. it is also used
    when there is no model to register).
    """

    qualname = f'odoo.addons.{module_name}'
    if qualname in sys.modules:
        return

    try:
        __import__(qualname)

        # Call the module's post-load hook. This can done before any model or
        # data has been initialized. This is ok as the post-load hook is for
        # server-wide (instead of registry-specific) functionalities.
        manifest = Manifest.for_addon(module_name)
        if post_load := manifest.get('post_load'):
            getattr(sys.modules[qualname], post_load)()

    except AttributeError as err:
        _logger.critical("Couldn't load module %s", module_name)
        trace = traceback.format_exc()
        match = TYPED_FIELD_DEFINITION_RE.search(trace)
        if match and "most likely due to a circular import" in trace:
            field_name = match['field_name']
            field_class = match['field_class']
            field_type = match['field_type'] or match['type_param']
            if "." not in field_type:
                field_type = f"{module_name}.{field_type}"
            raise AttributeError(
                f"{err}\n"
                "To avoid circular import for the the comodel use the annotation syntax:\n"
                f"    {field_name}: {field_type} = fields.{field_class}(...)\n"
                "and add at the beggining of the file:\n"
                "    from __future__ import annotations"
            ).with_traceback(err.__traceback__) from None
        raise
    except Exception:
        _logger.critical("Couldn't load module %s", module_name)
        raise


def load_script(path: str, module_name: str):
    full_path = tools.file_path(path) if not os.path.isabs(path) else path
    spec = importlib.util.spec_from_file_location(module_name, full_path)
    assert spec and spec.loader, f"spec not found for {module_name}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
