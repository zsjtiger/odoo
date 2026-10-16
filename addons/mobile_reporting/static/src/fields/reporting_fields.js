import { onWillUpdateProps, t, useProps } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { DashBoardCommonWidget } from "@reporting/widget/common/dashboard_widget";
import { DashBoardBarWidget } from "@reporting/widget/dashboard_bar/dashboard_bar";
import { DashBoardCardWidget } from "@reporting/widget/dashboard_card/dashboard_card";
import { DashBoardGaugeWidget } from "@reporting/widget/dashboard_gauge/dashboard_gauge";
import { DashBoardLineWidget } from "@reporting/widget/dashboard_line/dashboard_line";
import { DashBoardMapWidget } from "@reporting/widget/dashboard_map/dashboard_map";
import { DashBoardPieWidget } from "@reporting/widget/dashboard_pie/dashboard_pie";
import { DashBoardRadarWidget } from "@reporting/widget/dashboard_radar/dashboard_radar";
import { GALLERY_WIDGETS } from "@reporting/widget/gallery/gallery_charts";

/**
 * 移动端的图表部件: 继承桌面端 reporting 的图表部件 (数据转换, echarts 配置都复用),
 * 只替换移动端不同的部分:
 *  - 模型名取自字段组件的 resModel (移动端的记录适配层没有 resModel / context)
 *  - 点击图表打开的动作使用移动端的列表视图
 *
 * @param {typeof DashBoardCommonWidget} Base 桌面端的图表部件
 */
function mobileChart(Base) {
    return class extends Base {
        // 桌面端部件的 props 不含 resModel, 移动端的字段组件会传入, 需要在此声明
        props = useProps({
            ...standardFieldProps,
            options: t.object().optional({}),
            resModel: t.string().optional(),
        });

        setup() {
            super.setup();
            // 移动端表单先以空值渲染, 记录加载后字段值才到达: 此时重新解析图表数据
            onWillUpdateProps((nextProps) => this._parseFieldData(nextProps));
        }

        _parseFieldData(props = this.props) {
            const raw = props.record.data[props.name];
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

        async _loadFieldData(methodName) {
            this._fieldData = await this.orm.call(this.props.resModel, methodName, []);
            this._beforeLoadComplete();
            this.asyncState.loadComplete = true;
        }

        _doPageAction(name, category) {
            const actionRef = this._getDataField(name, category, "action_ref");
            if (actionRef) {
                this.actionService.doAction(actionRef);
                return;
            }
            const context = this._getDataField(name, category, "dashboard_context");
            this.actionService.doAction({
                type: "ir.actions.act_window",
                name,
                res_model: this.props.resModel,
                views: [[false, "list"]],
                domain: [...(this._getDataDomain(name, category) || [])],
                target: "current",
                context: typeof context === "object" && context !== null ? context : {},
            });
        }
    };
}

// 与 reporting 视图中的部件名一致 (board_dashboard_*), 移动端按同样的名字查找
const CHART_WIDGETS = {
    board_dashboard_bar: DashBoardBarWidget,
    board_dashboard_line: DashBoardLineWidget,
    board_dashboard_pie: DashBoardPieWidget,
    board_dashboard_gauge: DashBoardGaugeWidget,
    board_dashboard_radar: DashBoardRadarWidget,
    board_dashboard_card: DashBoardCardWidget,
    board_dashboard_map: DashBoardMapWidget,
};

// 扩展图表 (平滑/堆叠/标注折线, 饼图联动, 极坐标柱, 横向柱, 断轴柱, 渐变柱) 与桌面端共用同一个部件名
Object.assign(CHART_WIDGETS, GALLERY_WIDGETS);

for (const [name, Base] of Object.entries(CHART_WIDGETS)) {
    mobileFieldRegistry.add(name, mobileChart(Base));
}
