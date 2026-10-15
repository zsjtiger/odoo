# -*- coding: utf-8 -*-
{
    'name': "GPS Location",
    'category': 'Hidden',
    'summary': "Reusable GPS location record, owned by any record through a many2one field",
    'description': """
GPS Location
============

A ``gps`` record stores an address with its latitude and longitude. Each owner
record (for example an account) points to its own ``gps`` record through a
many2one field; locations are not shared between owners.

Models inherit ``gps.mixin`` to keep the owner link up to date, to copy the
location on duplicate and to remove it on delete. Locations that are no longer
referenced by their owner are removed by a daily cron job.
    """,
    'version': '1.0',
    'depends': ['base'],
    'data': [
        'security/ir.access.csv',
        'data/ir_cron.xml',
    ],
    'license': 'LGPL-3',
    'application': False,
}
