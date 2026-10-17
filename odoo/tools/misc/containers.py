# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Containers and iteration helpers: ordered and frozen collections, the splits and the groups."""

from __future__ import annotations
import collections
import enum
import itertools
import typing
import warnings
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, MutableMapping, MutableSet, Reversible
from functools import reduce
from itertools import islice
from types import MappingProxyType

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Collection, Sequence


class Sentinel(enum.Enum):
    """Class for typing parameters with a sentinel as a default"""
    SENTINEL = -1


SENTINEL = Sentinel.SENTINEL


def reverse_enumerate[T](lst: Sequence[T]) -> Iterator[tuple[int, T]]:
    """Like enumerate but in the other direction

    Usage::

        >>> a = ['a', 'b', 'c']
        >>> it = reverse_enumerate(a)
        >>> it.next()
        (2, 'c')
        >>> it.next()
        (1, 'b')
        >>> it.next()
        (0, 'a')
        >>> it.next()
        Traceback (most recent call last):
          File "<stdin>", line 1, in <module>
        StopIteration
    """
    return zip(range(len(lst) - 1, -1, -1), reversed(lst))


def partition[T](pred: Callable[[T], bool], elems: Iterable[T]) -> tuple[list[T], list[T]]:
    """ Return a pair equivalent to:
    ``filter(pred, elems), filter(lambda x: not pred(x), elems)`` """
    yes: list[T] = []
    nos: list[T] = []
    for elem in elems:
        (yes if pred(elem) else nos).append(elem)
    return yes, nos


@typing.overload
def split_every[T](n: int, iterable: Iterable[T]) -> Iterator[tuple[T, ...]]:
    ...


@typing.overload
def split_every[T](n: int, iterable: Iterable[T], piece_maker: type[Collection[T]]) -> Iterator[Collection[T]]:
    ...


@typing.overload
def split_every[T, P](n: int, iterable: Iterable[T], piece_maker: Callable[[Iterable[T]], P]) -> Iterator[P]:
    ...


def split_every[T](n: int, iterable: Iterable[T], piece_maker=tuple):
    """Splits an iterable into length-n pieces. The last piece will be shorter
       if ``n`` does not evenly divide the iterable length.

       :param int n: maximum size of each generated chunk
       :param Iterable iterable: iterable to chunk into pieces
       :param piece_maker: callable taking an iterable and collecting each
                           chunk from its slice, *must consume the entire slice*.
    """
    iterator = iter(iterable)
    piece = piece_maker(islice(iterator, n))
    while piece:
        yield piece
        piece = piece_maker(islice(iterator, n))


class ConstantMapping[T](Mapping[typing.Any, T]):
    """
    An immutable mapping returning the provided value for every single key.

    Useful for default value to methods
    """
    __slots__ = ['_value']

    def __init__(self, val: T):
        self._value = val

    def __len__(self):
        """
        defaultdict updates its length for each individually requested key, is
        that really useful?
        """
        return 0

    def __iter__(self):
        """
        same as len, defaultdict updates its iterable keyset with each key
        requested, is there a point for this?
        """
        return iter([])

    def __getitem__(self, item) -> T:
        return self._value


def freehash(arg: typing.Any) -> int:
    try:
        return hash(arg)
    except Exception:
        if isinstance(arg, Mapping):
            return hash(frozendict(arg))
        elif isinstance(arg, Iterable):
            return hash(frozenset(freehash(item) for item in arg))
        else:
            return id(arg)


