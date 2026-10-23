import { Component, proxy, useProps, xml } from "@odoo/owl";
import { AlertDialog } from "@web/core/dialogs/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// 提交说明的最大长度
const MAX_SUBMIT_INFO_LENGTH = 200;

/**
 * 审批提交前的风险提示 (widget="workflow_warning"): 展示提示内容, 可选勾选"已阅读并同意",
 * 填写提交说明后调用 context.confirm 指定的方法完成提交.
 */
export class WorkflowWarning extends Component {
    static template = xml`
        <t t-name="snow_workflow.WorkflowWarning">
            <div class="o_snow_workflow_warning" style="width: 100%;">
                <div t-if="this.showCheckBox" class="checkbox">
                    <label>
                        <input type="checkbox" id="read_and_agree" t-att-checked="this.state.agree" t-on-change="(ev) => this.state.agree = ev.target.checked"/>
                        <span style="color:red;"><t t-out="this.texts.agree"/></span>
                    </label>
                </div>
                <div>
                    <textarea class="form-control" rows="3" id="submit_info" t-att-value="this.state.submitInfo"
                              t-att-placeholder="this.warningInfo" t-on-input="(ev) => this.state.submitInfo = ev.target.value"/>
                </div>
                <div style="float: right; margin-top: 10px">
                    <button type="button" class="btn btn-secondary" id="cancel" t-on-click="this.onCancel">
                        <t t-out="this.texts.cancel"/>
                    </button>
                    <button type="button" class="btn btn-primary" id="submit" t-on-click="this.onSubmit">
                        <t t-out="this.texts.submit"/>
                    </button>
                </div>
            </div>
        </t>
    `;
    props = useProps(standardFieldProps);
    actionService = useService("action");
    dialog = useService("dialog");
    orm = useService("orm");
    texts = {
        agree: _t("Read and agree to this statement"),
        cancel: _t("cancel"),
        submit: _t("submit"),
        information: _t("information"),
        descriptionRequired: _t("The submission description is required."),
        descriptionTooLong: _t("The submission description cannot exceed 200 characters"),
        mustAgree: _t("You must click read and agree!"),
    };
    state = proxy({ agree: false, submitInfo: "" });

    get context() {
        return this.props.record.context || {};
    }
    get showCheckBox() {
        return this.context.show_check_box ?? true;
    }
    get warningInfo() {
        return this.context.temporary_verify_info;
    }

    showAlert(body) {
        this.dialog.add(AlertDialog, { title: this.texts.information, body });
    }

    onCancel() {
        this.actionService.doAction({ type: "ir.actions.act_window_close" });
    }

    async onSubmit() {
        if (this.showCheckBox && !this.state.agree) {
            this.showAlert(this.texts.mustAgree);
            return;
        }
        const submitInfo = this.state.submitInfo;
        if (!submitInfo.length && this.context.is_submit_text) {
            this.showAlert(this.texts.descriptionRequired);
            return;
        }
        if (submitInfo.length > MAX_SUBMIT_INFO_LENGTH) {
            this.showAlert(this.texts.descriptionTooLong);
            return;
        }
        // 不修改原 context, 只在提交时附带提交说明
        const context = { ...this.context, submit_info: submitInfo };
        const { model, method } = this.context.confirm;
        const results = await this.orm.call(model, method, [], { context });
        if (results) {
            results.target = "current";
        }
        this.actionService.doAction(results, { stackPosition: "replaceCurrentAction" });
    }
}

registry.category("fields").add("workflow_warning", {
    component: WorkflowWarning,
});
