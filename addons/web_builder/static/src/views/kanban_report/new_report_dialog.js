import { Component, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialogs/dialog/dialog";
import { _t } from "@web/core/data/l10n/translation";
import { rpc } from "@web/core/services/network/rpc";
import { user } from "@web/core/services/user";

export class NewReportDialog extends Component {
    static template = "web_builder.NewReportDialog";
    static components = { Dialog };
    props = useProps({
        resModel: t.any(),
        onReportCreated: t.any(),
        close: t.any(),
    });

    setup() {
        this.layouts = [
            {
                name: "web.external_layout",
                label: _t("External"),
                description: _t("Business header/footer"),
            },
            {
                name: "web.internal_layout",
                label: _t("Internal"),
                description: _t("Minimal header/footer"),
            },
            {
                name: "web.basic_layout",
                label: _t("Blank"),
                description: _t("No header/footer"),
            },
        ];
    }

    async createNewReport(layout) {
        const report = await rpc("/web_builder/create_new_report", {
            model_name: this.props.resModel,
            layout,
            context: user.context,
        });
        this.props.onReportCreated(report);
        this.props.close();
    }
}
