/**
 * Model of a Salesforce-style page layout: the form view of a model read as
 * header buttons, sections (with one or more columns of fields) and the
 * blocks the layout doesn't manage (kept as they are).
 *
 * The model works on DOM nodes so that the attributes of the nodes that are
 * not edited are preserved when the arch is written back.
 */

/** Module of the xml ids created for the buttons made in Studio. */
export const STUDIO_MODULE = "studio_customization";

let nextId = 1;
function uid(prefix) {
    return `${prefix}_${nextId++}`;
}

/**
 * Attributes that the compiled view gets from the server and that a stored arch
 * can't keep: the validation of the arch rejects them.
 */
const INTERNAL_ATTRIBUTES = ["actual_invisible", "actual_readonly", "studio_groups", "data-used-by"];

function parseXml(xml) {
    const root = new DOMParser().parseFromString(xml, "text/xml").documentElement;
    for (const node of [root, ...root.querySelectorAll("*")]) {
        for (const name of INTERNAL_ATTRIBUTES) {
            node.removeAttribute(name);
        }
    }
    return root;
}

function children(node) {
    return Array.from(node.children);
}

function attributesOf(node) {
    return Object.fromEntries(Array.from(node.attributes).map((attr) => [attr.name, attr.value]));
}

function setAttributes(node, attributes) {
    for (const [name, value] of Object.entries(attributes)) {
        node.setAttribute(name, value);
    }
}

/**
 * @param {string} name technical name of a field
 * @returns {Element} a `<field name="...">` node
 */
export function createFieldNode(name) {
    return parseXml(`<field name="${name}"/>`);
}

/**
 * @param {string} xmlid xml id of the server action of the button
 * @param {string} label
 * @returns {Element} a `<button type="action">` node for the header
 */
export function createActionButtonNode(xmlid, label) {
    const button = parseXml(`<button type="action"/>`);
    button.setAttribute("name", xmlid);
    button.setAttribute("string", label);
    return button;
}

/** A block the layout doesn't manage, kept as it is and editable as XML. */
function rawItem(node) {
    return { kind: "raw", id: uid("raw"), node };
}

function parseItem(node) {
    if (node.tagName === "field" && node.getAttribute("name")) {
        return { kind: "field", name: node.getAttribute("name"), node };
    }
    return rawItem(node);
}

function parseSection(node) {
    const innerGroups = children(node).filter((child) => child.tagName === "group");
    const columns = innerGroups.map((group) => ({
        id: uid("column"),
        attributes: attributesOf(group),
        items: children(group).map(parseItem),
    }));
    const extra = children(node)
        .filter((child) => child.tagName !== "group")
        .map(rawItem);
    if (!innerGroups.length) {
        // A group without inner groups is a single column
        columns.push({ id: uid("column"), attributes: {}, items: children(node).map(parseItem) });
    }
    const { string, ...attributes } = attributesOf(node);
    return {
        kind: "section",
        id: uid("section"),
        title: string || "",
        attributes,
        columns,
        extra: innerGroups.length ? extra : [],
    };
}

/** Templates of a kanban view that hold the card of a record. */
const CARD_TEMPLATE_NAMES = ["card", "kanban-box"];

/**
 * The card of a kanban view is laid out as a flat section, like a list: its
 * fields and blocks. The other nodes of the view are kept as they are.
 * @returns {Object|null} the layout, null if the view has no card template
 */
function parseKanbanLayout(root) {
    if (root.tagName !== "kanban") {
        return null;
    }
    const templates = children(root).find((child) => child.tagName === "templates");
    const card = templates
        ? children(templates).find(
              (child) => child.tagName === "t" && CARD_TEMPLATE_NAMES.includes(child.getAttribute("t-name"))
          )
        : null;
    if (!card) {
        return null;
    }
    return {
        rootTag: root.tagName,
        rootAttributes: attributesOf(root),
        header: [],
        hasSheet: false,
        sheetAttributes: {},
        body: [
            {
                kind: "section",
                id: uid("section"),
                title: "",
                attributes: {},
                columns: [{ id: uid("column"), attributes: {}, items: children(card).map(parseItem) }],
                extra: [],
                flat: true,
            },
        ],
        footer: children(root)
            .filter((child) => child !== templates)
            .map(rawItem),
        kanban: {
            cardTag: card.tagName,
            cardAttributes: attributesOf(card),
            templatesAttributes: attributesOf(templates),
            otherTemplates: children(templates)
                .filter((child) => child !== card)
                .map(rawItem),
        },
    };
}

/**
 * @param {string} arch arch of a form or a list view
 * @returns {Object} the layout of the view. A list or a search view has a single
 *   flat section: its fields, without title nor columns.
 */
