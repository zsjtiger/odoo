"""Conversion of the ES exports to the modules of Odoo, and of the translated strings."""

import re

from .imports import convert_as, remove_as
from .paths import URL_RE

EXPORT_FCT_RE = re.compile(r"""
    ^
    (?P<space>\s*)                          # space and empty line
    export\s+                               # export
    (?P<type>(async\s+)?function)\s+        # async function or function
    (?P<identifier>[\w$]+)                  # name of the function
    """, re.MULTILINE | re.VERBOSE)


def convert_export_function(content):
    """
    Transpile functions that are being exported.

    .. code-block:: javascript

        // before
        export function name
        // after
       __exports.name = name; function name

        // before
        export async function name
        // after
        __exports.name = name; async function name

    """
    repl = r"\g<space>__exports.\g<identifier> = \g<identifier>; \g<type> \g<identifier>"
    return EXPORT_FCT_RE.sub(repl, content)


EXPORT_CLASS_RE = re.compile(r"""
    ^
    (?P<space>\s*)                          # space and empty line
    export\s+                               # export
    (?P<type>class)\s+                      # class
    (?P<identifier>[\w$]+)                  # name of the class
    """, re.MULTILINE | re.VERBOSE)


def convert_export_class(content):
    """
    Transpile classes that are being exported.

    .. code-block:: javascript

        // before
        export class name
        // after
        const name = __exports.name = class name

    """
    repl = r"\g<space>const \g<identifier> = __exports.\g<identifier> = \g<type> \g<identifier>"
    return EXPORT_CLASS_RE.sub(repl, content)


EXPORT_FCT_DEFAULT_RE = re.compile(r"""
    ^
    (?P<space>\s*)                          # space and empty line
    export\s+default\s+                     # export default
    (?P<type>(async\s+)?function)\s+        # async function or function
    (?P<identifier>[\w$]+)                  # name of the function
    """, re.MULTILINE | re.VERBOSE)


def convert_export_function_default(content):
    """
    Transpile functions that are being exported as default value.

    .. code-block:: javascript

        // before
        export default function name
        // after
        __exports[Symbol.for("default")] = name; function name

        // before
        export default async function name
        // after
        __exports[Symbol.for("default")] = name; async function name

    """
    repl = r"""\g<space>__exports[Symbol.for("default")] = \g<identifier>; \g<type> \g<identifier>"""
    return EXPORT_FCT_DEFAULT_RE.sub(repl, content)


EXPORT_CLASS_DEFAULT_RE = re.compile(r"""
    ^
    (?P<space>\s*)                          # space and empty line
    export\s+default\s+                     # export default
    (?P<type>class)\s+                      # class
    (?P<identifier>[\w$]+)                  # name of the class or the function
    """, re.MULTILINE | re.VERBOSE)


def convert_export_class_default(content):
    """
    Transpile classes that are being exported as default value.

    .. code-block:: javascript

        // before
        export default class name
        // after
        const name = __exports[Symbol.for("default")] = class name

    """
    repl = r"""\g<space>const \g<identifier> = __exports[Symbol.for("default")] = \g<type> \g<identifier>"""
    return EXPORT_CLASS_DEFAULT_RE.sub(repl, content)


GETTEXT_RE = re.compile(r"""
    ^
    \s*const\s*{
    (?:\s*\w*\s*,)*
    \s*(_t)\s*
    (?:,\s*\w*\s*)*,?\s*
    }\s*=\s*require\("@web/core/data/l10n/translation"\);$
""", re.MULTILINE | re.VERBOSE)


T_FN_RE = re.compile(r"""
    ^
    \s*const\s*{
    (?:\s*\w*\s*,)*
    \s*(appTranslateFn)\s*
    (?:,\s*\w*\s*)*,?\s*
    }\s*=\s*require\("@web/core/data/l10n/translation"\);$
""", re.MULTILINE | re.VERBOSE)


def convert_t(url, content):
    if url.endswith(".test.js"):
        return content

    module_name = URL_RE.match(url)["module"]
    has_import_of_appTranslateFn = bool(T_FN_RE.search(content))

    def rename_gettext(match_):
        if has_import_of_appTranslateFn:
            renamed_import = match_.group(0).replace("_t", "__not_defined__")
        else:
            renamed_import = match_.group(0).replace("_t", "appTranslateFn")
        renamed_import += f"""const _t = (str, ...args) => appTranslateFn(str, "{module_name}", ...args);"""
        return renamed_import

    return GETTEXT_RE.sub(rename_gettext, content)


EXPORT_VAR_RE = re.compile(r"""
    ^
    (?P<space>\s*)              # space and empty line
    export\s+                   # export
    (?P<type>let|const|var)\s+  # let or cont or var
    (?P<identifier>[\w$]+)      # variable name
    """, re.MULTILINE | re.VERBOSE)


