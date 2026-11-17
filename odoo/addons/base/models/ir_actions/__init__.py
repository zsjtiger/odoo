# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The actions of the registry: the base of the actions, the window, URL, server, client and todo actions, and the history of the server actions. The names are re-exported here."""

# the helpers first, then the models in the order of their definitions: the order of the classes is the order of their extensions
from .helpers import LoggerProxy, _logger, _server_action_logger
from .actions import IrActionsActions
from .window import VIEW_TYPES, IrActionsAct_Window, IrActionsAct_WindowView, IrActionsAct_Window_Close
from .url import IrActionsAct_Url
from .server_history import ServerActionHistoryWizard, IrActionsServerHistory
from .server import ServerActionWithWarningsError, WEBHOOK_SAMPLE_VALUES, IrActionsServer
from .todo import IrActionsTodo
from .client import IrActionsClient
