// 移动端的类型声明: 扩展 web 的注册表与服务类型, 补充 Owl 组件上的 env / props

declare module "registries" {
    interface GlobalRegistryCategories {
        mobile_views: any;
        mobile_fields: any;
        mobile_pages: any;
    }
}

declare module "services" {
    interface Services {
        orm: any;
        mobileAction: {
            doAction(actionRequest: any, options?: { additionalContext?: Record<string, any> }): Promise<void>;
        };
    }
}

// 移动端的动作相关类型(与 actions/action_service.js 中的 JSDoc 保持一致, 供各模块共用)
type ActionRequest = number | string | Record<string, any>;
type Action = Record<string, any>;
type CurrentActionInfo = { name: string; action_id: number; svg_icon_href: string };
type MobilePageInfo = [number, string, string] | false;
