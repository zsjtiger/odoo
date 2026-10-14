import { Component, xml } from "@odoo/owl";
import { user } from '@web/core/services/user';


export class UserInfo extends Component {
    static template = xml`
        <t t-name="mobile_web.HomePage.UserInfo">
            <div class="mobile_home_page_user_info">
                <t t-out="this.userInfo.userName"/>
            </div>
        </t>
    `;

    setup() {
        this.userInfo = {};

        this.userInfo.userName = user.name;
    }
};