def convert_variable_export(content):
    """
    Transpile variables that are being exported.

    .. code-block:: javascript

        // before
        export let name
        // after
        let name = __exports.name
        // (same with var and const)

    """
    repl = r"\g<space>\g<type> \g<identifier> = __exports.\g<identifier>"
    return EXPORT_VAR_RE.sub(repl, content)


EXPORT_DEFAULT_VAR_RE = re.compile(r"""
    ^
    (?P<space>\s*)              # space and empty line
    export\s+default\s+         # export default
    (?P<type>let|const|var)\s+  # let or const or var
    (?P<identifier>[\w$]+)\s*   # variable name
    """, re.MULTILINE | re.VERBOSE)


def convert_variable_export_default(content):
    """
    Transpile the variables that are exported as default values.

    .. code-block:: javascript

        // before
        export default let name
        // after
        let name = __exports[Symbol.for("default")]

    """
    repl = r"""\g<space>\g<type> \g<identifier> = __exports[Symbol.for("default")]"""
    return EXPORT_DEFAULT_VAR_RE.sub(repl, content)


EXPORT_OBJECT_RE = re.compile(r"""
    ^
    (?P<space>\s*)                      # space and empty line
    export\s*                           # export
    (?P<object>{[\w$\s,]+})             # { a, b, c as x, ... }
    """, re.MULTILINE | re.VERBOSE)


def convert_object_export(content):
    """
    Transpile exports of multiple elements

    .. code-block:: javascript

        // before
        export { a, b, c as x }
        // after
        Object.assign(__exports, { a, b, x: c })
    """
    def repl(matchobj):
        object_process = "{" + ", ".join([convert_as(val) for val in matchobj["object"][1:-1].split(",")]) + "}"
        space = matchobj["space"]
        return f"{space}Object.assign(__exports, {object_process})"
    return EXPORT_OBJECT_RE.sub(repl, content)


EXPORT_FROM_RE = re.compile(r"""
    ^
    (?P<space>\s*)                      # space and empty line
    export\s*                           # export
    (?P<object>{[\w$\s,]+})\s*          # { a, b, c as x, ... }
    from\s*                             # from
    (?P<path>(?P<quote>["'`])([^"'`]+)(?P=quote))   # "file path" ("some/path.js")
    """, re.MULTILINE | re.VERBOSE)


def convert_from_export(content):
    """
    Transpile exports coming from another source

    .. code-block:: javascript

        // before
        export { a, b, c as x } from "some/path.js"
        // after
        { a, b, c } = {require("some/path.js"); Object.assign(__exports, { a, b, x: c });}
    """
    def repl(matchobj):
        object_clean = "{" + ",".join([remove_as(val) for val in matchobj["object"][1:-1].split(",")]) + "}"
        object_process = "{" + ", ".join([convert_as(val) for val in matchobj["object"][1:-1].split(",")]) + "}"
        return "%(space)s{const %(object_clean)s = require(%(path)s);Object.assign(__exports, %(object_process)s)}" % {
            'object_clean': object_clean,
            'object_process': object_process,
            'space': matchobj['space'],
            'path': matchobj['path'],
        }
    return EXPORT_FROM_RE.sub(repl, content)


EXPORT_STAR_FROM_RE = re.compile(r"""
    ^
    (?P<space>\s*)                      # space and empty line
    export\s*\*\s*from\s*               # export * from
    (?P<path>(?P<quote>["'`])([^"'`]+)(?P=quote))   # "file path" ("some/path.js")
    """, re.MULTILINE | re.VERBOSE)


def convert_star_from_export(content):
    """
    Transpile exports star coming from another source

    .. code-block:: javascript

        // before
        export * from "some/path.js"
        // after
        Object.assign(__exports, require("some/path.js"))
    """
    repl = r"\g<space>Object.assign(__exports, require(\g<path>))"
    return EXPORT_STAR_FROM_RE.sub(repl, content)


EXPORT_DEFAULT_RE = re.compile(r"""
    ^
    (?P<space>\s*)      # space and empty line
    export\s+default    # export default
    (\s+[\w$]+\s*=)?    # something (optional)
    """, re.MULTILINE | re.VERBOSE)


def convert_default_export(content):
    """
    This function handles the default exports.
    Either by calling another operation with a TRUE flag, and if any default is left, doing a simple replacement.

    (see convert_export_function_or_class_default and convert_variable_export_default).
    +
    .. code-block:: javascript

        // before
        export default
        // after
        __exports[Symbol.for("default")] =

    .. code-block:: javascript

        // before
        export default something =
        // after
        __exports[Symbol.for("default")] =
    """
    new_content = convert_export_function_default(content)
    new_content = convert_export_class_default(new_content)
    new_content = convert_variable_export_default(new_content)
    repl = r"""\g<space>__exports[Symbol.for("default")] ="""
    return EXPORT_DEFAULT_RE.sub(repl, new_content)
