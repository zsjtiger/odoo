# -*- coding: utf-8 -*-
{
    'name': "Mobile Reporting",
    'category': 'Hidden',
    'summary': "Reporting charts on the mobile web client",
    'description': """
Mobile Reporting
================

Shows the reporting charts (bar, line, pie, gauge, radar, card, map) on the
mobile web client. The chart data, models and desktop chart widgets come from
the ``reporting`` addon: the mobile field widgets subclass them and only add
what the mobile client needs (the click action and the view).
    """,
    'version': '1.0',
    'depends': ['mobile_web', 'reporting'],
    'data': [
        'views/mobile_reporting_views.xml',
    ],
    'assets': {
        'mobile_web.assets_backend': [
            'mobile_reporting/static/src/**/*',
        ],
        'web.assets_unit_tests': [
            'reporting/static/lib/echarts.min.js',
            'mobile_reporting/static/src/**/*.js',
            'mobile_reporting/static/tests/**/*.test.js',
        ],
    },
    'license': 'LGPL-3',
    'application': False,
}
