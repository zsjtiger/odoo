import { xml } from "@odoo/owl";
import { registry } from "@web/core/framework/registry";
import { Field } from "@web/views/fields/field";
import { X2ManyField, x2ManyField } from "@web/views/fields/relational/x2many/x2many_field";

/**
 * 内嵌明细表单 (一对多, widget="one2many_form"): 每条明细是一张卡片, 卡片中是明细的字段, 可以直接编辑.
 * "+" 追加一条空明细, 卡片右上角的 × 删除该明细; 与一对多的其他部件一样保存为 one2many 命令.
 *
 * 卡片的字段取明细的列表视图(与桌面端的一对多一致), 与移动端取表单视图的做法对应.
 */
export class One2manyFormField extends X2ManyField {
    static template = xml`
        <div class="o_one2many_form">
            <div t-foreach="this.list.records" t-as="record" t-key="record.id"
                 class="o_one2many_form_card card position-relative p-3 pe-5 mb-2">
                <button t-if="!this.props.readonly" type="button" class="btn-close position-absolute top-0 end-0 m-2"
                        aria-label="Delete" t-on-click="() => this.onDelete(record)"/>
                <div t-foreach="this.cardColumns" t-as="column" t-key="column.name" class="d-flex align-items-center mb-2">
                    <span class="text-muted text-nowrap flex-shrink-0 me-3" style="width: 110px"><t t-esc="column.string"/></span>
                    <div class="flex-grow-1 min-w-0">
                        <Field name="column.name" record="record" type="column.widget" fieldInfo="column"
                               readonly="this.props.readonly"/>
                    </div>
                </div>
            </div>
            <button t-if="!this.props.readonly" type="button" class="btn btn-secondary o_one2many_form_add rounded-circle"
                    aria-label="Add" t-on-click="() => this.onAdd({ editable: 'bottom' })">+</button>
        </div>
    `;
    static components = { ...X2ManyField.components, Field };

    /** 卡片中的字段: 列表视图中的字段列(隐藏的按钮与不可见字段不显示) */
    get cardColumns() {
        return (this.archInfo.columns || []).filter((column) => column.type === "field" && !column.invisible);
    }

    onDelete(record) {
        return this.list.delete(record);
    }
}

export const one2manyFormField = {
    ...x2ManyField,
    component: One2manyFormField,
    extractProps(params, dynamicInfo) {
        // 卡片需要子视图(列表视图的字段列), 未指定时默认使用列表视图
        return x2ManyField.extractProps({ ...params, viewMode: params.viewMode || "list" }, dynamicInfo);
    },
};

registry.category("fields").add("one2many_form", one2manyFormField);
