/**
 * 列表删除: 调用 web 的删除接口 (orm.unlink), 删除前由服务端检查删除权限.
 */

/**
 * 当前用户是否有删除该模型记录的权限.
 * 调用空记录集的 has_access, 即模型级别的检查 (与服务端的 ORM 访问控制一致); 出错时视为没有权限.
 *
 * @param {{ call: Function }} orm
 * @param {string} resModel
 * @returns {Promise<boolean>}
 */
export async function canDeleteRecords(orm, resModel) {
    try {
        return Boolean(await orm.call(resModel, "has_access", [[]], { operation: "unlink" }));
    } catch {
        return false;
    }
}

/**
 * 删除记录; 权限不足或记录受约束时服务端抛出的错误由调用方提示
 *
 * @param {{ unlink: Function }} orm
 * @param {string} resModel
 * @param {number[]} ids
 */
export function deleteRecords(orm, resModel, ids) {
    return orm.unlink(resModel, ids);
}
