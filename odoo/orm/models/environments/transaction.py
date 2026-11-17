"""The transactions of the cursors: the environments of a transaction, the caches, the signaling of the registry, and the commits and rollbacks."""

from __future__ import annotations

import inspect
import logging
import typing
from collections import defaultdict, deque
from collections.abc import MutableMapping
from contextlib import contextmanager, nullcontext
from weakref import ref as weakref
from odoo.orm.database.sql_db import BaseCursor
from odoo.tools import reset_cached_properties, OrderedSet
from odoo.tools.func import deprecated
from odoo.tools.lru import LRU
from odoo.tools.misc import StackMap
from odoo.orm.models.registry import _CACHES_BY_KEY, _REGISTRY_CACHES, Registry

if typing.TYPE_CHECKING:
    from weakref import ReferenceType
    from odoo.orm.core.identifiers import IdType
    from odoo.orm.core.types import Field

from .caches import Cache, CacheLayer

_logger = logging.getLogger('odoo.api')


_logger_signaling = logging.getLogger('odoo.registry')


ENVS_SIZE = 20  # used as a reference size in a transaction's environments


class Transaction:
    """ A object holding ORM data structures for a transaction.

    Signaling summary:

    - Creating the first `Environment` for a cursor triggers checks signaling.
    - `cr.commit` signals changes and resets the transaction.
    - `cr.rollback` resets the transaction without signaling.
    - Resetting a transaction checks signaling unless we are closing the
      cursor and won't be using the transaction anymore.

    Notes:

    - `transaction.will_change_registry()` before modifying registry
    - `Registry.new` should be followed by `cr.rollback()`.

    """
    __slots__ = (
        '_Transaction__file_open_tmp_paths',
        '_cache', '_recent_envs',
        '_registry_caches__', '_registry_invalidated', '_registry_sequence',
        '_state_stack__', '_weak_envs', '_wrote__',
        'access_read', 'default_env',
        'field_data', 'field_data_patches', 'field_dirty',
        'ormcaches__', 'protected', 'registry', 'tocompute',
    )

    def __init__(self, registry: Registry):
        self.registry = registry
        # recently used environments (maximum 2 * ENVS_SIZE)
        self._recent_envs: deque[Environment] = deque()
        # all environments in order of creation (weak)
        self._weak_envs: list[ReferenceType[Environment]] = []

        # default environment (for flushing)
        self.default_env: Environment | None = None
        self._registry_invalidated: int = 0
        self._registry_sequence = registry.registry_sequence
        # detecting the point from where we started, copy of what is on the Registry
        self._registry_caches__: dict[str, tuple[int, MutableMapping]] = {}
        # current ormcache data for the transaction
        self.ormcaches__: dict[str, CacheLayer] = {}
        # transaction state manipulated by savepoints
        self._state_stack__: list[TransactionState] = []
        # indicates whether updates were done in this transaction,
        # if so, rollback should not update the parent ormcache
        self._wrote__: bool = False
        # There is always one more ormcache layer than the number of state
        # stacks. Therefore the parent of a cache layer when the state stack is
        # empty is the mapping referenced in registry_caches unless that cache
        # has been invalidated.

        # cache data {field: cache_data_managed_by_field} often uses a dict
        # to store a mapping from id to a value, but fields may use this field
        # however they need
        self.field_data = defaultdict["Field", typing.Any](dict)
        # {field: set[id]} stores the fields and ids that are changed in the
        # cache, but not yet written in the database; their changed values are
        # in `data`
        self.field_dirty = defaultdict["Field", OrderedSet["IdType"]](OrderedSet)
        # {field: {record_id: ids}} record ids to be added to the values of
        # x2many fields if they are not in cache yet
        self.field_data_patches = defaultdict["Field", defaultdict["IdType", list["IdType"]]](lambda: defaultdict(list))
        # fields to protect {field: ids}
        self.protected = StackMap["Field", OrderedSet["IdType"]]()
        # pending computations {field: ids}
        self.tocompute = defaultdict["Field", OrderedSet["IdType"]](OrderedSet)
        # backward-compatible view of the cache
        self._cache = Cache(self)

        # permission cache for record access by user
        # {access_context: {model_name: {record_id: bool}}}
        self.access_read = defaultdict[tuple, defaultdict[str, dict["IdType", bool]]](lambda: defaultdict(dict))
        # temporary directories (managed in odoo.tools.file_open_temporary_directory)
        self.__file_open_tmp_paths = []  # type: ignore # noqa: PLE0237

    @property
    def cache(self):
        import warnings  # noqa: PLC0415
        warnings.warn("Since 20.0 use fields method directly for cache manipulation", DeprecationWarning, stacklevel=2)
        return self._cache

    @property
    def envs(self):
        for ref in self._weak_envs:
            if env := ref():
                yield env

    def lookup_env(self, uid: int, context: dict, su: bool) -> Environment | None:
        """ Return the environment that matches the given parameters, or ``None`` if not found. """
        recent_envs = self._recent_envs
        # Look up in recently accessed environments first
        for env_index, env in enumerate(recent_envs):
            if env.uid == uid and env.su == su and env.context == context:
                # move env first for faster access next time
                if env_index > 0:
                    del recent_envs[env_index]
                    recent_envs.appendleft(env)
                return env

        if len(self._weak_envs) <= len(recent_envs):
            return None

        # Check only the oldest environments, as they were probably created by
        # the original transaction, and we don't want to scan too many of them.
        for env_index, ref in enumerate(self._weak_envs):
            env = ref()
            if env is None:
                continue
            if env.uid == uid and env.su == su and env.context == context:
                # add to recent envs for faster access next time
                recent_envs.appendleft(env)
                if len(recent_envs) > ENVS_SIZE * 2:
                    self.compactify_envs()
                return env
            if env_index > ENVS_SIZE:
                break

        return None

    def add_env(self, env: Environment):
        """ Add ``env`` to the environments known by the transaction. """
        self._recent_envs.appendleft(env)
        self._weak_envs.append(weakref(env))
        # the default transaction's environment is the first one with a valid uid
        if self.default_env is None and env.uid and isinstance(env.uid, int):
            self.default_env = env
        # avoid filling the system with environments
        if len(self._recent_envs) > ENVS_SIZE * 2:
            self.compactify_envs()

    def compactify_envs(self) -> None:
        """ Deallocate environments to which nobody has a reference. """
        # Start by moving environments from the environment to a weak set.
        # Here cpython will start freeing environments that are only weakly
        # referenced because of reference counting.
        while len(self._recent_envs) > ENVS_SIZE:
            self._recent_envs.pop()

        ref_list = self._weak_envs
        if len(ref_list) <= ENVS_SIZE:
            return

        ref_list = [ref for ref in ref_list if ref() is not None]  # compactify

        # The following are heuristics to reduce the number of environments.
        # We call these only when the execution time can be bounded and give up
        # if the code references too many environments.
        if ENVS_SIZE * 3 <= len(ref_list) < ENVS_SIZE * 4:
            # Force a small GC run to remove environments that are in a
            # reference cycle. This includes, among others, the attributes
            # env.company and env.companies (that refers to env) and env.user
            # (that refers to env(su=True)).
            import gc  # noqa: PLC0415
            gc.collect(0)
            ref_list = [ref for ref in ref_list if ref() is not None]  # compactify

        if len(ref_list) > ENVS_SIZE * 10:
            _logger.debug("Creating too many environments: %d", len(ref_list))
        # Move back the environments to the queue
        self._weak_envs = ref_list

    def flush(self) -> None:
        """ Flush pending computations and updates in the transaction. """
        if self.default_env is not None:
            self.default_env.flush_all()
        else:
            for env in self.envs:
                _logger.warning("Missing default_env, flushing as public user")
                public_user = env.ref('base.public_user')
                Environment(env.cr, public_user.id, {}).flush_all()
                break

    def _check_signaling(self, cr: BaseCursor) -> None:
        """ Check the sequences in the database an invalidate accordingly.

        When the registry changed, create a new registry and rebind to it.
        Otherwise, invalidate named caches and their dependencies.
        """
        assert not self._registry_caches__, "Cannot check in the middle of a transaction"
        registry = self.registry
        with registry.registry_cache_lock:
            self._registry_caches__ = registry.registry_caches__.copy()
        for name, (seq, data) in self._registry_caches__.items():
            self.ormcaches__[name] = CacheLayer(data)
        if not registry.ready:
            _logger_signaling.debug("Skip signaling check, registry not ready")
            return

        db_registry_sequence, db_cache_sequences = registry.get_sequences(cr)
        changes = ''
        # Check if the model registry must be reloaded
        registry_sequence = registry.registry_sequence
        if registry_sequence != db_registry_sequence:
            _logger_signaling.info("Reloading the model registry after database signaling.")
            self.registry = registry = Registry.new(registry.db_name)
            self._registry_caches__ = registry.registry_caches__.copy()
            for name, (seq, data) in self._registry_caches__.items():
                self.ormcaches__[name] = CacheLayer(data)
            if _logger_signaling.isEnabledFor(logging.DEBUG):
                changes += "[Registry - %s -> %s]" % (registry_sequence, db_registry_sequence)
            # rebind all environments to the new registry
            self.clear()
        # Check if the model caches must be invalidated.
        else:
            invalidated = set()
            registry_caches = self._registry_caches__
            for cache_name, expected_sequence in db_cache_sequences.items():
                cache_sequence = registry_caches[cache_name][0]
                if cache_sequence == expected_sequence:
                    continue
                data = LRU(_REGISTRY_CACHES[cache_name])
                registry.registry_caches__[cache_name] = registry_caches[cache_name] = (expected_sequence, data)
                self.ormcaches__[cache_name] = CacheLayer(data)
                for name in _CACHES_BY_KEY[cache_name]:
                    if '.' in name:
                        data = LRU(_REGISTRY_CACHES[name])
                        registry.registry_caches__[name] = registry_caches[name] = (registry_caches[name][0] + 1, data)
                        self.ormcaches__[name] = CacheLayer(data)
                    invalidated.add(name)
                if _logger_signaling.isEnabledFor(logging.DEBUG):
                    changes += "[Cache %s - %s -> %s]" % (cache_name, cache_sequence, expected_sequence)
            if invalidated:
                _logger_signaling.info("Invalidating caches after database signaling: %s", sorted(invalidated))
        if changes:
            _logger_signaling.debug("Multiprocess signaling check: %s", changes)

    def will_change_registry(self) -> None:
        """ Invalidate the current registry.

        Note: registry changes are not thread-safe.
        """
        self._registry_invalidated += 1

    def _reset_registry_change(self):
        """ When the registry was invalidated, re-setup models. """
        assert not self.field_data, "Transaction must be cleared"
        env = self.default_env or next(iter(self.envs), None)
        if env is None:
            raise RuntimeError("resetting registry changes, but no cursor found!")
        cr = env.cr

        # retrieve the latest registry sequence to avoid recreating the
        # registry while checking signaling
        registry = self.registry
        new_sequence, _caches = registry.get_sequences(cr)
        # if we are executing post-rollback and the registry sequence changed,
        # skip resetup of the registry, a new one will be created
        if cr._closing and registry.registry_sequence != new_sequence:
            return
        registry.registry_sequence = self._registry_sequence = new_sequence
        registry._setup_models__(cr)
        self._registry_invalidated = 0  # mark transaction with valid registry

    def invalidate_ormcache(self, cache_name: str = 'default') -> None:
        """ Clear the caches associated to methods decorated with
        ``api.ormcache`` if cache is in `cache_name` subset. """
        assert '.' not in cache_name

        if _logger_signaling.isEnabledFor(logging.DEBUG):
            # log information about invalidation_cause
            # could be interresting to log in info but this will need to minimize invalidation first,
            # mainly in some setupclass and crons
            frame = inspect.currentframe().f_back
            code = frame.f_code
            frame_self = frame.f_locals.get('self')
            frame_str = f'{code.co_filename}:{frame.f_lineno} ({type(frame_self)})'
            _logger_signaling.debug('Invalidating %r model cache from %s', cache_name, frame_str)

        for name in _CACHES_BY_KEY.get(cache_name, ()):
            self.ormcaches__[name] = CacheLayer(None)

    @deprecated("Since 20.0, renamed to invalidate_access_cache")
    def clear_access_cache(self, model_name: str = '') -> None:
        self.invalidate_access_cache(model_name)

    def invalidate_access_cache(self, model_name: str = '') -> None:
        """ Clear the access cache for record rule checks. """
        # clear each context separately because it is cached in Environment
        for context_dict in self.access_read.values():
            if model_name:
                context_dict.pop(model_name, None)
            else:
                context_dict.clear()
        self._wrote__ = True  # assume we wrote something

    def invalidate_field_data(self) -> None:
        """ Invalidate the cache of all the fields.

        This operation is unsafe by default, and must be used with care.
        Indeed, invalidating a dirty field on a record may lead to an error,
        because doing so drops the value to be written in database.
        """
        self.field_data.clear()
        # reset Field._get_cache()
        for env in self.envs:
            env.__dict__.pop('_field_cache_memo', None)
        self._wrote__ = True  # assume we wrote something

    def clear(self):
        """ Clear the transaction data (for testing or internal).

        Clear the caches and pending computations, access and updates in the
        transaction and linked environments.
        """
        self.access_read.clear()  # faster invalidate_access_cache
        self.invalidate_field_data()
        self.field_data_patches.clear()
        self.field_dirty.clear()
        self.tocompute.clear()
        self._recent_envs.clear()
        self.compactify_envs()
        env = None
        for env in self.envs:
            reset_cached_properties(env)
        if env is not None:
            # all envs of the transaction share the same cursor
            env.cr.cache.clear()

    def reset(self) -> None:
        """ Reset the transaction.

        This is performed automatically after a commit or rollback!

        This clears the transaction, and reassigns the registry on all its
        environments. Use it *only after a commit or rollback* when the registry
        may have changed!
        """
        # get the registry and rebuild the stack of states
        new_registry = Registry(self.registry.db_name)
        if self.registry is new_registry:
            if self._registry_invalidated:
                self.clear()  # clear existing data if any
                self._reset_registry_change()
        else:
            self.registry = new_registry
            self._registry_invalidated = 0
        # the registry sequence can change during testing, always copy it
        self._registry_sequence = self.registry.registry_sequence
        self._state_stack__ = [
            TransactionState(
                default_env=state.default_env,
                ormcaches__=state.ormcaches__,
                registry_invalidated=self._registry_invalidated,
                registry_sequence=self._registry_sequence,
            ) for state in self._state_stack__]

        self.clear()

        # recheck signaling for the ormcache
        env = self.default_env or next(iter(self.envs), None)
        if env is not None and not env.cr._closing:
            self._registry_caches__.clear()
            self._check_signaling(env.cr)

    @contextmanager
    def committing(self):
        """ Context for committing the connection. """
        assert not self._state_stack__, "Pending savepoints not released, cannot commit!"
        registry = self.registry
        env = self.default_env or next(iter(self.envs), None)
        if env is None:
            _logger_signaling.debug("no cursor to flush signaling", stack_info=True)
            self.flush()
            yield
            for layer in self.ormcaches__.values():
                layer.update_parent()
            self.reset()
            return
        cr = env.cr
        cr.flush()  # flush remaining changes

        # Signal changes
        push_caches = {}
        names = set()
        if self._registry_invalidated:
            names.add('registry')
        for name, (seq, _registry_data) in self._registry_caches__.items():
            layer = self.ormcaches__[name]
            if layer.parent is not None:
                continue  # not invalidated
            if name in _CACHES_BY_KEY:
                names.add(name)
            layer.parent = LRU(_REGISTRY_CACHES[name])
            push_caches[name] = (seq + 1, layer.parent)

        # Propagate the cache to the registry after the commit.
        # We lock the registry so that another transaction cannot start checking
        # signaling between the commit and the push of the caches.
        if self._registry_invalidated:
            lock = registry._lock
        elif push_caches:
            lock = registry.registry_cache_lock
        else:
            lock = nullcontext()
        with lock:
            # signal changes just before committing to consume the sequence as late as possible
            registry._signal_changes(cr, names)
            # commit
            yield

            # Update caches
            registry.registry_caches__.update(push_caches)
            for layer in self.ormcaches__.values():
                layer.update_parent()

            # Skip resetting the registry because the transaction should leave
            # the registry in a correct state. Don't increment the sequence on
            # the registry to let the system cleanly setup the registry and
            # avoid potential memory leaks that may not be handled correctly by
            # the transaction.
            self._registry_invalidated = 0
            self.reset()
            if registry._lock is lock and cr._closing:
                # We are closing, reset() did not check signaling, force it so
                # that the next transaction is ready.
                self._registry_caches__.clear()
                self._check_signaling(cr)
        self._wrote__ = False

    @contextmanager
    def rollbacking(self):
        """ Context for rollbacking the connection. """
        assert not self._state_stack__, "Pending savepoints not released, cannot rollback!"
        yield
        self.restore_state()
        self._wrote__ = False

    def _free_resources(self) -> None:
        """ Free resources used by the transaction."""
        self.default_env = None  # break the cyclic reference
        self._recent_envs.clear()
        self._registry_caches__ = None
        self.ormcaches__ = None

    def save_state(self):
        """ Save the current state of the transaction for future restore. """
        self.flush()
        self._state_stack__.append(TransactionState(
            default_env=self.default_env,
            ormcaches__=self.ormcaches__,
            registry_invalidated=self._registry_invalidated,
            registry_sequence=self._registry_sequence,
        ))
        # create a new layer for the cache
        self.ormcaches__ = {
            name: CacheLayer(data)
            for name, data in self.ormcaches__.items()
        }

    def merge_state(self):
        """ Merge current state into the last saved state. """
        assert self._state_stack__, "no state to pop"
        state = self._state_stack__.pop()

        # merge into the parent layer
        for name, layer in self.ormcaches__.items():
            if layer.parent is None:
                # now, the parent layer invalidates the cache
                layer.parent = state.ormcaches__[name] = CacheLayer(None)
            layer.update_parent()
        self.ormcaches__ = state.ormcaches__

    def restore_state(self):
        """ Restore the previously saved state of the transaction after
        rollback execution (on savepoint or connection). """
        if self._state_stack__:
            state = self._state_stack__[-1]
            self.default_env = state.default_env
            parent_ormcaches = state.ormcaches__
            registry_invalidated = state.registry_invalidated
        else:
            parent_ormcaches = {
                name: data
                for name, (_seq, data) in self._registry_caches__.items()
            }
            registry_invalidated = 0

        if not self._wrote__:
            # if we rollback on a transaction that did not write anything, we
            # can still push the cached values to the parent layer
            for layer in self.ormcaches__.values():
                layer.update_parent()

        env = self.default_env or next(iter(self.envs), None)
        cr = env.cr if env is not None else None
        if (cr is None or not cr._closing or cr.postrollback) and (not self._state_stack__ or self.registry.registry_sequence != self._registry_sequence):
            # registry changed or rollback, reset the transaction
            self.reset()
            self._registry_invalidated = registry_invalidated
            return

        self.clear()
        self.ormcaches__ = {
            name: CacheLayer(data)
            for name, data in parent_ormcaches.items()
        }
        if self._registry_invalidated and self._registry_invalidated != registry_invalidated:
            self._reset_registry_change()
        self._registry_invalidated = registry_invalidated


class TransactionState(typing.NamedTuple):
    """ The state of the transaction that can be stacked for savepoint operations. """
    default_env: Environment | None
    ormcaches__: dict[str, CacheLayer]
    registry_invalidated: int
    registry_sequence: int


# imported at the end: the module of the other side imports this one
from .environment import Environment
