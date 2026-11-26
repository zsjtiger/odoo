# Record Type 设计（自底向上，参考 Salesforce）

状态：设计稿，待确认后实现。

本文档从 Odoo 框架的约束出发，逐层向上设计。每一条框架事实都注明了代码位置，已在仓库中核对。

## 0. 框架事实（设计的前提）

| 编号 | 事实 | 代码位置 | 对设计的影响 |
|---|---|---|---|
| F1 | 用户的有效组 = `all_group_ids`，包含通过 `implied_ids` 传递得到的组 | `res_users/user_groups.py` 第 142–147 行 | 类型的授权要用有效组判断，不能只看直接组 |
| F2 | 对象级访问（`ir.access`）按组 OR；记录级规则（`rule`）中，有组的规则 OR，没有组的全局规则 AND | `ir_access/access.py` 第 450–495 行 | 类型的记录规则可以叠加在对象访问之上，全局规则要谨慎 |
| F3 | 表单视图由动作或上下文决定（`form_view_ref`），不会按单条记录切换 | `ir_ui_view/base.py` 第 260–300 行 | "按类型切换布局"只能在动作（菜单）层实现 |
| F4 | 菜单按用户组过滤；`load_menus` 的缓存键是 `uid, debug, lang`，不含设备类型 | `ir_ui_menu.py` 第 229–231 行 | 移动端菜单会被 PC 菜单污染，需先修复（见第 7 节） |
| F5 | 菜单的 `create`、`write` 会清理缓存（`_clear_cache_name = 'default'`） | `ir_ui_menu.py` 第 21、148、154 行 | 类型变更后可以同步菜单并自动清缓存 |
| F6 | 任何非空的 `write` 都会更新 `write_date` 和 `write_uid`，不比较旧值 | `orm/models/write.py` 第 221–243 行 | 批量维护类型时要避免无意义的写入 |
| F7 | Odoo 没有 Salesforce 的 Profile，授权单位只有用户组 | — | 类型授权直接使用 `res.groups` |

## 1. 目标与边界

Salesforce 的 Record Type 有四个作用：

1. 同一对象下区分记录种类；
2. 每种类型可选的 picklist 值不同；
3. 每种类型有自己的页面布局；
4. 通过分配给 Profile 决定谁能用哪种类型。

本设计在 Odoo 中实现前三点加第四点的用户组版本，并提供：

- 每个用户组对每个模型的默认类型；
- 类型对应的菜单入口（PC 和移动端）；
- 按类型的记录级可见性。

边界（本期不做）：

- Permission Set（独立于用户组的授权）；
- 字段级安全；
- 按类型的审批流程；
- 单条记录在打开后切换布局（框架不支持，见 F3）。

## 2. 第 1 层：数据模型

### 2.1 `record.type`（新模块 `record_type`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `res_model` | Char，必填 | 绑定的模型，如 `pharaccount.account` |
| `name` | Char，必填 | 技术编码，`(res_model, name)` 唯一 |
| `label` | Char，必填，可翻译 | 界面名称 |
| `sequence` | Integer | 排序 |
| `active` | Boolean | 停用后不可新建或切换，已有记录保留 |
| `parent_id` | Many2one `record.type` | 父类型，必须是同一 `res_model` |
| `child_ids` | One2many | 反向 |
| `group_ids` | Many2many `res.groups` | 自身配置的可用组 |
| `allowed_group_ids` | 计算、存储 | `group_ids` 与所有祖先的 `group_ids` 的并集 |
| `picklist_value_ids` | Many2many | 自身配置的可选值 |
| `allowed_picklist_value_ids` | 计算、存储 | 与父类型取并集 |
| `view_id` | Many2one `ir.ui.view` | 绑定的表单视图（见第 5 节） |
| `menu_ids` | One2many `ir.ui.menu` | 系统生成的菜单，只读 |
| `default_for_group_ids` | Many2many `res.groups` | 对本类型设为默认的组（见 2.2） |
| `description` | Text | 说明 |

约束：

- `(res_model, name)` 唯一；
- `parent_id` 与自身的 `res_model` 相同；
- 沿 `parent_id` 不能循环（检查祖先链）；
- `view_id` 的 `model` 必须等于 `res_model`，且类型为 `form`；
- 没有组的类型只允许管理员使用（见第 4.1 节）。

### 2.2 默认类型

默认类型不做成独立模型，而是用 `record.type` 上的 `default_for_group_ids`，但需要保证每组每模型只有一个默认。用约束检查：

