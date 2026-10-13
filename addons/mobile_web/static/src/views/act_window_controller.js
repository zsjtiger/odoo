import { Component, onWillStart, onWillUpdateProps, proxy, t, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { makeContext } from "@web/core/data/context";
import { evaluateExpr } from "@web/core/data/py_js/py";
import { rpc } from "@web/core/services/network/rpc";
import { router as _router } from "@mobile_web/core/browser/router";
import { buildRouteState, getActionViews, hasFormView } from "@mobile_web/webclient/actions/action_utils";
import { mobileViewRegistry } from "@mobile_web/views/registries";
import "@mobile_web/views/index";

// -----------------------------------------------------------------------------
// MobileActWindowController
// -----------------------------------------------------------------------------

/**
 * 移动端 ActWindow 容器
 *
 * 根据 action 的视图列表(list / kanban / form), 加载各视图的 arch 与字段定义,
 * 并渲染移动端的视图组件(见 views/)。负责:
 * - 默认打开第一个视图
 * - 搜索(回车后按 _rec_name 搜索, 与动作 domain 合并)
 * - 列表/看板点击进入表单, 新建, 保存后跳转到记录
 * - 与 router 联动, 将当前 resId 写入 URL
 */
export class MobileActWindowController extends Component {
    static template = xml`
        <t t-name="mobile_web.MobileActWindowController">
            <div class="m_act_window_controller">
                <div class="m_search_bar" t-if="this.state.type !== 'form' and this.hasSearch">
                    <input type="search" class="m_search_input" placeholder="搜索" enterkeyhint="search"
                           t-on-keydown="this.onSearchKeydown"/>
                </div>
                <t t-if="this.state.ready">
                    <t t-component="this.viewComponent" t-key="this.viewKey" t-props="this.viewProps"/>
                </t>
                <button type="button" class="m_create_btn" t-if="this.state.ready and this.state.type !== 'form' and this.hasForm"
                        t-on-click="this.onCreateClick">+</button>
            </div>
        </t>
    `;
    props = useProps({
        action: t.object(),
        resId: t.or([t.number(), t.string(), t.literal(false)]).optional(),
        additionalContext: t.object().optional({}),
    });
    viewService = useService("view");

    setup() {
        this.state = proxy({
            ready: false,
            type: null,
            resId: false,
            domain: [],
            views: null,
        });
        this.fields = {};
        this.archs = {};
        this.baseDomain = [];

        onWillStart(() => this.prepare(this.props));
        // 同一个动作内切换记录(例如返回列表)时, 组件会被复用, 需要按新的 props 重新计算
        onWillUpdateProps((nextProps) => {
            if (nextProps.action !== this.props.action || nextProps.resId !== this.props.resId) {
                return this.prepare(nextProps);
            }
        });
    }

    get hasForm() {
        return hasFormView(this.props.action);
    }

    get hasSearch() {
        return this.state.type !== "form";
    }

    get viewComponent() {
        return mobileViewRegistry.get(this.state.type);
    }

    get viewKey() {
        return `${this.state.type}:${this.state.resId}`;
    }

    /**
     * 解析动作的上下文与 domain, 并加载视图定义
     */
    async prepare(props) {
        const action = props.action;
        const context = this.buildContext(props);
        this.baseDomain = this.buildDomain(action);

        const views = getActionViews(action);
        const loaded = await this.viewService.loadViews({
            resModel: action.res_model,
            views,
            context,
        }, { actionId: action.id });
        // 字段定义在模型级别共享, 各视图只有自己的 arch
        this.fields = loaded.fields;
        this.archs = Object.fromEntries(views.map(([, type]) => [type, loaded.views[type].arch]));

        // 如果 URL 中有 resId, 并且视图包含 form, 则直接打开 form
        let type = views[0][1];
        if (props.resId && hasFormView(action)) {
            type = "form";
        }
        // 移动端支持 list / kanban / form, 其他视图退回到第一个支持的视图
        const supported = views.map(([, t]) => t).filter((t) => mobileViewRegistry.contains(t));
        if (!supported.includes(type)) {
            type = supported[0];
        }

        this.context = context;
        this.state.type = type;
        this.state.resId = props.resId === "new" ? undefined : props.resId || false;
        this.state.domain = this.baseDomain;
        this.state.ready = true;
    }

    buildContext(props) {
        const action = props.action;
        let actionContext = {};
        if (action.context) {
            try {
                actionContext = makeContext([evaluateExpr(action.context)]);
            } catch (e) {
                actionContext = {};
            }
        }
        return makeContext([actionContext, props.additionalContext]);
    }

    buildDomain(action) {
        if (!action.domain) {
            return [];
        }
        try {
            return evaluateExpr(action.domain);
        } catch (e) {
            return [];
        }
    }

    /**
     * 传给当前视图组件的 props
     */
    get viewProps() {
        const common = {
            resModel: this.props.action.res_model,
            arch: this.archs[this.state.type],
            fields: this.fields,
            context: this.context,
        };
        if (this.state.type === "form") {
            return {
                ...common,
                resId: this.state.resId,
                onSaved: (resId) => this._onSelectRecord(resId),
                onDiscard: () => window.history.back(),
            };
        }
        return {
            ...common,
            domain: this.state.domain,
            onSelect: (resId) => this._onSelectRecord(resId),
        };
    }

    /**
     * 回车后按 `_rec_name` 搜索: 搜索条件与动作自身的 domain 合并
     */
    async onSearchKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        const searchDomain = await rpc("/mobile_web/search_domain", {
            model: this.props.action.res_model,
            text: ev.target.value,
        });
        this.state.domain = [...this.baseDomain, ...searchDomain];
    }

    onCreateClick() {
        this._onCreateRecord();
    }

    /**
     * 切换到 form 视图显示一条记录
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
        this.state.type = "form";
        this.state.resId = resId;
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
