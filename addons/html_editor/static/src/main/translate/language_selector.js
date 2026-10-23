import { Component, onWillStart, proxy, signal, t, useProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dropdown } from "@web/core/components/dropdown/dropdown";
import { DropdownItem } from "@web/core/components/dropdown/dropdown_item";
import { loadLanguages } from "@web/core/data/l10n/translation";
import { jsToPyLocale } from "@web/core/data/l10n/utils/locales";
import { toolbarButtonProps } from "@html_editor/main/toolbar/toolbar";
import { user } from "@web/core/services/user";
import { useDropdownAutoVisibility } from "@html_editor/toolbar_dropdown_hook";

export class LanguageSelector extends Component {
    static template = "html_editor.LanguageSelector";
    props = useProps({
        ...toolbarButtonProps,
        onSelected: t.function(),
    });
    static components = { Dropdown, DropdownItem };

    setup() {
        this.orm = useService("orm");
        this.state = proxy({
            languages: [],
        });
        this.menuRef = signal.ref();
        useDropdownAutoVisibility(this.env.overlayState, this.menuRef);
        onWillStart(() => {
            if (user.userId) {
                const userLang = jsToPyLocale(user.lang);
                loadLanguages(this.orm).then((res) => {
                    const userLangIndex = res.findIndex((lang) => lang[0] === userLang);
                    if (userLangIndex !== -1) {
                        const [userLangItem] = res.splice(userLangIndex, 1);
                        res.unshift(userLangItem);
                    }
                    this.state.languages = res;
                });
            }
        });
    }
    onSelected(targetLang) {
        this.props.onSelected(targetLang);
    }
}
