import { Component, xml } from "@crossnow/owl";
import { user } from '@web/core/user';


export class UserInfo extends Component {
    static template = xml`
        <t t-name="mobile_web.HomePage.UserInfo">
            <div class="mobile_home_page_user_info">
                <t t-out="userInfo.userName"/>
            </div>
        </t>
    `;

    setup() {
        this.userInfo = {};

        this.userInfo.userName = user.name || user.UserId;
    }
};
