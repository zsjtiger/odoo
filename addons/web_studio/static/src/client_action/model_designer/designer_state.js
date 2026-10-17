import { proxy } from "@odoo/owl";

// Kept outside the components so that coming back from the view editor
// reopens the model that was being configured.
export const designerState = proxy({ selectedModelId: null, section: "fields" });
