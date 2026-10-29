"""Triggers of the recomputation: the trigger trees of the fields, and the fields that depend on a field."""

from __future__ import annotations

import typing
from collections import defaultdict
from odoo.tools import OrderedSet
from odoo.tools.func import reset_cached_properties

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator
    from odoo.fields import Field


def get_trigger_tree(self, fields: list[Field], select: Callable[[Field], bool] = bool) -> TriggerTree:
    """ Return the trigger tree to traverse when ``fields`` have been modified.
    The function ``select`` is called on every field to determine which fields
    should be kept in the tree nodes.  This enables to discard some unnecessary
    fields from the tree nodes.
    """
    trees = [
        self.get_field_trigger_tree(field)
        for field in fields
        if field in self._field_triggers
    ]
    return TriggerTree.merge(trees, select)


def get_dependent_fields(self, field: Field) -> Iterator[Field]:
    """ Return an iterable on the fields that depend on ``field``. """
    if field not in self._field_triggers:
        return

    for tree in self.get_field_trigger_tree(field).depth_first():
        yield from tree.root


def _discard_fields(self, fields: list[Field]) -> None:
    """ Discard the given fields from the registry's internal data structures. """
    for f in fields:
        # tests usually don't reload the registry, so when they create
        # custom fields those may not have the entire dependency setup, and
        # may be missing from these maps
        self.field_depends.pop(f, None)
        self.field_depends_context.pop(f, None)
        self.not_null_fields.discard(f)

    # discard fields from all cached properties
    reset_cached_properties(self)
    self.field_setup_dependents.discard_keys_and_values(fields)


def _field_trigger_trees(self) -> dict[Field, TriggerTree]:
    return {}


def get_field_trigger_tree(self, field: Field) -> TriggerTree:
    """ Return the trigger tree of a field by computing it from the transitive
    closure of field triggers.
    """
    try:
        return self._field_trigger_trees[field]
    except KeyError:
        pass

    triggers = self._field_triggers

    if field not in triggers:
        return TriggerTree()

    def transitive_triggers(field, prefix=(), seen=()):
        if field in seen or field not in triggers:
            return
        for path, targets in triggers[field].items():
            full_path = concat(prefix, path)
            yield full_path, targets
            for target in targets:
                yield from transitive_triggers(target, full_path, seen + (field,))

    def concat(seq1, seq2):
        if seq1 and seq2:
            f1, f2 = seq1[-1], seq2[0]
            if (
                f1.type == 'many2one' and f2.type == 'one2many'
                and f1.name == f2.inverse_name
                and f1.model_name == f2.comodel_name
                and f1.comodel_name == f2.model_name
            ):
                return concat(seq1[:-1], seq2[1:])
        return seq1 + seq2

    tree = TriggerTree()
    for path, targets in transitive_triggers(field):
        current = tree
        for label in path:
            current = current.increase(label)
        if current.root:
            assert isinstance(current.root, OrderedSet)
            current.root.update(targets)
        else:
            current.root = OrderedSet(targets)

    self._field_trigger_trees[field] = tree

    return tree


def _field_triggers(self) -> defaultdict[Field, defaultdict[tuple[str, ...], OrderedSet[Field]]]:
    """ Return the field triggers, i.e., the inverse of field dependencies,
    as a dictionary like ``{field: {path: fields}}``, where ``field`` is a
    dependency, ``path`` is a sequence of fields to inverse and ``fields``
    is a collection of fields that depend on ``field``.
    """
    triggers: defaultdict[Field, defaultdict[tuple[str, ...], OrderedSet[Field]]] = defaultdict(lambda: defaultdict(OrderedSet))

    for Model in self.models.values():
        if Model._abstract:
            continue
        for field in Model._fields.values():
            try:
                dependencies = list(field.resolve_depends(self))
            except Exception:
                # dependencies of custom fields may not exist; ignore that case
                if not field.base_field.manual:
                    raise
            else:
                for dependency in dependencies:
                    *path, dep_field = dependency
                    triggers[dep_field][tuple(reversed(path))].add(field)

    return triggers


def _is_modifying_relations(self) -> dict[Field, bool]:
    return {}


def is_modifying_relations(self, field: Field) -> bool:
    """ Return whether ``field`` has dependent fields on some records, and
    that modifying ``field`` might change the dependent records.
    """
    try:
        return self._is_modifying_relations[field]
    except KeyError:
        result = field in self._field_triggers and bool(
            field.relational or self.field_inverses[field] or any(
                dep.relational or self.field_inverses[dep]
                for dep in self.get_dependent_fields(field)
            )
        )
        self._is_modifying_relations[field] = result
        return result


class TriggerTree(dict['Field', 'TriggerTree']):
    """ The triggers of a field F is a tree that contains the fields that
    depend on F, together with the fields to inverse to find out which records
    to recompute.

    For instance, assume that G depends on F, H depends on X.F, I depends on
    W.X.F, and J depends on Y.F. The triggers of F will be the tree:

                                 [G]
                               X/   \\Y
                             [H]     [J]
                           W/
                         [I]

    This tree provides perfect support for the trigger mechanism:
    when F is # modified on records,
     - mark G to recompute on records,
     - mark H to recompute on inverse(X, records),
     - mark I to recompute on inverse(W, inverse(X, records)),
     - mark J to recompute on inverse(Y, records).
    """
    __slots__ = ['root']
    root: Collection[Field]

    # pylint: disable=keyword-arg-before-vararg
    def __init__(self, root: Collection[Field] = (), *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.root = root

    def __bool__(self) -> bool:
        return bool(self.root or len(self))

    def __repr__(self) -> str:
        return f"TriggerTree(root={self.root!r}, {super().__repr__()})"

    def increase(self, key: Field) -> TriggerTree:
        try:
            return self[key]
        except KeyError:
            subtree = self[key] = TriggerTree()
            return subtree

    def depth_first(self) -> Iterator[TriggerTree]:
        yield self
        for subtree in self.values():
            yield from subtree.depth_first()

    @classmethod
    def merge(cls, trees: list[TriggerTree], select: Callable[[Field], bool] = bool) -> TriggerTree:
        """ Merge trigger trees into a single tree. The function ``select`` is
        called on every field to determine which fields should be kept in the
        tree nodes. This enables to discard some fields from the tree nodes.
        """
        root_fields: OrderedSet[Field] = OrderedSet()              # fields in the root node
        subtrees_to_merge = defaultdict(list)   # subtrees to merge grouped by key

        for tree in trees:
            root_fields.update(tree.root)
            for label, subtree in tree.items():
                subtrees_to_merge[label].append(subtree)

        # the root node contains the collected fields for which select is true
        result = cls([field for field in root_fields if select(field)])
        for label, subtrees in subtrees_to_merge.items():
            subtree = cls.merge(subtrees, select)
            if subtree:
                result[label] = subtree

        return result
