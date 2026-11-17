import { jsToPyLocale } from "@web/core/data/l10n/utils/locales";
import { registry } from "@web/core/framework/registry";
import { user } from "@web/core/services/user";

export const websitePageService = {
    start() {
        const htmlEl = document.querySelector("html");
        // TODO this is duplicated in website_service.js at least... to share
        const match = htmlEl.dataset.mainObject?.match(/(.+)\((-?\d+),(.*)\)/);

        return {
            context: {
                ...user.context,
                website_id: htmlEl.dataset.websiteId | 0,
                lang: jsToPyLocale(htmlEl.getAttribute("lang")) || "en_US",
                user_lang: user.context.lang,
            },
            mainObject: {
                model: match && match[1],
                id: match && match[2] | 0,
            },
        };
    },
};

registry.category("services").add("website_page", websitePageService);