export function parseFormArch(arch) {
    const root = parseXml(arch);
    const kanbanLayout = parseKanbanLayout(root);
    if (kanbanLayout) {
        return kanbanLayout;
    }
    const headerNode = children(root).find((child) => child.tagName === "header");
    const sheetNode = children(root).find((child) => child.tagName === "sheet");
    // A list or a search view has a single flat set of fields and blocks
    const flat = root.tagName === "list" || root.tagName === "search";
    const layout = {
        rootTag: root.tagName,
        rootAttributes: attributesOf(root),
        header: headerNode
            ? children(headerNode).map((node) =>
                  node.tagName === "button" && node.getAttribute("type") === "action"
                      ? { kind: "button", node }
                      : rawItem(node)
              )
            : [],
        hasSheet: Boolean(sheetNode),
        sheetAttributes: sheetNode ? attributesOf(sheetNode) : {},
        body: [],
        footer: [],
    };
    const bodyParent = sheetNode || root;
    const bodyNodes = children(bodyParent).filter((child) => child !== headerNode);
    if (flat) {
        layout.body = [
            {
                kind: "section",
                id: uid("section"),
                title: "",
                attributes: {},
                columns: [{ id: uid("column"), attributes: {}, items: bodyNodes.map(parseItem) }],
                extra: [],
                flat: true,
            },
        ];
    } else {
        layout.body = bodyNodes.map((node) => (node.tagName === "group" ? parseSection(node) : rawItem(node)));
    }
    if (sheetNode) {
        layout.footer = children(root)
            .filter((child) => child !== headerNode && child !== sheetNode)
            .map(rawItem);
    }
    return layout;
}

/**
 * @param {Object} layout
 * @returns {string} the arch of the form, without the xml declaration
 */
export function serializeFormLayout(layout) {
    const doc = document.implementation.createDocument(null, layout.rootTag, null);
    const root = doc.documentElement;
    setAttributes(root, layout.rootAttributes);

    if (layout.header.length) {
        const header = doc.createElement("header");
        for (const item of layout.header) {
            header.appendChild(doc.importNode(item.node, true));
        }
        root.appendChild(header);
    }

    let container = root;
    if (layout.hasSheet) {
        container = doc.createElement("sheet");
        setAttributes(container, layout.sheetAttributes);
        root.appendChild(container);
    }

    if (layout.kanban) {
        const templates = doc.createElement("templates");
        setAttributes(templates, layout.kanban.templatesAttributes);
        const card = doc.createElement(layout.kanban.cardTag);
        setAttributes(card, layout.kanban.cardAttributes);
        for (const item of layout.body[0].columns[0].items) {
            card.appendChild(doc.importNode(item.node, true));
        }
        templates.appendChild(card);
        for (const item of layout.kanban.otherTemplates) {
            templates.appendChild(doc.importNode(item.node, true));
        }
        root.appendChild(templates);
    }

    for (const entry of layout.kanban ? [] : layout.body) {
        if (entry.kind !== "section") {
            container.appendChild(doc.importNode(entry.node, true));
            continue;
        }
        if (entry.flat) {
            for (const item of entry.columns[0].items) {
                container.appendChild(doc.importNode(item.node, true));
            }
            continue;
        }
        const group = doc.createElement("group");
        setAttributes(group, entry.attributes);
        if (entry.title) {
            group.setAttribute("string", entry.title);
        }
        for (const column of entry.columns) {
            const columnNode = doc.createElement("group");
            setAttributes(columnNode, column.attributes);
            for (const item of column.items) {
                columnNode.appendChild(doc.importNode(item.node, true));
            }
            group.appendChild(columnNode);
        }
        for (const item of entry.extra) {
            group.appendChild(doc.importNode(item.node, true));
        }
        container.appendChild(group);
    }

    for (const item of layout.footer) {
        root.appendChild(doc.importNode(item.node, true));
    }
    return new XMLSerializer().serializeToString(doc);
}

/**
 * @param {Object} layout
 * @returns {Set<string>} the names of the fields placed in the layout
 */
export function fieldsInLayout(layout) {
    const names = new Set();
    for (const entry of layout.body) {
        if (entry.kind === "section") {
            for (const column of entry.columns) {
                for (const item of column.items) {
                    if (item.kind === "field") {
                        names.add(item.name);
                    }
                }
            }
        }
    }
    return names;
}

/** @returns {Object|undefined} the section with the given id */
export function findSection(layout, sectionId) {
    return layout.body.find((entry) => entry.kind === "section" && entry.id === sectionId);
}

/** @returns {Object|undefined} the column of the section with the given id */
export function findColumn(section, columnId) {
    return section.columns.find((column) => column.id === columnId);
}

/**
 * Adds a section with two columns at the end of the layout.
 * @returns {Object} the new section
 */
export function addSection(layout, title = "") {
    const section = {
        kind: "section",
        id: uid("section"),
        title,
        attributes: {},
        columns: [
            { id: uid("column"), attributes: {}, items: [] },
            { id: uid("column"), attributes: {}, items: [] },
        ],
        extra: [],
    };
    layout.body.push(section);
    return section;
}

/**
 * Removes a section. Its fields are moved to the first remaining section,
 * so that no field disappears from the layout.
 */
