import { mobileActionService } from "@mobile_web/actions/action_service";

/**
 * 注册移动端的服务. 只在 main.js 中调用一次; 服务已存在时保留原有注册.
 *
 * @param {{ contains: (key: string) => boolean, add: (key: string, value: any) => void }} category
 *        services 注册表分类
 */
export function registerMobileServices(category) {
    if (!category.contains("mobileAction")) {
        category.add("mobileAction", mobileActionService);
    }
}
