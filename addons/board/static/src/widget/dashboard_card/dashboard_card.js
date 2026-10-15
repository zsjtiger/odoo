/** @crossnow-module **/
import { registry } from "@web/core/registry";
import fieldRegistryOwl from 'web.field_registry_owl';
import { DashBoardCommonWidget } from "../common/dashboard_widget";


const formatterRegistry = registry.category("formatters");


export class DashBoardCardWidget extends DashBoardCommonWidget {
    static props = {
        record: {type: Object, optional: true},
        fieldName: {type: String, optional: true},
        options: {type: Object, optional: true}
    };

    static template = "snow_mdm.DashBoardCardFieldWidget";

    /**
     * @override
     * 同步加载 this._dashboardData 用于渲染card
     */
    setup() {
        super.setup();
        if (! this._showLoading) {
            this._dashboardData = this._mergeDashboardDataDimensions(this._getDashboardData());
        }   
    }

    /**
     * @override
     * 异步加载回掉, 用于加载 this._dashboardData 用于渲染card
     */
    _beforeLoadComplete() {
        this._dashboardData = this._mergeDashboardDataDimensions(this._getDashboardData());
    }

    /**
     * @override
     */
    _initChart(attachEl) {
        const cardContainerEl = attachEl.querySelector('.snow_mdm_dashboard_card_container');
        const columnCount = parseInt(this.attrs.column);
        const totalCardCount = this._dashboardData.length;
        if (columnCount) {
            // 补充placeholder
            const desiredItems = Math.ceil(totalCardCount / columnCount) * columnCount;
            const toAdd = desiredItems - totalCardCount;

            for (let i = 0; i < toAdd; i++) {
                const placeholder = document.createElement("div");
                placeholder.classList.add("snow_mdm_dashboard_card", "snow_mdm_dashboard_card_placeholder"); // 空白项样式类名
                cardContainerEl.appendChild(placeholder);
            }

            const items = cardContainerEl.querySelectorAll('.snow_mdm_dashboard_card');
            // 设置card的宽度为统一的宽度
            items.forEach(element => {
                element.style.flexBasis = `calc(${(100 / columnCount)}% - 20px)`;
            });
        } else {
            const items = cardContainerEl.querySelectorAll('.snow_mdm_dashboard_card');
            items.forEach(element => {
                element.style.flexGrow = 1;
            });
        }
    }

    _onItemClick(ev) {
        const filterName = ev.currentTarget.dataset.dataName;
        this._doPageAction(filterName, null);
    }

    _fromatInteger(value) {
        if (value) {
            const integerFormatter = formatterRegistry.get('integer');
            return integerFormatter(value);
        }
    }
}

fieldRegistryOwl.add("snow_mdm_dashboard_card", DashBoardCardWidget);
