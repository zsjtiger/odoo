import { Component, t, useProps, xml } from "@odoo/owl";

/**
 * 移动端 form 视图底部的操作按钮: 放弃 / 保存
 *
 * 按钮只转发事件, 实际的保存与放弃由父组件(MobileActWindowController)处理
 */
export class MobileFormActions extends Component {
    static template = xml`
        <t t-name="mobile_web.MobileFormActions">
            <div class="m_form_actions">
                <button type="button" class="m_form_discard" t-on-click="this.props.onDiscard">放弃</button>
                <button type="button" class="m_form_save" t-on-click="this.props.onSave">保存</button>
            </div>
        </t>
    `;
    props = useProps({
        onDiscard: t.function(),
        onSave: t.function(),
    });
}
