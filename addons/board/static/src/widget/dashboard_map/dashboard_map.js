import { registry } from "@web/core/registry";
import fieldRegistryOwl from 'web.field_registry_owl';
import { DashBoardCommonWidget } from '../common/dashboard_widget';


const formatterRegistry = registry.category("formatters");


export class DashBoardMapWidget extends DashBoardCommonWidget {
    static props = {
        record: {type: Object, optional: true},
        fieldName: {type: String, optional: true},
        options: {type: Object, optional: true}
    };

    /**
     * @override
     */
    _initChart(mapAttachElement) {
        this.mapChart = echarts.init(mapAttachElement);
        
        $.get('/board/static/public/cn_geo.json', (geoJson) => {
            // 注册地图geo json
            this.mapChart.hideLoading();
            echarts.registerMap('CN', geoJson);
            
            // 配置mapChart的显示
            this.mapChart.setOption(this._mapChartOption);

            // 支持点击跳转
            this.mapChart.on('click', (params) => this._handleEchartsChartClick(params));

            // 缩放时的label显示控制
            this.mapChart.on('georoam', (param) => {
                const { totalZoom } = param;
                if (typeof totalZoom === 'number') {
                    this.mapChart.setOption({
                        series: [{
                            label: {
                                show: true ? totalZoom > 2 : false
                            },
                        }]
                    });
                }
            });
        });
    }

    get _mapChartOption() {
        return {
            tooltip: {
                trigger: 'item',
                // formatter: '{b}<br/>{c}',
                formatter: (param) => {
                    const integerFormatter = formatterRegistry.get('integer');
                    const fromattedName = param.data.name;
                    const formattedValue = param.data.value ? integerFormatter(param.data.value) : null ;

                    return `${fromattedName} <br/> ${formattedValue}`;
                },
            },
            visualMap: {
                min: 0,
                max: 100000,
                text: ['High', 'Low'],
                realtime: false,
                calculable: true,
                inRange: {
                    color: ['lightskyblue', 'yellow', 'orangered']
                }
            },
            series: [
                {
                    // 这个series.name一定是value,不要设置成其他的，靠这个来判断后端数据的category是否为空
                    // 自定义options时一定要注意这里，name要么是'value'，要么是后端数据的category字段的值
                    name: 'value',
                    type: 'map',
                    map: 'CN',
                    roam: true,
                    label: {
                        // 放大时会有label显示
                        show: false
                    },
                    zoom: 1.2,
                    scaleLimit: {
                        min: 1,
                        max: 15
                    },
                    data: this._fieldData,
                }
            ]
        };
    }
}

fieldRegistryOwl.add("snow_mdm_dashboard_map", DashBoardMapWidget);
