import fieldRegistryOwl from 'web.field_registry_owl';
import { DashBoardCommonWidget } from '../common/dashboard_widget';


export class DashBoardBarWidget extends DashBoardCommonWidget {
    static props = {
        record: {type: Object, optional: true},
        fieldName: {type: String, optional: true},
        options: {type: Object, optional: true}
    };

    /**
     * @override
     */
    _initChart(attachEl) {
        this.chart = echarts.init(attachEl);
        this.chart.hideLoading();
        this.chart.setOption({
            legend: {},
            tooltip: {
                trigger: 'axis',
                axisPointer: {
                    type: 'shadow'
                }
            },
            dataset: this._getEchartsDataSet(),
            series: this._getEchartsSeries('bar'),
            ...this._getAxis(),
        });

        this.chart.on('click', (params) => this._handleEchartsChartClick(params));
    }

    _getAxis() {
        const direction = this.attrs.direction;
        const categoryAxisConfig = {
            type: 'category',
            axisLabel: {
                interval: 0,
                rotate: 45
            },
            splitLine: {
                show: true
            }
        };
        const valueAxisConfig = {
            type: 'value',
            minorSplitLine: {
                show: true,
            },
            axisLabel: {
                formatter: (v) => this._formatValueHumanReadble(v),
            },
        };

        if (direction === 'horizontal') {
            return {
                xAxis: valueAxisConfig,
                yAxis: categoryAxisConfig
            };
        }
        return {
            xAxis: categoryAxisConfig,
            yAxis: valueAxisConfig
        };
    }
}

fieldRegistryOwl.add("snow_mdm_dashboard_bar", DashBoardBarWidget);
