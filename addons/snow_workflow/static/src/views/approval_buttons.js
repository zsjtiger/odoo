import { Component, onWillStart, onWillUpdateProps, proxy, t, useProps, xml } from "@odoo/owl";
import { session } from "@web/boot/session";
import { _t } from "@web/core/data/l10n/translation";
import { useService } from "@web/core/utils/hooks";

// 连续点击的间隔小于该值时只执行第一次 (防止双击重复提交)
const CLICK_DEBOUNCE_MS = 300;

/** 从 RPC 错误中取出可展示给用户的文本 */
function errorMessage(error) {
    return error?.data?.message || error?.message || String(error);
}

/**
 * 表单状态栏中的审批按钮: 只读时显示当前可执行的审批操作, 编辑时显示"保存并提交".
 * 仅对 session 中 approval_models 包含的模型生效, 且审批流开关开启时显示.
 */
export class ApprovalButtons extends Component {
    static template = xml`
        <t t-name="snow_workflow.ApprovalButtons">
            <div t-if="this.state.buttons.length" class="o_snow_approval_buttons d-inline-flex flex-wrap gap-1">
                <t t-foreach="this.state.buttons" t-as="button" t-key="button_index">
                    <button type="button" class="btn btn-primary" t-on-click="() => this.onClick(button)">
                        <t t-out="button.label"/>
                    </button>
                </t>
            </div>
        </t>
    `;
    props = useProps({ record: t.object() });
    orm = useService("orm");
    actionService = useService("action");
    notification = useService("notification");
    state = proxy({ buttons: [] });
    lastClick = 0;
    loadedKey = null;

    setup() {
        onWillStart(() => this.load(this.props.record));
        onWillUpdateProps((nextProps) => this.load(nextProps.record));
    }

    get enabled() {
        return Boolean(session.enable_common_workflow) &&
            (session.approval_models || []).includes(this.props.record.resModel);
    }

    /** 记录或编辑状态变化时重新计算按钮 */
    async load(record) {
        const key = `${record.resModel}:${record.resId}:${record.isInEdition}`;
        if (!this.enabled) {
            this.state.buttons = [];
            return;
        }
        if (key === this.loadedKey) {
            return;
        }
        this.loadedKey = key;
        const resId = record.resId || false;
        const context = record.context;
        let values;
        try {
            if (record.isInEdition) {
                const button = await this.orm.call(
                    "snow.workflow.action", "get_save_and_submit_button", [record.resModel, resId], { context }
                );
                values = button ? [button] : [];
            } else {
                values = await this.orm.call(
                    "snow.workflow.action", "get_status", [record.resModel, resId], { context }
                );
            }
        } catch (error) {
            // 加载失败不能影响表单显示: 清空按钮, 允许下次重新加载, 并提示原因
            if (key === this.loadedKey) {
                this.loadedKey = null;
            }
            this.state.buttons = [];
            this.notification.add(errorMessage(error), { type: "danger" });
            return;
        }
        if (key !== this.loadedKey) {
            return; // 已有更新的加载结果
        }
        this.state.buttons = (values || []).map((value, index) => ({
            index,
            label: _t(value.button_name),
            value,
        }));
    }

    onClick(button) {
        const now = Date.now();
        if (now - this.lastClick < CLICK_DEBOUNCE_MS) {
            return;
        }
        this.lastClick = now;
        if (this.props.record.isInEdition) {
            return this.saveAndSubmit(button.value);
        }
        return this.approve(button.value);
    }

    /** 审批操作: 提交审批 / 通过 / 拒绝 等, 后端返回刷新动作或 submit_success */
    async approve(value) {
        const record = this.props.record;
        const payload = { ...value, model_name: record.resModel, record_id: record.resId };
        const result = await this.orm.call("snow.workflow.action", "approval_action", [payload], {
            context: record.context,
        });
        if (result?.tag === "submit_success") {
            await record.model.load();
        } else if (result) {
            this.actionService.doAction(result);
        }
    }

    /** 保存当前记录后提交审批, 完成后回到只读状态 */
    async saveAndSubmit() {
        const record = this.props.record;
        const saved = await record.save({ reload: true });
        if (!saved) {
            return;
        }
        const result = await this.orm.call(
            "snow.workflow.action", "submit_after_save", [record.resModel, record.resId],
            { context: record.context }
        );
        await record.switchMode("readonly");
        await record.model.load();
        if (result) {
            this.actionService.doAction(result);
        } else {
            this.notification.add(_t("No approval workflow is defined for this record."), { type: "warning" });
        }
    }
}
