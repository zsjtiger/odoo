"""Conversion of the ES imports and of the require calls to the modules of Odoo."""

import re

from .paths import IS_PATH_LEGACY_RE, ODOO_MODULE_RE, relative_path_to_module_path

IMPORT_BASIC_RE = re.compile(r"""
    ^
    (?P<space>\s*)                      # space and empty line
    import\s+                           # import
    (?P<object>{[\s\w$,]+})\s*          # { a, b, c as x, ... }
    from\s*                             # from
    (?P<path>(?P<quote>["'`])([^"'`]+)(?P=quote))   # "file path" ("some/path")
    """, re.MULTILINE | re.VERBOSE)


def convert_basic_import(content):
    """
    Transpile the simpler import call.

    .. code-block:: javascript

        // before
        import { a, b, c as x } from "some/path"
        // after
        const {a, b, c: x} = require("some/path")
    """
    def repl(matchobj):
        new_object = matchobj["object"].replace(" as ", ": ")
        return f"{matchobj['space']}const {new_object} = require({matchobj['path']})"
    return IMPORT_BASIC_RE.sub(repl, content)


IMPORT_LEGACY_DEFAULT_RE = re.compile(r"""
    ^
    (?P<space>\s*)                                      # space and empty line
    import\s+                                           # import
    (?P<identifier>[\w$]+)\s*                           # default variable name
    from\s*                                             # from
    (?P<path>(?P<quote>["'`])([^@\."'`][^"'`]*)(?P=quote))  # legacy alias file ("addon_name.module_name" or "some/path")
    """, re.MULTILINE | re.VERBOSE)


def convert_legacy_default_import(content):
    """
    Transpile legacy imports (that were used as they were default import).
    Legacy imports means that their name is not a path but a <addon_name>.<module_name>.
    It requires slightly different processing.

    .. code-block:: javascript

        // before
        import module_name from "addon.module_name"
        // after
        const module_name = require("addon.module_name")
    """
    repl = r"""\g<space>const \g<identifier> = require(\g<path>)"""
    return IMPORT_LEGACY_DEFAULT_RE.sub(repl, content)


IMPORT_DEFAULT = re.compile(r"""
    ^
    (?P<space>\s*)                      # space and empty line
    import\s+                           # import
    (?P<identifier>[\w$]+)\s*           # default variable name
    from\s*                             # from
    (?P<path>(?P<quote>["'`])([^"'`]+)(?P=quote))   # "file path" ("some/path")
    """, re.MULTILINE | re.VERBOSE)


def convert_default_import(content):
    """
    Transpile the default import call.

    .. code-block:: javascript

        // before
        import something from "some/path"
        // after
        const something = require("some/path")[Symbol.for("default")]
    """
    repl = r"""\g<space>const \g<identifier> = require(\g<path>)[Symbol.for("default")]"""
    return IMPORT_DEFAULT.sub(repl, content)


IMPORT_DEFAULT_AND_NAMED_RE = re.compile(r"""
    ^
    (?P<space>\s*)                                  # space and empty line
    import\s+                                       # import
    (?P<default_export>[\w$]+)\s*,\s*               # default variable name,
    (?P<named_exports>{[\s\w$,]+})\s*                # { a, b, c as x, ... }
    from\s*                                         # from
    (?P<path>(?P<quote>["'`])([^"'`]+)(?P=quote))   # "file path" ("some/path")
    """, re.MULTILINE | re.VERBOSE)


def convert_default_and_named_import(content):
    """
    Transpile default and named import on one line.

    .. code-block:: javascript

        // before
        import something, { a } from "some/path";
        import somethingElse, { b } from "legacy.module";
        // after
        const { [Symbol.for("default")]: something, a } = require("some/path");
        const somethingElse = require("legacy.module");
        const { b } = somethingElse;
    """
    def repl(matchobj):
        is_legacy = IS_PATH_LEGACY_RE.match(matchobj['path'])
        new_object = matchobj["named_exports"].replace(" as ", ": ")
        if is_legacy:
            return f"""{matchobj['space']}const {matchobj['default_export']} = require({matchobj['path']});
{matchobj['space']}const {new_object} = {matchobj['default_export']}"""
        new_object = f"""{{ [Symbol.for("default")]: {matchobj['default_export']},{new_object[1:]}"""
        return f"{matchobj['space']}const {new_object} = require({matchobj['path']})"
    return IMPORT_DEFAULT_AND_NAMED_RE.sub(repl, content)


RELATIVE_REQUIRE_RE = re.compile(r"""
    ^[^/*\n]*require\((?P<quote>[\"'`])([^\"'`]+)(?P=quote)\) # require("some/path")
    """, re.MULTILINE | re.VERBOSE)


