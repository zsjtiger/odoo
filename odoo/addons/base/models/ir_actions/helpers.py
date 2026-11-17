"""The helpers of the actions: the loggers, and the logger proxy of the server actions."""

from __future__ import annotations

import logging


_logger = logging.getLogger('odoo.addons.base.models.ir_actions')


_server_action_logger = _logger.getChild("server_action_safe_eval")


class LoggerProxy:
    """ Proxy of the `_logger` element in order to be used in server actions.
    We purposefully restrict its method as it will be executed in `safe_eval`.
    """
    @staticmethod
    def log(level, message, *args, stack_info=False, exc_info=False):
        _server_action_logger.log(level, message, *args, stack_info=stack_info, exc_info=exc_info)

    @staticmethod
    def info(message, *args, stack_info=False, exc_info=False):
        _server_action_logger.info(message, *args, stack_info=stack_info, exc_info=exc_info)

    @staticmethod
    def warning(message, *args, stack_info=False, exc_info=False):
        _server_action_logger.warning(message, *args, stack_info=stack_info, exc_info=exc_info)

    @staticmethod
    def error(message, *args, stack_info=False, exc_info=False):
        _server_action_logger.error(message, *args, stack_info=stack_info, exc_info=exc_info)

    @staticmethod
    def exception(message, *args, stack_info=False, exc_info=True):
        _server_action_logger.exception(message, *args, stack_info=stack_info, exc_info=exc_info)
