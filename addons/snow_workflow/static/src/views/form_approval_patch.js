import { patch } from "@web/core/utils/patch";
import { append, createElement } from "@web/core/utils/xml";
import { FormCompiler } from "@web/views/form/form_compiler";
import { FormRenderer } from "@web/views/form/form_renderer";
import { ApprovalButtons } from "@snow_workflow/views/approval_buttons";

// 每个表单的状态栏末尾追加审批按钮 (按钮自身判断是否显示)
patch(FormCompiler.prototype, {
    compileHeader(el, params) {
        const statusBar = super.compileHeader(el, params);
        append(statusBar, createElement("ApprovalButtons", { record: "__comp__.props.record" }));
        return statusBar;
    },
});

patch(FormRenderer, {
    components: { ...FormRenderer.components, ApprovalButtons },
});
