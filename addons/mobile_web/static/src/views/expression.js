/**
 * 视图属性中的表达式 (readonly / required / invisible), 例如 "state == 'done'" 或 "not is_urgent".
 * 只支持 Python 表达式中常用的子集: 字段名, 字符串, 数字, True/False/None, == != < > <= >=,
 * in / not in, and / or / not, 括号. 不执行任意代码.
 */

const TOKEN_RE = /\s*(?:(\d+(?:\.\d+)?)|('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|(==|!=|<=|>=|<|>|\(|\)|\[|\]|,)|([A-Za-z_]\w*))/y;

function tokenize(source) {
    const tokens = [];
    let pos = 0;
    const text = source.trim();
    while (pos < text.length) {
        TOKEN_RE.lastIndex = pos;
        const match = TOKEN_RE.exec(text);
        if (!match) {
            throw new Error(`Unexpected token in expression: ${source}`);
        }
        pos = TOKEN_RE.lastIndex;
        const [, number, string, operator, name] = match;
        if (number !== undefined) {
            tokens.push({ type: "value", value: Number(number) });
        } else if (string !== undefined) {
            tokens.push({ type: "value", value: string.slice(1, -1).replace(/\\(.)/g, "$1") });
        } else if (operator !== undefined) {
            tokens.push({ type: "op", value: operator });
        } else if (["and", "or", "not", "in"].includes(name)) {
            tokens.push({ type: "op", value: name });
        } else if (name === "True" || name === "False" || name === "None") {
            tokens.push({ type: "value", value: name === "True" ? true : name === "False" ? false : null });
        } else {
            tokens.push({ type: "name", value: name });
        }
    }
    return tokens;
}

/** 语法树: or < and < not < 比较 < 原子 */
function parse(tokens) {
    let index = 0;
    const peek = () => tokens[index];
    const take = () => tokens[index++];
    const isOp = (value) => peek()?.type === "op" && peek().value === value;

    function parseOr() {
        let node = parseAnd();
        while (isOp("or")) {
            take();
            node = { op: "or", left: node, right: parseAnd() };
        }
        return node;
    }
    function parseAnd() {
        let node = parseNot();
        while (isOp("and")) {
            take();
            node = { op: "and", left: node, right: parseNot() };
        }
        return node;
    }
    function parseNot() {
        if (isOp("not") && tokens[index + 1]?.value !== "in") {
            take();
            return { op: "not", operand: parseNot() };
        }
        return parseComparison();
    }
    function parseComparison() {
        let node = parseAtom();
        for (;;) {
            if (isOp("not") && tokens[index + 1]?.value === "in") {
                take();
                take();
                node = { op: "not in", left: node, right: parseAtom() };
            } else if (peek()?.type === "op" && ["==", "!=", "<", ">", "<=", ">=", "in"].includes(peek().value)) {
                const op = take().value;
                node = { op, left: node, right: parseAtom() };
            } else {
                return node;
            }
        }
    }
    function parseAtom() {
        const token = take();
        if (!token) {
            throw new Error("Unexpected end of expression");
        }
        if (token.type === "value") {
            return { literal: token.value };
        }
        if (token.type === "name") {
            return { name: token.value };
        }
        if (token.type === "op" && (token.value === "(" || token.value === "[")) {
            const close = token.value === "(" ? ")" : "]";
            const items = [];
            let trailingComma = false;
            while (peek() && !(peek().type === "op" && peek().value === close)) {
                items.push(parseOr());
                trailingComma = peek()?.type === "op" && peek().value === ",";
                if (trailingComma) {
                    take();
                }
            }
            if (take()?.value !== close) {
                throw new Error("Missing closing bracket");
            }
            // 单个表达式加括号只是分组; 有逗号或用方括号才是元组/列表
            if (items.length === 1 && token.value === "(" && !trailingComma) {
                return items[0];
            }
            return { list: items };
        }
        throw new Error(`Unexpected token ${token.value}`);
    }

    const tree = parseOr();
    if (index !== tokens.length) {
        throw new Error("Unexpected trailing tokens");
    }
    return tree;
}

const cache = new Map();

function compile(source) {
    if (!cache.has(source)) {
        cache.set(source, parse(tokenize(source)));
    }
    return cache.get(source);
}

/** 与 Python 一致的真假判断 */
export function truthy(value) {
    if (Array.isArray(value)) {
        return value.length > 0;
    }
    return Boolean(value);
}

/** 关系字段的值 [id, name] 比较时使用 id */
function comparable(value) {
    return Array.isArray(value) ? value[0] : value;
}

function evaluateNode(node, values) {
    if ("literal" in node) {
        return node.literal;
    }
    if ("name" in node) {
        return comparable(values[node.name] ?? false);
    }
    if ("list" in node) {
        return node.list.map((item) => evaluateNode(item, values));
    }
    switch (node.op) {
        case "and":
            return truthy(evaluateNode(node.left, values)) && truthy(evaluateNode(node.right, values));
        case "or":
            return truthy(evaluateNode(node.left, values)) || truthy(evaluateNode(node.right, values));
        case "not":
            return !truthy(evaluateNode(node.operand, values));
        case "in":
            return contains(evaluateNode(node.right, values), evaluateNode(node.left, values));
        case "not in":
            return !contains(evaluateNode(node.right, values), evaluateNode(node.left, values));
        default: {
            const left = evaluateNode(node.left, values);
            const right = evaluateNode(node.right, values);
            switch (node.op) {
                case "==": return left === right;
                case "!=": return left !== right;
                case "<": return left < right;
                case ">": return left > right;
                case "<=": return left <= right;
                case ">=": return left >= right;
            }
            return false;
        }
    }
}

function contains(container, item) {
    if (Array.isArray(container)) {
        return container.map(comparable).includes(item);
    }
    return typeof container === "string" && container.includes(item);
}

/**
 * 计算表达式的真假. 属性为空或无法解析时返回 fallback.
 *
 * @param {string|undefined} source
 * @param {Object} values  字段名 -> 界面值
 * @param {boolean} fallback
 * @returns {boolean}
 */
export function evaluateModifier(source, values, fallback = false) {
    if (source === undefined || source === null || source === "") {
        return fallback;
    }
    if (source === "1" || source === "True" || source === "true") {
        return true;
    }
    if (source === "0" || source === "False" || source === "false") {
        return false;
    }
    try {
        return truthy(evaluateNode(compile(source), values));
    } catch {
        // 无法解析的表达式按缺省值处理, 不影响表单显示
        return fallback;
    }
}
