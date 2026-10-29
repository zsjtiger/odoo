import { describe, expect, test } from "@odoo/hoot";
import { computePlacements, parseBoardArch } from "@reporting/views/board_view";

describe.current.tags("headless");

const ARCH = `
    <form js_class="board">
        <board layout="2-2">
            <action string="Partners" name="base.action_partner_form" view_mode="list" layout="1-1"/>
            <action string="Companies" name="base.action_res_company_form" view_mode="list,form" layout="1-2"/>
        </board>
    </form>
`;

test("the board arch gives the layout and the actions in order", () => {
    const { layout, actions } = parseBoardArch(ARCH);
    expect(layout).toBe("2-2");
    expect(actions.map((a) => a.string)).toEqual(["Partners", "Companies"]);
    expect(actions[1].viewMode).toBe("list,form");
    expect(actions[1].layout).toBe("1-2");
});

test("a board without <board> has no actions", () => {
    expect(parseBoardArch("<form/>").actions).toEqual([]);
});

test("actions are placed from the top left, first fit first", () => {
    const { layout, actions } = parseBoardArch(ARCH);
    const placements = computePlacements(layout, actions);
    expect(placements[0].style).toBe("grid-column: 1 / span 1; grid-row: 1 / span 1;");
    // 第二个动作占 1 行 2 列, 第一行第二列起放不下, 所以放到第二行
    expect(placements[1].style).toBe("grid-column: 1 / span 2; grid-row: 2 / span 1;");
});

test("an action that does not fit is not placed", () => {
    const placements = computePlacements("1-1", [
        { key: "a", layout: "1-1" },
        { key: "b", layout: "1-1" },
    ]);
    expect(placements[0].placed).toBe(true);
    expect(placements[1].placed).toBe(false);
});
