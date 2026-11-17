# -*- coding: utf-8 -*-
# from odoo import http


# class SnowWorkflow(http.Controller):
#     @http.route('/snow_workflow/snow_workflow', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/snow_workflow/snow_workflow/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('snow_workflow.listing', {
#             'root': '/snow_workflow/snow_workflow',
#             'objects': http.request.env['snow_workflow.snow_workflow'].search([]),
#         })

#     @http.route('/snow_workflow/snow_workflow/objects/<model("snow_workflow.snow_workflow"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('snow_workflow.object', {
#             'object': obj
#         })
