/**
 * 显示通知. web 的 notification.add 类型声明与实际的 options 不完全一致,
 * 这里集中做一次类型转换, 调用方仍然使用 { type, sticky, title } 这样的写法.
 *
 * @param {{ add: (message: string, options?: Record<string, any>) => any }} service notification 服务
 * @param {any} message 字符串, 或惰性翻译字符串(_t 的返回值)
 * @param {Record<string, any>} [options]
 */
export function notify(service, message, options = {}) {
    return service.add(message, /** @type {any} */ (options));
}
