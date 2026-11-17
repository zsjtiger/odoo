import { render } from "@web/core/owl/utils";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/framework/registry";
import { rpc } from "@web/core/services/network/rpc";
import { KeepLast } from "@web/core/utils/concurrency";
import {
    Component,
    markup,
    onWillStart,
    onWillUnmount,
    onWillUpdateProps,
    t,
    useProps,
    xml,
} from "@odoo/owl";
import { useStudioServiceAsReactive } from "@web_builder/studio_service";
import { resetViewCompilerCache } from "@web/views/view_compiler";

const editorTabRegistry = registry.category("web_builder.editor_tabs");

export class StudioActionContainer extends Component {
    props = useProps({
        reloadId: t.number(),
    });

    static template = xml`
        <t t-name="web.ActionContainer">
        <div class="o_action_manager">
            <t t-if="this.info.Component" t-component="this.info.Component" className="'o_action'" t-props="this.info.componentProps" t-key="this.info.id"/>
        </div>
        </t>`;

    setup() {
        this.actionService = useService("action");
        this.studio = useStudioServiceAsReactive();
        this.info = {};

        let actionKey = 1;
        const onUiUpdate = ({ detail: info }) => {
            this.info = info;
            actionKey++;
            render(this);
        };
        this.env.bus.addEventListener("ACTION_MANAGER:UPDATE", onUiUpdate);
        onWillUnmount(() => this.env.bus.removeEventListener("ACTION_MANAGER:UPDATE", onUiUpdate));

        const doAction = async (action, options) => {
            try {
                await this.actionService.doAction(action, options);
                this.actionKey = actionKey;
            } catch (e) {
                if (action !== "web_builder.action_editor") {
                    // Fallback on the actionEditor, except if the actionEditor crashes
                    this.studio.setParams({ editorTab: "views" });
                }
                // Rethrow anyway: the error doesn't originates from a user's action
                throw e;
            }
        };

        onWillStart(async () => {
            const action = await this.getStudioAction();
            this.studioKey = this.studio.requestId;
            doAction(action);
            await Promise.resolve();
        });

        const willUpdateKeepLast = new KeepLast();
        onWillUpdateProps(async () => {
            if (this.studio.requestId !== this.studioKey || this.actionKey !== actionKey) {
                const action = await willUpdateKeepLast.add(this.getStudioAction());
                resetViewCompilerCache();
                return new Promise((_resolve) => {
                    const resolve = () => {
                        this.env.bus.removeEventListener("ACTION_MANAGER:UPDATE", resolve);
                        _resolve();
                    };
                    this.studioKey = this.studio.requestId;
                    doAction(action, { clearBreadcrumbs: true, noEmptyTransition: true }).finally(
                        () => {
                            this.env.bus.removeEventListener("ACTION_MANAGER:UPDATE", resolve);
                        }
                    );
                    this.env.bus.addEventListener("ACTION_MANAGER:UPDATE", resolve);
                });
            }
        });
    }
    async getStudioAction() {
        const { editorTab, editedAction, editedReport, editedViewType } = this.studio;
        const tab = editorTabRegistry.get(editorTab);
        if (editorTab === "views") {
            if (editedViewType) {
                return "web_builder.view_editor";
            }
            return tab.action;
        }
        if (tab.action) {
            const action = tab.action;
            return action instanceof Function ? action(this.env) : action;
        } else if (editorTab === "reports" && editedReport) {
            return "web_builder.report_editor";
        } else {
            const action = await rpc("/web_builder/get_studio_action", {
                action_name: editorTab,
                model: editedAction.res_model,
                view_id: editedAction.view_id && editedAction.view_id[0], // Not sure it is correct or desirable
            });
            action.help = action.help && markup(action.help);
            return action;
        }
    }
}
