import AbstractFieldOwl from 'web.AbstractFieldOwl';
const fieldUtils = require("web.field_utils");
const { FORMAT_OPTIONS } = require('web/static/src/js/views/graph/graph_utils');
const {useState} = owl.hooks;


/**
 * @typedef {[string, string, any]} Domain
 */

/**
 * 
 * @typedef {Object} FieldDataItem
 * @property {string} name
 * @property {number} value
 * @property {string | null} category
 * @property {Domain[]} filter_domain
 * @property {Object} [dashboard_context]
 * @property {string} [adcode]
 * @property {string} [action_ref]
 */

/**
 * @typedef {FieldDataItem[]} FieldData
 */

/**
 * 二维数据
 * @typedef {Object} DashboardDataItem2D
 * @property {string} name
 * @property {number} value
 */

/**
 * 多维数据
 * @typedef {Object<string, number> & { name: string }} DashboardDataItemXD
 */

/**
 * echarts DataSet
 * 
 * reference: https://echarts.apache.org/handbook/zh/concepts/dataset
 * 
 * ```ts
 * type DashboardDataItemXD = Record<string, number | string>;
 * type DimensionsFromSource<T> = Array<keyof T>;
 *
 * type EchartsDataSet<T extends Record<string, any>> = {
 *   dimensions: DimensionsFromSource<T>;
 *   source: T[];
 * };
 * ```
 * 
 * @typedef {Object} EchartsDataSet
 * @property {EchartsDataSetDimensions} dimensions
 * @property {EchartsDataSetSource} source
 */

/**
 * @typedef {string[]} EchartsDataSetDimensions
 * @typedef {DashboardDataItem2D[] | DashboardDataItemXD[]} EchartsDataSetSource
 */

/**
 * Echarts的“系列”，一个系列为一个图表
 * @typedef {EchartsSeriesItem[]} EchartsSeries
 */

/**
 * @typedef {Object} EchartsSeriesItem
 * @property {string} type
 */

/**
 * Echarts EventParam
 * 
 * reference: https://echarts.apache.org/handbook/zh/concepts/event
 * 
 * @typedef {Object} EchartsEventParams
 * @property {string} componentType - 当前点击的图形元素所属的组件名称，如 'series'、'markLine'、'markPoint'、'timeLine' 等。
 * @property {string} seriesType - 系列类型，如 'line'、'bar'、'pie' 等，仅当 componentType 为 'series' 时有意义。
 * @property {number} seriesIndex - 系列在 option.series 中的索引，仅当 componentType 为 'series' 时有意义。
 * @property {string} seriesName - 系列名称，仅当 componentType 为 'series' 时有意义。
 * @property {string} name - 数据名或类目名。
 * @property {number} dataIndex - 数据在原始 data 数组中的索引。
 * @property {Object} data - 原始传入的数据项。
 * @property {string} dataType - 当图表类型为 sankey、graph 等时，表示点击的是 'node' 或 'edge'；其他图表中通常无意义。
 * @property {number|Array} value - 数据对应的数值。
 * @property {string} color - 数据图形的颜色，仅当 componentType 为 'series' 时有意义。
 */


export class DashBoardCommonWidget extends AbstractFieldOwl {
    static template = 'snow_mdm.DashBoardWidget';

    static props = {
        record: {type: Object, optional: true},
        fieldName: {type: String, optional: true},
        options: {type: Object, optional: true}
    };

    setup() {
        super.setup();

        /** @type {FieldData} this._fieldData */
        this._fieldData = JSON.parse(this.value);

        this._asyncLoad = false;
        this._asyncLoadState = useState({ loadComplete: false });

        if (typeof this._fieldData === 'object' && this._fieldData.hasOwnProperty('async')) {
            this._asyncLoad = this._fieldData['async'];
            this._asyncCallMethod = this._fieldData['method'];
        }
    }

    mounted() {
        if (this._showLoading) {
            this._loadFieldData(this._asyncCallMethod);
        } else {
            this._initChart(this.el);
        }
    }

    /**
     * @override
     * 
     * 渲染完template后，执行_initChart方法
     */
    async render(force) {
        return super.render(force).then((r) => {
            if (!this._showLoading && !this.chart) {
                this._initChart(this.el);
            }
        });
    }

