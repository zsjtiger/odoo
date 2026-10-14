import { Component, proxy, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { fieldProps, displayOrEmpty } from "@mobile_web/fields/field_utils";
import { MobileSelectSheet } from "@mobile_web/widgets/select_sheet/select_sheet";
import { PickerButton } from "@mobile_web/widgets/picker/picker";
import { Button } from "@mobile_web/widgets/button/button";
import { FileButton } from "@mobile_web/widgets/file_button/file_button";
import { fieldTexts } from "@mobile_web/core/texts";
import { _t } from "@web/core/data/l10n/translation";

/**
 * 关系字段的值统一为 [id, name] (many2one) 或 [[id, name], ...] (x2many)
 */
function pairName(pair) {
    return pair && (pair[1] ?? `#${pair[0]}`);
}

/**
 * 按关键字搜索关联模型, 使用服务端的 name_search
 */
function makeNameSearch(orm, relation, context) {
    return async (text) => {
        const results = await orm.call(relation, "name_search", [], {
            name: text,
            operator: "ilike",
            limit: 30,
            context,
        });
        return results.map(([id, name]) => ({ id, name }));
    };
}

// -----------------------------------------------------------------------------
// many2one
// -----------------------------------------------------------------------------

export class Many2oneField extends Component {
    texts = fieldTexts;
    static components = { MobileSelectSheet, PickerButton };
    static template = xml`
        <t t-name="mobile_web.Many2oneField">
            <span t-if="this.props.readonly" class="m_field_value"><t t-esc="this.displayName"/></span>
            <t t-else="">
                <PickerButton value="this.current ? this.displayName : false" placeholder="this.texts.select" onClick="this.openSheet"/>
                <MobileSelectSheet t-if="this.state.open" title="this.props.field.string"
                    search="this.search" selected="this.currentItems" allowClear="true"
                    onConfirm="this.onConfirm" onClose="this.close"/>
            </t>
        </t>
    `;
    props = useProps(fieldProps);
    orm = useService("orm");
    state = proxy({ open: false });

    setup() {
        this.search = makeNameSearch(this.orm, this.props.field.relation, {});
    }

    get current() {
        return this.props.record.data[this.props.name] || false;
    }
    get displayName() {
        return displayOrEmpty(pairName(this.current));
    }
    get currentItems() {
        return this.current ? [{ id: this.current[0], name: pairName(this.current) }] : [];
    }
    openSheet = () => {
        this.state.open = true;
    };
    close = () => {
        this.state.open = false;
    };
    onConfirm = (selected) => {
        const item = selected[0];
        this.props.onChange(item ? [item.id, item.name] : false);
        this.close();
    };
}
mobileFieldRegistry.add("many2one", Many2oneField);

// -----------------------------------------------------------------------------
// many2many (标签 + 多选弹层)
// -----------------------------------------------------------------------------

export class Many2manyField extends Component {
    texts = fieldTexts;
    static components = { MobileSelectSheet, Button };
    static template = xml`
        <t t-name="mobile_web.Many2manyField">
            <div class="m_tags">
                <span t-foreach="this.pairs" t-as="pair" t-key="pair[0]" class="m_tag"><t t-esc="pair[1]"/></span>
                <span t-if="!this.pairs.length and !this.props.compact" class="m_field_value m_field_empty"><t t-esc="this.texts.none"/></span>
            </div>
            <Button t-if="!this.props.readonly" label="this.texts.edit" compact="true" caret="true" onClick="this.openSheet"/>
            <MobileSelectSheet t-if="this.state.open" title="this.props.field.string" multiple="true"
                search="this.search" selected="this.currentItems"
                onConfirm="this.onConfirm" onClose="this.close"/>
        </t>
    `;
    props = useProps(fieldProps);
    orm = useService("orm");
    state = proxy({ open: false });

    setup() {
        this.search = makeNameSearch(this.orm, this.props.field.relation, {});
    }

    get pairs() {
        return (this.props.record.data[this.props.name] || []).map(([id, name]) => [id, name ?? `#${id}`]);
    }
    get currentItems() {
        return this.pairs.map(([id, name]) => ({ id, name }));
    }
    openSheet = () => {
        this.state.open = true;
    };
    close = () => {
        this.state.open = false;
    };
    onConfirm = (selected) => {
        this.props.onChange(selected.map((s) => [s.id, s.name]));
        this.close();
    };
}
mobileFieldRegistry.add("many2many", Many2manyField);

// -----------------------------------------------------------------------------
// one2many (v1: 只读列表, 明细在电脑端编辑)
// -----------------------------------------------------------------------------

const ONE2MANY_PREVIEW = 5;

export class One2manyField extends Component {
    texts = fieldTexts;
    static template = xml`
        <t t-name="mobile_web.One2manyField">
            <ul class="m_one2many_list">
                <li t-foreach="this.preview" t-as="pair" t-key="pair[0]"><t t-esc="pair[1]"/></li>
                <li t-if="this.hiddenCount > 0" class="m_field_empty"><t t-esc="this.moreText"/></li>
                <li t-if="!this.pairs.length and !this.props.compact" class="m_field_empty"><t t-esc="this.texts.none"/></li>
            </ul>
            <p t-if="!this.props.readonly" class="m_field_hint"><t t-esc="this.texts.editOnDesktop"/></p>
        </t>
    `;
    props = useProps(fieldProps);

    get moreText() {
        return _t("%s more lines", this.hiddenCount);
    }

    get pairs() {
        return (this.props.record.data[this.props.name] || []).map(([id, name]) => [id, name ?? `#${id}`]);
    }
    get preview() {
        return this.pairs.slice(0, ONE2MANY_PREVIEW);
    }
    get hiddenCount() {
        return Math.max(0, this.pairs.length - ONE2MANY_PREVIEW);
    }
}
mobileFieldRegistry.add("one2many", One2manyField);

// -----------------------------------------------------------------------------
// binary / image (拍照或从相册选择)
// -----------------------------------------------------------------------------

export class BinaryField extends Component {
    texts = fieldTexts;
    static components = { Button, FileButton };
    static template = xml`
        <t t-name="mobile_web.BinaryField">
            <t t-if="this.props.readonly">
                <img t-if="this.imageSrc" class="m_field_image" t-att-src="this.imageSrc" alt=""/>
                <span t-elif="!this.props.compact" class="m_field_value m_field_empty"><t t-esc="this.texts.none"/></span>
            </t>
            <div t-else="" class="m_binary">
                <img t-if="this.imageSrc" class="m_field_image" t-att-src="this.imageSrc" alt=""/>
                <div class="m_binary_actions">
                    <FileButton label="this.hasValue ? this.texts.changeImage : this.texts.selectImage" capture="environment" onFile="this.onFileData"/>
                    <Button t-if="this.hasValue" label="this.texts.delete" compact="true" danger="true" onClick="this.onClear"/>
                </div>
            </div>
        </t>
    `;
    props = useProps(fieldProps);

    get hasValue() {
        return !!this.props.record.data[this.props.name];
    }
    get imageSrc() {
        const value = this.props.record.data[this.props.name];
        if (!value) {
            return null;
        }
        // 刚选择(未保存)的图片是 base64, 已保存的通过 /web/image 读取
        if (this.props.record.changes[this.props.name] !== undefined) {
            return `data:image/*;base64,${value}`;
        }
        return `/web/image/${this.props.resModel}/${this.props.record.resId}/${this.props.name}`;
    }
    /** 选中的图片内容(base64), 由文件按钮回传 */
    onFileData = (base64) => {
        this.props.onChange(base64);
    };
    onClear = () => {
        this.props.onChange(false);
    };
}
mobileFieldRegistry.add("binary", BinaryField);
mobileFieldRegistry.add("image", BinaryField);
