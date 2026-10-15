/**
 * GPS 位置的公共逻辑 (桌面端与移动端共用): 坐标校验与保存.
 *
 * 位置保存为 gps 记录, 所属记录通过 many2one 指向它; 更新已有位置时只写这条记录.
 */

/**
 * 坐标是否在合法范围内 (与服务端 gps 模型的约束一致)
 *
 * @returns {"latitude" | "longitude" | null} 不合法的坐标名称, 合法时为 null
 */
export function invalidCoordinate(latitude, longitude) {
    if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90) {
        return "latitude";
    }
    if (!Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
        return "longitude";
    }
    return null;
}

/**
 * 保存位置, 返回 many2one 的界面值 {id, display_name}
 *
 * @param {Object} orm 服务
 * @param {Object} params
 * @param {{id: number, display_name: string} | false} params.value 当前值 (有则更新该记录)
 * @param {{address: string, latitude: number, longitude: number, source: string}} params.location
 * @param {{model: string, field: string, resId: number | false}} params.owner 所属记录
 */
export async function saveLocation(orm, { value, location, owner }) {
    const values = {
        address: location.address || "",
        latitude: location.latitude,
        longitude: location.longitude,
        source: location.source || "manual",
    };
    if (value) {
        await orm.write("gps", [value.id], values);
        return { id: value.id, display_name: location.address || value.display_name };
    }
    const [id] = await orm.create("gps", [
        {
            ...values,
            res_model: owner.model,
            res_field: owner.field,
            // 所属记录未保存时为 0, 保存所属记录后由服务端补上
            res_id: owner.resId || 0,
        },
    ]);
    const [record] = await orm.read("gps", [id], ["display_name"]);
    return { id, display_name: record.display_name };
}
