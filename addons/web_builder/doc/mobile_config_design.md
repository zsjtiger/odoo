# Studio 支持移动端配置（mobile_web）：设计方案

状态：设计草案，尚未实现。范围：在 Studio（web_builder）的模型设计器里配置 mobile_web 的移动端界面。

## 1. 背景

mobile_web 的移动端配置现在分散在几个模型里，只能通过代码或数据文件修改，Studio 里看不到：

| 配置 | 模型 / 位置 | 作用 | 现在如何配置 |
|---|---|---|---|
| 菜单的显示端 | `ir.ui.menu.device_type`（mobile / pc / both） | 菜单只在手机、PC 或两端显示 | 代码或数据 |
| 移动端动作与视图 | `ir.actions.act_window` + `ir.actions.act_window.view`（移动端动作，如 `action_pharaccount_account_mobile`） | 移动端列表、表单、看板使用哪些视图 | 代码或数据 |
| 移动端页面与导航 | `ir.actions.mobile_page`、`mobile_web.mobile.page`、`mobile_web.mobile.page.actions` | 底部导航：页面组件、导航项、图标、排序 | 数据文件（`data/mobile_pages.xml`） |
| 自定义字段 | `mobile.custom.field` | 把 many2one 路径上的字段显示在移动端列表 / 表单，并生成对应字段与视图 | 手机端的配置界面 / 代码 |
| 筛选面板 | `base.dynamic_filter_config()` | 移动端列表的筛选分组（选项、域、卡片） | 代码覆盖方法 |

Studio 目前只管理 PC 端的视图、字段和菜单，没有移动端的入口。

## 2. 约束（决定了哪些能在 Studio 里配置）

1. **页面组件由前端代码注册**：`mobile_web/models/mobile_page.py` 中的 `PAGE_COMPONENT_IDS` 与前端 `page_keys.js` 保持一致。Studio 只能把导航项指向已有的页面组件，不能新建页面组件。
2. **图标来自图标包**：`static/public/iconfont.js` 中的 symbol。Studio 只能从中选择；新增图标需要重新生成图标包，属于开发工作。
3. **移动端只渲染 list、kanban、form**：其他视图退回到第一个支持的视图（`action_utils.js`）。search 视图作为筛选来源。
4. **移动端视图靠移动端动作挂载**：PC 动作不变，移动端动作单独列出视图。因此"移动端表单"就是移动端动作上的 form 视图，不改 PC 的表单。
5. **菜单的显示端是 `device_type`**：过滤逻辑在 `ir.ui.menu._filter_visible_menus`，不需要改动。

## 3. 方案

### 3.1 入口：模型设计器中的"Mobile"页签

在 Studio 模型页的导航中增加 "Mobile"（与 "Record Types" 同级）。页签内分五个小节：

| 小节 | 配置内容 | 数据来源 |
|---|---|---|
| 布局（Layouts） | 移动端的列表、看板、表单：选择视图并用 Studio 的页面布局编辑器编辑（与 PC 的 Page Layouts 类似，但保存到移动端动作的视图上） | 移动端动作与其 `act_window.view` |
| 自定义字段（Fields） | 添加 `mobile.custom.field`：标签、路径（many2one 链）、是否显示在列表、排序、是否存储 | `mobile.custom.field` |
| 筛选（Filters） | 分组、选项（名称、域、单选 / 多选）、卡片（many2one 字段与子字段） | 新增配置模型，见 3.3 |
| 菜单（Menus） | 每个菜单的显示端：手机 / PC / 两端 | `ir.ui.menu.device_type` |
| 导航（Navigation） | 手机端底部导航：页面组件（从已注册列表选）、导航项、图标（从图标包选）、排序 | `mobile_web.mobile.page`、`mobile_web.mobile.page.actions` |

每个小节都只读写已有模型，除"筛选"外不新增模型。

### 3.2 移动端布局

