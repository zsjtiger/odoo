import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { defineModels, fields, models, onRpc } from "@web/../tests/web_test_helpers";
import { CascadeField } from "@mobile_web/fields/cascade_field";
import { fieldProps, recordOf } from "@mobile_web/../tests/helpers/field_props";

describe.current.tags("mobile");

class Region extends models.Model {
    _name = "mobile.demo.region";
    name = fields.Char();
    _records = [];
}
defineModels([Region]);

const REGIONS = [
    { id: 1, name: "北京市", parent_id: false, child_ids: [2] },
    { id: 2, name: "北京市", parent_id: [1, "北京市"], child_ids: [3, 4] },
    { id: 3, name: "东城区", parent_id: [2, "北京市"], child_ids: [] },
    { id: 4, name: "西城区", parent_id: [2, "北京市"], child_ids: [] },
];

function mockRegions() {
    onRpc("mobile.demo.region", "search_read", ({ kwargs }) => {
        const parent = kwargs.domain[0][2];
        return REGIONS.filter((r) => (r.parent_id ? r.parent_id[0] : false) === parent).map(
            ({ id, name, child_ids }) => ({ id, name, child_ids })
        );
    });
    onRpc("mobile.demo.region", "read", ({ args }) =>
        REGIONS.filter((r) => args[0].includes(r.id)).map(({ id, name, parent_id }) => ({ id, name, parent_id }))
    );
}

async function settle() {
    for (let i = 0; i < 5; i++) {
        await animationFrame();
    }
}

const FIELD = { type: "many2one", string: "Region", relation: "mobile.demo.region" };

test("the value shows the full path of the region", async () => {
    mockRegions();
    await mountWithCleanup(CascadeField, {
        props: fieldProps({
            name: "region_id",
            field: FIELD,
            record: recordOf({ region_id: [3, "北京市 北京市 东城区"] }),
        }),
    });
    expect(queryOne(".m_picker_value")).toHaveText("北京市 北京市 东城区");
});

test("in readonly mode the path is shown as text without a picker", async () => {
    mockRegions();
    await mountWithCleanup(CascadeField, {
        props: fieldProps({
            name: "region_id",
            field: FIELD,
            readonly: true,
            record: recordOf({ region_id: [3, "北京市 北京市 东城区"] }),
        }),
    });
    expect(queryOne(".m_field_value")).toHaveText("北京市 北京市 东城区");
    expect(queryAll(".m_picker_button").length).toBe(0);
});

test("choosing a sibling in the sheet reports its id and full path", async () => {
    mockRegions();
    const values = [];
    await mountWithCleanup(CascadeField, {
        props: fieldProps({
            name: "region_id",
            field: FIELD,
            record: recordOf({ region_id: [3, "北京市 北京市 东城区"] }),
            onChange: (value) => values.push(value),
        }),
    });
    await click(".m_picker_button");
    await settle();
    await click(queryAll(".m_cascade_sheet .m_sheet_item")[1]);
    await settle();
    await click(queryOne(".m_sheet_btn_primary"));
    await settle();
    expect(values).toEqual([[4, "北京市 北京市 西城区"]]);
});
