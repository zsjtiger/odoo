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

## 9. 控件与布局的支持范围

Studio 的编辑器能放的控件，与移动端能渲染的控件并不完全相同。移动端编辑器只能提供移动端能显示的内容，否则配置后在手机上看不到。下面按代码核对的结果列出两边的对应关系。

### 9.1 字段类型（Studio 的 "Data Type" 与移动端字段组件）

| Studio 类型 | 移动端组件 | 处理 |
|---|---|---|
| Checkbox（boolean） | boolean（另有 boolean_toggle） | 支持 |
| Text（char） | char | 支持 |
| Long text（text） | text | 支持（标签放在上方） |
| Rich text（html） | html | 支持 |
| Number（integer） | integer | 支持 |
| Decimal（float） | float | 支持 |
| Currency（monetary） | monetary | 支持 |
| Date / Date/Time | date / datetime | 支持 |
| Picklist（selection） | selection，widget 为 radio / badge / priority / statusbar 时使用对应组件 | 支持 |
| Lookup（many2one） | many2one（或 many2one_avatar） | 支持 |
| Multi-select lookup（many2many） | many2many、many2many_tags、many2many_checkboxes | 支持 |
| Related list（one2many） | one2many、one2many_form（内嵌表单） | 支持 |
| File（binary）、Image（image） | binary、image | 支持 |
| Properties（properties） | 无对应组件，回退为 fallback（只读显示值） | 不支持：编辑器隐藏；已有的字段在移动端只读显示 |
| Signature（视图编辑器的新字段列表中有） | 无，回退为 fallback（只读显示值） | 不支持：编辑器隐藏；已有的字段在移动端只读显示 |
| Related field（related） | 按目标字段类型渲染 | 支持 |

`widget` 属性：移动端只识别已注册的 widget 名（见 `mobile_web/static/src/fields/`）。Studio 中设置的 PC 专用 widget（如 `statinfo`、`ace`、`html_frame`）在移动端会回退为字段类型的默认组件。编辑器需要在选择 widget 时显示"移动端的显示方式"，并对回退的情况给出提示。

### 9.2 布局结构

| Studio 结构 | 移动端 | 处理 |
|---|---|---|
| 表头按钮（header buttons） | 底部按钮栏（只在表头） | 支持，只允许放在表头 |
| 状态条（statusbar） | statusbar 组件，显示为 "进度: 状态" | 支持 |
| 分区（Section，带标题） | 带标题的分组（group） | 支持 |
| 分区的多列（Column，两列及以上） | 单列：多列被压平 | 不支持多列：移动端编辑器只允许一列，已有的多列配置显示提示 |
| 标签页（Tabs，notebook / page） | notebook，每页一个标签 | 支持 |
| 分隔线（separator） | separator | 支持 |
| 聊天框（chatter） | 不渲染 | 不支持：移动端隐藏 |
| 表单正文中的按钮（button） | 不渲染（只在表头） | 不支持：移动端隐藏，并提示改放到表头 |
| 原样保留的 XML 块（raw blocks） | 不渲染 | 不支持：移动端隐藏 |
| 看板卡片模板（kanban templates） | 卡片的标题是第一个字段，其余字段是卡片内容；只读取 arch 中的 field 节点，QWeb 指令（t-if、t-att 等）被忽略 | 部分支持：只允许字段，不允许条件与样式指令 |
| 列表的字段列 | list 视图的列 | 支持 |

### 9.3 视图类型

| Studio 视图 | 移动端 | 处理 |
|---|---|---|
| form | form | 支持 |
| list | list | 支持 |
| kanban | kanban | 支持（卡片见 9.2） |
| calendar | calendar | 支持（与 PC 共用视图 arch） |
| graph、pivot、gantt、activity | 不支持 | 移动端隐藏；移动端布局的视图选择只列出支持的类型 |
| search | 作为移动端的筛选来源（facets） | 不在本方案的编辑范围内，沿用现有搜索视图 |

### 9.4 字段属性

| 属性 | 移动端 | 处理 |
|---|---|---|
| invisible、readonly、required | 支持（`views/form/modifiers.js`） | 支持 |
| domain（多对一） | 支持：多对一选择器使用字段的 domain，可引用记录上的其他字段 | 支持 |
| domain（多对多、一对多） | 不支持：多对多的选择器不使用 domain | 编辑器提示；不支持的字段不设置 domain |
| context（关系字段） | 不支持：移动端的名称搜索 context 固定为空 | 编辑器隐藏 context 相关配置 |
| widget | 见 9.1 | 提示 |

### 9.5 设计决定

1. **能力的唯一来源**：在 `mobile_web` 中新增 `models/mobile_capabilities.py`，列出字段组件、表单标签、视图类型。一个测试扫描前端的 `mobileFieldRegistry.add(...)` 与 `mobileViewRegistry.add(...)`，确认与这个列表一致，避免两边不同步。
2. **编辑器的移动端模式**：页面布局编辑器增加"移动端"模式（与 PC 的布局并排）。移动端模式只显示 9.1 至 9.3 中"支持"的控件，多列只允许一列，不支持的结构隐藏。
3. **已有配置的处理**：打开移动端模式时，如果已有不支持的配置（如多列、正文按钮），不自动删除，而是在界面上列出警告，由用户决定是否修改。
4. **保存时校验**：视图类型不支持的（如移动端配置了 graph）拒绝保存；控件层面的不支持只给警告，保存仍然允许，因为 PC 端仍然需要这些配置。
5. **PC 与移动端的 arch 分开**：移动端的布局保存为移动端动作上的视图（见 3.2），PC 视图不被修改。但字段的定义（字段本身）是共享的，修改字段类型会同时影响两端，编辑器需要提示。

### 9.6 核对结果与待决定的问题

9.6.1 核对结果（已对照代码）

| 问题 | 核对结果 |
|---|---|
| 看板卡片能支持到什么程度 | `mobile_kanban_view.js`：标题取第一个字段，其余字段作为卡片内容；只读取 field 节点，QWeb 指令被忽略。因此看板模板只能配置字段，不能配置条件或样式。 |
| 关系字段的 domain、context 是否生效 | domain：只有多对一选择器使用（`relational_fields.js`，可引用记录上的其他字段）；多对多和一对多不使用。context：所有关系字段的名称搜索都传入空 context，不生效。 |
| Signature、Properties 的处理 | 移动端回退为只读的 fallback 组件，显示值，不会报错，也不会隐藏。因此编辑器隐藏这两种字段，但已有的字段在手机上仍会以只读形式出现。 |

9.6.2 待决定的问题

1. **警告与拒绝的边界**：建议与 9.5 第 4 点一致：视图类型不支持的拒绝保存；控件层面的不支持只警告。（这是策略问题，代码无法判断。）
2. **看板卡片**：建议只允许字段，不允许 QWeb 指令；编辑器中的看板模板在移动端模式下去掉条件和样式。
3. **domain、context**：建议多对一保留 domain 配置；多对多、一对多的 domain 在移动端模式下隐藏并提示；context 在移动端模式下隐藏。
4. **Signature、Properties**：建议编辑器隐藏；已有字段在移动端只读显示，编辑器给出提示说明这一点。
