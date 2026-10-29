/**
 * 只读展示 html 字段时使用的清理函数: 只保留常见的排版标签与安全属性.
 *
 * 不在白名单中的标签保留其文字内容, 脚本/样式/嵌入类标签整体删除;
 * 链接与图片地址只允许 http(s)、邮件、电话、站内相对路径, 以及常见图片格式的 data URI.
 */

const DROPPED_TAGS = new Set([
    "script", "style", "iframe", "object", "embed", "template", "noscript",
    "svg", "math", "form", "input", "button", "select", "textarea", "link", "meta", "base",
]);

const ALLOWED_TAGS = new Set([
    "p", "br", "div", "span", "strong", "b", "em", "i", "u", "s", "sub", "sup", "small",
    "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code", "hr",
    "a", "img", "table", "thead", "tbody", "tfoot", "tr", "td", "th",
]);

const ALLOWED_ATTRS = new Set(["href", "src", "alt", "title", "colspan", "rowspan"]);

// 去掉控制字符与空白后再判断协议, 防止 "java\tscript:" 之类的写法绕过
const SCHEME = /^([a-z][a-z0-9+.-]*):/;
const SAFE_IMAGE_DATA = /^data:image\/(png|jpe?g|gif|webp);/;

function normalizeUrl(value) {
    return value.replace(/[\u0000- \u007f]/g, "").toLowerCase();
}

function isSafeHref(value) {
    const url = normalizeUrl(value);
    const scheme = url.match(SCHEME);
    return !scheme || ["http", "https", "mailto", "tel"].includes(scheme[1]);
}

function isSafeSrc(value) {
    const url = normalizeUrl(value);
    if (url.startsWith("data:")) {
        return SAFE_IMAGE_DATA.test(url);
    }
    const scheme = url.match(SCHEME);
    return !scheme || scheme[1] === "http" || scheme[1] === "https";
}

function cleanAttributes(el) {
    for (const attr of Array.from(el.attributes)) {
        const name = attr.name.toLowerCase();
        const keep =
            ALLOWED_ATTRS.has(name) &&
            (name !== "href" || isSafeHref(attr.value)) &&
            (name !== "src" || isSafeSrc(attr.value));
        if (!keep) {
            el.removeAttribute(attr.name);
        }
    }
    if (el.tagName === "A" && el.hasAttribute("href")) {
        el.setAttribute("target", "_blank");
        el.setAttribute("rel", "noopener noreferrer");
    }
}

function cleanNode(node) {
    for (const child of Array.from(node.childNodes)) {
        if (child.nodeType === Node.TEXT_NODE) {
            continue;
        }
        if (child.nodeType !== Node.ELEMENT_NODE) {
            child.remove();
            continue;
        }
        const tag = child.tagName.toLowerCase();
        if (DROPPED_TAGS.has(tag)) {
            child.remove();
            continue;
        }
        cleanNode(child);
        if (!ALLOWED_TAGS.has(tag)) {
            // 未知标签: 保留内容, 去掉标签
            child.replaceWith(...Array.from(child.childNodes));
            continue;
        }
        cleanAttributes(child);
    }
}

/**
 * @param {string} raw  存储的 html 内容
 * @returns {string}    可安全插入的 html
 */
export function sanitizeHtml(raw) {
    if (!raw) {
        return "";
    }
    const body = new DOMParser().parseFromString(raw, "text/html").body;
    cleanNode(body);
    return body.innerHTML;
}