def convert_relative_require(url, dependencies, content):
    """
    Convert the relative path contained in a 'require()'
    to the new path system (@module/path).
    Adds all modules path to dependencies.
    .. code-block:: javascript

        // Relative path:
        // before
        require("./path")
        // after
        require("@module/path")

        // Not a relative path:
        // before
        require("other_alias")
        // after
        require("other_alias")
    """
    new_content = content
    for quote, path in RELATIVE_REQUIRE_RE.findall(new_content):
        module_path = path
        if path.startswith(".") and "/" in path:
            pattern = rf"require\({quote}{path}{quote}\)"
            module_path = relative_path_to_module_path(url, path)
            repl = f'require("{module_path}")'
            new_content = re.sub(pattern, repl, new_content)
        dependencies.add(module_path)
    return new_content


IMPORT_STAR = re.compile(r"""
    ^(?P<space>\s*)         # indentation
    import\s+\*\s+as\s+     # import * as
    (?P<identifier>[\w$]+)  # alias
    \s*from\s*              # from
    (?P<path>[^;\n]+)       # path
""", re.MULTILINE | re.VERBOSE)


def convert_star_import(content):
    """
    Transpile import star.

    .. code-block:: javascript

        // before
        import * as name from "some/path"
        // after
        const name = require("some/path")
    """
    repl = r"\g<space>const \g<identifier> = require(\g<path>)"
    return IMPORT_STAR.sub(repl, content)


IMPORT_DEFAULT_AND_STAR = re.compile(r"""
    ^(?P<space>\s*)                    # indentation
    import\s+                          # import
    (?P<default_export>[\w$]+)\s*,\s*  # default export name,
    \*\s+as\s+                         # * as
    (?P<named_exports_alias>[\w$]+)    # alias
    \s*from\s*                         # from
    (?P<path>[^;\n]+)                  # path
""", re.MULTILINE | re.VERBOSE)


def convert_default_and_star_import(content):
    """
    Transpile import star.

    .. code-block:: javascript

        // before
        import something, * as name from "some/path";
        // after
        const name = require("some/path");
        const something = name[Symbol.for("default")];
    """
    repl = r"""\g<space>const \g<named_exports_alias> = require(\g<path>);
\g<space>const \g<default_export> = \g<named_exports_alias>[Symbol.for("default")]"""
    return IMPORT_DEFAULT_AND_STAR.sub(repl, content)


IMPORT_UNNAMED_RELATIVE_RE = re.compile(r"""
    ^(?P<space>\s*)     # indentation
    import\s+           # import
    (?P<path>[^;\n]+)   # relative path
""", re.MULTILINE | re.VERBOSE)


def convert_unnamed_relative_import(content):
    """
    Transpile relative "direct" imports. Direct meaning they are not store in a variable.

    .. code-block:: javascript

        // before
        import "some/path"
        // after
        require("some/path")
    """
    repl = r"\g<space>require(\g<path>)"
    return IMPORT_UNNAMED_RELATIVE_RE.sub(repl, content)


def get_aliased_odoo_define_content(module_path, content):
    """
    To allow smooth transition between the new system and the legacy one, we have the possibility to
    defined an alternative module name (an alias) that will act as proxy between legacy require calls and
    new modules.

    Example:
    If we have a require call somewhere in the odoo source base being:
    > vat AbstractAction require("web.AbstractAction")
    we have a problem when we will have converted to module to ES6: its new name will be more like
    "web/chrome/abstract_action". So the require would fail !
    So we add a second small modules, an alias, as such:
    > odoo.define("web/chrome/abstract_action", ['web.AbstractAction'], function (require) {
    >  return require('web.AbstractAction')[Symbol.for("default")];
    > });

    To generate this, change your comment on the top of the file.

    .. code-block:: javascript

        // before
        /** @odoo-module */
        // after
        /** @odoo-module alias=web.AbstractAction */

    Notice that often, the legacy system acted like they it did defaukt imports. That's why we have the
    "[Symbol.for("default")];" bit. If your use case does not need this default import, just do:

    .. code-block:: javascript

        // before
        /** @odoo-module */
        // after
        /** @odoo-module alias=web.AbstractAction default=false */

    :return: the alias content to append to the source code.
    """
    matchobj = ODOO_MODULE_RE.match(content)
    if matchobj:
        alias = matchobj['alias']
        if alias:
            if matchobj['default']:
                return """\nodoo.define(`%s`, ['%s'], function (require) {
                        return require('%s');
                        });\n""" % (alias, module_path, module_path)
            else:
                return """\nodoo.define(`%s`, ['%s'], function (require) {
                        return require('%s')[Symbol.for("default")];
                        });\n""" % (alias, module_path, module_path)


def convert_as(val):
    parts = val.split(" as ")
    return val if len(parts) < 2 else "%s: %s" % tuple(reversed(parts))


def remove_as(val):
    parts = val.split(" as ")
    return val if len(parts) < 2 else parts[0]
