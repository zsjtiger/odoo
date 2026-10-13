from odoo import api, models, fields


# 前端注册的页面组件id, 与 static/src/pages/common/page_keys.js 保持一致
PAGE_COMPONENT_IDS = (
    'mobile_page.home_page',
    'mobile_page.todo_page',
    'mobile_page.schedule_page',
    'mobile_page.user_my_page',
)


class MobilePage(models.Model):
    _name = 'mobile_web.mobile.page'

    name = fields.Char(string="page name")
    page_component_id = fields.Char(string="Owl Component ID which defined in frontend MobilePage registry")
    binding_views = fields.Many2many('ir.ui.view', string='ir.ui.view records which bind to current MobilePage')


class MobilePageActions(models.Model):
    """
    Page上的关联的操作(导航栏)
    """
    _name = 'mobile_web.mobile.page.actions'
    
    name = fields.Char(string="Relation Action Name")
    mobile_page = fields.Many2one('mobile_web.mobile.page', string="relation mobile_page")
    ir_action = fields.Many2one('ir.actions.actions', string="relation ir_action")
    svg_icon_href = fields.Char(string="svg use item href(xlink:href) property, such as `#crossnow-icon-TabMy`")
    sequence = fields.Integer(string="Sequence")

    @api.model
    def get_page_actions(self, mobile_page_id) -> list:
        result = []
        
        res = self.search(domain=[('mobile_page', '=', mobile_page_id)], order="sequence asc")
        for rec in res:
            result.append({
                'name': rec.name,
                'action_id': rec.ir_action.id,
                'svg_icon_href': rec.svg_icon_href,
            })
        
        return result
