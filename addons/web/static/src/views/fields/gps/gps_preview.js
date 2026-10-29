import { Component, onMounted, onWillDestroy, onWillStart, signal, t, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { GpsEditor } from "@web/views/fields/gps/gps_editor";

/**
 * 只读位置预览 (桌面端与移动端共用): 配置了地图时显示只读地图, 并列出经纬度.
 * 没有地图配置时只显示经纬度, 不加载任何地图.
 *
 * props.location: {address, latitude, longitude}
 * props.mapConfig: 地图配置 {provider, key} 或 {}
 * props.height: 地图高度 (像素)
 */
export class GpsPreview extends Component {
    static template = xml`
        <div class="o_gps_preview">
            <div class="o_gps_preview_map" t-ref="this.mapRef" t-att-style="'height: ' + this.props.height + 'px'"/>
            <div class="o_gps_preview_coords">
                <t t-esc="this.coordinatesText"/>
            </div>
        </div>
    `;
    props = useProps({
        location: t.object(),
        mapConfig: t.object().optional({}),
        height: t.number().optional(160),
    });
    orm = useService("orm");
    mapRef = signal.ref();

    setup() {
        this.editor = new GpsEditor(this.orm, { location: this.props.location, mapConfig: this.props.mapConfig });
        onWillStart(() => this.editor.loadMap());
        onMounted(() => this.editor.mountMap(this.mapRef(), { interactive: false }));
        onWillDestroy(() => this.editor.destroy());
    }

    get coordinatesText() {
        const { latitude, longitude } = this.props.location;
        return `${Number(latitude).toFixed(6)}, ${Number(longitude).toFixed(6)}`;
    }
}

/** 按 gps 记录的 id 读取位置 (地址与经纬度), 记录不存在时返回 null */
export async function readLocation(orm, id) {
    if (!id) {
        return null;
    }
    const [gps] = await orm.read("gps", [id], ["address", "latitude", "longitude"]);
    return gps || null;
}
