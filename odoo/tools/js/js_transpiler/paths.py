"""Paths and URLs of the JavaScript modules: their conversion to the module names of Odoo."""

import re


URL_RE = re.compile(r"""
    /?(?P<module>\S+)    # /module name
    /([\S/]*/)?static/   # ... /static/
    (?P<type>src|tests|lib)  # src, test, or lib file
    (?P<url>/[\S/]*)     # URL (/...)
    """, re.VERBOSE)


def url_to_module_path(url):
    """
    Odoo modules each have a name. (odoo.define("<the name>", [<dependencies>], function (require) {...});
    It is used in to be required later. (const { something } = require("<the name>").
    The transpiler transforms the url of the file in the project to this name.
    It takes the module name and add a @ on the start of it, and map it to be the source of the static/src (or
    static/tests, or static/lib) folder in that module.

    in: web/static/src/one/two/three.js
    out: @web/one/two/three.js
    The module would therefore be defined and required by this path.

    :param url: an url in the project
    :return: a special path starting with @<module-name>.
    """
    match = URL_RE.match(url)
    if match:
        url = match["url"]
        if url.endswith(('/index.js', '/index')):
            url, _ = url.rsplit('/', 1)
        if url.endswith('.js'):
            url = url[:-3]
        if match["type"] == "src":
            return "@%s%s" % (match['module'], url)
        elif match["type"] == "lib":
            return "@%s/../lib%s" % (match['module'], url)
        else:
            return "@%s/../tests%s" % (match['module'], url)
    else:
        raise ValueError("The js file %r must be in the folder '/static/src' or '/static/lib' or '/static/test'" % url)


IS_PATH_LEGACY_RE = re.compile(r"""(?P<quote>["'`])([^@\."'`][^"'`]*)(?P=quote)""")


URL_INDEX_RE = re.compile(r"""
    require\s*                 # require
    \(\s*                      # (
    (?P<path>(?P<quote>["'`])([^"'`]*/index/?)(?P=quote))  # path ended by /index or /index/
    \s*\)                      # )
""", re.MULTILINE | re.VERBOSE)


def remove_index(content):
    """
    Remove in the paths the /index.js.
    We want to be able to import a module just trough its directory name if it contains an index.js.
    So we no longer need to specify the index.js in the paths.
    """
    def repl(matchobj):
        path = matchobj["path"]
        new_path = path[: path.rfind("/index")] + path[0]
        return f"require({new_path})"
    return URL_INDEX_RE.sub(repl, content)


def relative_path_to_module_path(url, path_rel):
    """Convert the relative path into a module path, which is more generic and
    fancy.

    :param str url:
    :param path_rel: a relative path to the current url.
    :return: module path (@module/...)
    """
    url_split = url.split("/")
    path_rel_split = path_rel.split("/")
    nb_back = len([v for v in path_rel_split if v == ".."]) + 1
    result = "/".join(url_split[:-nb_back] + [v for v in path_rel_split if not v in ["..", "."]])
    return url_to_module_path(result)


ODOO_MODULE_RE = re.compile(r"""
    \s*                                # starting white space
    \/(\*|\/)                          # /* or //
    .*                                 # any comment in between (optional)
    @odoo-module                       # '@odoo-module' statement
    (?P<ignore>\s+ignore)?             # module in src | tests which should not be transpiled (optional)
    (\s+alias=(?P<alias>[^\s*]+))?     # alias (e.g. alias=web.Widget, alias=@web/../tests/utils) (optional)
    (\s+default=(?P<default>[\w$]+))?  # no implicit default export (e.g. default=false) (optional)
""", re.VERBOSE)


def is_odoo_module(url, content):
    """
    Detect if the file is a native odoo module.
    We look for a comment containing @odoo-module.

    :param url:
    :param content: source code
    :return: is this a odoo module that need transpilation ?
    """
    result = ODOO_MODULE_RE.match(content)
    if result and result['ignore']:
        return False
    addon = url.split('/')[1]
    if url.startswith(f'/{addon}/static/src') or url.startswith(f'/{addon}/static/tests'):
        return True
    return bool(result)
