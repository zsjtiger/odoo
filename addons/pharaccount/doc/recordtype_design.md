# Record Type 设计（Odoo 原生方式，类似 ir.rule / ir.ui.view）

状态：设计稿，待确认后实现。

本版设计不再做一个独立的"功能"，而是用 Odoo 已有的几种机制来表达 Record Type：

- 类型本身是一条**配置数据**，结构和 `ir.ui.view` 一样：按模型绑定、有优先级、可以继承、可以按组分配；
- 类型的可见性不靠代码判断，而是**生成 `ir.rule`**，由框架的记录规则统一执行；
- 默认类型的结构和 `ir.default` 一样：按组、按模型保存一条记录；
- 类型的布局是一条 `ir.ui.view`（扩展视图），和普通视图继承的方式一致；
- 类型对应的菜单和动作由代码同步生成，和 `ir.actions` 的做法一致。

每条设计都在框架代码中核对过，引用的位置见第 1 节。

## 1. 框架依据

| 编号 | 事实 | 代码位置 |
|---|---|---|
| F1 | 用户的有效组是 `all_group_ids`，包含 `implied_ids` 传递得到的组 | `base/models/res_users/user_groups.py` 第 142–147 行 |
| F2 | `ir.access` 按组 OR；记录规则中有组的规则 OR，无组的全局规则 AND | `base/models/ir_access/access.py` 第 450–495 行 |
| F3 | 表单视图由动作或上下文决定（`form_view_ref`），不按单条记录切换 | `base/models/ir_ui_view/base.py` 第 260–300 行 |
| F4 | `ir.ui.view` 的字段：`model`、`priority`、`inherit_id`、`mode`（primary / extension）、`group_ids`、`active` | `base/models/ir_ui_view/view.py` 第 19–66 行 |
| F5 | `ir.access` 的字段：`model_id`、`group_id`、`operation`、`domain`、`active` | `base/models/ir_access/access.py` 第 25–35 行 |
| F6 | `ir.default` 的字段：`field_id`、`user_id`、`company_id`、`condition`、`json_value` | `base/models/ir_default.py` 第 21–28 行 |
| F7 | `load_menus` 缓存键为 `uid, debug, lang`，不含设备类型；菜单 `create`/`write` 会清缓存 | `base/models/ir_ui_menu.py` 第 21、148、154、229–231 行 |
| F8 | 任何非空 `write` 都会更新 `write_date`、`write_uid`，不比较旧值 | `orm/models/write.py` 第 221–243 行 |

## 2. 设计原则

1. **配置即数据**：类型、默认值、规则都是数据库记录，可以导出、迁移、在界面里查看；不把类型写死在代码里。
2. **复用框架机制**：可见性用 `ir.rule`，布局用 `ir.ui.view`，默认值用 `ir.default` 的结构。不自建鉴权或视图引擎。
3. **生成而非手写**：`ir.rule`、菜单、动作都由类型记录生成，手工修改生成物会被覆盖（生成物带标记字段）。
4. **只做增量**：继承只增加，不能减少父类型的组或选项，与 `ir.ui.view` 的扩展视图一致。

## 3. 数据模型

### 3.1 `ir.record.type`（类型定义，类似 `ir.ui.view`）

| 字段 | 类型 | 说明 | 类比 |
|---|---|---|---|
| `name` | Char，必填，可翻译 | 界面名称 | `ir.ui.view.name` |
| `code` | Char，必填 | 技术编码，`(model_id, code)` 唯一 | `ir.ui.view.key` |
| `model_id` | Many2one `ir.model`，必填，`ondelete='cascade'` | 绑定的模型 | `ir.access.model_id` |
| `priority` | Integer，默认 16 | 显示顺序，同 `ir.ui.view` 的 priority 含义 | `ir.ui.view.priority` |
| `mode` | Selection：`primary` / `extension` | 根类型为 primary，子类型为 extension | `ir.ui.view.mode` |
| `inherit_id` | Many2one `ir.record.type` | 父类型，必须是 primary 或同模型的类型 | `ir.ui.view.inherit_id` |
| `group_ids` | Many2many `res.groups` | 自身配置的可用组 | `ir.ui.view.group_ids` |
| `picklist_value_ids` | Many2many `pharaccount.picklist.value` | 自身配置的可选值 | — |
| `view_id` | Many2one `ir.ui.view` | 类型的布局（扩展视图，见第 5 节） | — |
| `rule_id` | Many2one `ir.rule`，只读 | 系统生成的记录规则（见第 4 节） | — |
| `menu_id` | Many2one `ir.ui.menu`，只读 | 系统生成的菜单（见第 6 节） | — |
| `active` | Boolean | 停用后不可新建或切换，已有记录仍由规则保留可见性 | `ir.ui.view.active` |
| `allowed_group_ids` | 计算、存储 | 自身与所有祖先的组的并集 | — |
| `allowed_picklist_value_ids` | 计算、存储 | 自身与所有祖先的选项的并集 | — |

