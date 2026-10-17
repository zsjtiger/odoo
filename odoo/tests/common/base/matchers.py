"""Values that compare equal to others in the assertions: the patterns, the queries, the whitespace and the floats."""

from __future__ import annotations

import re
import typing
from functools import partial
from odoo.tools import float_compare
import odoo.addons.base

if typing.TYPE_CHECKING:
    pass


class Like:
    """
        A string-like object comparable to other strings but where the substring
        '...' can match anything in the other string.

        Example of usage:

            self.assertEqual("SELECT field1, field2, field3 FROM model", Like('SELECT ... FROM model'))
            self.assertIn(Like('Company ... (SF)'), ['TestPartner', 'Company 8 (SF)', 'SomeAdress'])
            self.assertEqual([
                'TestPartner',
                'Company 8 (SF)',
                'Anything else'
            ], [
                'TestPartner',
                Like('Company ... (SF)'),
                Like('...'),
            ])

        In case of mismatch, here is an example of error message

            AssertionError: Lists differ: ['TestPartner', 'Company 8 (LA)', 'Anything else'] != ['TestPartner', ~Company ... (SF), ~...]

            First differing element 1:
            'Company 8 (LA)'
            ~Company ... (SF)~

            - ['TestPartner', 'Company 8 (LA)', 'Anything else']
            + ['TestPartner', ~Company ... (SF), ~...]


        """
    def __init__(self, pattern):
        self.pattern = pattern
        self.regex = '.*'.join([re.escape(part.strip()) for part in self.pattern.split('...')])

    def __eq__(self, other):
        return re.fullmatch(self.regex, other.strip(), re.DOTALL)

    def __repr__(self):
        return repr(self.pattern)


class QueryLike(str):
    """ Wrapper for comparing query strings. The comparison ignores case and
    spaces, and the substring ``"..."`` can match anything on the right-hand
    side of operator `==`.
    """
    __slots__ = ('_regex', '_stripped')

    def __init__(self, value):
        # ignore case and spaces when comparing
        self._stripped = "".join(value.lower().split())
        # "..." matches anything
        self._regex = ".*".join(re.escape(part) for part in self._stripped.split('...'))

    def __hash__(self):
        return hash(self._stripped)

    def __eq__(self, other):
        if not isinstance(other, QueryLike):
            return NotImplemented
        return re.fullmatch(self._regex, other._stripped, re.DOTALL)


class WhitespaceInsensitive(str):
    __slots__ = ()

    def __hash__(self):
        return hash(re.sub(r'\s+', ' ', self))

    def __eq__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return re.sub(r'\s+', ' ', self) == re.sub(r'\s+', ' ', other)


class Approx:  # noqa: PLW1641
    """A wrapper for approximate float comparisons. Uses float_compare under
    the hood.

    Most of the time, :meth:`TestCase.assertAlmostEqual` is more useful, but it
    doesn't work for all helpers.
    """
    def __init__(self, value: float, rounding: int | float | odoo.addons.base.models.res_currency.ResCurrency, /, decorate: bool) -> None:  # noqa: PYI041
        self.value = value
        self.decorate = decorate
        if isinstance(rounding, int):
            self.cmp = partial(float_compare, precision_digits=rounding)
        elif isinstance(rounding, float):
            self.cmp = partial(float_compare, precision_rounding=rounding)
        else:
            self.cmp = rounding.compare_amounts

    def __repr__(self) -> str:
        if self.decorate:
            return f"~{self.value!r}"
        return repr(self.value)

    def __eq__(self, other: object) -> bool | NotImplemented:
        if not isinstance(other, (float, int)):
            return NotImplemented
        return self.cmp(self.value, other) == 0
