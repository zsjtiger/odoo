import { Component, onWillStart, onWillUpdateProps, proxy, t, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { makeContext } from "@web/core/data/context";
import { evaluateExpr } from "@web/core/data/py_js/py";
import { router as _router } from "@mobile_web/core/browser/router";
import { buildRouteState, getActionViews, hasFormView } from "@mobile_web/actions/action_utils";
import { mobileViewRegistry } from "@mobile_web/views/registries";
import { fieldTexts } from "@mobile_web/core/texts";
import { _t } from "@web/core/data/l10n/translation";
import "@mobile_web/views/index";
import { envOf } from "@mobile_web/core/env";
import { parseArch, isHiddenColumn } from "@mobile_web/views/arch";
import { filterableFields, sortableFields } from "@mobile_web/views/record_filters";
import { parseSearchFilters } from "@mobile_web/views/search_filters";
import { mobileFilterDomain } from "@mobile_web/views/mobile_filters";
import { MobileFilterSheet } from "@mobile_web/widgets/filter_sheet/filter_sheet";
import { SortMenu } from "@mobile_web/widgets/sort_menu/sort_menu";
import { MobileSelectSheet } from "@mobile_web/widgets/select_sheet/select_sheet";
import { facetFromRow, facetsDomain, suggestionRows } from "@mobile_web/views/search_facets";

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
    texts = fieldTexts;
    static template = xml`
        <t t-name="mobile_web.MobileActWindowController">
            <div class="m_act_window_controller">
                <div class="m_search_bar" t-if="this.state.type !== 'form' and this.hasSearch">
                    <div class="m_search_top">
                    <div class="m_search_box">
                        <span t-foreach="this.state.facets" t-as="facet" t-key="facet.id" class="m_facet">
                            <span class="m_facet_text"><t t-esc="facet.label"/>: <t t-esc="facet.display"/></span>
                            <button type="button" class="m_facet_remove" t-att-data-index="facet_index"
                                    t-att-aria-label="this.texts.removeFilter" t-on-click="this.onRemoveFacet">×</button>
                        </span>
                        <input type="search" class="m_search_input" t-att-value="this.state.text" t-att-placeholder="this.texts.search"
                               enterkeyhint="search" t-on-input="this.onSearchInput" t-on-keydown="this.onSearchKeydown"/>
                        <button t-if="this.state.facets.length or this.state.text" type="button" class="m_search_clear"
                                t-att-aria-label="this.texts.clear" t-on-click="this.onClearFacets">
                            <svg viewBox="0 0 24 24" aria-hidden="true">
                                <circle cx="12" cy="12" r="9" fill="currentColor"/>
                                <path d="M9 9l6 6M15 9l-6 6" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"/>
                            </svg>
                        </button>
                    </div>
                    <div class="m_search_actions">
                        <button t-if="this.filters.length or this.mobileFilterSections.length" type="button"
                                t-attf-class="m_search_icon_btn {{ this.state.activeFilters.length or this.hasMobileSelection ? 'is_active' : '' }}"
                                t-att-aria-label="this.texts.filter" t-on-click="this.openFilters">
                            <svg viewBox="0 0 24 24" aria-hidden="true">
                                <path d="M3 5h18l-7 8v6l-4-2v-4z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
                            </svg>
                        </button>
                        <SortMenu t-if="this.sortFields.length" iconOnly="true" sortFields="this.sortFields" onChange="this.onSortChange"/>
                    </div>
                    </div>
                    <ul t-if="this.suggestions.length" class="m_search_suggest">
                        <li t-foreach="this.suggestions" t-as="row" t-key="row.key" class="m_search_row_item">
                            <div class="m_search_row_main">
                                <button type="button" class="m_search_row" t-att-data-index="row_index" t-on-click="this.onSuggestionClick">
                                    <t t-esc="this.searchForText(row)"/>
                                </button>
                                <button t-if="row.expandable" type="button" class="m_search_expand" t-att-data-index="row_index"
                                        t-on-click="this.onExpandClick" t-att-aria-expanded="row.expanded ? 'true' : 'false'">
                                    <t t-esc="row.expanded ? '▾' : '▸'"/>
                                </button>
                            </div>
                            <ul t-if="row.expanded" class="m_search_options">
                                <li t-foreach="row.options" t-as="option" t-key="option_index">
                                    <button type="button" class="m_search_option" t-att-data-row="row_index" t-att-data-option="option_index"
                                            t-on-click="this.onOptionClick"><t t-esc="option[1]"/></button>
                                </li>
                            </ul>
                        </li>
                    </ul>
                </div>
                <t t-if="this.state.ready">
                    <t t-component="this.viewComponent" t-key="this.viewKey" t-props="this.viewProps"/>
                </t>
                <MobileFilterSheet t-if="this.state.filterPanel" title="this.texts.filter" sections="this.state.filterPanel"
                    selected="this.state.mobileSelected" onConfirm="this.onMobileFilterConfirm" onClose="this.closeFilters"/>
                <MobileSelectSheet t-if="this.state.filterSheet" title="this.texts.filter" options="this.filterOptions"
                    selected="this.selectedFilterItems" multiple="true" onConfirm="this.onFilterConfirm" onClose="this.closeFilters"/>
                <button type="button" class="m_create_btn" t-if="this.state.ready and this.state.type !== 'form' and this.hasForm"
                        t-on-click="this.onCreateClick">+</button>
            </div>
        </t>
    `;
    static components = { SortMenu, MobileSelectSheet, MobileFilterSheet };
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
            // 顶部搜索: 已生效的条件, 正在输入的文字, 展开的字段与其候选项
            facets: [],
            text: "",
            expanded: null,
            options: {},
            // 排序 (Odoo 排序字符串) 与已选择的筛选项 (筛选项的 key)
            order: "",
            activeFilters: [],
            filterSheet: false,
            // 模型自定义的筛选面板: 已选的选项与卡片, 以及打开时的分组 (含卡片记录)
            mobileSelected: { options: [], cards: {} },
            filterPanel: null,
        });
        this.mobileFilterSections = [];
        this.facetCounter = 0;
        this.orm = useService("orm");
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
        // 搜索视图的筛选项与列表视图的可排序字段一起加载
        const loaded = await this.viewService.loadViews({
            resModel: action.res_model,
            views: /** @type {[number, string][]} */ ([...views, [false, "search"]]),
            context,
        }, /** @type {any} */ ({ actionId: action.id }));
        // 字段定义在模型级别共享, 各视图只有自己的 arch
        this.fields = loaded.fields;
        this.archs = Object.fromEntries(views.map(([, type]) => [type, loaded.views[type].arch]));
        this.filters = parseSearchFilters(loaded.views.search?.arch);
        this.mobileFilterSections = await this.loadMobileFilterConfig(action.res_model);
        this.sortFields = this.computeSortFields();

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
        this.applyFacets();
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
            order: this.state.order,
            onSelect: (resId) => this._onSelectRecord(resId),
        };
    }

    /** 可搜索的字段: 列表 arch 中可筛选的列 (与筛选菜单相同的 filterable 规则) */
    get searchFields() {
        const arch = this.archs.list;
        if (!arch) {
            return [];
        }
        const node = parseArch(arch);
        const columns = node.children
            .filter((c) => c.tag === "field" && c.attrs.name && !isHiddenColumn(c))
            .map((c) => ({ name: c.attrs.name, attrs: c.attrs, field: this.fields[c.attrs.name] }));
        return filterableFields(columns);
    }

    /** 当前输入对应的建议行 */
    get suggestions() {
        return suggestionRows(this.state.text, this.searchFields, this.state.options, this.state.expanded);
    }

    /** 建议行的文字: 搜索 〈字段〉 为: 〈文字〉 */
    searchForText(row) {
        return _t("Search %s for: %s", row.label, row.text);
    }

    /** 按已生效的条件重新计算查询 domain: 动作的 domain 在前, 条件在后 */
    applyFacets() {
        this.state.domain = [
            ...this.baseDomain,
            ...facetsDomain(this.state.facets),
            ...this.activeFilterDomains(),
            ...mobileFilterDomain(this.mobileFilterSections, this.state.mobileSelected),
        ];
    }

    /** 已选择的筛选项对应的条件 (不同筛选项之间为且) */
    activeFilterDomains() {
        const domains = [];
        for (const filter of this.filters || []) {
            if (this.state.activeFilters.includes(filter.key)) {
                try {
                    domains.push(...evaluateExpr(filter.domain));
                } catch {
                    // 无法解析的筛选条件忽略, 不影响其他条件
                }
            }
        }
        return domains;
    }

    /** 排序菜单的字段: 列表(或看板)中标记为 sortable 的字段 */
    computeSortFields() {
        const arch = this.archs.list || this.archs.kanban;
        if (!arch) {
            return [];
        }
        const node = parseArch(arch);
        const columns = node.children
            .filter((c) => c.tag === "field" && c.attrs.name && this.fields[c.attrs.name])
            .map((c) => ({ name: c.attrs.name, attrs: c.attrs, field: this.fields[c.attrs.name] }));
        return sortableFields(columns);
    }

    get filterOptions() {
        return (this.filters || []).map((filter) => ({ id: filter.key, name: filter.label }));
    }

    get hasMobileSelection() {
        const selected = this.state.mobileSelected;
        return selected.options.length > 0 || Object.values(selected.cards).some((ids) => ids.length > 0);
    }

    get selectedFilterItems() {
        return this.filterOptions.filter((option) => this.state.activeFilters.includes(option.id));
    }

    /** 模型自定义的筛选面板配置 (dynamic_filter_config); 没有配置时使用搜索视图的筛选项 */
    async loadMobileFilterConfig(resModel) {
        try {
            return (await this.orm.call(resModel, "dynamic_filter_config", [])) || [];
        } catch {
            return [];
        }
    }

    /** 卡片的记录: 多对一字段对应模型的记录, subfield 作为卡片的第二行 */
    async loadCardRecords({ field, subfield }) {
        const relation = this.fields[field]?.relation;
        if (!relation) {
            return [];
        }
        const names = ["display_name", subfield].filter(Boolean);
        const records = await this.orm.searchRead(relation, [], names, { limit: 80 });
        return records.map((record) => ({
            id: record.id,
            name: record.display_name,
            sub: subfield ? String(record[subfield] || "") : "",
        }));
    }

    async openFilters() {
        if (!this.mobileFilterSections.length) {
            this.state.filterSheet = true;
            return;
        }
        const sections = await Promise.all(
            this.mobileFilterSections.map(async (section) => ({
                ...section,
                cards: section.cards ? { field: section.cards.field, records: await this.loadCardRecords(section.cards) } : null,
            }))
        );
        this.state.filterPanel = sections;
    }

    // 作为子组件的回调传递, 使用箭头函数保持 this
    closeFilters = () => {
        this.state.filterSheet = false;
        this.state.filterPanel = null;
    };

    onMobileFilterConfirm = (selected) => {
        this.state.mobileSelected = selected;
        this.state.filterPanel = null;
        this.applyFacets();
    };

    onFilterConfirm = (selected) => {
        this.state.activeFilters = selected.map((item) => item.id);
        this.state.filterSheet = false;
        this.applyFacets();
    };

    onSortChange = ({ order }) => {
        this.state.order = order;
    };

    addFacet(facet) {
        this.state.facets.push({ ...facet, id: ++this.facetCounter });
        this.state.text = "";
        this.state.expanded = null;
        this.applyFacets();
    }

    onSearchInput(ev) {
        this.state.text = ev.target.value;
        this.state.expanded = null;
    }

    /** 回车: 添加第一个可直接搜索的建议 */
    onSearchKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        const row = this.suggestions.find((r) => !r.expandable);
        if (row) {
            this.addFacet(facetFromRow(row, null));
        }
    }

    onSuggestionClick(ev) {
        const row = this.suggestions[Number(ev.currentTarget.dataset.index)];
        if (row.expandable) {
            return this.toggleExpand(row);
        }
        this.addFacet(facetFromRow(row, null));
    }

    onExpandClick(ev) {
        const row = this.suggestions[Number(ev.currentTarget.dataset.index)];
        return this.toggleExpand(row);
    }

    async toggleExpand(row) {
        if (this.state.expanded === row.name) {
            this.state.expanded = null;
            return;
        }
        this.state.expanded = row.name;
        if (row.type === "many2one") {
            await this.loadRecordOptions(row);
        }
    }

    /** 多对一的候选记录: 按输入的文字做名称搜索 */
    async loadRecordOptions(row) {
        const relation = this.fields[row.name].relation;
        const results = await this.orm.call(relation, "name_search", [], {
            name: row.text,
            operator: "ilike",
            limit: 20,
            context: this.context,
        });
        this.state.options[row.name] = results.map(([id, label]) => [id, label]);
    }

    onOptionClick(ev) {
        const row = this.suggestions[Number(ev.currentTarget.dataset.row)];
        const [value, label] = row.options[Number(ev.currentTarget.dataset.option)];
        this.addFacet(facetFromRow(row, { value, display: label }));
    }

    /** 清除: 删除全部条件与输入的文字 */
    onClearFacets() {
        this.state.facets = [];
        this.state.text = "";
        this.state.expanded = null;
        this.applyFacets();
    }

    onRemoveFacet(ev) {
        this.state.facets.splice(Number(ev.currentTarget.dataset.index), 1);
        this.applyFacets();
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
        this._setNavbarTitle(_t("%s - New", action.display_name || "Odoo"));
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
        envOf(this).bus.trigger("NAVBAR_TITLE:UPDATE", { title });
    }
}
