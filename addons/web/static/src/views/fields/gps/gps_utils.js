/**
 * GPS 位置的公共逻辑 (桌面端与移动端共用): 坐标校验与保存.
 *
 * 位置保存为 gps 记录, 所属记录通过 many2one 指向它; 更新已有位置时只写这条记录.
 */

const PI = Math.PI;
const AXIS = 6378245.0;
const OFFSET = 0.00669342162296594323;

function outOfChina(lat, lng) {
    return lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271;
}

function transformLat(x, y) {
    let r = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
    r += ((20 * Math.sin(6 * x * PI) + 20 * Math.sin(2 * x * PI)) * 2) / 3;
    r += ((20 * Math.sin(y * PI) + 40 * Math.sin((y / 3) * PI)) * 2) / 3;
    r += ((160 * Math.sin((y / 12) * PI) + 320 * Math.sin((y * PI) / 30)) * 2) / 3;
    return r;
}

function transformLng(x, y) {
    let r = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
    r += ((20 * Math.sin(6 * x * PI) + 20 * Math.sin(2 * x * PI)) * 2) / 3;
    r += ((20 * Math.sin(x * PI) + 40 * Math.sin((x / 3) * PI)) * 2) / 3;
    r += ((150 * Math.sin((x / 12) * PI) + 300 * Math.sin((x / 30) * PI)) * 2) / 3;
    return r;
}

/**
 * WGS84 (GPS、地址服务) 转为 GCJ-02 (高德地图使用的坐标). 中国大陆之外不做偏移.
 *
 * @returns {{latitude: number, longitude: number}}
 */
export function wgs84ToGcj02(latitude, longitude) {
    if (outOfChina(latitude, longitude)) {
        return { latitude, longitude };
    }
    let dLat = transformLat(longitude - 105, latitude - 35);
    let dLng = transformLng(longitude - 105, latitude - 35);
    const radLat = (latitude / 180) * PI;
    let magic = Math.sin(radLat);
    magic = 1 - OFFSET * magic * magic;
    const sqrtMagic = Math.sqrt(magic);
    dLat = (dLat * 180) / (((AXIS * (1 - OFFSET)) / (magic * sqrtMagic)) * PI);
    dLng = (dLng * 180) / ((AXIS / sqrtMagic) * Math.cos(radLat) * PI);
    return { latitude: latitude + dLat, longitude: longitude + dLng };
}

/**
 * GCJ-02 (高德地图上点击得到的坐标) 转回 WGS84, 精度约 1 米
 *
 * @returns {{latitude: number, longitude: number}}
 */
export function gcj02ToWgs84(latitude, longitude) {
    const shifted = wgs84ToGcj02(latitude, longitude);
    return {
        latitude: 2 * latitude - shifted.latitude,
        longitude: 2 * longitude - shifted.longitude,
    };
}

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
