import fieldRegistryOwl from 'web.field_registry_owl';
import { DashBoardCommonWidget } from '../common/dashboard_widget';


export class DashBoardLineWidget extends DashBoardCommonWidget {
    static props = {
        record: {type: Object, optional: true},
        fieldName: {type: String, optional: true},
        options: {type: Object, optional: true}
    };

    /**
     * @override
     */
    mounted() {
        this._formatValueHumanReadble();
        super.mounted();
    }

    /**
     * @override
     */
    _initChart(lineAttachEl) {
        this.chart = echarts.init(lineAttachEl);
        this.chart.hideLoading();
        this.chart.setOption({
            legend: {},
            tooltip: {trigger: 'axis'},
            dataset: this._getEchartsDataSet(),
            xAxis: {
                type: 'category',
                axisLabel: {
                    interval: 0,
                    rotate: 45
                },
                splitLine: {
                    show: true
                }
            },
            yAxis: {
                type: 'value',
                minorSplitLine: {
                    show: true,
                },
                axisLabel: {
                    formatter: (v) => this._formatValueHumanReadble(v),
                },
            },
            series: this._getEchartsSeries('line'),
        });

        this.chart.on('click', (params) => this._handleEchartsChartClick(params));
    }
}

fieldRegistryOwl.add("snow_mdm_dashboard_line", DashBoardLineWidget);
