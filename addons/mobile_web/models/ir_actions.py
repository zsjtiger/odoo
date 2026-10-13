from crossnow import models, fields, api


class IrActionMobilePage(models.Model):
    _name = 'ir.actions.mobile_page'
    _description = 'Action Mobile Page'
    _table = 'ir_act_mobile_page'
    _inherit = 'ir.actions.actions'
    
    binding_mobile_page = fields.Many2one(
        'mobile_web.mobile.page',
        string="action type: `ir.actions.mobile_page` binding mobile_web.mobile.page record"
    )
    
    def _get_readable_fields(self):
        return super()._get_readable_fields() | {
            "binding_mobile_page"
        }

    def read(self, fields=None, load='_classic_read'):
        def get_bingding_mobile_page_id(value: dict) -> int | None:
            """
            read方法内的通用逻辑, 从read的结果中获取binding_mobile_page字段的id值
            例如:
                {
                    'id': 100,
                    'name': 'Some Mobile Action',
                    'binding_mobile_page': (1, 'some_mobile_page_name')
                }
            从中获取:
                binding_mobile_page字段对应的id, 也就是`1`.
                
            bpm: binding_mobile_page
            """
            bmp_data = value.get('binding_mobile_page', False)
            if bmp_data:
                bmp_id = bmp_data[0]
                if isinstance(bmp_id, int):
                    return bmp_id
                return None

        result: list[dict] = super().read(fields, load)

        if fields and "binding_mobile_page" not in fields:
            return result

        # 默认情况下, many2one字段的read返回值是`(id, name)`, 这里我们让binding_mobile_page字段返回(id, display_name, binding_mobile_page)
        # bmp: bingding_mobile_page

        all_bmp_id = []
        for val in result:
            if bmp_id := get_bingding_mobile_page_id(val):
                all_bmp_id.append(bmp_id)

        all_bmp_res = self.env['mobile_web.mobile.page'].browse(all_bmp_id)

        for val in result:
            if bmp_id := get_bingding_mobile_page_id(val):
                bmp_rec = all_bmp_res.filtered(lambda o: o.id == bmp_id).ensure_one()
                val["binding_mobile_page"] = (bmp_rec.id, bmp_rec.display_name ,bmp_rec.page_component_id)

        return result
