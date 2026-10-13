import { Component, t, useProps, xml } from "@odoo/owl";


export class SvgIcon extends Component {
    static components = {};
    props = useProps({
        iconHref: t.or([t.string(), t.boolean()]).optional(false),
        className: t.or([t.string(), t.boolean()]).optional(false),
    });

    static template = xml`
        <t t-name="mobile_web.SvgIcon">
            <t t-if="this.props.iconHref">
                <div>
                    <svg t-att-class="this.props.className or 'm_svg_icon'">
                        <use t-att="{'href': this.props.iconHref}"></use>
                    </svg>
                </div>
            </t>
        </t>
    `;
}
