# Part of Odoo. See LICENSE file for full copyright and licensing details.

RELEASE_LEVELS_DISPLAY = {'alpha': 'a',
                          'beta': 'b',
                          'candidate': 'rc',
                          'final': ''}

# version_info format: (MAJOR, MINOR, MICRO, RELEASE_LEVEL, SERIAL)
# inspired by Python's own sys.version_info, in order to be
# properly comparable using normal operators, for example:
#  (6,1,0,'beta',0) < (6,1,0,'candidate',1) < (6,1,0,'candidate',2)
#  (6,1,0,'candidate',2) < (6,1,0,'final',0) < (6,1,2,'final',0)
# NOTE: during release, the MAJOR version can become an arbitrary string ('saas~xx')
version_info = (20, 0, 0, 'final', 0, '')
series = serie = major_version = '.'.join(str(s) for s in version_info[:2])
version = series + RELEASE_LEVELS_DISPLAY[version_info[3]] + str(version_info[4] or '') + version_info[5]

product_name = 'Odoo'
description = 'Odoo Server'
author = 'OpenERP S.A.'

MIN_PY_VERSION = (3, 12)
MAX_PY_VERSION = (3, 14)
MIN_PG_VERSION = 16
