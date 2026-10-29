import { Component, onWillStart, onWillUpdateProps, proxy, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { deserializeDateTime, formatDateTime } from "@web/core/data/l10n/dates";
import { registry } from "@web/core/framework/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// 每种审批状态的文字, 颜色与图标
const ACTION_LIST = {
    submit: { name: _t("submit for approval"), color: "#03A09C", icon: "fa fa-arrow-circle-o-up" },
    ready: { name: _t("under approval"), color: "#F99902", icon: "fa fa-clock-o" },
    suspend: { name: _t("suspend"), color: "#F99902", icon: "fa fa-play-circle-o" },
    unsuspend: { name: _t("suspended recovery"), color: "#03A09C", icon: "fa fa-pause-circle-o" },
    reject: { name: _t("reject"), color: "#ff0000", icon: "fa fa-times-circle-o" },
    pass: { name: _t("pass"), color: "#03A09C", icon: "fa fa-check-circle-o" },
    withdraw: { name: _t("withdrawn"), color: "#ff0000", icon: "fa fa-minus-circle" },
    wait: { name: _t("wait"), color: "#ccc", icon: "fa fa-dot-circle-o" },
    // 其他人通过或拒绝, 被动结束
    finished: { name: "", color: "#03A09C", icon: "fa fa-dot-circle-o" },
};
const UNKNOWN_STATE = { name: "", color: "#ccc", icon: "fa fa-dot-circle-o" };

function actionOf(state) {
    return ACTION_LIST[state] || UNKNOWN_STATE;
}

function formatDate(value) {
    return value ? formatDateTime(deserializeDateTime(value)) : "";
}

/**
 * 审批进度 (widget="workflow_process"): 每个环节一段, 展开后列出各审批人的状态.
 * 数据来自 snow.workflow.action.get_process_json.
 */
export class WorkflowProcess extends Component {
    static template = xml`
        <t t-name="snow_workflow.WorkflowProcess">
            <div class="snow-steps-content" t-if="this.state.steps.length">
                <t t-foreach="this.state.steps" t-as="step" t-key="step_index">
                    <div t-attf-class="adm-step adm-step-header {{ this.isOpen(step_index) ? '' : 'snow_hide' }}"
                         style="background-color: #f4fbfb;" t-on-click="() => this.toggle(step_index)">
                        <div class="adm-step-title">
                            <div class="title">
                                <div class="title-left">
                                    <div class="title-name" style="color:#03A09C;margin-right:20px">
                                        <t t-out="step.create_date"/>
                                    </div>
                                    <div class="title-subtitle"><t t-out="step.submitter"/></div>
                                </div>
                                <div class="adm-step-icon-container title-right">
                                    <div class="right-icon angle-down" style="margin-right:10px;margin-bottom:10px;">
                                        <i class="fa fa-light fa-angle-down"/>
                                    </div>
                                    <div class="right-icon angle-up" style="margin-right:10px;margin-bottom:10px;">
                                        <i class="fa fa-light fa-angle-up"/>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div t-attf-class="snow-steps-content {{ this.isOpen(step_index) ? '' : 'snow_hide' }}">
                        <div class="adm-steps adm-steps-vertical">
                            <t t-foreach="step.approve_roadmap" t-as="group" t-key="group_index">
                                <div class="adm-step adm-step-status-finish">
                                    <div class="adm-step-indicator">
                                        <div class="adm-step-icon-container">
                                            <div class="left-icon" t-attf-style="color:{{ this.actionOf(group.state).color }};">
                                                <i t-attf-class="{{ this.actionOf(group.state).icon }}"/>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="adm-step-content"
                                         t-att-style="['and', 'or'].includes(group.group_type) ? 'border: 1px solid #ccc; border-radius: 10px; padding: 10px; margin-bottom: 10px' : ''">
                                        <div t-if="['and', 'or'].includes(group.group_type)" class="title-subtitle">
                                            <t t-if="group.group_type === 'and'">【Multiple Signature】</t>
                                            <t t-else="">【Signed by One】</t>
                                        </div>
                                        <t t-foreach="group.members" t-as="member" t-key="member_index">
                                            <div class="adm-step-title">
                                                <div class="title">
                                                    <div class="title-left">
                                                        <div class="title-name">
                                                            <t t-if="member.actor === 'empty'">empty</t>
                                                            <t t-else=""><t t-out="member.actor"/></t>
                                                        </div>
                                                        <div t-if="group.group_type === 'add'" class="title-subtitle">
                                                            【Additional Signature】
                                                        </div>
                                                    </div>
                                                    <div class="title-right">
                                                        <div class="status" t-attf-style="color:{{ this.actionOf(member.state).color }};">
                                                            <t t-out="this.actionOf(member.state).name"/>
                                                        </div>
                                                        <div class="time"><t t-out="member.create_date"/></div>
                                                    </div>
                                                </div>
                                            </div>
                                            <div class="adm-step-description">
                                                <div class="description"><t t-out="member.comments"/></div>
                                            </div>
                                        </t>
                                    </div>
                                </div>
                            </t>
                        </div>
                    </div>
                </t>
            </div>
        </t>
    `;
    props = useProps(standardFieldProps);
    orm = useService("orm");
    state = proxy({ steps: [], open: {} });
    actionOf = actionOf;

    setup() {
        onWillStart(() => this.load(this.props));
        onWillUpdateProps((nextProps) => {
            if (nextProps.record.resId !== this.props.record.resId) {
                return this.load(nextProps);
            }
        });
    }

    isOpen(index) {
        // 第一个环节默认展开
        return this.state.open[index] ?? index === 0;
    }

    toggle(index) {
        this.state.open[index] = !this.isOpen(index);
    }

    async load(props) {
        const { record } = props;
        if (!record.resId) {
            this.state.steps = [];
            return;
        }
        const result = await this.orm.call(
            "snow.workflow.action",
            "get_process_json",
            [record.resModel, record.resId],
            { context: record.context }
        );
        const parsed = typeof result === "string" && result ? JSON.parse(result) : [];
        this.state.steps = Object.values(parsed).map((step) => ({
            ...step,
            create_date: formatDate(step.create_date),
            approve_roadmap: (step.approve_roadmap || []).map((group) => ({
                ...group,
                members: (group.members || []).map((member) => ({
                    ...member,
                    create_date: formatDate(member.create_date),
                })),
            })),
        }));
    }
}

registry.category("fields").add("workflow_process", {
    component: WorkflowProcess,
    supportedTypes: ["one2many", "text", "char"],
});
