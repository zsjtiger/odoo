import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { onRpc } from "@web/../tests/web_test_helpers";
import { TodoPage } from "@mobile_web/pages/todo/todo_page";
import { SchedulePage } from "@mobile_web/pages/schedule/schedule_page";
import { UserMyPage } from "@mobile_web/pages/my/my_page";
import { Unavailable } from "@mobile_web/pages/shared/components/unavailable";
import { isModelAvailable } from "@mobile_web/pages/shared/data/model_access";
import { patchTranslations } from "@web/../tests/_framework/translation_test_helpers";

describe.current.tags("mobile");

async function settle() {
    for (let i = 0; i < 10; i++) {
        await animationFrame();
    }
}

/** 模拟模块是否安装: ir.model 中是否存在该模型 */
function modelInstalled(installed) {
    onRpc("ir.model", "search_count", () => (installed ? 1 : 0));
}

test("a model that is not installed is reported as unavailable", async () => {
    modelInstalled(false);
    expect(await isModelAvailable({ call: async () => 0 }, "mail.activity")).toBe(false);
    expect(await isModelAvailable({ call: async () => 1 }, "mail.activity")).toBe(true);
    expect(await isModelAvailable({ call: async () => { throw new Error("x"); } }, "mail.activity")).toBe(false);
});

test("the unavailable placeholder says the feature is not open yet", async () => {
    patchTranslations({});
    await mountWithCleanup(Unavailable);
    expect(queryOne(".m_unavailable")).toHaveText("Not available yet");
});

test("the todo page shows the not-open placeholder when mail is not installed", async () => {
    modelInstalled(false);
    await mountWithCleanup(TodoPage);
    await settle();
    expect(queryAll(".m_unavailable").length).toBe(1);
    expect(queryAll(".m_plain_list").length).toBe(0);
});

test("the todo page lists the current user's activities when mail is installed", async () => {
    modelInstalled(true);
    onRpc("mail.activity", "search_read", () => [
        { id: 1, summary: "Call Alpha", res_name: "Alpha", date_deadline: "2026-10-20" },
        { id: 2, summary: false, res_name: "Beta", date_deadline: "2026-10-21" },
    ]);
    await mountWithCleanup(TodoPage);
    await settle();
    expect(queryAll(".m_plain_list_title").map((el) => el.textContent)).toEqual(["Call Alpha", "Beta"]);
});

test("the todo page says so when there is nothing to do", async () => {
    modelInstalled(true);
    onRpc("mail.activity", "search_read", () => []);
    patchTranslations({});
    await mountWithCleanup(TodoPage);
    await settle();
    expect(queryOne(".m_empty")).toHaveText("Nothing to do");
});

test("the schedule page shows the not-open placeholder when the calendar is not installed", async () => {
    modelInstalled(false);
    await mountWithCleanup(SchedulePage);
    await settle();
    expect(queryAll(".m_unavailable").length).toBe(1);
});

test("the schedule page lists today's events when the calendar is installed", async () => {
    modelInstalled(true);
    onRpc("calendar.event", "search_read", () => [{ id: 5, name: "Review", start: "2026-10-14 09:00:00" }]);
    await mountWithCleanup(SchedulePage);
    await settle();
    expect(queryAll(".m_plain_list_title")[0]).toHaveText("Review");
});

test("the my page shows the current user's name, login, email and company", async () => {
    onRpc("res.users", "read", () => [
        { id: 2, name: "Administrator", login: "admin", email: "admin@example.com", company_id: [1, "My Company"] },
    ]);
    await mountWithCleanup(UserMyPage);
    await settle();
    expect(queryAll(".m_my_info dd").map((el) => el.textContent)).toEqual([
        "Administrator",
        "admin",
        "admin@example.com",
        "My Company",
    ]);
});
