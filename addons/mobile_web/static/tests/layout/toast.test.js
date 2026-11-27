import { Component, t, useProps, xml } from "@odoo/owl";
import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { useService } from "@web/core/utils/hooks";
import { MobileToast } from "@mobile_web/layout/toast/toast";

describe.current.tags("mobile");

/**
 * 宿主组件: 通过按钮调用 notification 服务, 与应用中 notify() 的调用方式一致
 */
class Host extends Component {
    static components = { MobileToast };
    static template = xml`
        <div class="host">
            <button class="add-success" t-on-click="this.onSuccess">success</button>
            <button class="add-sticky" t-on-click="this.onSticky">sticky</button>
            <button class="add-quick" t-on-click="this.onQuick">quick</button>
            <MobileToast/>
        </div>
    `;
    notification = useService("notification");
    onSuccess = () => {
        this.notification.add("Saved", { type: "success" });
    };
    onSticky = () => {
        this.notification.add("Something failed", { type: "danger", sticky: true });
    };
    onQuick = () => {
        this.notification.add("Gone soon", { type: "info", autocloseDelay: 300 });
    };
}

async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

test("a notification is shown with its message and type", async () => {
    await mountWithCleanup(Host);
    await click(".add-success");
    await settle();
    expect(queryOne(".m_toast")).toHaveClass("is_success");
    expect(queryOne(".m_toast_message")).toHaveText("Saved");
});

test("the close button removes the notification", async () => {
    await mountWithCleanup(Host);
    await click(".add-sticky");
    await settle();
    expect(queryAll(".m_toast").length).toBe(1);
    await click(".m_toast_close");
    await settle();
    expect(queryAll(".m_toast").length).toBe(0);
});

test("a non-sticky notification closes itself after its delay", async () => {
    await mountWithCleanup(Host);
    await click(".add-quick");
    await settle();
    expect(queryAll(".m_toast").length).toBe(1);
    await new Promise((resolve) => setTimeout(resolve, 500));
    await settle();
    expect(queryAll(".m_toast").length).toBe(0);
});

test("a sticky danger notification stays until it is closed", async () => {
    await mountWithCleanup(Host);
    await click(".add-sticky");
    await settle();
    await new Promise((resolve) => setTimeout(resolve, 200));
    await settle();
    expect(queryOne(".m_toast")).toHaveClass("is_danger");
});
