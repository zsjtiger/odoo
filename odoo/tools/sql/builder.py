"""The SQL builder: the SQL objects, the escaping of the identifiers and the formatting of the queries."""

from __future__ import annotations

import re
import typing
from binascii import crc32
from psycopg2.extensions import quote_ident
from odoo.tools.func import deprecated
from odoo.tools.misc import freehash, named_to_positional_printf

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

    from odoo.fields import Field


IDENT_RE = re.compile(r'^[a-z0-9_][a-z0-9_$\-]*$', re.IGNORECASE)


class _SQLMeta(type):
    @staticmethod
    def identifier(name: str, subname: str | None = None, to_flush: Field | None = None) -> SQL:
        """ Return an SQL object that represents an identifier. """
        assert name.isidentifier() or IDENT_RE.match(name), f"{name!r} invalid for SQL.identifier()"
        if subname is None:
            return SQL(f'"{name}"', to_flush=to_flush)  # pylint: disable=sql-injection
        assert subname.isidentifier() or IDENT_RE.match(subname), f"{subname!r} invalid for SQL.identifier()"
        return SQL(f'"{name}"."{subname}"', to_flush=to_flush)  # pylint: disable=sql-injection


class SQL(metaclass=_SQLMeta):
    """ An object that wraps SQL code with its parameters, like::

        sql = SQL("UPDATE TABLE foo SET a = %s, b = %s", 'hello', 42)
        cr.execute(sql)

    The code is given as a ``%``-format string, and supports either positional
    arguments (with `%s`) or named arguments (with `%(name)s`). The arguments
    are meant to be merged into the code using the `%` formatting operator.
    Note that the character ``%`` must always be escaped (as ``%%``), even if
    the code does not have parameters, like in ``SQL("foo LIKE 'a%%'")``.

    The SQL wrapper is designed to be composable: the arguments can be either
    actual parameters, or SQL objects themselves::

        sql = SQL(
            "UPDATE TABLE %s SET %s",
            SQL.identifier(tablename),
            SQL("%s = %s", SQL.identifier(columnname), value),
        )

    The combined result is available in ``_sql_tuple`` which contains ``code``,
    ``params``, ``to_flush``. This allows to combine any number of SQL terms
    without having to separately combine their parameters, which can be tedious,
    bug-prone, and is the main downside of `psycopg2.sql
    <https://www.psycopg.org/docs/sql.html>`.
    The metadata ``to_flush`` contains fields on which the SQL code depends on.

    The second purpose of the wrapper is to discourage SQL injections. Indeed,
    if ``code`` is a string literal (not a dynamic string), then the SQL object
    made with ``code`` is guaranteed to be safe, provided the SQL objects
    within its parameters are themselves safe.
    """
    __slots__ = ()

    @typing.overload
    def __new__[T: SQL](cls: type[T], *a, **kw) -> T:
        ...

    @typing.overload
    def __new__(cls: type[SQL], code: typing.LiteralString | SQL, /, *args, to_flush: Field | Iterable[Field] | None = None, **kw) -> LiteralSQL:
        ...

    def __new__(cls, *a, **kw):
        if cls is SQL:
            cls = LiteralSQL  # noqa: PLW0642
        return object.__new__(cls)

    _sql_tuple: tuple[str, tuple, tuple[Field, ...]]
    """ The tuple used to execute the query: (code, params, to_flush) """

    def __eq__(self, other):
        if not isinstance(other, SQL):
            return False
        return self._sql_tuple[:2] == other._sql_tuple[:2]

    def __hash__(self):
        return freehash(self._sql_tuple[:2])

    def __bool__(self):
        return bool(self._sql_tuple[0])


class LiteralSQL(SQL):
    __slots__ = ('__sql_tuple',)
    __sql_tuple: tuple[str, tuple, tuple[Field, ...]]

    def __init__(self, code: typing.LiteralString | SQL = "", /, *args, to_flush: Field | Iterable[Field] | None = None, **kwargs):
        if isinstance(code, SQL) or (code == "%s" and len(args) == 1 and isinstance(args[0], SQL)):
            if code == "%s":
                code, args = args[0], ()
            if args or kwargs:
                raise TypeError("SQL() unexpected arguments when code has type SQL")
            if to_flush is None:
                self.__sql_tuple = code._sql_tuple
            else:
                code, args, _ = code._sql_tuple
                to_flush = (to_flush,) if getattr(to_flush.__class__, '__iter__', None) is None else tuple(to_flush)
                self.__sql_tuple = (code, args, to_flush)
            return

        # validate the format of code and parameters
        if args and kwargs:
            raise TypeError("SQL() takes either positional arguments, or named arguments")

        if kwargs:
            code, args = named_to_positional_printf(code, kwargs)
        elif not args:
            code % ()  # check that code does not contain %s
            if to_flush is None:
                to_flush = ()
            elif getattr(to_flush.__class__, '__iter__', None) is not None:
                to_flush = tuple(to_flush)
            else:
                to_flush = (to_flush,)
            self.__sql_tuple = (code, (), to_flush)
            return

        code_list = []
        params_list = []
        to_flush_list = []
        for arg in args:
            if isinstance(arg, SQL):
                arg_code, arg_params, arg_to_flush = arg._sql_tuple
                code_list.append(arg_code)
                params_list.extend(arg_params)
                to_flush_list.extend(arg_to_flush)
            else:
                code_list.append("%s")
                params_list.append(arg)
        if to_flush is not None:
            if getattr(to_flush.__class__, '__iter__', None) is not None:
                to_flush_list.extend(to_flush)
            else:
                to_flush_list.append(to_flush)

        code = code.replace('%%', '%%%%') % tuple(code_list)
        params = tuple(params_list)
        to_flush = tuple(to_flush_list)
        self.__sql_tuple = (code, params, to_flush)

    @property
    def _sql_tuple(self):
        # property makes the attribute read-only
        return self.__sql_tuple

    def __repr__(self):
        code, params, _ = self.__sql_tuple
        return f"SQL({', '.join(map(repr, [code, *params]))})"

    def join(self, args: Iterable) -> SQL:
        """ Join SQL objects or parameters with ``self`` as a separator. """
        args = list(args)
        # optimizations for special cases
        if len(args) == 0:
            return SQL()
        if len(args) == 1 and isinstance(args[0], SQL):
            return args[0]
        code, params, to_flush = self.__sql_tuple
        if not params:
            return SQL(code.join(("%s",) * len(args)), *args, to_flush=to_flush)  # pylint: disable=sql-injection
        # general case: alternate args with self
        items = [self] * (len(args) * 2 - 1)
        for index, arg in enumerate(args):
            items[index * 2] = arg
        return SQL("%s" * len(items), *items)  # pylint: disable=sql-injection


