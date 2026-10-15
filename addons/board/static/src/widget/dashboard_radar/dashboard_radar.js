import fieldRegistryOwl from 'web.field_registry_owl';
import { DashBoardCommonWidget } from '../common/dashboard_widget';


export class DashBoardRadarWidget extends DashBoardCommonWidget {
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
        this.chart.setOption(this._radarOption);

        this.chart.on('click', (params) => this._handleChartClick(params));
    }

    get _radarOption() {
        const dashboardData = this._getDashboardData();
        
        // 1. 处理数据的维度
        const dimensions = Object.keys(dashboardData[0] || {}).filter(key => key !== 'name');

        // 2. 处理雷达图的数据范围
        const allValues = [];
        dashboardData.forEach(item => {
            dimensions.forEach(dim => {
                if (typeof item[dim] === 'number') {
                    allValues.push(item[dim]);
                }
            });
        });

        const count = allValues.length;
        const sum = allValues.reduce((a, b) => a + b, 0);
        const mean = sum / count;

        const squaredDeviations = allValues.map(v => Math.pow(v - mean, 2));
        const variance = squaredDeviations.reduce((a, b) => a + b, 0) / count;

        const std = Math.sqrt(variance);
        const reasonableMaxValue = mean + 2 * std;  // 使用 (均值 + 2) 倍标准差作为 max
        
        // 3. 设置雷达图的维度
        const indicators = dashboardData.map(item => ({
            name: item.name,
            max: reasonableMaxValue
        }));

        // 4. 填充雷达图数据
        const seriesData = dimensions.map(dim => ({
            name: dim,
            value: dashboardData.map(item => item[dim] || 0)
        }));

        return {
            legend: {
                data: seriesData.map(d => d.name),
                type: 'scroll',
                orient: 'vertical',
                left: 2,
                bottom: 2
                
            },
            tooltip: {
                trigger: 'item'
            },
            radar: {
                indicator: indicators,
            },
            series: [{
                type: 'radar',
                data: seriesData
            }]
        };
    }

    _handleChartClick(eventParams) {
        console.log('The radar chart does not support click do action.');
    }
}

fieldRegistryOwl.add("snow_mdm_dashboard_radar", DashBoardRadarWidget);
