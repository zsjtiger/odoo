"""Errors of the safe evaluation and the policy applied to the unsafe accesses."""

import functools
import logging
import os
from enum import IntEnum, auto
from json.encoder import c_make_encoder  # noqa: OLS02001
from ...config import config


_logger_runtime = logging.getLogger('odoo.tools.safe_eval.runtime')


class UnsafePolicy(IntEnum):
    DISABLE = 0
    LOG = auto()
    RAISE = auto()
    TERMINATE = auto()


@functools.cache
def unsafe_policy():
    policy = UnsafePolicy[config['unsafe_policy'].upper()]

    if policy and c_make_encoder is None:
        _logger_runtime.warning(
            "Unsafe object policy '%s' is configured, but it is not supported on this runtime "
            "(missing native encoder). The policy will be ignored.",
            policy.name,
        )
        policy = UnsafePolicy.DISABLE

    return policy


class UnsafeError(BaseException):
    """
    Base class for exceptions triggered by unsafe operations.

    Ideally used as a high-level handler to catch exceptions related
    to unsafe errors.
    Since this inherits from `BaseException`, it will bypass standard
    `except Exception:` blocks.
    """


class UnsafeContextError(UnsafeError):
    """ Exception raised when the evaluation context is unsafe. """


class UnsafeObjectError(UnsafeError):
    """ Exception raised when an object is unsafe. """


class UnsafeModuleError(UnsafeObjectError):

    def __init__(self, obj):
        super().__init__(f'Unsafe module access: {obj!r}')


def handle_unsafe_error(error):
    _logger_runtime.warning(error)
    if unsafe_policy() is UnsafePolicy.RAISE:
        raise error
    if unsafe_policy() is UnsafePolicy.TERMINATE:
        os._exit(1)