@deprecated("Since 20.0, use escape_like_value")
def escape_psql(to_escape: str) -> str:
    return escape_like_value(to_escape)


def escape_like_value(to_escape: str) -> str:
    """ Escapes a string for injection into a LIKE statement. """
    return to_escape.replace('\\', r'\\').replace('%', r'\%').replace('_', r'\_')


@deprecated("Removed after 20.0")
def reverse_order(order):
    """ Reverse an ORDER BY clause """
    items = []
    for item in order.split(','):
        item = item.lower().split()
        direction = 'asc' if item[1:] == ['desc'] else 'desc'
        items.append('%s %s' % (item[0], direction))
    return ', '.join(items)


def make_identifier(identifier: str) -> str:
    """ Return ``identifier``, possibly modified to fit PostgreSQL's identifier size limitation.
    If too long, ``identifier`` is truncated and padded with a hash to make it mostly unique.
    """
    # if length exceeds the PostgreSQL limit of 63 characters.
    if len(identifier) > 63:
        # We have to fit a crc32 hash and one underscore into a 63 character
        # alias. The remaining space we can use to add a human readable prefix.
        return f"{identifier[:54]}_{crc32(identifier.encode()):08x}"
    return identifier


def make_index_name(table_name: str, column_name: str) -> str:
    """ Return an index name according to conventions for the given table and column. """
    return make_identifier(f"{table_name}__{column_name}_index")


def quoted_identifier(cr, name: str) -> SQL:
    """Quote a database identifier.

    Use instead of `SQL.identifier` to accept all kinds of identifiers.
    """
    name = quote_ident(name, cr._cnx)
    return SQL(name)  # pylint: disable=sql-injection


_TOKEN_SPECIFICATION = [
    ('PAREN_OPEN', r'\('),
    ('PAREN_CLOSE', r'\)'),
    ('LINE_COMMENT', r'--[^\n]*'),
    ('STATEMENT_TERMINATOR', r';'),
    ('STRING_LITERAL', r"'[^']*'"),
    ('QUOTED_IDENTIFIER', r'"[^"]*"'),
    ('KEYWORD', r'''(?<![\w.])(?:
                          and | or | with | select | from | where | having | limit | offset | exists
                        | (?:group|order)\s+by | union(?:\s+all)? | values | returning
                        | insert\s+into | delete\s+from | update | set
                        | (?:(?:left|right|full|inner|cross)\s+)?(?:outer\s+)?join
                    )(?![\w.])'''),
]


_TOKEN_REGEX = re.compile(
    '|'.join(f'(?P<{name}>{pattern})' for name, pattern in _TOKEN_SPECIFICATION),
    re.IGNORECASE | re.VERBOSE
)


def format_query(query: str) -> str:
    """ This is a naive, best-effort SQL query formatter. The result is not meant to be "correct".
    """
    lines: list[str] = []
    line = ''
    depth = 0  # current parenthesis nesting level
    end = 0  # end of the previous token in ``query``

    for match in _TOKEN_REGEX.finditer(query):
        kind = match.lastgroup
        token = match.group()

        # `finditer` leaps between tokens and we manually grab the raw text we skipped over.
        line += query[end:match.start()]
        end = match.end()

        if kind == 'KEYWORD':
            # start a new line
            lines.append(line)
            indent = depth + (token.lower() in ('and', 'or'))  # one level deeper for the conditions of a WHERE clause
            line = 4 * indent * ' ' + ' '.join(token.split())

        elif kind == 'PAREN_OPEN':
            depth += 1
            line += token

        elif kind == 'PAREN_CLOSE':
            depth -= 1
            line += token

        else:
            line += token

    line += query[end:]
    lines.append(line)

    result = '\n'.join(line.rstrip() for line in lines).strip()
    return result if result.endswith(';') else result + ';'
