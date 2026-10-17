import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { user } from "@web/core/services/user";
import { mobilePageRegistry } from "@mobile_web/pages/shared/page_registry";
import { PAGE_KEYS } from "@mobile_web/pages/shared/page_keys";
import { HomePage } from "@mobile_web/pages/home/home_page";
import { UserInfo } from "@mobile_web/pages/home/components/user_info";
import { HomeReport } from "@mobile_web/reports/home_report/home_report";
import { SuggestionList } from "@mobile_web/pages/home/components/suggestion_list";
import { TodoPage } from "@mobile_web/pages/todo/todo_page";
import { SchedulePage } from "@mobile_web/pages/schedule/schedule_page";
import { UserMyPage } from "@mobile_web/pages/my/my_page";
import { MobilePage } from "@mobile_web/pages/shared/components/mobile_page";
import { AIPage } from "@mobile_web/pages/ai/ai_page";

describe.current.tags("mobile");

test("every page key is registered, so the backend page data can be resolved", () => {
    expect(mobilePageRegistry.get(PAGE_KEYS.HOME)).toBe(HomePage);
    expect(mobilePageRegistry.get(PAGE_KEYS.TODO)).toBe(TodoPage);
    expect(mobilePageRegistry.get(PAGE_KEYS.SCHEDULE)).toBe(SchedulePage);
    expect(mobilePageRegistry.get(PAGE_KEYS.MY)).toBe(UserMyPage);
    expect(mobilePageRegistry.get(PAGE_KEYS.AI)).toBe(AIPage);
});

test("the page keys match the backend list", () => {
    expect(Object.values(PAGE_KEYS)).toEqual([
        "mobile_page.home_page",
        "mobile_page.todo_page",
        "mobile_page.schedule_page",
        "mobile_page.user_my_page",
        "mobile_page.ai_page",
    ]);
});

test("pages extend the shared base page", () => {
    expect(HomePage.prototype instanceof MobilePage).toBe(true);
    expect(TodoPage.prototype instanceof MobilePage).toBe(true);
});

test("the user info shows the current user's name", async () => {
    await mountWithCleanup(UserInfo);
    expect(queryOne(".mobile_home_page_user_info")).toHaveText(user.name || String(user.UserId));
});

test("the home report shows its three data points and a more link", async () => {
    await mountWithCleanup(HomeReport);
    expect(queryAll(".report_data").length).toBe(3);
    expect(queryAll(".report_data_name").map((el) => el.textContent)).toEqual(["Data 1", "Data 2", "Data 3"]);
    expect(queryOne(".more_report")).toHaveText("More >");
});

test("the suggestion list shows the empty state", async () => {
    await mountWithCleanup(SuggestionList);
    expect(queryOne(".m_home_page_suggestion strong")).toHaveText("No suggestions yet");
});

test("the todo, schedule and my pages show their titles", async () => {
    await mountWithCleanup(TodoPage);
    expect(queryOne("strong")).toHaveText("To do");
    await mountWithCleanup(SchedulePage);
    expect(queryAll("strong")[1]).toHaveText("Schedule");
    await mountWithCleanup(UserMyPage);
    expect(queryAll("strong")[2]).toHaveText("My");
});
