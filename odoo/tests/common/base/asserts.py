"""The assertions of the test cases: the raises, the queries, the records and the XML and HTML trees."""

from __future__ import annotations

import difflib
import inspect
import logging
import pprint
import typing
from contextlib import ExitStack, contextmanager
from itertools import zip_longest
from unittest.mock import patch
from lxml import etree
import odoo.cli
import odoo.models
from odoo.exceptions import AccessError
from odoo.orm.database.sql_db import Cursor
from odoo.tools import SQL
from odoo.tools.misc import diff_zip

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

from .base import BaseCase
from .matchers import Approx, QueryLike

@contextmanager
def _raisesContext(self, method, expected_exception, *args, **kwargs):
    """ Context manager that clears the environment upon failure. """
    with ExitStack() as init:
        if self.env:
            init.enter_context(self.env.cr.savepoint())
            if isinstance(expected_exception, tuple):
                clear_cache = any(issubclass(e, AccessError) for e in expected_exception)
            else:
                clear_cache = issubclass(expected_exception, AccessError)
            if clear_cache:
                # When checking for an `AccessError`, the cache is cleared
                # before executing the code. This avoids cache pollution issues and
                # ensures that access are re-evaluated correctly.
                self.env.transaction.clear()

        with ExitStack() as inner:
            cm = inner.enter_context(method(expected_exception, *args, **kwargs))
            # *moves* the cleanups from init to inner, this ensures the
            # savepoint gets rolled back when `yield` raises `exception`,
            # but still allows the initialisation to be protected *and* not
            # interfered with by `assertRaises`.
            inner.push(init.pop_all())

            yield cm


def assertRaises(self, expected_exception, callable=None, *args, **kwargs):
    if callable:
        with self._raisesContext(super(BaseCase, self).assertRaises, expected_exception):
            callable(*args, **kwargs)
        return None
    return self._raisesContext(super(BaseCase, self).assertRaises, expected_exception, *args, **kwargs)


def assertRaisesRegex(self, expected_exception, expected_regex, callable=None, *args, **kwargs):
    if callable:
        with self._raisesContext(super(BaseCase, self).assertRaisesRegex, expected_exception, expected_regex):
            callable(*args, **kwargs)
        return None
    return self._raisesContext(super(BaseCase, self).assertRaisesRegex, expected_exception, expected_regex, *args, **kwargs)


def _patchExecute(self, actual_queries, flush=True):
    Cursor_execute = Cursor.execute

    def execute(self, query, params=None, log_exceptions=None):
        if isinstance(query, SQL):
            assert params is None
            query, params, _ = query._sql_tuple
        actual_queries.append(query)
        return Cursor_execute(self, query, params, log_exceptions)

    if flush:
        self.env.cr.flush()

    with (
        patch('odoo.orm.database.sql_db.Cursor.execute', execute),
        patch.object(self.env.registry, 'unaccent', lambda x: x),
    ):
        yield actual_queries
        if flush:
            self.env.cr.flush()


@contextmanager
def assertQueries(self, expected, flush=True):
    """ Check the queries made by the current cursor. ``expected`` is a list
    of strings representing the expected queries being made. Query strings
    are matched against each other, ignoring case and whitespaces. Moreover,
    the substring ``"..."`` can be used as a wildcard to match anything in
    the corresponding actual query.
    """
    actual_queries = []

    yield from self._patchExecute(actual_queries, flush)

    if not self.warm:
        return

    # diff lists of queries 'expected' and 'actual_queries'
    queries1 = [QueryLike(query) for query in expected]
    queries2 = [QueryLike(query) for query in actual_queries]
    if queries1 == queries2:
        return

    diff = "\n".join(
        (f"--- {query1}" if query2 is None else
         f"+++ {query2}" if query1 is None else
         f"=== {query2}")
        for query1, query2 in diff_zip(queries1, queries2)
    )
    self.fail(self._formatMessage("\n" + diff, "Not the expected queries"))


@contextmanager
def assertQueryCount(self, default=0, flush=True, **counters):
    """ Context manager that counts queries. It may be invoked either with
        one value, or with a set of named arguments like ``login=value``::

            with self.assertQueryCount(42):
                ...

            with self.assertQueryCount(admin=3, demo=5):
                ...

        The second form is convenient when used with :func:`users`.
    """
    flush_func = self.env.cr.flush if flush else lambda: None
    if self.warm:
        # mock random in order to avoid random bus gc
        with patch('random.random', lambda: 1):
            login = self.env.user.login
            expected = counters.get(login, default)
            flush_func()
            count0 = self.cr.sql_log_count
            yield
            flush_func()
            count = self.cr.sql_log_count - count0
            if count != expected:
                # add some info on caller to allow semi-automatic update of query count
                _frame, filename, linenum, funcname, _lines, _index = inspect.stack()[2]
                filename = filename.replace('\\', '/')
                if "/odoo/addons/" in filename:
                    filename = filename.rsplit("/odoo/addons/", 1)[1]
                if count > expected:
                    msg = "Query count more than expected for user %s: %d > %d in %s at %s:%s"
                    # add a subtest in order to continue the test_method in case of failures
                    with self.subTest():
                        self.fail(msg % (login, count, expected, funcname, filename, linenum))
                elif expected and not count:
                    msg = "Query count did not detect any queries %s: expected %d in %s at %s:%s"
                    with self.subTest():
                        self.fail(msg % (login, expected, funcname, filename, linenum))
                else:
                    logger = logging.getLogger(type(self).__module__)
                    msg = "Query count less than expected for user %s: %d < %d in %s at %s:%s"
                    logger.info(msg, login, count, expected, funcname, filename, linenum)
    else:
        # flush before and after during warmup, in order to reproduce the
        # same operations, otherwise the caches might not be ready!
        flush_func()
        yield
        flush_func()


