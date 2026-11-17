import re
from pathlib import Path

from odoo import api, models, fields


# 前端注册的页面组件id, 与 static/src/pages/shared/page_keys.js 保持一致
PAGE_COMPONENT_IDS = (
    'mobile_page.home_page',
    'mobile_page.todo_page',
    'mobile_page.schedule_page',
    'mobile_page.user_my_page',
    'mobile_page.ai_page',
)


# 图标雪碧图(static/public/iconfont.js)中的 symbol id. 只保留了移动端用到的图标以减小体积,
# 新增图标时需要重新生成该文件(从 iconfont.cn 下载完整包后裁剪). 数据中配置的图标须在其中
ICON_SPRITE_JS = Path(__file__).resolve().parents[1] / 'static' / 'public' / 'iconfont.js'


def get_sprite_icon_ids() -> set:
    return set(re.findall(r'<symbol id="([^"]+)"', ICON_SPRITE_JS.read_text(encoding='utf-8')))


class MobilePage(models.Model):
    _name = 'mobile_web.mobile.page'

    name = fields.Char(string="page name", translate=True)
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