- 对同一个组，`default_for_group_ids` 与同一 `res_model` 的其他类型互斥；
- 默认类型必须属于该组的 `allowed_group_ids`。

理由：避免新增一个模型，约束写在一处。缺点是跨类型的约束需要 `@api.constrains` 手动查询，性能可接受（类型数量很少）。

### 2.3 Mixin `record.type.mixin`（抽象模型）

业务模型继承后获得：

- `record_type_id`：Many2one `record.type`，`ondelete='restrict'`，`index=True`；
- `record_type_id` 的域：`[('res_model', '=', _name), ('active', '=', True)]`，并且只显示当前用户可用的类型（在域中用 `allowed_group_ids` 过滤，见第 4.2 节）；
- `default_get`：对当前有效组，取默认类型，只有一个时直接选中；
- 写入校验（见 3.3 节）。

## 3. 第 2 层：业务逻辑

### 3.1 继承计算

`allowed_group_ids` 与 `allowed_picklist_value_ids` 用 `@api.depends` 沿 `parent_id` 链计算，存储以便用于域。依赖链变化时需要重算所有子类型，这由 ORM 自动完成。

### 3.2 默认值选择

`default_get` 的规则：

1. 取当前用户所有有效组（`all_group_ids`）；
2. 在这些组的默认类型中选择；
3. 若多个组给出不同的默认类型，取 `sequence` 最小的；
4. 若没有默认，则取用户可用的第一个类型；
5. 若没有任何可用类型，不设置默认值，保存时由校验报错。

### 3.3 写入校验

在 `write` 和 `create` 中：

- 新记录或修改 `record_type_id` 时，要求新类型的 `allowed_group_ids` 与用户的 `all_group_ids` 有交集，否则报错；
- 修改已有记录的类型时，同样校验；
- 类型不可以被管理员以外的用户修改（类型本身的配置权限见第 4.3 节）。

注意：按 F6，只在真正修改类型时写入，避免无意义的 `write`。

## 4. 第 3 层：权限

### 4.1 三层控制（与 F2 对应）

1. **谁能用某个类型**：`allowed_group_ids` 与有效组有交集；
2. **能看到哪些记录**：记录规则，见 4.2；
3. **能做什么操作**：模型自己的 `ir.access` 记录，与类型无关。

### 4.2 记录规则

规则域（有组的规则，在 `ir.rule` 中按组 OR 生效）：

```
[('record_type_id.allowed_group_ids', 'in', user.all_group_ids.ids)]
```

应用于每个绑定了类型的模型，组为 `base.group_user`（所有内部用户）。

由于 F2 中有组的规则之间是 OR，此规则应当与"可见"的其他规则叠加方式一致。需要注意：

- 如果模型上已有其他组的规则，要确认 OR 的结果符合预期；
- 对管理员组（`base.group_system`）单独加一条不带限制的规则，或者直接不挂此规则。

### 4.3 空组规则（需要确认）

没有分配任何组的类型：

- 方案 A（Salesforce 式）：对所有非管理员不可见、不可用；
- 方案 B（现有 pharaccount 式）：对所有人可用。

建议方案 A。实现时，方案 A 对应的域为 `[('record_type_id.allowed_group_ids', 'in', user.all_group_ids.ids)]`，因为空组的类型在 `in` 中永远不匹配；方案 B 需要在域中额外加 `record_type_id.allowed_group_ids = False`。

### 4.4 类型配置权限

`record.type` 本身的增删改，授予一个新组 `record_type.group_config`，并由 `ir.access` 控制。普通用户只读。

## 5. 第 4 层：视图（页面布局）

按 F3，框架不支持单条记录按类型切换表单。因此：

- 类型的布局在**菜单动作**上实现：每个类型的菜单动作指定 `form_view_ref` 为类型绑定的视图；
- 通过菜单打开时，列表和表单都使用该类型的视图；
- 如果记录是从其他入口打开的（例如相关字段、搜索），使用模型的默认表单；
- 类型绑定的视图通过 `ir.ui.view` 的继承实现，不复制整个视图。

这意味着：同一条记录，从不同菜单打开时布局可能不同。这一点需要用户接受，也是与 Salesforce 的主要差异。

## 6. 第 5 层：菜单

### 6.1 生成规则

每个 `record.type` 生成一个菜单，由函数 `_sync_menus()` 维护：

