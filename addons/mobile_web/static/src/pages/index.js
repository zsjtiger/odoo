// 页面注册入口: 每个页面模块在加载时把自己加入 mobilePageRegistry.
// 在这里显式 import, 新增页面时只需在此登记, 不依赖打包时的文件顺序.
import "@mobile_web/pages/home/home_page";
import "@mobile_web/pages/todo/todo_page";
import "@mobile_web/pages/schedule/schedule_page";
import "@mobile_web/pages/my/my_page";
import "@mobile_web/pages/ai/ai_page";
