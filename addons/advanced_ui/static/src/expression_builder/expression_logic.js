import { _t } from "@web/core/data/l10n/translation";

/**
 * Pure logic of the expression builder: the tree model, the operators of each
 * field kind, and the conversion of the tree to an Odoo domain.
 *
 * A tree is a group: { kind: "group", mode, customLogic, formula, children }.
 * A child is either a group or a condition: { kind: "condition", resource, type,
 * operator, value }.
 */

export const MODES = [
    { value: "all", label: _t("All Conditions Are Met") },
    { value: "any", label: _t("Any Condition Is Met") },
    { value: "custom", label: _t("Custom Logic Is Met") },
    { value: "always", label: _t("Always (No Criteria)") },
    { value: "formula", label: _t("Formula Evaluates To True") },
];

const COMPARISONS = [
    { value: "=", label: _t("is equal to") },
    { value: "!=", label: _t("is not equal to") },
];
const ORDERINGS = [
    { value: ">", label: _t("is greater than") },
    { value: ">=", label: _t("is greater than or equal to") },
    { value: "<", label: _t("is less than") },
    { value: "<=", label: _t("is less than or equal to") },
];
const PRESENCE = [
    { value: "set", label: _t("is set"), noValue: true },
    { value: "not set", label: _t("is not set"), noValue: true },
];

/** Operators available for each field kind. */
export const OPERATORS = {
    char: [
        ...COMPARISONS,
        { value: "ilike", label: _t("contains") },
        { value: "not ilike", label: _t("does not contain") },
        ...PRESENCE,
    ],
    number: [...COMPARISONS, ...ORDERINGS, ...PRESENCE],
    date: [...COMPARISONS, ...ORDERINGS, ...PRESENCE],
    boolean: [{ value: "=", label: _t("is") }],
    selection: [...COMPARISONS, ...PRESENCE],
};

/**
 * Maps an Odoo field type to the kind used by the builder, or null when the
 * builder cannot compare values of that type.
 *
 * @param {string} type Odoo field type
 * @returns {string | null}
 */
export function fieldKind(type) {
    switch (type) {
        case "char":
        case "text":
            return "char";
        case "integer":
        case "float":
        case "monetary":
            return "number";
        case "date":
            return "date";
        case "boolean":
            return "boolean";
        case "selection":
            return "selection";
        default:
            return null;
    }
}

export function newCondition() {
    return { kind: "condition", resource: "", type: "", operator: "", value: "" };
}

export function newGroup(mode = "all") {
    return { kind: "group", mode, customLogic: "", formula: "", children: [] };
}

/** The tree shown when the builder has no value yet: one empty condition. */
export function defaultTree() {
    const group = newGroup("all");
    group.children.push(newCondition());
    return group;
}

/**
 * Casts a value typed in the builder to the value used in the domain.
 *
 * @param {string | boolean} value
 * @param {string} kind
 */
export function castValue(value, kind) {
    if (kind === "number") {
        return Number(value);
    }
    if (kind === "boolean") {
        return value === true || value === "true";
    }
    return value;
}

/**
 * @param {object} condition
 * @returns {Array | null} the domain tokens of the condition, [] when the
 *   condition is incomplete
 */
export function conditionDomain(condition) {
    if (!condition.resource || !condition.operator) {
        return [];
    }
    const { resource, operator, type } = condition;
    if (operator === "set") {
        return [[resource, "!=", false]];
    }
    if (operator === "not set") {
        return [[resource, "=", false]];
    }
    return [[resource, operator, castValue(condition.value, type)]];
}

const TRUE_TOKENS = () => [[1, "=", 1]];

/**
 * Joins domains with a logical operator, in prefix notation: n domains need
 * n - 1 operators before them.
 *
 * @param {"&" | "|"} operator
 * @param {Array[]} domains
 */
function joinDomains(operator, domains) {
    if (domains.length === 1) {
        return domains[0];
    }
    return [...Array(domains.length - 1).fill(operator), ...domains.flat()];
}

/**
 * Parses the custom logic of a group: the numbers are the 1-based positions of
 * the children, combined with AND, OR, NOT and parentheses. AND binds tighter
 * than OR. Throws an Error when the text is not a valid expression.
 *
 * @param {string} text
 * @param {number} count number of children of the group
 * @returns {object} the syntax tree
 */
export function parseCustomLogic(text, count) {
    const tokens = text.match(/\d+|\(|\)|[A-Za-z]+/g) ?? [];
    if (text.replace(/\s|\d+|\(|\)|AND|OR|NOT/gi, "") !== "" || !tokens.length) {
        throw new Error(_t("Custom logic must use numbers, AND, OR, NOT and parentheses."));
    }
    let pos = 0;
    const peek = () => tokens[pos]?.toUpperCase();
    const next = () => tokens[pos++];

    function parseOr() {
        const items = [parseAnd()];
        while (peek() === "OR") {
            next();
            items.push(parseAnd());
        }
        return items.length === 1 ? items[0] : { op: "|", items };
    }
    function parseAnd() {
        const items = [parseUnary()];
        while (peek() === "AND") {
            next();
            items.push(parseUnary());
        }
        return items.length === 1 ? items[0] : { op: "&", items };
    }
    function parseUnary() {
        if (peek() === "NOT") {
            next();
            return { op: "!", item: parseUnary() };
        }
        return parsePrimary();
    }
    function parsePrimary() {
        const token = next();
        if (token === "(") {
            const ast = parseOr();
            if (next() !== ")") {
                throw new Error(_t("Custom logic is missing a closing parenthesis."));
            }
            return ast;
        }
        if (/^\d+$/.test(token)) {
            const position = Number(token);
            if (position < 1 || position > count) {
                throw new Error(_t("Custom logic refers to condition %s, which does not exist.", position));
            }
            return { index: position - 1 };
        }
        throw new Error(_t("Custom logic is incomplete."));
    }

    const ast = parseOr();
    if (pos !== tokens.length) {
        throw new Error(_t("Custom logic has an unexpected token."));
    }
    return ast;
}

function astDomain(ast, parts) {
    if ("index" in ast) {
        return parts[ast.index];
    }
    if (ast.op === "!") {
        return ["!", ...astDomain(ast.item, parts)];
    }
    return joinDomains(ast.op, ast.items.map((item) => astDomain(item, parts)));
}

/**
 * @param {object} group
 * @returns {Array | null} the domain of the group, [] when it has no criteria,
 *   null when it cannot be expressed as a domain (formula mode)
 */
export function groupDomain(group) {
    if (group.mode === "formula") {
        return null;
    }
    if (group.mode === "always") {
        return [];
    }
    const parts = group.children.map(nodeDomain);
    if (parts.some((part) => part === null)) {
        return null;
    }
    if (group.mode === "custom") {
        const ast = parseCustomLogic(group.customLogic, group.children.length);
        return astDomain(
            ast,
            parts.map((part) => (part.length ? part : TRUE_TOKENS()))
        );
    }
    const operator = group.mode === "any" ? "|" : "&";
    const filled = parts.filter((part) => part.length);
    return filled.length ? joinDomains(operator, filled) : [];
}

/**
 * @param {object} node a group or a condition
 * @returns {Array | null}
 */
export function nodeDomain(node) {
    return node.kind === "group" ? groupDomain(node) : conditionDomain(node);
}

/**
 * Converts the tree to an Odoo domain.
 *
 * @param {object} tree
 * @returns {Array | null} null when the tree is in formula mode, which has no domain
 * @throws {Error} when the custom logic of a group is not valid
 */
export function toDomain(tree) {
    return nodeDomain(tree);
}
