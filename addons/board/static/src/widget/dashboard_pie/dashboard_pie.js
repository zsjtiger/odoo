/** @crossnow-module **/
import { registry } from "@web/core/registry";
import fieldRegistryOwl from 'web.field_registry_owl';
import { DashBoardCommonWidget } from '../common/dashboard_widget';


const formatterRegistry = registry.category("formatters");


export class DashBoardPieWidget extends DashBoardCommonWidget {
    static props = {
        record: {type: Object, optional: true},
        fieldName: {type: String, optional: true},
        options: {type: Object, optional: true}
    };

    /**
     * @override
     */
    _initChart(lineAttachEl) {
        this.chart = echarts.init(lineAttachEl);
        this.chart.hideLoading();

        const chartSeries = this._getEchartsSeries('pie');
        chartSeries.forEach(s => {
            s.center = ['50%', '60%'];
            s.label = { show: false };
            s.labelLine = { show: false };
        });

        this.chart.setOption({
            tooltip: {
                trigger: "item",
                formatter: (param) => {
                    const integerFormatter = formatterRegistry.get('integer');
                    const fromattedName = param.data.name;
                    const formattedValue = param.data.value ? integerFormatter(param.data.value) : null ;

                    return `${fromattedName} <br/> ${formattedValue}`;
                },
            },
            legend: { type: "scroll" },
            dataset: this._getEchartsDataSet(),
            series: chartSeries,
        });

        this.chart.on('click', (params) => this._handleEchartsChartClick(params));
    }
}

fieldRegistryOwl.add("snow_mdm_dashboard_pie", DashBoardPieWidget);
