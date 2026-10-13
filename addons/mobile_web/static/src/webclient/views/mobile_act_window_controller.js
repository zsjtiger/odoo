import { Component, markRaw, onWillStart, onWillUpdateProps, proxy, t, useProps, xml } from "@odoo/owl";
import { useSubEnv } from "@web/core/owl/utils";
import { registry } from "@web/core/framework/registry";
import { useService } from "@web/core/utils/hooks";
import { View, getDefaultConfig } from "@web/views/view";
import { rpc } from "@web/core/services/network/rpc";
import { makeContext } from "@web/core/data/context";
import { evaluateExpr } from "@web/core/data/py_js/py";
import { router as _router } from "@mobile_web/core/browser/router";
import { MobileFormActions } from "@mobile_web/webclient/views/mobile_form_actions";
import { buildRouteState, getActionViews, hasFormView } from "@mobile_web/webclient/actions/action_utils";
import { findDescendant } from "@mobile_web/common/owl_tree";

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
 * - 支持新建记录、搜索、保存、放弃
 * - 与 router 联动, 将当前 resId 写入 URL
 */
export class MobileActWindowController extends Component {
    static template = xml`
        <t t-name="mobile_web.MobileActWindowController">
            <div class="m_act_window_controller">
                <t t-if="this.state.viewProps">
                    <div class="m_search_bar" t-if="this.state.viewProps.type !== 'form'">
                        <input type="search" class="m_search_input" placeholder="搜索" t-on-keydown="this.onSearchKeydown"/>
                    </div>
                    <View t-key="this.viewKey" t-props="this.state.viewProps"/>
                    <button type="button" class="m_create_btn" t-if="this.state.viewProps.type !== 'form'" t-on-click="this.onCreateClick">+</button>
                    <MobileFormActions t-if="this.state.viewProps.type === 'form'" onSave="this.onSaveClick" onDiscard="this.onDiscardClick"/>
                </t>
            </div>
        </t>
    `;
    static components = { View, MobileFormActions };
    props = useProps({
        action: t.object(),
        resId: t.or([t.number(), t.string(), t.literal(false)]).optional(),
        additionalContext: t.object().optional({}),
    });

    setup() {
        this.viewService = useService("view");
        this.dialogService = useService("dialog");

        this.state = proxy({
            viewProps: null,
        });

        // 操作按钮把 handler 作为 prop 传给子组件, 需要绑定 this
        this.onSaveClick = this.onSaveClick.bind(this);
        this.onDiscardClick = this.onDiscardClick.bind(this);

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
        // 同一个动作内切换记录(例如返回列表)时, 组件会被复用, 需要按新的 props 重新计算视图
        onWillUpdateProps((nextProps) => {
            if (nextProps.action !== this.props.action || nextProps.resId !== this.props.resId) {
                return this._prepareViewProps(nextProps);
            }
        });
    }

    /**
     * 解析 action 信息, 构造 View 组件可用的 props
     */
    async _prepareViewProps(props = this.props) {
        const action = props.action;
        const views = getActionViews(action);

        // 默认打开第一个视图
        const defaultViewType = views[0][1];
        // 如果 URL 中有 resId, 并且视图包含 form, 则直接打开 form
        let targetType = defaultViewType;
        let targetResId = props.resId || false;
        if (targetResId && hasFormView(action)) {
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
            props.additionalContext,
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

        // 搜索时在这个条件的基础上追加搜索条件
        this.baseDomain = domain;

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
            // many2one 的值形如 [id, name], 视图服务需要的是 id
            searchViewId: action.search_view_id ? action.search_view_id[0] : false,
            loadIrFilters: false,
            loadActionMenus: false,
            selectRecord: this._onSelectRecord.bind(this),
            createRecord: this._onCreateRecord.bind(this),
            resId: targetResId === "new" ? undefined : targetResId,
            __getGlobalState__: null,
            __getLocalState__: null,
            __getContext__: null,
            __getOrderBy__: null,
        };
    }

    /**
     * 切换视图类型或记录时重新挂载 View (web 的 View 不会因为 type 变化而重建控制器);
     * 搜索只改变 domain, 因此 key 不变, View 只做增量更新
     */
    get viewKey() {
        const viewProps = this.state.viewProps;
        return viewProps ? `${viewProps.type}:${viewProps.resId}` : "none";
    }

    _getFormController() {
        return findDescendant(this, (c) => typeof c.saveButtonClicked === "function");
    }

    /**
     * 回车后按 `_rec_name` 搜索: 搜索条件与动作自身的 domain 合并
     */
    async onSearchKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        const searchDomain = await rpc("/mobile_web/search_domain", {
            model: this.state.viewProps.resModel,
            text: ev.target.value,
        });
        this.state.viewProps = {
            ...this.state.viewProps,
            domain: [...this.baseDomain, ...searchDomain],
        };
    }

    onCreateClick() {
        this._onCreateRecord();
    }

    async onSaveClick() {
        const isNew = this.state.viewProps.resId === undefined;
        const controller = this._getFormController();
        // save() 等待保存完成; 新建记录保存后打开保存后的记录(与 web 一致)
        const saved = await controller?.save();
        const savedId = controller?.model?.root?.resId;
        if (saved && isNew && savedId) {
            this._onSelectRecord(savedId);
        }
    }

    async onDiscardClick() {
        this._getFormController()?.discard();
        // 放弃后回到进入表单之前的页面(列表)
        window.history.back();
    }

    /**
     * 列表视图点击行, 切换到 form 视图
     *
     * 桌面端 ListController 调用 selectRecord 时传入的是 resId(number) 和 options,
     * 而非 record 对象。
     *
     * @param {number} resId
     */
    _onSelectRecord(resId) {
        if (!hasFormView(this.props.action)) {
            return;
        }
        this._switchToForm(resId);
        this._pushRouteState(resId);
        this._setNavbarTitle(this.props.action.display_name || "CrossNow");
    }

    /**
     * 新建记录, 切换到 form 视图的 "new" 状态
     */
    _onCreateRecord() {
        const action = this.props.action;
        if (!hasFormView(action)) {
            return;
        }
        // web 的视图使用 undefined 表示新建记录, "new" 只保留在 URL 状态中
        this._switchToForm(undefined);
        this._pushRouteState("new");
        this._setNavbarTitle(`${action.display_name || "Odoo"} - 新建`);
    }

    _switchToForm(resId) {
        this.state.viewProps = {
            ...this.state.viewProps,
            type: "form",
            resId,
        };
    }

    /**
     * 同步路由状态, resId 为 "new" 表示新建
     */
    _pushRouteState(resId) {
        _router.pushState(buildRouteState(this.props.action, resId));
    }

    _setNavbarTitle(title) {
        this.env.bus.trigger("NAVBAR_TITLE:UPDATE", { title });
    }
}
