import { _t } from "@web/core/data/l10n/translation";

/**
 * 字段组件与选择弹层共用的界面文字.
 * 用 _t 包装, 由 i18n/*.po 提供翻译; 模板中通过 `this.texts` 引用.
 */
export const fieldTexts = {
    yes: _t("Yes"),
    no: _t("No"),
    none: _t("None"),
    select: _t("Select…"),
    edit: _t("Edit"),
    changeImage: _t("Change image"),
    selectImage: _t("Select image"),
    delete: _t("Delete"),
    editOnDesktop: _t("Edit line items on the desktop"),
    save: _t("Save"),
    addLine: _t("Add line"),
    newLine: _t("New line"),
    editLine: _t("Edit line"),
    deleteLine: _t("Delete line"),
    editRichTextOnDesktop: _t("Edit rich text on the desktop"),
    cancel: _t("Cancel"),
    confirm: _t("Confirm"),
    search: _t("Search"),
    removeFilter: _t("Remove filter"),
    clear: _t("Clear"),
    loading: _t("Loading…"),
    noMatch: _t("No matching results"),
};