    willUnmount() {
        this.chart && this.chart.dispose();
    }

    _initChart(attachEl) {
        throw Error('This method needs to be inherited and implemented');
    }

    //------------------------------------------------
    //  dashboardData 转换相关:
    //  二维: {name: <维度1>, value: <维度2>}
    //  多维: {name: <维度1>, <维度3>: <维度2>, <维度3>: <维度2>...}
    //------------------------------------------------

    /**
     * 将 @type {FieldData} 解析为 dashboardData
     * 
     * @returns {DashboardDataItem2D[] | DashboardDataItemXD[]} dashboardData
     */
    _getDashboardData() {
        const result = this._fieldData.reduce((resultMap, item) => {
            const title = item.name;
            
            if (!resultMap[title]) {
                resultMap[title] = { name: title };
            }
            
            if (item.category === null) {
                resultMap[title]['value'] = item.value;
            } else {
                resultMap[title][item.category] = item.value;
            }

            return resultMap;
        }, {});
        
        return Object.values(result);
    }

    /**
     * 数据降维，将除了'name'之外的所有key，其value相加，并赋值给'value'
     * 
     * @param {DashboardDataItemXD[] | DashboardDataItem2D[]} dashboardData
     * @returns {DashboardDataItem2D[]} dashboardData2D
     */
    _mergeDashboardDataDimensions(dashboardData) {
        return dashboardData.map(item => {
            const dimensionsKeys = Object.keys(item).filter(key => key !== 'name');
            const total = dimensionsKeys.reduce((sum, key) => sum + (item[key] || 0), 0);
            return {
                name: item.name,
                value: total
            };
        });
    }

    //------------------------------------------------
    //  Echarts 转换相关
    //------------------------------------------------

    /**
     * 从 @type {FieldData} 从解析出 echartsDataSet
     * 
     * @returns {EchartsDataSet} echartsDataSet
     */
    _getEchartsDataSet() {
        return {
            'dimensions': this._getEchartsDataSetDimensions(),
            'source': this._getEchartsDataSetSource()
        };
    }

    /**
     * @returns {EchartsDataSetSource}
     */
    _getEchartsDataSetSource() {
        return this._getDashboardData();
    }

    /**
     * @returns {EchartsDataSetDimensions}
     */
    _getEchartsDataSetDimensions() {
        const categorySet = new Set();

        this._fieldData.forEach(element => {
            if (element.category !== null) {
                categorySet.add(element.category);
            }
        });

        const dimensions = categorySet.size === 0 ? ['name', 'value'] : ['name', ...Array.from(categorySet)];
        return dimensions;
    }

    /**
     * 
     * @param {string} type 
     * @returns {EchartsSeries}
     */
    _getEchartsSeries(type) {
        const dm = this._getEchartsDataSetDimensions();
        const seriesCount = dm.length - 1;
        
        return Array.from({length: seriesCount}, () => ({type: type}));
    }

    //------------------------------------------------
    //  Event Handler & Tools
    //------------------------------------------------

    /**
     * 从 @type {FieldData} 中，通过name, category 定位 @type {FieldDataItem} 然后获取filter_domain字段
     * 
     * @param {string} name 
     * @param {string} [category]
     * @returns {Domain[]} dataDomain
     */
    _getDataDomain(name, category) {
        const domain = [];
        const filterName = name;
        const categoryName = !category || ['name', 'value'].includes(category) ? null : category;

        // 在_fieldData里寻找, 先使用name
        const filteredDatas = this._fieldData.filter(d => d.name === filterName);
        if (filteredDatas.length === 1) {
            domain.push(...filteredDatas[0].filter_domain);
            return domain;
        }

        // 多于1个data, 当前的_fieldData属于多维数据
        if (categoryName === null) {
            // categoryName 为 null，说明图表不支持多维数据展示，聚合domain
            const allCategoryDomainStrings = [];
            filteredDatas.forEach(d => {
                const domainStrings = [];
                d.filter_domain.forEach(f => domainStrings.push(JSON.stringify(f)));
                allCategoryDomainStrings.push(domainStrings);
            });
            // 找到共有的domain
            const commonDomains = allCategoryDomainStrings.reduce((common, current) => {
                return common.filter(item => current.includes(item)); 
            });
            commonDomains.forEach(domainStr => domain.push(JSON.parse(domainStr)));
            return domain;
        } else {
            const filteredDatas = this._fieldData.find(d => d.name === filterName && d.category === categoryName);
            return filteredDatas.filter_domain;
        }
    }

