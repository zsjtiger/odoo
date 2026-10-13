import { Component, xml } from "@crossnow/owl";


export class SuggestionList extends Component {
    static template = xml`
        <t t-name="mobile_web.HomePage.SuggestionList">
            <div class="m_home_page_suggestion card">
                <strong>暂无推荐内容</strong>
            </div>
        </t>
    `;
};