约束：

- `(model_id, code)` 唯一；
- `mode = 'primary'` 时 `inherit_id` 为空；`mode = 'extension'` 时 `inherit_id` 必填，且同一 `model_id`；
- 沿 `inherit_id` 不能循环（与 `ir.ui.view` 的检查方式一致）；
- `view_id` 的 `model` 必须等于绑定模型，且 `type = 'form'`。

### 3.2 `ir.record.type.default`（默认类型，类似 `ir.default`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `model_id` | Many2one `ir.model`，必填，`ondelete='cascade'` | 模型 |
| `group_id` | Many2one `res.groups`，必填，`ondelete='cascade'` | 用户组 |
| `record_type_id` | Many2one `ir.record.type`，必填，`ondelete='cascade'` | 默认类型 |

约束：

- `(model_id, group_id)` 唯一，即每组每模型只有一个默认；
- `record_type_id.model_id` 必须等于 `model_id`；
- `group_id` 必须属于 `record_type_id.allowed_group_ids`。

默认值的选取与 `ir.default` 相同方式：按用户的有效组（F1）查找，多个组给出不同默认时取类型 `priority` 最小的。

### 3.3 Mixin：`record.type.mixin`

业务模型继承后获得：

- `record_type_id`：Many2one `ir.record.type`，`required=True`（迁移期间可先为空），`index=True`，`ondelete='restrict'`；
- `record_type_id` 的域：`[('model_id.model', '=', _name), ('active', '=', True)]`，并叠加"当前用户组可用"的过滤；
- `default_get`：按 3.2 查找默认类型。

## 4. 权限：生成 `ir.rule`

### 4.1 生成规则

每个 `ir.record.type` 生成一条 `ir.rule`，由 `rule_id` 关联：

- 模型：`model_id`（与类型相同）；
- 组：`group_ids` 为类型的 `allowed_group_ids`（F2：有组的规则之间 OR）；
- 域：`[('record_type_id', '=', <类型 id>)]`；
- `perm_read`、`perm_write`、`perm_create`、`perm_unlink` 全部为真。

这样，用户能看到某条记录，当且仅当存在一条规则，其组与用户的有效组（F1）有交集，并且记录的类型就是该规则对应的类型。

### 4.2 语义

- 类型没有任何组时，生成的规则没有组。根据 F2，无组的规则是全局 AND 规则，会把记录限制为空集。因此**没有组的类型，记录对非管理员不可见**。这是需要确认的决定（见第 9 节）。
- 对管理员，框架的 `base.group_system` 不会自动绕过规则，需要额外生成一条管理员规则：组为 `base.group_system`，域为 `[(1, '=', 1)]`。
- 类型继承：子类型的 `allowed_group_ids` 已包含父类型的组，所以子类型的规则自动包含父类型的组，无需额外处理。

### 4.3 启用风险

给一个模型第一次生成规则时，所有非管理员对这个模型的访问都会被规则限制。因此必须：

1. 先为现有记录补齐 `record_type_id`；
2. 再为每个类型生成规则，并生成管理员规则；
3. 在同一个事务中完成，避免中间状态下用户看不到数据。

### 4.4 维护

- 类型 `create` 时生成规则；
- 类型的 `allowed_group_ids`、`active` 变化时更新规则的 `group_ids`；
- 类型删除时，`ondelete='restrict'`（已有记录引用时不允许删除），没有记录时删除规则；
- 只写入真正变化的字段，避免 F8 下的无意义写入。

## 5. 布局：类型的扩展视图

- 每个类型可以有一个 `ir.ui.view`，`mode = 'extension'`，`inherit_id` 为模型的默认表单视图，内容只写该类型与默认布局的差异；
- 与 F3 对应：布局在菜单动作上生效。菜单的动作把 `form_view_ref` 设为类型的视图（见第 6 节）；
- 通过其他入口打开的记录，使用模型的默认表单；
- 同一记录从不同菜单打开，布局可能不同，这是框架的限制，也是与 Salesforce 的主要差异。

## 6. 菜单与动作：生成

每个类型生成一个菜单（`menu_id`）和一个窗口动作：

