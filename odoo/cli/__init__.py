# Part of Odoo. See LICENSE file for full copyright and licensing details.

# the base imports the core first, the rest of the package relies on it
from .base import Command
from .main import main

COMMAND = None
