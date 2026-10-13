import { Component, xml, onWillStart, useState, useSubEnv, markRaw, useRef } from "@crossnow/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { View, getDefaultConfig } from "@web/views/view";
import { makeContext } from "@web/core/context";
import { evaluateExpr } from "@web/core/py_js/py";
import { router as _router } from "@mobile_web/core/browser/router";

// -----------------------------------------------------------------------------
// MobileActWindowController
// -----------------------------------------------------------------------------

/**
 * 移动端 ActWindow 视图容器
 *
 * 负责将 PC 端的 ir.actions.act_window 转换为移动端可渲染的 View 组件。
 * 主要能力:
 * - 根据 action 的 view_mode 默认打开第一个视图(通常是 list)
 * - 列表点击行打开 form 视图
 * - 支持新建记录
 * - 与 router 联动, 将当前 resId 写入 URL
 */
export class MobileActWindowController extends Component {
    static template = xml`
        <t t-name="mobile_web.MobileActWindowController">
            <div class="m_act_window_controller" t-ref="root">
                <t t-if="viewProps">
                    <View t-props="viewProps"/>
                </t>
            </div>
        </t>
    `;
    static components = { View };
    static props = {
        action: Object,
        resId: { type: [Number, String, { value: false }], optional: true },
        additionalContext: { type: Object, optional: true },
    };
    static defaultProps = {
        additionalContext: {},
    };

    setup() {
        this.rootRef = useRef("root");
        this.viewService = useService("view");
        this.dialogService = useService("dialog");

        this.state = useState({
            viewProps: null,
        });

        // 移动端标记为 small, 触发后端返回移动版视图
        useSubEnv({
            isSmall: true,
            inDialog: false,
            config: {
                ...getDefaultConfig(),
                actionId: this.props.action.id,
                actionType: this.props.action.type,
                views: this.props.action.views,
            },
        });

        onWillStart(() => this._prepareViewProps());
    }

    /**
     * 解析 action 信息, 构造 View 组件可用的 props
     */
    async _prepareViewProps() {
        const action = this.props.action;
        const views = action.views || [];
        if (!views.length) {
            // 没有明确指定 views, 使用 view_mode 推导
            const viewModes = (action.view_mode || "list,form").split(",");
            for (const viewMode of viewModes) {
                views.push([false, viewMode.trim()]);
            }
        }

        // 默认打开第一个视图
        const defaultViewType = views[0][1];
        // 如果 URL 中有 resId, 并且视图包含 form, 则直接打开 form
        let targetType = defaultViewType;
        let targetResId = this.props.resId || false;
        const hasFormView = views.some((v) => v[1] === "form");
        if (targetResId && hasFormView) {
            targetType = "form";
        }

        // 过滤掉当前 unsupported 的 view 类型, 移动端优先 list/form
        const supportedTypes = new Set(["list", "form", "kanban"]);
        if (!supportedTypes.has(targetType)) {
            const fallbackView = views.find((v) => supportedTypes.has(v[1]));
            if (fallbackView) {
                targetType = fallbackView[1];
            }
        }

        // 解析 action context
        let actionContext = {};
        if (action.context) {
            try {
                actionContext = makeContext([evaluateExpr(action.context)]);
            } catch (e) {
                actionContext = {};
            }
        }
        const context = makeContext([
            actionContext,
            this.props.additionalContext,
        ]);

        // 解析 domain
        let domain = [];
        if (action.domain) {
            try {
                domain = evaluateExpr(action.domain);
            } catch (e) {
                domain = [];
            }
        }

        this.state.viewProps = {
            resModel: action.res_model,
            type: targetType,
            views: markRaw(views),
            viewId: false,
            context: markRaw(context),
            domain,
            display: {
                controlPanel: false, // 移动端默认隐藏 ControlPanel
                searchPanel: false,
                banner: false,
            },
            searchViewId: action.search_view_id || false,
            loadIrFilters: false,
            loadActionMenus: false,
            selectRecord: this._onSelectRecord.bind(this),
            createRecord: this._onCreateRecord.bind(this),
            resId: targetResId === "new" ? "new" : targetResId,
            __getGlobalState__: null,
            __getLocalState__: null,
            __getContext__: null,
            __getOrderBy__: null,
        };
    }

    /**
     * 列表视图点击行, 切换到 form 视图
     *
     * 桌面端 ListController 调用 selectRecord 时传入的是 resId(number) 和 options,
     * 而非 record 对象。
     *
     * @param {number} resId
     * @param {object} options
     */
    _onSelectRecord(resId, options = {}) {
        const action = this.props.action;
        const views = action.views || [];
        const hasFormView = views.some((v) => v[1] === "form");
        if (!hasFormView) {
            return;
        }

        this.state.viewProps = {
            ...this.state.viewProps,
            type: "form",
            resId,
        };

        // 同步路由状态
        const stateAction = action.path ? action.path : action.id;
        _router.pushState({
            action: stateAction,
            resId,
            _isMobile: true,
            actionStack: [{
                action: stateAction,
                resId,
                _isMobile: true,
            }],
        });

        // 更新导航栏标题
        this.env.bus.trigger("NAVBAR_TITLE:UPDATE", {
            title: action.display_name || "CrossNow",
        });
    }

    /**
     * 新建记录, 切换到 form 视图的 "new" 状态
     */
    _onCreateRecord() {
        const action = this.props.action;
        const views = action.views || [];
        const hasFormView = views.some((v) => v[1] === "form");
        if (!hasFormView) {
            return;
        }

        this.state.viewProps = {
            ...this.state.viewProps,
            type: "form",
            resId: "new",
        };

        const stateAction = action.path ? action.path : action.id;
        _router.pushState({
            action: stateAction,
            resId: "new",
            _isMobile: true,
            actionStack: [{
                action: stateAction,
                resId: "new",
                _isMobile: true,
            }],
        });

        this.env.bus.trigger("NAVBAR_TITLE:UPDATE", {
            title: `${action.display_name || "CrossNow"} - 新建`,
        });
    }
}


// -----------------------------------------------------------------------------
// Registry
// -----------------------------------------------------------------------------

registry.category("services").add("mobileActWindow", {
    dependencies: ["view", "orm", "dialog"],
    start() {
        return {};
    },
});
