# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Access rights of the records and of their fields.

The methods of :class:`~odoo.orm.models.BaseModel` with the same names delegate
to the functions of this module. The hooks that addons may override are still
called as methods of the records (``records._access_domain``,
``records._has_field_access``), so the overrides keep working.
"""
import itertools
import logging
import typing

from odoo.exceptions import AccessError, MissingError
from odoo.tools import unique
from odoo.tools.safe_eval import safe_eval
from odoo.tools.text.translate import _

from odoo.orm.core.domains import Domain
from odoo.orm.fields import Field
from odoo.orm.core.identifiers import IdType

# the logger keeps the name of the former location, so the configuration of the logs is unchanged
_logger = logging.getLogger('odoo.orm.models')

# hacky-ish way to prevent access to a field through the ORM (except for sudo mode)
NO_ACCESS = '.'


def check_access(records, operation: str) -> None:
    """ Verify that the current user is allowed to perform ``operation`` on
    all the records in ``records``. The method raises an :class:`AccessError`
    if the operation is forbidden on the model in general, or on any record
    in ``records``.

    In particular, when ``records`` is empty, the method checks whether the
    current user has some permission to perform ``operation`` on the model
    in general::

        # check that user has some minimal permission on the model
        records.browse().check_access(operation)

    """
    if records.has_access(operation):
        return
    inaccessible = records - filtered_access(records, operation)
    domain = records._access_domain(operation)
    raise inaccessible._make_access_error_message(operation, domain)


def has_access(records, operation: str) -> bool:
    """ Return whether the current user is allowed to perform ``operation``
    on all the records in ``records``. The method is fully consistent with
    method :meth:`check_access` but returns a boolean instead.
    """
    if records.env.su:
        return True

    origin = records._origin
    # check the records for read access
    if operation == 'read' and origin:
        access = records.env._access_cache[records._name]
        if all(map(access.get, origin._ids)):
            return True
        domain = records._access_domain(operation)
        fill_access_cache(origin, access, domain)
        return all(map(access.__getitem__, origin._ids))

    # resolve the 'access' operator if just checking model access
    # so that a rule `('order_id', 'access', 'read')` may become false
    if not origin:
        if operation == 'read':
            access = records.env._access_cache[records._name]
            if isinstance(result := access.get(0), bool):
                return result
        domain = records._access_domain(operation)
        domain = domain.map_conditions(
            lambda cond: cond.optimize_dynamic(records.sudo()) if cond.operator == 'access' else cond)
        result = not domain.is_false()
        if operation == 'read':
            access[0] = result
        return result

    # check the records for other access
    domain = records._access_domain(operation)
    if domain.is_false():
        return False
    if domain.is_true():
        return True
    return origin == origin.sudo().with_context(active_test=False).filtered_domain(domain)


def filtered_access(records, operation: str) -> typing.Self:
    """ Return the subset of ``records`` for which the current user is allowed
    to perform ``operation``. The method is fully equivalent to::

        records.filtered(lambda record: record.has_access(operation))

    """
    if records.env.su or not records:  # su or empty
        return records

    origin = records._origin
    if operation == 'read' and origin:
        access = records.env._access_cache[records._name]
        if all(map(access.get, origin._ids)):
            return records
        domain = records._access_domain(operation)
        fill_access_cache(origin, access, domain)
        if domain.is_true():
            return records
        if domain.is_false():
            return records.browse()
        if origin is not records:  # we have some new ids
            return records.filtered(lambda rec: not (id_ := rec._origin.id) or access.get(id_))
        return records.filtered(lambda rec: access[rec._ids[0]])

    domain = records._access_domain(operation)
    if domain.is_false():
        return records.browse()
    if not origin or domain.is_true():
        return records
    accessible = origin.sudo().with_context(active_test=False).filtered_domain(domain).with_env(records.env)
    if origin is not records:  # we have some new ids
        accessible_ids = {False, *accessible._ids}
        return records.filtered(lambda rec: rec._origin.id in accessible_ids)
    return accessible


def fill_access_cache(records, access: dict[IdType, bool], domain: Domain) -> None:
    """ Fill the access cache for records in records. """
    ids = records._ids

    # Select records:
    # We get unknown ids and recheck forbidden ids.  If we have a small
    # number of ids, we only add unknown records from the prefetch to check
    # access in batch.
    # We want to avoid rechecking *all* the prefetch every time we have an
    # inaccessible record.
    ids_to_check = tuple(id_ for id_ in unique(itertools.chain(ids, records._prefetch_ids)) if not access.get(id_))
    records = records.browse(ids_to_check).sudo().with_context(active_test=False)

    # Check access
    try:
        accessible = records.filtered_domain(domain)
    except MissingError:
        existing = records.exists()
        missing_ids = set(records._ids) - set(existing._ids)
        if not missing_ids.isdisjoint(ids):
            # raise if initial ids intersect with missing ids
            raise
        records = existing
        accessible = records.filtered_domain(domain)

    # Update the cache
    if len(accessible) == len(records):
        access.update(dict.fromkeys(records._ids, True))
    else:
        accessible_ids = set(accessible._ids)
        for id_ in records._ids:
            access[id_] = id_ in accessible_ids


def access_domain(records, operation: str) -> Domain:
    """Get the security domain for the given operation.

    Return the domain that determines on which records of this model
    the current user is allowed to perform ``operation``.  The domain comes
    from the permissions and restrictions that apply to the current user.
    """
    from odoo.addons.base.models.ir_access import IN_SELECTION  # noqa: PLC0415

    assert operation in IN_SELECTION, (
        f"Invalid access operation {operation!r} "
        f"(expected {', '.join(map(repr, IN_SELECTION))})"
    )
    operations = IN_SELECTION[operation]

    # collect permissions and restrictions
    permissions = []
    restrictions = []

    # add access for parent models as restrictions
    if records._check_inherits_access:
        for parent_model_name, parent_field_name in records._inherits.items():
            domain = records.env[parent_model_name]._access_domain(operation)
            if domain.is_false():
                return Domain.FALSE
            restrictions.append(Domain(parent_field_name, 'any', domain))

    IrAccess = records.env['ir.access']
    # include False in user groups to catch global rules
    group_ids = {*records.env.user._get_group_ids(), False}
    # some domains have been pre-evaluated, evaluate only if needed
    eval_context = None
    for access in IrAccess._get_all_access().get(records._name, ()):
        if access.operation in operations and access.group_id in group_ids:
            domain = access.domain
            if not isinstance(domain, Domain):
                if eval_context is None:
                    eval_context = IrAccess._eval_context()
                domain = Domain(safe_eval(domain, eval_context))
            if access.group_id:
                permissions.append(domain)
            else:
                restrictions.append(domain)

    return Domain.OR(permissions) & Domain.AND(restrictions)


def has_field_access(records, field: Field, operation: typing.Literal['read', 'write']) -> bool:
    """ Determine whether the user access rights on the given field for the given operation.

    :param field: the field to check
    :param operation: one of ``read``, ``write``
    :return: whether the field is accessible
    """
    if operation == 'read':
        env = records.env
        memo = env._field_access_memo
        if env.su or field in memo:
            return True
        if records._has_field_access(field, 'read'):
            memo.add(field)
            return True
        return False
    return records._has_field_access(field, operation)


def check_field_access(records, field: Field, operation: typing.Literal['read', 'write']) -> None:
    """Check the user access rights on the given field.

    :param field: the field to check
    :param operation: one of ``read``, ``write``
    :raise AccessError: if the user is not allowed to access the provided field
    """
    if operation == 'read':
        env = records.env
        memo = env._field_access_memo
        if env.su or field in memo:
            return
        if records._has_field_access(field, 'read'):
            memo.add(field)
            return
    elif records._has_field_access(field, operation):
        return

    _logger.info('Access Denied by ACLs for operation: %s, uid: %s, model: %s, field: %s',
        operation, records.env.uid, records._name, field.name)

    description = records.env['ir.model']._get(records._name).name

    error_msg = _(
        "You do not have enough rights to access the field \"%(field)s\""
        " on %(document_kind)s (%(document_model)s). "
        "Please contact your system administrator."
        "\n\nOperation: %(operation)s",
        field=field.name,
        document_kind=description,
        document_model=records._name,
        operation=operation,
    )

    if records.env.user._has_group('base.group_no_one'):
        if field.groups == NO_ACCESS:
            allowed_groups_msg = _("always forbidden")
        elif not field.groups:
            allowed_groups_msg = _("custom field access rules")
        else:
            groups_list = [records.env.ref(g) for g in field.groups.split(',')]
            groups = records.env['res.groups'].union(groups_list).sorted('id')
            allowed_groups_msg = _(
                "allowed for groups %s",
                ', '.join(repr(g.display_name) for g in groups),
            )
        error_msg += _(
            "\nUser: %(user)s"
            "\nGroups: %(allowed_groups_msg)s",
            user=records.env.uid,
            allowed_groups_msg=allowed_groups_msg,
        )

    raise AccessError(error_msg)
