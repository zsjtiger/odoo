# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The users of the registry: the helpers, the password hashing, the log, the users, their multi-company fields, the identity checks, the password wizards and the API keys. The names are re-exported here."""

# the helpers first, then the models in the order of their definitions: the order of the classes is the order of their extensions
from .helpers import NO_GROUP_CHANGE_LOG, _jsonable, _logger, check_identity, concat
from .crypt import CryptContext, MIN_ROUNDS
from .log import ResUsersLog
from .users import ResUsers, ResUsersPatchedInTest
from .multi_company import UsersMultiCompany
from .identitycheck import ResUsersIdentitycheck
from .password import ChangePasswordOwn, ChangePasswordUser, ChangePasswordWizard
from .apikeys import API_KEY_SIZE, DEFAULT_PROGRAMMATIC_API_KEYS_LIMIT, INDEX_SIZE, KEY_CRYPT_CONTEXT, ResUsersApikeys, ResUsersApikeysDescription, ResUsersApikeysShow, _check_apikey_credentials