- 移动端的动作由 Studio 按需创建：模型已有移动端动作时直接使用；没有时创建 `ir.actions.act_window`（名称 "<模型名> (Mobile)"），并把它记录在 `ir.model.data` 中（Studio 已有的做法，`create_studio_model_data`）。
- 移动端动作的 `view_mode` 为 `kanban,form` 或 `list,form`，视图使用 `ir.actions.act_window.view` 挂载。
- 表单与列表的布局使用 Studio 的页面布局编辑器（`PageLayoutEditor`），保存的是这些视图的 arch，不影响 PC 视图。
- "在视图编辑器中打开" 的入口保留，用于复杂修改。

### 3.3 筛选（新增配置模型）

`base.dynamic_filter_config()` 现在返回 `[]`，因此移动端使用搜索视图的筛选。要在 Studio 中配置，需要一个数据模型：

| 模型 | 字段 |
|---|---|
| `mobile.filter.section` | 模型（model_id）、名称、标签、序号、激活 |
| `mobile.filter.option` | 分组（section_id）、key、标签、域（domain，字面量列表）、单选（radio）、序号 |
| `mobile.filter.card` | 分组（section_id）、many2one 字段（field_id）、子字段（subfield）、序号 |

`dynamic_filter_config()` 的 `Base` 实现改为读取上面三个模型，并保持返回格式不变。没有配置时仍返回 `[]`。

域的编辑复用 Studio 已有的域选择器。域必须是字面量（与 ir_data_import 的规则一致），不接受 Python 表达式。

### 3.4 自定义字段

- 直接复用 `mobile.custom.field`。Studio 中只提供界面：标签、路径（字段选择器，只允许 many2one 链）、是否显示在列表、序号、存储。
- 保存时沿用模型中已有的生成逻辑（`field_name`、`field_id`、`view_id` 由配置创建与删除）。

### 3.5 菜单的显示端

- 在 Studio 的菜单编辑处增加"显示在"选择：手机、PC、两端（对应 `device_type`）。
- 默认值保持 `pc`，与现有行为一致。

### 3.6 移动端导航

- 只允许选择已注册的页面组件（`PAGE_COMPONENT_IDS`），不允许新建。
- 图标选择器读取图标包中的 symbol id，与 `get_sprite_icon_ids()` 一致。
- 导航项指向一个动作（`ir.actions.act_window` 或 `ir.actions.mobile_page`），在 Studio 中选择即可。

## 4. 权限

- 只有 Studio 用户（`base.group_system` 或 Studio 的开发组）可以编辑移动端配置。
- 移动端动作、视图、字段都是系统配置，读写时按现有的 ACL，不额外开放。
- 筛选的域是代码执行之外的字面量，不会执行任意代码。

## 5. 数据迁移与兼容

- 现有的移动端配置（如药店的移动端动作、导航数据文件）保持不变，Studio 只读取它们。
- 在 Studio 中修改后的数据，与数据文件中的 `noupdate` 记录的关系需要说明：只有 Studio 创建或修改的记录会被标记，升级时不覆盖。
- 新增的筛选模型在 web_builder 中定义，不影响 mobile_web 的已有行为（未配置时返回 `[]`）。

## 6. 不做（超出范围）

- 新建移动端页面组件（需要前端开发）。
- 新增图标（需要重新生成图标包）。
- 移动端自定义的 JS 组件或交互。
- 移动端的记录类型入口（如 pharaccount 的类型选择器）：它是前端行为，目前由代码实现；Studio 只配置它所用的记录类型，见 `ir_data_import` 与 `ir_recordtype`。

## 7. 实施阶段

1. **阶段 1**：菜单的显示端；自定义字段；导航项（只选已有页面与图标）。这些都复用现有模型，改动最小。
2. **阶段 2**：移动端布局（移动端动作与视图，复用页面布局编辑器）。
3. **阶段 3**：筛选（新增三个模型与 `dynamic_filter_config` 的实现）。

## 8. 待确认

1. 阶段 1 是否先做？（建议：是，改动最小，且能立即看到效果。）
2. 移动端布局是否需要"移动端视图"与 PC 视图完全分开（推荐：是，与现有的移动端动作一致）。
3. 筛选是否需要在阶段 3 中实现，还是暂时只保留代码配置？
