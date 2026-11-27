"""Transpilation of the JavaScript sources of the modules to the Odoo module format."""

from functools import partial
from odoo.tools.misc import OrderedSet

from .exports import convert_default_export, convert_export_class, convert_export_function, convert_from_export, convert_object_export, convert_star_from_export, convert_t, convert_variable_export
from .imports import convert_basic_import, convert_default_and_named_import, convert_default_and_star_import, convert_default_import, convert_legacy_default_import, convert_relative_require, convert_star_import, convert_unnamed_relative_import, get_aliased_odoo_define_content
from .paths import remove_index, url_to_module_path

def transpile_javascript(url, content):
    """
    Transpile the code from native JS modules to custom odoo modules.

    :param content: The original source code
    :param url: The url of the file in the project
    :return: The transpiled source code
    """
    module_path = url_to_module_path(url)
    legacy_odoo_define = get_aliased_odoo_define_content(module_path, content)
    dependencies = OrderedSet()
    # The order of the operations does sometimes matter.
    steps = [
        convert_legacy_default_import,
        convert_basic_import,
        convert_default_and_named_import,
        convert_default_and_star_import,
        convert_default_import,
        convert_star_import,
        convert_unnamed_relative_import,
        convert_from_export,
        convert_star_from_export,
        remove_index,
        partial(convert_relative_require, url, dependencies),
        convert_export_function,
        convert_export_class,
        convert_variable_export,
        convert_object_export,
        convert_default_export,
        partial(wrap_with_odoo_define, module_path, dependencies),
        partial(convert_t, url)
    ]
    for s in steps:
        content = s(content)
    if legacy_odoo_define:
        content += legacy_odoo_define
    return content


def wrap_with_odoo_define(module_path, dependencies, content):
    """
    Wraps the current content (source code) with the odoo.define call.
    It adds as a second argument the list of dependencies.
    Should logically be called once all other operations have been performed.
    """
    return f"""odoo.define({module_path!r}, {list(dependencies)}, function (require) {{
'use strict';
let __exports = {{}};
{content}
return __exports;
}});
"""
