import { registry } from "@web/core/framework/registry";
import { TextField, textField } from "@web/views/fields/text/text/text_field";

// 只读时只显示前几行, 完整内容在编辑时查看
const PREVIEW_LINES = 5;

/**
 * 审批流定义的流程内容 (widget="definition_content"): 只读时截取前 5 行并加省略号.
 */
export class DefinitionContent extends TextField {
    get value() {
        const value = super.value;
        if (!this.props.readonly) {
            return value;
        }
        const lines = value.split("\n");
        const preview = lines.slice(0, PREVIEW_LINES).join("\n");
        return lines.length > PREVIEW_LINES ? `${preview}\n...` : preview;
    }
}

registry.category("fields").add("definition_content", {
    ...textField,
    component: DefinitionContent,
    supportedTypes: ["text"],
});
