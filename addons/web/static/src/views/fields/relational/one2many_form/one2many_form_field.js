import { onWillRender, onWillStart, xml } from "@odoo/owl";
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
                 class="o_one2many_form_card card position-relative p-3 pe-5 mb-2"
                 t-on-focusin="() => this.onCardFocus(record)">
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
                    aria-label="Add" t-on-click="() => this.onAddCard()">+</button>
        </div>
    `;
    static components = { ...X2ManyField.components, Field };

    setup() {
        super.setup();
        // 列表同一时间只允许一条明细处于编辑状态: 没有编辑中的明细时, 让第一张卡片进入编辑
        const enableCardEditing = () => {
            if (this.props.readonly || this.list.editedRecord) {
                return;
            }
            const first = this.list.records[0];
            if (first) {
                first.switchMode("edit");
            }
        };
        onWillStart(enableCardEditing);
        onWillRender(enableCardEditing);
    }

    /** 点击(获得焦点)某张卡片时, 结束当前编辑的明细并让该卡片进入编辑, 与列表行的行为一致 */
    async onCardFocus(record) {
        if (this.props.readonly || record.isInEdition) {
            return;
        }
        await this.list.leaveEditMode();
        await record.switchMode("edit");
    }

    /** 卡片中的字段: 列表视图中的字段列(隐藏的按钮与不可见字段不显示) */
    get cardColumns() {
        return (this.archInfo.columns || []).filter((column) => column.type === "field" && !column.invisible);
    }

    /** 追加一张空卡片: 先结束当前编辑的明细(保存), 再在末尾新增一条 */
    async onAddCard() {
        await this.list.leaveEditMode();
        await this.list.addNewRecord({ mode: "edit", position: "bottom" });
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
