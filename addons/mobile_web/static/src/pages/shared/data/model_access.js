/**
 * 判断某个模型在当前数据库中是否可用 (即其所属模块是否已安装).
 * 页面依赖的模块(如日历、待办)未安装时, 页面显示"暂未开放", 而不是报错.
 *
 * @param {{ call: (model: string, method: string, args: any[], kwargs?: object) => Promise<any> }} orm
 * @param {string} model 技术名称, 如 "calendar.event"
 * @returns {Promise<boolean>}
 */
export async function isModelAvailable(orm, model) {
    try {
        const count = await orm.call("ir.model", "search_count", [[["model", "=", model]]]);
        return count > 0;
    } catch {
        return false;
    }
}
