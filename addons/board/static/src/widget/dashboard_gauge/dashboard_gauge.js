/** @crossnow-module **/
import fieldRegistryOwl from 'web.field_registry_owl';
import { DashBoardCommonWidget } from '../common/dashboard_widget';


export class DashBoardGaugeWidget extends DashBoardCommonWidget {
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
        this.chart.setOption(this._getGaugeOption());

        this.chart.on('click', (params) => this._handleEchartsChartClick(params));
    }

    _getGaugeOption() {
        const gaugeData = [];
        const dashboardData = this._mergeDashboardDataDimensions(this._getDashboardData());
        const minSize = Math.min(this.el.clientHeight, this.el.clientWidth);

        // value相关
        const valueTotal = dashboardData.reduce((sum, item) => sum + item.value, 0);

        // 仪表图例显示相关，与data一起定义，无法拆开
        const dataCount = dashboardData.length;

        dashboardData.forEach((item, index) => {
            // 图表的数据
            const data = {
                name: item.name,
                value: parseFloat(((item.value / valueTotal) * 100).toFixed(2)),
            }

            // 宽度自适应, 调整不同的图例显示方式
            const legendInfo = {
                title: { fontSize: 11 },
                detail: { fontSize: 11 },
            };
            if (minSize < 200) {
                const titleGapY = 200 / dataCount;  // 用来控制图例之间的间距
                const yOffsetCenter = `${(index - (dataCount - 1) / 2) * titleGapY}%`;

                legendInfo.title.offsetCenter = ['-250%', yOffsetCenter];
                legendInfo.detail.offsetCenter = ['-150%', yOffsetCenter];
            } else {
                const titleGapX = 200 / dataCount;  // 用来控制图例之间的间距
                const xOffsetCenter = `${(index - (dataCount - 1) / 2) * titleGapX}%`;

                legendInfo.title.offsetCenter = [xOffsetCenter, '80%'];
                legendInfo.detail.offsetCenter = [xOffsetCenter, '100%'];
            }

            gaugeData.push({...data, ...legendInfo});
        })

        return {
            series: [
                {
                    name: 'value',
                    type: 'gauge',
                    anchor: {
                        show: true,
                        showAbove: true,
                        size: 18,
                        itemStyle: {
                            color: '#FAC858'
                        }
                    },
                    progress: {
                        show: true,
                        overlap: true,
                        roundCap: true
                    },
                    pointer: {
                        icon: 'path://M2.9,0.7L2.9,0.7c1.4,0,2.6,1.2,2.6,2.6v115c0,1.4-1.2,2.6-2.6,2.6l0,0c-1.4,0-2.6-1.2-2.6-2.6V3.3C0.3,1.9,1.4,0.7,2.9,0.7z',
                        width: 4,
                        length: '80%',
                        offsetCenter: [0, '8%']
                    },
                    axisLine: {
                        roundCap: true
                    },
                    data: gaugeData,
                    detail: {
                        width: 20,
                        height: 11,
                        fontSize: 14,
                        color: '#fff',
                        backgroundColor: 'inherit',
                        borderRadius: 3,
                        formatter: '{value}%'
                    },
                    axisLabel: {
                        show: minSize < 200 ? false : true,
                    },
                }
            ]
        };
    }
}

fieldRegistryOwl.add("snow_mdm_dashboard_gauge", DashBoardGaugeWidget);
