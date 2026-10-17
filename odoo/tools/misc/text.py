# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Text helpers: the booleans, the escaping, the quoting and the diffs of the strings."""

from __future__ import annotations
import typing
import unicodedata
import warnings
from collections.abc import Mapping
from difflib import HtmlDiff
import markupsafe

if typing.TYPE_CHECKING:
    pass


def str2bool(s: str, default: bool | None = None) -> bool:
    # allow this (for now?) because it's used for get_param
    if type(s) is bool:
        return s  # type: ignore

    if not isinstance(s, str):
        warnings.warn(
            f"Passed a non-str to `str2bool`: {s}",
            DeprecationWarning,
            stacklevel=2,
        )

        if default is None:
            raise ValueError('Use 0/1/yes/no/true/false/on/off')
        return bool(default)

    s = s.lower()
    if s in ('y', 'yes', '1', 'true', 't', 'on'):
        return True
    if s in ('n', 'no', '0', 'false', 'f', 'off'):
        return False
    if default is None:
        raise ValueError('Use 0/1/yes/no/true/false/on/off')
    return bool(default)


def remove_accents(input_str: str) -> str:
    """Suboptimal-but-better-than-nothing way to replace accented
    latin letters by an ASCII equivalent. Will obviously change the
    meaning of input_str and work only for some cases"""
    if not input_str:
        return input_str
    nkfd_form = unicodedata.normalize('NFKD', input_str)
    return ''.join(c for c in nkfd_form if not unicodedata.combining(c))


class unquote(str):
    """A subclass of str that implements repr() without enclosing quotation marks
       or escaping, keeping the original string untouched. The name come from Lisp's unquote.
       One of the uses for this is to preserve or insert bare variable names within dicts during eval()
       of a dict's repr(). Use with care.

       Some examples (notice that there are never quotes surrounding
       the ``active_id`` name:

       >>> unquote('active_id')
       active_id
       >>> d = {'test': unquote('active_id')}
       >>> d
       {'test': active_id}
       >>> print d
       {'test': active_id}
    """
    __slots__ = ()

    def __repr__(self):
        return self


html_escape = markupsafe.escape


def get_diff(data_from, data_to, custom_style=False, dark_color_scheme=False):
    """
    Return, in an HTML table, the diff between two texts.

    :param tuple data_from: tuple(text, name), name will be used as table header
    :param tuple data_to: tuple(text, name), name will be used as table header
    :param tuple custom_style: string, style css including <style> tag.
    :param bool dark_color_scheme: true if dark color scheme is used
    :return: a string containing the diff in an HTML table format.
    """
    def handle_style(html_diff, custom_style, dark_color_scheme):
        """ The HtmlDiff lib will add some useful classes on the DOM to
        identify elements. Simply append to those classes some BS4 ones.
        For the table to fit the modal width, some custom style is needed.
        """
        to_append = {
            'diff_header': 'bg-600 text-light text-center align-top px-2',
            'diff_next': 'd-none',
        }
        for old, new in to_append.items():
            html_diff = html_diff.replace(old, "%s %s" % (old, new))
        html_diff = html_diff.replace('nowrap', '')
        colors = ('#7f2d2f', '#406a2d', '#51232f', '#3f483b') if dark_color_scheme else (
            '#ffc1c0', '#abf2bc', '#ffebe9', '#e6ffec')
        html_diff += custom_style or '''
            <style>
                .modal-dialog.modal-lg:has(table.diff) {
                    max-width: 1600px;
                    padding-left: 1.75rem;
                    padding-right: 1.75rem;
                }
                table.diff { width: 100%%; }
                table.diff th.diff_header { width: 50%%; }
                table.diff td.diff_header { white-space: nowrap; }
                table.diff td.diff_header + td { width: 50%%; }
                table.diff td { word-break: break-all; vertical-align: top; }
                table.diff .diff_chg, table.diff .diff_sub, table.diff .diff_add {
                    display: inline-block;
                    color: inherit;
                }
                table.diff .diff_sub, table.diff td:nth-child(3) > .diff_chg { background-color: %s }
                table.diff .diff_add, table.diff td:nth-child(6) > .diff_chg { background-color: %s }
                table.diff td:nth-child(3):has(>.diff_chg, .diff_sub) { background-color: %s }
                table.diff td:nth-child(6):has(>.diff_chg, .diff_add) { background-color: %s }
            </style>
        ''' % colors
        return html_diff

    diff = HtmlDiff(tabsize=2).make_table(
        data_from[0].splitlines(),
        data_to[0].splitlines(),
        data_from[1],
        data_to[1],
        context=True,  # Show only diff lines, not all the code
        numlines=3,
    )
    return handle_style(diff, custom_style, dark_color_scheme)


def diff_zip(items1: list, items2: list):
    """ Return pairs of matching items in both lists, which represents the diff
    between the lists. The elements of the pairs ``(item1, item2)`` are either
    elements of ``items1`` (resp. ``items2``) or ``None``, where the latter
    represents a non-matching item.
    For instance, ``diff_zip(list('abcd'), list('acde'))`` returns the pairs::

        ('a', 'a'), ('b', None), ('c', 'c'), ('d', 'd'), (None, 'e')
    """
    size1, size2 = len(items1), len(items2)

    def _iter_block(index1, index2):
        """ Iterate on coordinates in range(index1, size1) x range(index2, size2)
        in increasing distance order, the distance being the sum of both indices.
        The pairs are returned in the following order::

            (index1, index2),
            (index1 + 1, index2), (index1, index2 + 1),
            (index1 + 2, index2), (index1 + 1, index2 + 1), (index1, index2 + 2),
            ...,
        """
        dist1, dist2 = size1 - index1, size2 - index2
        for delta in range(dist1 + dist2 - 1):
            # delta1 + delta2 == delta
            for delta2 in range(min(delta + 1, dist2)):
                if (delta1 := delta - delta2) < dist1:
                    yield index1 + delta1, index2 + delta2

    index1, index2 = 0, 0  # next indices to match
    while index1 < size1:
        # find the closest matching pair from (index1, index2)
        for current1, current2 in _iter_block(index1, index2):
            if items1[current1] == items2[current2]:
                for it in range(index1, current1):
                    yield (items1[it], None)
                for it in range(index2, current2):
                    yield (None, items2[it])
                yield (items1[current1], items2[current2])
                index1, index2 = current1 + 1, current2 + 1
                break
        else:
            break
    for it in range(index1, size1):
        yield (items1[it], None)
    for it in range(index2, size2):
        yield (None, items2[it])


def named_to_positional_printf(string: str, args: Mapping) -> tuple[str, tuple]:
    """ Convert a named printf-style format string with its arguments to an
    equivalent positional format string with its arguments.
    """
    pargs = _PrintfArgs(args)
    return string.replace('%%', '%%%%') % pargs, tuple(pargs.values)


class _PrintfArgs:
    """ Helper object to turn a named printf-style format string into a positional one. """
    __slots__ = ('mapping', 'values')

    def __init__(self, mapping):
        self.mapping: Mapping = mapping
        self.values: list = []

    def __getitem__(self, key):
        self.values.append(self.mapping[key])
        return "%s"
