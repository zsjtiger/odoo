import { Component, onMounted, onPatched, onWillStart, onWillUnmount, proxy, signal, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/views/fields/formatters";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * 仪表盘图表的基类 (字段组件): 字段值为 JSON 数据, 由 echarts 绘制.
 *
 * 数据格式 (每一项):
 *   {name, value, category, filter_domain, dashboard_context?, action_ref?}
 * 点击图表时, 按 name / category 找到数据对应的 domain, 打开列表视图.
 */
export class DashBoardCommonWidget extends Component {
    static template = xml`
        <t t-name="board.DashBoardWidget">
            <div class="snow_mdm_dashboard_chart_container" t-ref="this.chartRef">
                <t t-if="this.showLoading"><t t-esc="this.texts.loading"/></t>
            </div>
        </t>
    `;
    props = useProps({
        ...standardFieldProps,
        options: t.object().optional({}),
    });

    texts = { loading: _t("Loading chart data…") };
    chartRef = signal.ref();
    orm = useService("orm");
    actionService = useService("action");
    asyncState = proxy({ loadComplete: false });

    setup() {
        this.chart = null;
        this._renderedKey = null;
        this._parseFieldData();
        onWillStart(async () => {
            if (this._asyncLoad) {
                await this._loadFieldData(this._asyncCallMethod);
            }
        });
        onMounted(() => this.renderChart());
        onPatched(() => this.renderChart());
        onWillUnmount(() => this.disposeChart());
    }

    /** 字段值: JSON 数组, 或 {async, method} 表示数据需要异步加载 */
    _parseFieldData() {
        const raw = this.props.record.data[this.props.name];
        const parsed = raw ? JSON.parse(raw) : [];
        if (parsed && !Array.isArray(parsed) && "async" in parsed) {
            this._asyncLoad = parsed.async;
            this._asyncCallMethod = parsed.method;
            this._fieldData = [];
        } else {
            this._asyncLoad = false;
            this._fieldData = Array.isArray(parsed) ? parsed : [];
        }
    }

    get showLoading() {
        return this._asyncLoad && !this.asyncState.loadComplete;
    }

    async _loadFieldData(methodName) {
        this._fieldData = await this.orm.call(this.props.record.resModel, methodName, []);
        this._beforeLoadComplete();
        this.asyncState.loadComplete = true;
    }

    /** 异步数据加载完成后调用, 子类可覆盖 */
    _beforeLoadComplete() {}

    /** 数据与配置变化时才重新绘制, 避免每次渲染都重建图表 */
    renderChart() {
        if (this.showLoading) {
            return;
        }
        const key = JSON.stringify([this._fieldData, this.props.options]);
        if (key === this._renderedKey) {
            return;
        }
        this._renderedKey = key;
        const el = this.chartRef();
        if (!el || !window.echarts) {
            return;
        }
        if (!this.chart || this.chart.getDom() !== el) {
            this.disposeChart();
            this.chart = window.echarts.init(el);
        }
        this.chart.setOption(this.getChartOption(), true);
        this.chart.off("click");
        this.chart.on("click", (params) => this._handleEchartsChartClick(params));
    }

    disposeChart() {
        if (this.chart) {
            this.chart.dispose();
            this.chart = null;
        }
    }

    /** 子类实现: 返回 echarts 配置 */
    getChartOption() {
        throw Error("This method needs to be inherited and implemented");
    }

    //------------------------------------------------
    //  dashboardData 转换相关:
    //  二维: {name: <维度1>, value: <维度2>}
    //  多维: {name: <维度1>, <维度3>: <维度2>, <维度3>: <维度2>...}
    //------------------------------------------------

    _getDashboardData() {
        const result = this._fieldData.reduce((resultMap, item) => {
            const title = item.name;
            if (!resultMap[title]) {
                resultMap[title] = { name: title };
            }
            if (item.category === null) {
                resultMap[title]["value"] = item.value;
            } else {
                resultMap[title][item.category] = item.value;
            }
            return resultMap;
        }, {});
        return Object.values(result);
    }

    /** 数据降维: 除 name 之外的所有维度求和, 结果写入 value */
    _mergeDashboardDataDimensions(dashboardData) {
        return dashboardData.map((item) => {
            const dimensionsKeys = Object.keys(item).filter((key) => key !== "name");
            const total = dimensionsKeys.reduce((sum, key) => sum + (item[key] || 0), 0);
            return { name: item.name, value: total };
        });
    }

    //------------------------------------------------
    //  echarts 转换相关
    //------------------------------------------------

    _getEchartsDataSet() {
        return {
            dimensions: this._getEchartsDataSetDimensions(),
            source: this._getDashboardData(),
        };
    }

    _getEchartsDataSetDimensions() {
        const categorySet = new Set();
        this._fieldData.forEach((element) => {
            if (element.category !== null) {
                categorySet.add(element.category);
            }
        });
        return categorySet.size === 0 ? ["name", "value"] : ["name", ...Array.from(categorySet)];
    }

    _getEchartsSeries(type) {
        const seriesCount = this._getEchartsDataSetDimensions().length - 1;
        return Array.from({ length: seriesCount }, () => ({ type }));
    }

    //------------------------------------------------
    //  点击跳转
    //------------------------------------------------

    /** 按 name / category 找到数据项对应的 domain */
    _getDataDomain(name, category) {
        const domain = [];
        const categoryName = !category || ["name", "value"].includes(category) ? null : category;

        const filteredDatas = this._fieldData.filter((d) => d.name === name);
        if (filteredDatas.length === 1) {
            domain.push(...filteredDatas[0].filter_domain);
            return domain;
        }
        if (categoryName === null) {
            // 多维数据但图表不区分维度: 取所有维度共有的 domain
            const allDomainStrings = filteredDatas.map((d) => d.filter_domain.map((f) => JSON.stringify(f)));
            const common = allDomainStrings.reduce((acc, current) => acc.filter((item) => current.includes(item)));
            (common || []).forEach((domainStr) => domain.push(JSON.parse(domainStr)));
            return domain;
        }
        const item = this._fieldData.find((d) => d.name === name && d.category === categoryName);
        return item ? item.filter_domain : domain;
    }

    _getDataField(name, category, field) {
        const categoryName = !category || ["name", "value"].includes(category) ? null : category;
        const item =
            categoryName === null
                ? this._fieldData.find((d) => d.name === name)
                : this._fieldData.find((d) => d.name === name && d.category === categoryName);
        return item ? item[field] : undefined;
    }

    _handleEchartsChartClick(eventParams) {
        this._doPageAction(eventParams?.name, eventParams?.seriesName);
    }

    _doPageAction(name, category) {
        let ctx = { ...(this.props.record.context || {}) };
        const dataActionRef = this._getDataField(name, category, "action_ref");
        if (dataActionRef) {
            this.actionService.doAction(dataActionRef);
            return;
        }

        const domain = [...(this._getDataDomain(name, category) || [])];
        if (Object.prototype.hasOwnProperty.call(ctx, "__dashboard_domain__")) {
            domain.push(...ctx["__dashboard_domain__"]);
            delete ctx["__dashboard_domain__"];
        }
        const dataContext = this._getDataField(name, category, "dashboard_context");
        if (typeof dataContext === "object" && dataContext !== null) {
            ctx = { ...ctx, ...dataContext };
        }

        this.actionService.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: this.props.record.resModel,
            views: [
                [false, "list"],
                [false, "form"],
                [false, "search"],
            ],
            domain,
            target: "current",
            context: ctx,
        });
    }

    /** 大数字缩写显示, 例如 50000 -> 50k */
    _formatValueHumanReadble(value) {
        return formatFloat(value, { humanReadable: true });
    }
}
