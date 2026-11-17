import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { FileButton } from "@mobile_web/widgets/file_button/file_button";

describe.current.tags("mobile");

async function waitFor(check) {
    for (let i = 0; i < 50; i++) {
        if (check()) {
            return;
        }
        await new Promise((resolve) => setTimeout(resolve, 10));
    }
}

test("the button shows its label and the file input is hidden", async () => {
    await mountWithCleanup(FileButton, { props: { label: "Select image", onFile: () => {} } });
    expect(queryOne("button")).toHaveText("Select image");
    expect(queryOne("input[type=file]")).toHaveClass("m_visually_hidden");
});

test("the file input accepts images and uses the requested capture", async () => {
    await mountWithCleanup(FileButton, {
        props: { label: "Take photo", capture: "environment", onFile: () => {} },
    });
    const input = queryOne("input[type=file]");
    expect(input).toHaveAttribute("accept", "image/*");
    expect(input).toHaveAttribute("capture", "environment");
});

test("choosing a file reports its content as base64", async () => {
    const values = [];
    await mountWithCleanup(FileButton, {
        props: { label: "Select image", onFile: (value) => values.push(value) },
    });
    const input = queryOne("input[type=file]");
    const data = new DataTransfer();
    data.items.add(new File(["abc"], "a.png", { type: "image/png" }));
    input.files = data.files;
    input.dispatchEvent(new Event("change"));
    await waitFor(() => values.length > 0);
    expect(values).toEqual(["YWJj"]);
});

test("cancelling the picker reports nothing", async () => {
    const values = [];
    await mountWithCleanup(FileButton, {
        props: { label: "Select image", onFile: (value) => values.push(value) },
    });
    queryOne("input[type=file]").dispatchEvent(new Event("change"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(values).toEqual([]);
});
