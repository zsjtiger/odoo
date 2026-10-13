import { Component, xml } from "@odoo/owl";


export class SvgIcon extends Component {
    static components = {};
    static props = {
        iconHref: [String, Boolean],
        className: [String, Boolean],
    };
    static defaultProps = {
        iconHref: false,
        className: false
    };

    static template = xml`
        <t t-name="mobile_web.SvgIcon">
            <t t-if="props.iconHref">
                <div>
                    <svg t-att-class="props.className or 'm_svg_icon'">
                        <use t-att="{'href': props.iconHref}"></use>
                    </svg>
                </div>
            </t>
        </t>
    `;
}
