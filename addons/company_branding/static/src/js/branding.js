/*
 * Company branding for the web and mobile web clients.
 *
 * Reads /company_branding/config and applies the URLs configured on the company:
 * tab title, tab icon, login logo and login background. Runs on every page of the
 * web and mobile bundles; only the login pages get the logo and background.
 */
(function () {
    "use strict";

    var CONFIG_URL = "/company_branding/config";

    function isMobile(path) {
        return path.indexOf("/mobile_web") === 0;
    }

    function isLoginPage(path) {
        return /\/(web|mobile_web)\/login\b/.test(path);
    }

    function safeUrl(url) {
        try {
            var parsed = new URL(url, window.location.href);
            return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : "";
        } catch (e) {
            return "";
        }
    }

    function applyTitle(title) {
        if (title) {
            document.title = title;
        }
    }

    function applyIcon(url) {
        if (!url) {
            return;
        }
        var link = document.querySelector("link[rel~='icon']");
        if (!link) {
            link = document.createElement("link");
            link.rel = "icon";
            document.head.appendChild(link);
        }
        link.href = url;
    }

    function applyLogo(url) {
        if (!url) {
            return;
        }
        // the mobile login page already has a logo: replace its source instead of adding a second one
        // the big logo at the top of the mobile login page is the company logo slot
        var existing = document.querySelector("img[src*='/mobile_web/static/public/img/login/login.png']");
        if (existing) {
            existing.src = url;
            existing.style.setProperty("object-fit", "contain", "important");
            return;
        }
        var img = document.createElement("img");
        img.className = "o_company_branding_logo";
        img.alt = "";
        img.src = url;
        img.style.cssText = "display:block;max-width:200px;max-height:80px;margin:0 auto 16px;";
        var container = document.querySelector(".card-body, form, main") || document.body;
        container.insertBefore(img, container.firstChild);
    }

    function applyBackground(url) {
        if (!url) {
            return;
        }
        // encodeURI keeps the URL inside url("...") even when it contains quotes or parentheses
        var escaped = encodeURI(url).replace(/\(/g, "%28").replace(/\)/g, "%29");
        document.body.style.setProperty("background-image", 'url("' + escaped + '")', "important");
        document.body.style.setProperty("background-size", "cover", "important");
        document.body.style.setProperty("background-position", "center", "important");
        // the mobile login card has its own white background that would hide the image
        var card = document.querySelector(".m_login");
        if (card) {
            card.style.setProperty("background", "transparent", "important");
        }
    }

    // the small default logo in the corner of the mobile login page is hidden once a company logo is set
    function hideDefaultMobileCorner() {
        var corner = document.querySelector("img[src*='/mobile_web/static/public/img/login/logo.png']");
        if (corner) {
            corner.style.setProperty("display", "none", "important");
        }
    }

    function apply(config) {
        var path = window.location.pathname;
        var mobile = isMobile(path);
        var title = mobile ? config.mobile_title : config.web_title;
        var icon = safeUrl(mobile ? config.mobile_icon_url : config.web_icon_url);
        var logo = safeUrl(mobile ? config.mobile_logo_url : config.web_logo_url);
        var background = safeUrl(config.login_background_url);

        applyTitle(title);
        applyIcon(icon);
        if (isLoginPage(path)) {
            applyLogo(logo);
            applyBackground(background);
            if (mobile && logo) {
                hideDefaultMobileCorner();
            }
        }
    }

    function start() {
        fetch(CONFIG_URL, { credentials: "same-origin" })
            .then(function (response) {
                return response.ok ? response.json() : null;
            })
            .then(function (config) {
                if (config) {
                    apply(config);
                }
            })
            .catch(function () {
                // branding is cosmetic: keep the default look if the endpoint is unavailable
            });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();