| 项 | 值 |
|---|---|
| 菜单父级 | 模型的根菜单（由模块提供） |
| 菜单名称 | 类型的 `name` |
| 菜单 `groups_id` | 类型的 `allowed_group_ids`（F7 下按组过滤） |
| 菜单 `sequence` | 类型的 `priority` |
| 动作 `res_model` | 绑定模型 |
| 动作 `domain` | `[('record_type_id', '=', <类型 id>)]` |
| 动作 `context` | `{'default_record_type_id': <类型 id>}` |
| 动作 `view_id` 或 `form_view_ref` | 类型的 `view_id` |

`_sync_menus()` 幂等：只更新有变化的字段（F8）。菜单 `create` 和 `write` 会清缓存（F7）。停用的类型，菜单设为不可用，不删除。

### 6.1 移动端

F7：`load_menus` 的缓存不区分设备，直接生成移动端菜单会让 PC 菜单出现在移动端列表中。移动端菜单要等 `mobile_web` 的缓存键修复后再做，修复需要单独评审。

## 7. 继承

与 `ir.ui.view` 的扩展视图一致：

- 子类型只能增加组和选项，不能减少父类型的；
- `allowed_group_ids` 和 `allowed_picklist_value_ids` 是父子的并集，存储在子类型上，用于规则域和控件过滤；
- 修改父类型时，所有后代的计算字段自动重算，生成的规则和菜单随之同步（通过 `_sync_menus()` 与 `_sync_rules()` 在依赖变化时调用）。

## 8. 迁移 pharaccount

1. 新模块 `record_type` 上线，定义上面的模型和 mixin；
2. `pharaccount.account` 继承 mixin，`record_type_id` 暂时允许为空；
3. 迁移脚本（`migrations/` 目录，`post` 阶段）：
   - 把 `pharaccount.record.type` 的每条记录转为 `ir.record.type`，`model_id = pharaccount.account`，`mode` 按 `parent_id` 决定，`inherit_id` 映射父类型；
   - 把 `group_ids`、`picklist_value_ids` 原样映射；
   - 把 `pharaccount.account.record_type_id` 映射到新类型；
   - 对没有组的类型，按第 9 节的决定补齐组，否则迁移后对非管理员不可见；
   - 生成规则、管理员规则和菜单；
4. 把 `record_type_id` 改为必填；
5. 旧的 `pharaccount.record.type` 保留一个版本，只读，然后删除。

注意：迁移中的写入会更新 `write_date` 和 `write_uid`（F8），需要在迁移说明中记录。

## 9. 需要你确认的决定

1. **空组规则**：没有组的类型对非管理员不可见（本设计的默认，接近 Salesforce），还是保留现在的"空表示所有人可用"？后者需要额外的全局规则，并且与 F2 的 AND 语义冲突，实现会复杂。
2. **管理员绕过**：是否统一加管理员规则 `[(1, '=', 1)]`，还是只对 `base.group_system` 生效？
3. **布局限制**：接受"同一记录从不同菜单打开布局可能不同"吗？
4. **移动端**：先修 `mobile_web` 缓存键（F7）再做移动端菜单，还是本期只做 PC？
5. **菜单位置**：类型做成模型根菜单下的子菜单（建议），还是顶层菜单？
6. **Permission Set**：本期不做独立于用户组的授权，是否同意？

## 10. 测试

- 数据：唯一约束、`mode` 与 `inherit_id` 的一致性、循环检测、`view_id` 的模型一致；
- 默认（3.2）：每组每模型唯一；默认属于该组的可用类型；
- 规则（4）：有组用户只看到自己类型的记录；无组类型对非管理员不可见；管理员看到全部；
- 继承：子类型组和选项为并集，父类型修改后后代同步；
- 菜单（6）：生成、停用、组过滤、幂等；
- 布局（5）：菜单动作使用类型视图，其他入口使用默认视图；
- 迁移（8）：迁移前后，每个用户可见的记录数一致；
- 启用风险（4.3）：在无规则的模型上启用时，先补齐类型再生成规则，中间状态不暴露数据。

## 11. 实现顺序

1. `ir.record.type` 与 `ir.record.type.default` 的模型、约束、继承计算，附测试；
2. 规则生成（4.1–4.4），附测试，包括管理员规则；
3. mixin 与 `default_get`（3.3）；
4. 菜单与动作同步（6）；
5. 类型视图（5）；
6. picklist 控件过滤；
7. pharaccount 迁移（8）；
8. 移动端菜单（6.1），等 F7 修复后。

每一步单独提交并跑对应测试。
