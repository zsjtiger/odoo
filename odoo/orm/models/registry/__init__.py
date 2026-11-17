# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The registry of the models, split by concern: the base registry, the setup of the models, the triggers of the recomputation, the schema and the signaling. The names are re-exported here."""

from .base import Registry, _CACHES_BY_KEY, _REGISTRY_CACHES, _REPLICA_RETRY_TIME, _logger, _schema, _unaccent
from .triggers import TriggerTree, _discard_fields, _field_trigger_trees, _field_triggers, _is_modifying_relations, get_dependent_fields, get_field_trigger_tree, get_trigger_tree, is_modifying_relations
