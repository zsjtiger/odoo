import { Component, xml, onWillStart } from "@odoo/owl";


export class HomeReport extends Component {
    static template = xml`
        <t t-name="mobile_web.HomePage.HomeReport">
            <div class="m_home_page_report card">
                <t t-foreach="reportData" t-as="d" t-key="d">
                    <div class="report_data">
                        <div class="report_data_value"><t t-esc="d.value"/></div>
                        <div class="report_data_name"><t t-esc="d.name"/></div>
                    </div>
                </t>

                <div class="more_report">
                    更多>
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
     * @returns {Object[]}
     */
    async _loadReportData() {
        return [
            {
                name: '数据1',
                value: 70
            },
            {
                name: '数据2',
                value: 33
            },
            {
                name: '数据3',
                value: 32
            }
        ]
    }
};

