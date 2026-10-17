# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Graphs and sequences: topological sorts, circular dependencies and merges."""

from __future__ import annotations
import typing
from collections import defaultdict
from collections.abc import Iterable, Mapping

if typing.TYPE_CHECKING:
    from collections.abc import Collection

from .containers import SENTINEL, Sentinel

def topological_sort[T](elems: Mapping[T, Collection[T]]) -> list[T]:
    """ Return a list of elements sorted so that their dependencies are listed
    before them in the result.

    :param elems: specifies the elements to sort with their dependencies; it is
        a dictionary like `{element: dependencies}` where `dependencies` is a
        collection of elements that must appear before `element`. The elements
        of `dependencies` are not required to appear in `elems`; they will
        simply not appear in the result.

    :returns: a list with the keys of `elems` sorted according to their
        specification.
    """
    # the algorithm is inspired by [Tarjan 1976],
    # http://en.wikipedia.org/wiki/Topological_sorting#Algorithms
    result = []
    visited = set()

    def visit(n):
        if n not in visited:
            visited.add(n)
            if n in elems:
                # first visit all dependencies of n, then append n to result
                for it in elems[n]:
                    visit(it)
                result.append(n)

    for el in elems:
        visit(el)

    return result


def find_circular_dependency[T](elems: Mapping[T, Collection[T]]) -> list[T]:
    """
    Check for circular dependencies in the given mapping.

    Uses procedural DFS implementation.

    :param elems: Mapping of elements to their dependencies. See also :func:`topological_sort`.
    :return: List representing the circular dependency chain if found, empty list otherwise
    """
    visited: set[T] = set()
    path: list[T] = []
    deps_iters = [iter(elems)]

    while True:
        node = next(deps_iters[-1], SENTINEL)

        if node is SENTINEL:  # Backtrack
            if not path:
                return []

            path.pop()
            deps_iters.pop()

        elif node in visited:
            if node in path:  # Cycle found
                return path[path.index(node):] + [node]

        else:  # Traverse
            visited.add(node)
            path.append(node)
            deps_iters.append(iter(elems.get(node, ())))


def merge_sequences[T](*iterables: Iterable[T]) -> list[T]:
    """ Merge several iterables into a list. The result is the union of the
        iterables, ordered following the partial order given by the iterables,
        with a bias towards the end for the last iterable::

            seq = merge_sequences(['A', 'B', 'C'])
            assert seq == ['A', 'B', 'C']

            seq = merge_sequences(
                ['A', 'B', 'C'],
                ['Z'],                  # 'Z' can be anywhere
                ['Y', 'C'],             # 'Y' must precede 'C';
                ['A', 'X', 'Y'],        # 'X' must follow 'A' and precede 'Y'
            )
            assert seq == ['A', 'B', 'X', 'Y', 'C', 'Z']
    """
    # dict is ordered
    deps: defaultdict[T, list[T]] = defaultdict(list)  # {item: elems_before_item}
    for iterable in iterables:
        prev: T | Sentinel = SENTINEL
        for item in iterable:
            if prev is SENTINEL:
                deps[item]  # just set the default
            else:
                deps[item].append(prev)
            prev = item
    return topological_sort(deps)
