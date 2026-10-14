import { describe, expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { SvgIcon } from "@mobile_web/common/components/svg_icon";

describe.current.tags("mobile");

test("an icon renders an svg use element pointing at the sprite symbol", async () => {
    await mountWithCleanup(SvgIcon, { props: { iconHref: "#crossnow-icon-Home" } });
    expect(queryOne("svg use")).toHaveAttribute("href", "#crossnow-icon-Home");
});

test("the default class is m_svg_icon, and a custom class replaces it", async () => {
    await mountWithCleanup(SvgIcon, { props: { iconHref: "#a" } });
    expect(queryOne("svg")).toHaveClass("m_svg_icon");
    await mountWithCleanup(SvgIcon, { props: { iconHref: "#a", className: "action_icon" } });
    expect(queryAll("svg")[1]).toHaveClass("action_icon");
});

test("nothing is rendered without an icon href", async () => {
    await mountWithCleanup(SvgIcon, { props: { iconHref: false } });
    expect(queryAll("svg").length).toBe(0);
});
