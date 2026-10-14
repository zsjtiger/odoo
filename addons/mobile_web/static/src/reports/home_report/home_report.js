import { Component, xml, onWillStart } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";


// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译(模板中用 this.texts 引用)
const TEXTS = {
    more: _t("More >"),
};

export class HomeReport extends Component {
    texts = TEXTS;
    static template = xml`
        <t t-name="mobile_web.HomePage.HomeReport">
            <div class="m_home_page_report card">
                <t t-foreach="this.reportData" t-as="d" t-key="d.name">
                    <div class="report_data">
                        <div class="report_data_value"><t t-esc="d.value"/></div>
                        <div class="report_data_name"><t t-esc="d.name"/></div>
                    </div>
                </t>

                <div class="more_report">
                    <t t-esc="this.texts.more"/>
                </div>
            </div>
        </t>
    `;

    setup() {
        onWillStart(async () => {
            this.reportData = await this._loadReportData();
        })
    }

    /**
     * 
     * @returns {Promise<Object[]>}
     */
    async _loadReportData() {
        return [
            {
                name: _t("Data 1"),
                value: 70
            },
            {
                name: _t("Data 2"),
                value: 33
            },
            {
                name: _t("Data 3"),
                value: 32
            }
        ]
    }
};

