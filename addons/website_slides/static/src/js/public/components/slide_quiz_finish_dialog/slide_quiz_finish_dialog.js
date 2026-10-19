import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { Dialog } from "@web/core/dialog/dialog";
import { Component, onMounted, proxy, t, useProps } from "@odoo/owl";

export class SlideQuizFinishDialog extends Component {
    static components = { Dialog };
    props = useProps({
        close: t.function(),
        hasNext: t.boolean(),
        onClickNext: t.function(),
        quiz: t.object(),
        userId: t.number(),
    });
    static template = "website_slides.SlideQuizFinishDialog";

    setup() {
        super.setup();
        this.state = proxy({
            hideDismissBtns: true,
        });
        this.title = _t("Amazing!");
        onMounted(() => this.animateText());
    }

    //--------------------------------
    // Handler
    //--------------------------------

    onClickNext() {
        this.props.onClickNext();
        this.props.close();
    }

    //--------------------------------
    // Business methods
    //--------------------------------

    /**
     * Shows the dismiss buttons once the success message is displayed.
     * @public
     */
    animateText() {
        browser.setTimeout(() => {
            this.state.hideDismissBtns = false;
        }, 800);
    }
}
