import { describe, expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { onRpc } from "@web/../tests/web_test_helpers";
import { mobilePageRegistry } from "@mobile_web/pages/shared/page_registry";
import { PAGE_KEYS } from "@mobile_web/pages/shared/page_keys";
import { AIPage } from "@mobile_ai/pages/ai/ai_page";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";

describe.current.tags("mobile");

async function settle() {
    for (let i = 0; i < 10; i++) {
        await animationFrame();
    }
}

test("the AI page is registered for its page key", () => {
    expect(mobilePageRegistry.get(PAGE_KEYS.AI)).toBe(AIPage);
});

test("the AI page shows the not-open placeholder when the AI module is not installed", async () => {
    defineMailModels();
    onRpc("ir.model", "search_count", () => 0);
    await mountWithCleanup(AIPage);
    await settle();
    expect(queryAll(".m_unavailable").length).toBe(1);
    expect(queryAll(".m_ai_composer").length).toBe(0);
});
