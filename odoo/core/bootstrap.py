# ruff: noqa: E402, F401
# Part of Odoo. See LICENSE file for full copyright and licensing details.

""" Odoo initialization. """

import gc
import sys
from odoo.release import MIN_PY_VERSION


if sys.flags.optimize:
    raise RuntimeError(
        "Running odoo with Python optimization enabled (-O/-OO/PYTHONOPTIMIZE) is not supported"
    )

assert sys.version_info > MIN_PY_VERSION, f"Outdated python version detected, Odoo requires Python >= {'.'.join(map(str, MIN_PY_VERSION))} to run."

# ----------------------------------------------------------
# Set gc thresolds if they are default, see `odoo.tools.gc`.
# Defaults changed from (700, 10, 10) to (2000, 10, 10) in 3.13
# and the last generation was removed in 3.14.
# ----------------------------------------------------------
if gc.get_threshold()[0] in (700, 2000):
    # Handling requests can sometimes allocate over 5k new objects, let leave
    # some space before starting any collection.
    gc.set_threshold(12_000, 20, 25)

# ----------------------------------------------------------
# Import tools to patch code and libraries
# required to do as early as possible for evented and timezone
# ----------------------------------------------------------
from odoo.core import patches
patches.patch_init()

from odoo.tools.gc import gc_set_timing
gc_set_timing(enable=True)
