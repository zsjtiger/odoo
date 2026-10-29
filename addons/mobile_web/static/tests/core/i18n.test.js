import { describe, expect, test } from "@odoo/hoot";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { patchTranslations } from "@web/../tests/_framework/translation_test_helpers";
import { queryOne } from "@odoo/hoot-dom";
import { parseArch } from "@mobile_web/views/arch";
import { buildLayout } from "@mobile_web/views/form/layout";
import { BooleanField } from "@mobile_web/fields/basic_fields";

describe.current.tags("mobile");

/** 挂载字段组件时的公共 props */
function fieldProps(overrides) {
    return {
        name: "active",
        field: { type: "boolean", string: "Active" },
        record: { data: {} },
        readonly: false,
        attrs: {},
        onChange: () => {},
        ...overrides,
    };
}

// 模拟 i18n/zh_CN.po 中的翻译: 与 web 的做法一致, 通过 translatedTerms 按模块查找
const ZH_CN = {
    mobile_web: {
        Yes: "是",
        No: "否",
        "Page %s": "页 %s",
    },
};

test("mobile strings are translated with the module's catalog", async () => {
    patchTranslations(ZH_CN);
    await mountWithCleanup(BooleanField, {
        props: fieldProps({ readonly: true, record: { data: { active: true } } }),
    });
    expect(queryOne(".m_field_value")).toHaveText("是");
});

test("untranslated mobile strings fall back to the English source", async () => {
    patchTranslations({ mobile_web: {} });
    await mountWithCleanup(BooleanField, {
        props: fieldProps({ readonly: true, record: { data: { active: false } } }),
    });
    expect(queryOne(".m_field_value")).toHaveText("No");
});

test("notebook page titles are translated with their placeholder", () => {
    patchTranslations(ZH_CN);
    const blocks = buildLayout(
        parseArch(`<form><notebook><page name="a"/><page name="b"/></notebook></form>`),
        {}
    );
    expect(blocks[0].kind).toBe("notebook");
    expect(blocks[0].pages[1].title.toString()).toBe("页 2");
});
