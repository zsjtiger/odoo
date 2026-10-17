import { proxy } from "@odoo/owl";

// Kept outside the components so that coming back from the view editor
// reopens the model that was being configured.
export const designerState = proxy({
    selectedModelId: null,
    // Snapshot of the selected model, used by the editor breadcrumb: { id, name, model }
    selectedModel: null,
    // "fields" | "field" | "layouts" | "buttons"
    section: "fields",
    selectedFieldId: null,
});