def assertRecordValues(
        self,
        records: odoo.models.BaseModel,
        expected_values: list[dict],
        *,
        field_names: Iterable[str] | None = None,
) -> None:
    ''' Compare a recordset with a list of dictionaries representing the expected results.
    This method performs a comparison element by element based on their index.
    Then, the order of the expected values is extremely important.

    .. note::

        - ``None`` expected values can be used for empty fields.
        - x2many fields are expected by ids (so the expected value should be
          a ``list[int]``
        - many2one fields are expected by id (so the expected value should
          be an ``int``

    :param records: The records to compare.
    :param expected_values: Items to check the ``records`` against.
    :param field_names: list of fields to check during comparison, if
                        unspecified all expected_values must have the same
                        keys and all are checked
    '''
    if not field_names:
        field_names = expected_values[0].keys()
        for i, v in enumerate(expected_values):
            self.assertEqual(
                v.keys(), field_names,
                f"All expected values must have the same keys, found differences between records 0 and {i}",
            )

    expected_reformatted = []
    for vs in expected_values:
        r = {}
        for f in field_names:
            t = records._fields[f].type
            if t in ('one2many', 'many2many'):
                r[f] = sorted(vs[f])
            elif t == 'float':
                r[f] = float(vs[f])
            elif t == 'integer':
                r[f] = int(vs[f])
            elif t == 'binary':
                r[f] = bytes(vs[f])
            elif vs[f] is None:
                r[f] = False
            else:
                r[f] = vs[f]
        expected_reformatted.append(r)

    record_reformatted = []
    for record in records:
        r = {}
        for field_name in field_names:
            record_value = record[field_name]
            match record._fields[field_name]:
                case odoo.fields.Many2one():
                    record_value = record_value.id
                case odoo.fields.One2many() | odoo.fields.Many2many():
                    record_value = sorted(record_value.ids)
                case odoo.fields.Float() as field if digits := field.get_digits(record.env):
                    record_value = Approx(record_value, digits[1], decorate=False)
                case odoo.fields.Monetary() as field if currency_field_name := field.get_currency_field(record):
                    # don't round if there's no currency set
                    if c := record[currency_field_name]:
                        record_value = Approx(record_value, c, decorate=False)
                case odoo.fields.Binary() as field:
                    record_value = record_value.content

            r[field_name] = record_value
        record_reformatted.append(r)

    try:
        self.assertSequenceEqual(expected_reformatted, record_reformatted, seq_type=list)
        return
    except AssertionError as e:
        standardMsg, _, diffMsg = str(e).rpartition('\n')
        if 'self.maxDiff' not in diffMsg:
            raise
        # move out of handler to avoid exception chaining

    diffMsg = "".join(difflib.unified_diff(
        pprint.pformat(expected_reformatted).splitlines(keepends=True),
        pprint.pformat(record_reformatted).splitlines(keepends=True),
        fromfile="expected", tofile="records",
    ))
    self.fail(self._formatMessage(None, standardMsg + '\n' + diffMsg))


def assertItemsEqual(self, a, b, msg=None):
    self.assertCountEqual(a, b, msg=None)


def assertTreesEqual(self, n1, n2, msg=None):
    self.assertIsNotNone(n1, msg)
    self.assertIsNotNone(n2, msg)
    self.assertEqual(n1.tag, n2.tag, msg)
    # Because lxml.attrib is an ordereddict for which order is important
    # to equality, even though *we* don't care
    self.assertEqual(dict(n1.attrib), dict(n2.attrib), msg)
    self.assertEqual((n1.text or u'').strip(), (n2.text or u'').strip(), msg)
    self.assertEqual((n1.tail or u'').strip(), (n2.tail or u'').strip(), msg)

    for c1, c2 in zip_longest(n1, n2):
        self.assertTreesEqual(c1, c2, msg)


def _assertXMLEqual(self, original, expected, parser="xml"):
    """Asserts that two xmls archs are equal

    :param original: the xml arch to test
    :type original: str
    :param expected: the xml arch of reference
    :type expected: str
    :param parser: an string representing which lxml.Parser class to use
        when normalizing both archs. Takes either "xml" or "html"
    :type parser: str
    """
    self.maxDiff = 10000
    if original:
        original = _normalize_arch_for_assert(original, parser)
    if expected:
        expected = _normalize_arch_for_assert(expected, parser)
    self.assertEqual(original, expected)


def assertXMLEqual(self, original, expected):
    return self._assertXMLEqual(original, expected)


def assertHTMLEqual(self, original, expected):
    return self._assertXMLEqual(original, expected, 'html')


def _normalize_arch_for_assert(arch_string, parser_method="xml"):
    """Takes some xml and normalize it to make it comparable to other xml
    in particular, blank text is removed, and the output is pretty-printed

    :param str arch_string: the string representing an XML arch
    :param str parser_method: an string representing which lxml.Parser class to use
        when normalizing both archs. Takes either "xml" or "html"
    :return: the normalized arch
    :rtype str:
    """
    Parser = None
    if parser_method == 'xml':
        Parser = etree.XMLParser
    elif parser_method == 'html':
        Parser = etree.HTMLParser
    parser = Parser(remove_blank_text=True)
    arch_string = etree.fromstring(arch_string, parser=parser)
    return etree.tostring(arch_string, pretty_print=True, encoding='unicode')
