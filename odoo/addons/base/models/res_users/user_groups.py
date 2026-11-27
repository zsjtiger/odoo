# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The groups of the users: the default groups, the roles, the implied groups and the checks on the groups."""

from __future__ import annotations

from odoo import _
from odoo.fields import Domain


def _default_groups(self):
    """Default groups for employees

        All the groups of the Default User Group
        """
    groups = self.env.ref('base.group_user')
    default_group = self.env.ref('base.default_user_group', raise_if_not_found=False)
    if default_group:
        groups += default_group.implied_ids
    return groups


def _default_view_group_hierarchy(self):
    return self.env['res.groups']._get_view_group_hierarchy()


def _compute_role(self):
    group_system = self.env.ref('base.group_system', raise_if_not_found=False)
    group_user = self.env.ref('base.group_user', raise_if_not_found=False)

    for user in self:
        # A group is almost never held directly: ``base.group_user`` and the
        # light/regular tier both come from the application groups the user
        # is given, so the role is determined on the implied groups.
        all_groups = user.group_ids._origin.all_implied_ids
        user.role = (
            'group_system' if group_system and group_system in all_groups else
            'light_user' if group_user and group_user in all_groups and all_groups._is_light_groups() else
            'regular_user' if group_user and group_user in all_groups else
            False
        )


def _onchange_role(self):
    group_admin = self.env['res.groups'].new(origin=self.env.ref('base.group_system'))
    group_regular = self.env['res.groups'].new(origin=self.env.ref('base.group_user_regular'))
    group_user = self.env['res.groups'].new(origin=self.env.ref('base.group_user'))

    if self.role == 'regular_user':
        if group_regular not in self.all_group_ids:
            self.group_ids += group_regular
        self.group_ids -= group_admin
    elif self.role == 'group_system':
        self.group_ids += group_admin + group_user
    elif self.role == 'light_user':
        # If set to light user from portal or public user then add default groups
        if group_user not in self.all_group_ids:
            self.group_ids += self._default_groups()
        # Reduce all access to light user.
        self.group_ids = group_user + self.group_ids._origin._reduce_to_light_groups()


def _search_role(self, operator, value):
    if operator != 'in':
        return NotImplemented

    group_definitions = self.env['res.groups']._get_group_definitions()
    light_group_ids = {group_definitions.get_id(xid) for xid in self.env['res.groups']._get_light_group_xmlids()}
    regular_group_ids = set(group_definitions.get_all_ids()) - light_group_ids

    is_system = Domain('all_group_ids', 'in', [self.env.ref('base.group_system').id])
    is_user_regular = Domain('all_group_ids', 'in', regular_group_ids)
    is_user = Domain('all_group_ids', 'in', [self.env.ref('base.group_user').id])
    domains_by_role = {
        'light_user': is_user & ~is_user_regular,
        'regular_user': is_user & is_user_regular & ~is_system,
        'group_system': is_system,
        False: ~is_user,
    }
    return Domain.OR([domains_by_role[v] for v in value if v in domains_by_role])


def _compute_all_group_ids(self):
    for user in self:
        user.all_group_ids = user.group_ids.all_implied_ids


def _search_all_group_ids(self, operator, value):
    if operator in Domain.NEGATIVE_OPERATORS:
        return NotImplemented
    domain = Domain('group_ids.all_implied_ids', operator, value)
    if operator == 'in' and False in value:  # relation may be falsy
        domain |= Domain('group_ids', '=', False)
    return domain


def has_groups(self, group_spec: str) -> bool:
    """ Return whether user ``self`` satisfies the given group restrictions
        ``group_spec``, i.e., whether it is member of at least one of the groups,
        and is not a member of any of the groups preceded by ``!``.

        Note that the group ``"base.group_no_one"`` is only effective in debug
        mode, just like method :meth:`~.has_group` does.

        :param str group_spec: comma-separated list of fully-qualified group
            external IDs, optionally preceded by ``!``.
            Example:``"base.group_user,base.group_portal,!base.group_system"``.
        """
    if group_spec == '.':
        return False

    positives = []
    negatives = []
    for group_ext_id in group_spec.split(','):
        group_ext_id = group_ext_id.strip()
        if group_ext_id.startswith('!'):
            negatives.append(group_ext_id[1:])
        else:
            positives.append(group_ext_id)

    # for the sake of performance, check negatives first
    if any(self.has_group(ext_id) for ext_id in negatives):
        return False
    if any(self.has_group(ext_id) for ext_id in positives):
        return True
    return not positives


def _has_group(self, group_ext_id: str) -> bool:
    """ Return whether user ``self`` belongs to the given group.

        :param str group_ext_id: external ID (XML ID) of the group.
           Must be provided in fully-qualified form (``module.ext_id``), as there
           is no implicit module to use..
        :return: True if user ``self`` is a member of the group with the
           given external ID (XML ID), else False.
        """
    group_id = self.env['res.groups']._get_group_definitions().get_id(group_ext_id)
    # for new record don't fill the ormcache
    return group_id in (self._get_group_ids() if self.id else self.all_group_ids._origin._ids)


def _get_group_ids(self):
    """ Return ``self``'s group ids (as a tuple)."""
    self.ensure_one()
    # `with_context({})` because this method is decorated with `@ormcache('self._ids')`,
    # it cannot depend on the context (e.g. `active_test`, `lang`, ...)
    return self.with_context({}).all_group_ids._ids


def _action_show(self):
    """Directly access the form view"""
    return {
        'type': 'ir.actions.act_window',
        'res_model': 'res.users',
        'context': {'create': False},
        'name': _('Users'),
        'view_mode': 'form',
        'views': [[self.env.ref('base.view_users_form').id, 'form']],
        'domain': [('id', 'in', self.ids)],
    }


def action_show_groups(self):
    self.ensure_one()
    return {
        'name': _('Groups'),
        'view_mode': 'list,form',
        'res_model': 'res.groups',
        'type': 'ir.actions.act_window',
        'context': {'create': False, 'delete': False},
        'domain': [('id', 'in', self.all_group_ids.ids)],
        'target': 'current',
    }


def action_show_accesses(self):
    self.ensure_one()
    return {
        'name': _('Access Rights'),
        'view_mode': 'list,form',
        'res_model': 'ir.access',
        'type': 'ir.actions.act_window',
        'context': {'create': False, 'delete': False},
        'domain': [('group_id', 'in', self.all_group_ids.ids)],
        'target': 'current',
    }