def clean_context(context: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """ This function take a dictionary and remove each entry with its key
    starting with ``default_``
    """
    return {k: v for k, v in context.items() if not k.startswith('default_')}


class Collector[K, T](dict[K, tuple[T, ...]]):  # noqa: FURB189
    """ A mapping from keys to tuples.  This implements a relation, and can be
        seen as a space optimization for ``defaultdict(tuple)``.
    """
    __slots__ = ()

    def __getitem__(self, key: K) -> tuple[T, ...]:
        return self.get(key, ())

    def __setitem__(self, key: K, val: Iterable[T]):
        val = tuple(val)
        if val:
            super().__setitem__(key, val)
        else:
            super().pop(key, None)

    def add(self, key: K, val: T):
        vals = self[key]
        if val not in vals:
            self[key] = vals + (val,)

    def discard_keys_and_values(self, excludes: Collection[K | T]) -> None:
        for key in excludes:
            self.pop(key, None)  # type: ignore
        for key, vals in list(self.items()):
            self[key] = tuple(val for val in vals if val not in excludes)  # type: ignore


class StackMap[K, T](MutableMapping[K, T]):
    """ A stack of mappings behaving as a single mapping, and used to implement
        nested scopes. The lookups search the stack from top to bottom, and
        returns the first value found. Mutable operations modify the topmost
        mapping only.
    """
    __slots__ = ['_maps']

    def __init__(self, m: MutableMapping[K, T] | None = None):
        self._maps = [] if m is None else [m]

    def __getitem__(self, key: K) -> T:
        for mapping in reversed(self._maps):
            try:
                return mapping[key]
            except KeyError:
                pass
        raise KeyError(key)

    def __setitem__(self, key: K, val: T):
        self._maps[-1][key] = val

    def __delitem__(self, key: K):
        del self._maps[-1][key]

    def __iter__(self) -> Iterator[K]:
        return iter({key for mapping in self._maps for key in mapping})

    def __len__(self) -> int:
        return sum(1 for key in self)

    def __str__(self) -> str:
        return f"<StackMap {self._maps}>"

    def pushmap(self, m: MutableMapping[K, T] | None = None):
        self._maps.append({} if m is None else m)

    def popmap(self) -> MutableMapping[K, T]:
        return self._maps.pop()


class LazyDict[K, T](dict[K, T]):
    """A kind of `defaultdict` where the function accepts the key."""
    def __init__(self, func: Callable[[K], T]):
        super().__init__()
        self._func = func

    def __missing__(self, k: K) -> T:
        v = self._func(k)
        self[k] = v
        return v


class OrderedSet[T](MutableSet[T]):
    """ A set collection that remembers the elements first insertion order. """
    __slots__ = ['_map']

    def __init__(self, elems: Iterable[T] = ()):
        self._map: dict[T, None] = dict.fromkeys(elems)

    def __contains__(self, elem):
        return elem in self._map

    def __iter__(self):
        return iter(self._map)

    def __reversed__(self):
        return reversed(self._map)

    def __len__(self):
        return len(self._map)

    def __and__(self, other):
        # preserve order of this set
        if not isinstance(other, Iterable):
            return NotImplemented
        other = set(other)
        return self._from_iterable(value for value in self if value in other)

    def add(self, elem):
        self._map[elem] = None

    def discard(self, elem):
        self._map.pop(elem, None)

    def update(self, elems):
        self._map.update(zip(elems, itertools.repeat(None)))

    def difference_update(self, elems):
        for elem in elems:
            self.discard(elem)

    def __repr__(self):
        return f'{type(self).__name__}({list(self)!r})'

    def intersection(self, *others):
        return reduce(OrderedSet.__and__, others, self)

    def copy(self):
        new_set = OrderedSet()
        new_set._map = self._map.copy()  # Atomic dict copy
        return new_set


class LastOrderedSet[T](OrderedSet[T]):
    """ A set collection that remembers the elements last insertion order. """
    def add(self, elem):
        self.discard(elem)
        super().add(elem)

    def copy(self):
        new_set = LastOrderedSet()
        new_set._map = self._map.copy()  # Atomic dict copy
        return new_set


class Callbacks:
    """ A simple queue of callback functions.  Upon run, every function is
    called (in addition order), and the queue is emptied.

    ::

        callbacks = Callbacks()

        # add foo
        def foo():
            print("foo")

        callbacks.add(foo)

        # add bar
        callbacks.add
        def bar():
            print("bar")

        # add foo again
        callbacks.add(foo)

        # call foo(), bar(), foo(), then clear the callback queue
        callbacks.run()

    The queue also provides a ``data`` dictionary, that may be freely used to
    store anything, but is mostly aimed at aggregating data for callbacks.  The
    dictionary is automatically cleared by ``run()`` once all callback functions
    have been called.

    ::

        # register foo to process aggregated data
        @callbacks.add
        def foo():
            print(sum(callbacks.data['foo']))

        callbacks.data.setdefault('foo', []).append(1)
        ...
        callbacks.data.setdefault('foo', []).append(2)
        ...
        callbacks.data.setdefault('foo', []).append(3)

        # call foo(), which prints 6
        callbacks.run()

    Given the global nature of ``data``, the keys should identify in a unique
    way the data being stored.  It is recommended to use strings with a
    structure like ``"{module}.{feature}"``.
    """
    __slots__ = ['_funcs', 'data']

    def __init__(self):
        self._funcs: collections.deque[Callable] = collections.deque()
        self.data = {}

    def add(self, func: Callable) -> None:
        """ Add the given function. """
        self._funcs.append(func)

    def run(self) -> None:
        """ Call all the functions (in addition order), then clear associated data.
        """
        while self._funcs:
            func = self._funcs.popleft()
            func()
        self.clear()

    def clear(self) -> None:
        """ Remove all callbacks and data from self. """
        self._funcs.clear()
        self.data.clear()

    def __len__(self) -> int:
        return len(self._funcs)


class ReversedIterable[T](Reversible[T]):
    """ An iterable implementing the reversal of another iterable. """
    __slots__ = ['iterable']

    def __init__(self, iterable: Reversible[T]):
        self.iterable = iterable

    def __iter__(self):
        return reversed(self.iterable)

    def __reversed__(self):
        return iter(self.iterable)


def groupby[K, T](iterable: Iterable[T], key: Callable[[T], K] = lambda arg: arg) -> Iterable[tuple[K, list[T]]]:
    """ Return a collection of pairs ``(key, elements)`` from ``iterable``. The
        ``key`` is a function computing a key value for each element. This
        function is similar to ``itertools.groupby``, but aggregates all
        elements under the same key, not only consecutive elements.
    """
    groups = defaultdict(list)
    for elem in iterable:
        groups[key(elem)].append(elem)
    return groups.items()


def unique[T](it: Iterable[T]) -> Iterator[T]:
    """ "Uniquifier" for the provided iterable: will output each element of
    the iterable once.

    The iterable's elements must be hashahble.

    :param Iterable it:
    :rtype: Iterator
    """
    seen = set()
    for e in it:
        if e not in seen:
            seen.add(e)
            yield e


def submap[K, T](mapping: Mapping[K, T], keys: Iterable[K]) -> Mapping[K, T]:
    """
    Get a filtered copy of the mapping where only some keys are present.

    :param Mapping mapping: the original dict-like structure to filter
    :param Iterable keys: the list of keys to keep
    :return dict: a filtered dict copy of the original mapping
    """
    keys = frozenset(keys)
    return {key: mapping[key] for key in mapping if key in keys}


class Reverse(object):
    """ Wraps a value and reverses its ordering, useful in key functions when
    mixing ascending and descending sort on non-numeric data as the
    ``reverse`` parameter can not do piecemeal reordering.
    """
    __slots__ = ['val']

    def __init__(self, val):
        warnings.warn("Deprecated since 20.0, unused")
        self.val = val

    def __eq__(self, other): return self.val == other.val
    def __ne__(self, other): return self.val != other.val

    def __ge__(self, other): return self.val <= other.val
    def __gt__(self, other): return self.val < other.val
    def __le__(self, other): return self.val >= other.val
    def __lt__(self, other): return self.val > other.val


class _HashDict[K, V](dict[K, V]):
    """ Simple extension of ``dict`` that provides a hash function.
        For the hash to be correct, one should not modify the dict's content.
    """

    __slots__ = ()

    def __hash__(self):
        return hash(frozenset((key, freehash(val)) for key, val in self.items()))


class frozendict[K, V]:
    "Immutable dict."
    def __new__(cls, mapping: Iterable[tuple[K, V]] | Mapping[K, V] = (), /, **kw: V):
        """ Return an immutable copy of a mapping.
            This allows the returned proxy mapping to be hashed.
            The reference to the newly created internal dictionary is not
            accessible, which guarantees immutability
        """
        return MappingProxyType(_HashDict(mapping, **kw))

    def __subclasscheck__(self, subclass):
        assert False, "cannot subclass frozendict"  # not a real class


def ReadonlyDict(mapping=(), /, **kw) -> MappingProxyType:
    warnings.warn(
        "ReadonlyDict is deprecated starting Odoo 20, use frozendict",
        category=DeprecationWarning,
        stacklevel=2,
    )
    return frozendict(mapping, **kw)


class DotDict[T](dict[str, T]):
    """Helper for dot.notation access to dictionary attributes

        E.g.
          foo = DotDict({'bar': False})
          return foo.bar
    """
    def __getattr__(self, attrib) -> DotDict | T | None:
        val = self.get(attrib)
        return DotDict(val) if isinstance(val, dict) else val


def is_list_of(values, type_: type | tuple[type, ...]) -> bool:
    """Return True if the given values is a list / tuple of the given type.

    :param values: The values to check
    :param type_: The type of the elements in the list / tuple
    """
    return isinstance(values, (list, tuple)) and all(isinstance(item, type_) for item in values)


def has_list_types(values, types: tuple[type, ...]) -> bool:
    """Return True if the given values have the same types as
    the one given in argument, in the same order.

    :param values: The values to check
    :param types: The types of the elements in the list / tuple
    """
    return (
        isinstance(values, (list, tuple)) and len(values) == len(types)
        and all(map(isinstance, values, types))
    )
