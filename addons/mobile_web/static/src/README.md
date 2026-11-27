# 移动端前端代码结构

按功能域组织, 同一功能的 js、scss 与测试放在一起. 依赖只能向下:
`app → pages / reports / layout / actions / views → fields / widgets → core`

| 目录 | 内容 |
|---|---|
| `app/` | 入口与 webclient 根组件 (`main.js`, `webclient.js`) |
| `core/` | 与界面无关的基础设施: 路由 (`browser/router.js`)、界面文字 (`texts.js`) |
| `styles/` | 全局样式: 颜色变量 (`variables.scss`, 样式包中排在最前)、基础样式 |
| `layout/` | 页面外壳: 导航栏 `navbar/`、动作容器 `action_container/` |
| `actions/` | 动作系统: action 服务、加载器、动作菜单 `action_menu/`、记录按钮 (`record_buttons.js`: 表单头部与列表/看板的操作) |
| `views/` | 视图框架: arch 解析、记录模型与列表、视图注册表; 视图本身在 `list/`、`kanban/`、`form/`、`act_window/` |
| `fields/` | 字段组件与字段记录适配层 (`field_record.js`); 选择类 (`selection_fields.js`: radio、statusbar、priority)、数值类 (`numeric_fields.js`: percentage、float_time) |
| `widgets/` | 通用控件: 底部弹层 `select_sheet/`、操作弹层 `action_sheet/`、选择器按钮 `picker/`、按钮 `button/`、文件按钮 `file_button/`、开关 `switch/`、图标 `svg_icon/`、通用样式 `ui/` |
| `reports/` | 报表类展示组件: `home_report/` |
| `pages/` | 页面: 首页 (`home/`)、待办、日程、我的; 页面注册表在 `shared/` |

约定:
- 每个组件的样式放在组件旁边 (`*.scss`), 通过清单 `__manifest__.py` 中的资产包加载.
- 对外的导入路径使用 `@mobile_web/<目录>/<文件>`, 不要跨目录导入其它组件的内部文件.
- 测试在 `static/tests/` 下镜像源码目录结构, 公共测试工具在 `static/tests/helpers/`.

类型检查:
- 源码是 JS, 用 JSDoc 标注类型; `../jsconfig.json` 开启了 `checkJs`, 并引用 web 的 `@types` 与 `owl.d.ts`.
- 运行 `../typecheck.sh` 检查 `src/` 下的错误 (需要 `tsc`, 例如 `npm i -g typescript@5`).
- `src/@types/mobile.d.ts` 补充移动端的注册表分类与服务类型; Owl 的 `Component` 没有 `env` 等类型, 通过 `core/env.js` 的 `envOf` 访问.
