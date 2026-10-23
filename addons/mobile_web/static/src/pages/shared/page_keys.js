/**
 * 手机端页面的注册key, 与 `models/mobile_page.py` 中的 `PAGE_COMPONENT_IDS` 保持一致
 * (数据中的 `page_component_id` 必须是其中之一, 由 tests/test_mobile_page.py 校验)
 */
export const PAGE_KEYS = Object.freeze({
    HOME: "mobile_page.home_page",
    TODO: "mobile_page.todo_page",
    SCHEDULE: "mobile_page.schedule_page",
    MY: "mobile_page.user_my_page",
    AI: "mobile_page.ai_page",
});
