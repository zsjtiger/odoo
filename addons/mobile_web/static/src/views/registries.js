import { registry } from "@web/core/framework/registry";

/**
 * 移动端视图注册表: key 为 view type (list / kanban / form)
 */
export const mobileViewRegistry = registry.category("mobile_views");

/**
 * 移动端字段注册表: key 为 widget 名称, 没有指定 widget 时使用字段类型(char, many2one, ...)
 */
export const mobileFieldRegistry = registry.category("mobile_fields");