export function removeSection(layout, sectionId) {
    const index = layout.body.findIndex((entry) => entry.kind === "section" && entry.id === sectionId);
    if (index === -1) {
        return;
    }
    const [section] = layout.body.splice(index, 1);
    const target = layout.body.find((entry) => entry.kind === "section");
    if (target) {
        const items = section.columns.flatMap((column) => column.items);
        target.columns[0].items.push(...items);
    }
}

/**
 * Changes the number of columns of a section. Items of removed columns are
 * appended to the last remaining column.
 * @param {Object} section
 * @param {number} count 1 or 2 (or more)
 */
export function setColumnCount(section, count) {
    while (section.columns.length < count) {
        section.columns.push({ id: uid("column"), attributes: {}, items: [] });
    }
    while (section.columns.length > count) {
        const removed = section.columns.pop();
        section.columns[section.columns.length - 1].items.push(...removed.items);
    }
}

/**
 * Adds a field at the given position of a column.
 * @returns {boolean} whether the field was added
 */
export function addField(layout, sectionId, columnId, name, index = null) {
    const section = findSection(layout, sectionId);
    const column = section && findColumn(section, columnId);
    if (!column || fieldsInLayout(layout).has(name)) {
        return false;
    }
    const item = { kind: "field", name, node: createFieldNode(name) };
    if (index === null) {
        column.items.push(item);
    } else {
        column.items.splice(index, 0, item);
    }
    return true;
}

/**
 * Moves a field to a position of a column, possibly of another section.
 * @param {Object} from {sectionId, columnId, index}
 * @param {Object} to {sectionId, columnId, index}, index is the position before which to insert
 */
export function moveField(layout, from, to) {
    const fromSection = findSection(layout, from.sectionId);
    const fromColumn = fromSection && findColumn(fromSection, from.columnId);
    const toSection = findSection(layout, to.sectionId);
    const toColumn = toSection && findColumn(toSection, to.columnId);
    if (!fromColumn || !toColumn) {
        return;
    }
    const [item] = fromColumn.items.splice(from.index, 1);
    let index = to.index === null || to.index === undefined ? toColumn.items.length : to.index;
    if (fromColumn === toColumn && from.index < index) {
        index -= 1;
    }
    toColumn.items.splice(index, 0, item);
}

/** Removes the item at the given position of a column. */
export function removeItem(layout, position) {
    const section = findSection(layout, position.sectionId);
    const column = section && findColumn(section, position.columnId);
    if (column) {
        column.items.splice(position.index, 1);
    }
}

/**
 * Adds a button to the header, unless the same action is already there.
 * @returns {boolean} whether the button was added
 */
export function addHeaderButton(layout, xmlid, label) {
    const exists = layout.header.some(
        (item) => item.kind === "button" && item.node.getAttribute("name") === xmlid
    );
    if (exists) {
        return false;
    }
    layout.header.push({ kind: "button", node: createActionButtonNode(xmlid, label) });
    return true;
}

/** Removes the header button at the given index. */
export function removeHeaderButton(layout, index) {
    layout.header.splice(index, 1);
}

/** @returns {string[]} the xml ids of the action buttons of the header */
export function headerButtonNames(layout) {
    return layout.header
        .filter((item) => item.kind === "button")
        .map((item) => item.node.getAttribute("name"));
}

/** @returns {Object[]} every block of the layout that is kept as XML. */
export function rawItems(layout) {
    const items = [...layout.header.filter((item) => item.kind === "raw"), ...layout.footer];
    if (layout.kanban) {
        items.push(...layout.kanban.otherTemplates);
    }
    for (const entry of layout.body) {
        if (entry.kind !== "section") {
            items.push(entry);
            continue;
        }
        items.push(...entry.extra);
        for (const column of entry.columns) {
            items.push(...column.items.filter((item) => item.kind === "raw"));
        }
    }
    return items;
}

/**
 * Replaces the XML of a block the layout keeps as it is.
 * @param {Object} layout
 * @param {string} id id of the block
 * @param {string} xml the new XML of the block, a single element
 * @throws {Error} if the XML is not well formed
 */
export function setRawXml(layout, id, xml) {
    const item = rawItems(layout).find((candidate) => candidate.id === id);
    if (!item) {
        return;
    }
    const doc = new DOMParser().parseFromString(xml, "text/xml");
    if (doc.getElementsByTagName("parsererror").length) {
        throw new Error("The XML is not well formed.");
    }
    item.node = doc.documentElement;
}

/** @returns {string} the XML of a block, as it is written in the arch */
export function rawXml(item) {
    return new XMLSerializer().serializeToString(item.node);
}

/**
 * Builds the studio view arch replacing the root of the form. This is what
 * gets saved, so that the layout is the one of the form.
 * @param {string} formArch arch returned by serializeFormLayout
 * @param {string} rootTag
 * @returns {string}
 */
export function replaceRootArch(formArch, rootTag) {
    return `<data><xpath expr="/${rootTag}" position="replace">${formArch}</xpath></data>`;
}
