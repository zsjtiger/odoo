import { registry } from "@web/core/framework/registry";
import { listView } from "@web/views/list/list_view";

registry.category("views").add("tour_list", {
    ...listView,
    buttonTemplate: "web_tour.TourListController.Buttons",
});