    /**
     * 从 @type {FieldData} 中，通过name, category 定位 @type {FieldDataItem} 然后获取dashboard_context字段
     * 
     * @param {string} name 
     * @param {string} [category] 
     * @returns {Object}
     */
    _getDataContext(name, category) {
        return this._getDataField(name, category, 'dashboard_context');
    }

    /**
     * 从 @type {FieldData} 中，通过name, category 定位 @type {FieldDataItem} 然后获取action_ref字段
     * 
     * @param {string} name 
     * @param {string} [category] 
     * @returns {string}
     */
    _getDataActionRef(name, category) {
        return this._getDataField(name, category, 'action_ref');
    }

    /**
     * 通用方法，从 @type {FieldData} 中，通过name, category 定位 @type {FieldDataItem} 然后获取 field参数 指定的字段
     * 
     * @param {string} name 
     * @param {string} [category] 
     * @param {string} field 
     * @returns 
     */
    _getDataField(name, category, field) {
        const filterName = name;
        const categoryName = !category || ['name', 'value'].includes(category) ? null : category;

        if (categoryName === null) {
            const fd = this._fieldData.find(d => d.name === filterName);
            return fd[field];
        } else {
            const fd = this._fieldData.find(d => d.name === filterName && d.category === categoryName);
            return fd[field];
        }
    }

    /**
     * @param {EchartsEventParams} eventParams 
     */
    _handleEchartsChartClick(eventParams) {
        const filterName = eventParams?.name;
        const categoryName = eventParams?.seriesName;
        this._doPageAction(filterName, categoryName);
    }

    _doPageAction(name, category) {
        let ctx = this.record.getContext();
        const filterDomain = this._getDataDomain(name, category);
        const dataContext = this._getDataContext(name, category);
        const dataActionRef = this._getDataActionRef(name, category);

        // 如果配置了dataActionRef, 直接跳转
        if (dataActionRef) {
            this.trigger('do_action', {
                action: dataActionRef
            });
            return;
        }

        const domain = [];
        if (filterDomain) {
            filterDomain.forEach(d => domain.push(d));
        }
        // 统一的domain
        if (ctx.hasOwnProperty('__dashboard_domain__')) {
            const additionalDomain = ctx['__dashboard_domain__'];
            additionalDomain.forEach(d => domain.push(d));
            delete ctx.dashboard_domain;
        }
        // 存在于field_data上的指定context
        if (typeof dataContext === 'object') {
            ctx = Object.assign({}, ctx, dataContext);
        }

        const action = {
            type: 'ir.actions.act_window',
            name: name,
            res_model: this.model,
            view_mode: 'list,form,search',
            views: [
                [false, 'list'],
                [false, 'form'],
                [false, 'search'],
            ],
            domain: domain,
            target: 'current',
            context: ctx
        };

        this.trigger('do_action', {
            action: action
        });
    }

    /**
     * 将大数字缩写为可读性高的字符串，比如50000 -> 50k
     * 
     * @param {number} value 
     * @returns {string}
     */
    _formatValueHumanReadble(value) {
        const formatter = fieldUtils.format.float;
        return formatter(value, undefined, FORMAT_OPTIONS);
    }

    //------------------------------------------------
    //  异步加载相关
    //------------------------------------------------

    get _showLoading() {
        return this._asyncLoad && ! this._asyncLoadState.loadComplete;
    }

    _loadFieldData(methodName) {
        return this.env.services.rpc({
            'model': this.model,
            'method': methodName
        }).then((res) => {
            this._fieldData = res;
        }).then(() => {
            this._beforeLoadComplete();
        }).then(() => {
            this._asyncLoadState.loadComplete = true;
        })
    }

    /**
     * 在_loadFieldData将重新渲染组件之前调用的方法，可以重写此方法实现自定义功能
     * 参考card
     */
    _beforeLoadComplete() {}
}