- 父菜单：模型的根菜单，由模块提供；
- 菜单名称：类型的 `label`；
- 菜单的 `groups_id`：类型的 `allowed_group_ids`（F4，`load_menus` 按此过滤）；
- 菜单动作：`ir.actions.act_window`，`res_model` 为绑定模型，`domain` 为 `[('record_type_id', '=', id)]`，`context` 为 `{'default_record_type_id': id}`，`view_id` 为类型的视图（见第 5 节）；
- `sequence` 取类型的 `sequence`。

### 6.2 维护时机

- 类型 `create`、`write`（`label`、`group_ids`、`active`、`sequence`、`view_id`），以及其父类型变化时，调用 `_sync_menus()`；
- 停用的类型：菜单设为 `active=False`，不删除，避免破坏已有的书签；
- 删除类型：只允许没有记录引用的类型删除（`ondelete='restrict'` 已保证）。

`_sync_menus()` 要求幂等：多次调用结果相同。写入时只更新有变化的字段，避免 F6 下的无意义写入。

### 6.3 移动端

- 移动端菜单使用 `mobile_web` 的菜单设备类型（`device_type`）；
- 在修复 F4 之前，不能为移动端生成菜单，否则 PC 菜单会出现在移动端列表中（已经观察到）；
- 修复方式：把 `load_menus` 的缓存键加上设备类型。这是 `mobile_web` 的改动，需要单独评审。

## 7. 第 6 层：picklist 与控件

- `pharaccount_picklist` 控件（以及以后的通用控件）接收当前记录的 `record_type_id`，只显示 `allowed_picklist_value_ids` 中的选项；
- 类型变化时，控件重新加载选项；
- 已保存但不可选的值保留，并以禁用状态显示（沿用现有行为），不自动清空。

## 8. 第 7 层：迁移 pharaccount

1. 新模块 `record_type` 上线，`pharaccount.account` 继承 mixin，`record_type_id` 暂时允许为空；
2. 数据迁移脚本（`migrations/` 目录，`post` 阶段）：
   - 将 `pharaccount.record.type` 的每条记录复制为 `record.type`，`res_model = 'pharaccount.account'`，保留 `parent_id`、`group_ids`、`picklist_value_ids`；
   - 将 `pharaccount.account.record_type_id` 映射到新类型；
   - 对没有组的类型，按第 4.3 节的决定补齐组，否则迁移后对非管理员不可见；
3. 把 `record_type_id` 改为必填；
4. 旧的 `pharaccount.record.type` 模型保留一个版本，只读，然后删除。

注意：迁移脚本里的写入会更新 `write_date` 和 `write_uid`（F6），这是可以接受的，但要在迁移记录里说明。

## 9. 测试

按层组织：

- **数据层**：唯一约束、父类型同模型、循环检测、视图模型一致；
- **继承**：子类型的组和选项为并集；
- **默认**：每组每模型只有一个默认；默认属于该组的可用类型；
- **权限**：有效组（含传递继承）决定可用性；空组按 4.3 的决定；管理员不受限制；
- **记录规则**：只返回有权类型的记录；
- **菜单**：生成、停用、组过滤、幂等；
- **视图**：动作上的视图被使用；
- **迁移**：迁移前后可见的记录数和可用类型一致。

## 10. 实现顺序

1. 数据层和约束（第 2 节），附测试；
2. 记录规则和类型写入校验（第 3、4 节）；
3. `_sync_menus()` 和 PC 菜单（第 6.1、6.2 节）；
4. 视图绑定（第 5 节）；
5. picklist 控件过滤（第 7 节）；
6. 迁移（第 8 节）；
7. 移动端菜单，等 F4 修复后（第 6.3 节）。

每一步完成后单独提交并跑对应测试。

## 11. 需要你确认的决定

1. **空组规则**：方案 A（没有组则对非管理员不可用，建议）还是方案 B（保留现有"空表示所有人可用"）？
2. **默认类型**：用类型上的 `default_for_group_ids` 实现（当前设计），还是单独的模型？
3. **布局**：接受"布局在菜单层、同一记录从不同菜单打开可能布局不同"这一限制吗？
4. **菜单位置**：类型做成模型根菜单下的子菜单（建议），还是顶层菜单？
5. **移动端**：先修 F4（`mobile_web` 缓存键）再做移动端菜单，还是本期只做 PC？
6. **Permission Set**：是否需要独立于用户组的授权？本期不做。

确认后按第 10 节顺序实现。
