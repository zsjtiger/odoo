# Record Type 设计（参考 Salesforce）

状态：设计稿，待确认后实现。

## 1. 目标与范围

Salesforce 的 Record Type 让同一个对象下的记录分成几种类型，每种类型有自己的：

- **可用的下拉选项**（每个 picklist 字段，每种类型可选的值不同）；
- **页面布局**（哪些字段显示、显示在哪里）；
- **谁能用**（通过 Profile / Permission Set 分配）；
- **入口**（新建时选择类型，列表可以按类型筛选）。

本设计在 Odoo 20 里做一个通用的 Record Type 能力，并让 `pharaccount` 复用它。

范围内：

- 任意模型通过 mixin 启用 Record Type；
- 按 Odoo 用户组分配可用的类型（对应 Salesforce 的 Profile）；
- 每个用户组可以有一个默认类型；
- 类型之间可以继承（沿用 `pharaccount` 已有的并集规则）；
- 每个类型可以绑定自己的表单视图；
- 每个类型生成一个菜单入口（PC 和移动端）；
- 记录级访问规则：只能看到自己有权使用的类型的记录。

不在本期范围内：

- Permission Set 这种独立于用户组的授权（先用 Odoo 用户组）；
- 字段级安全（Salesforce 的 FLS，Odoo 可用字段级 `groups` 另做）；
- 按类型做的审批流程。

## 2. Salesforce 概念与 Odoo 映射

| Salesforce | Odoo 实现 |
|---|---|
| Object | 任意 Odoo 模型，加入 `record.type.mixin` |
| Record Type | `record.type`（通用模型） |
| Picklist 在类型上的可选值 | `record.type` 的 `picklist_value_ids`（已有 `pharaccount` 的做法） |
| Page Layout（按类型） | `record.type` 的 `view_id`，表单视图按类型切换 |
| Profile 分配 RT | `record.type` 的 `group_ids`（Odoo 用户组） |
| Profile 默认 RT | `record.type.default` 表（组 → 默认类型） |
| Tab / App 菜单 | 每个类型生成一个 `ir.ui.menu`，动作带默认类型和域 |
| List View 按类型筛选 | 菜单动作的 `domain` + `context` |
| 记录级可见性 | `ir.rule`：只看自己有权使用的类型的记录 |

## 3. 数据模型

### 3.1 通用模型 `record.type`（新模块 `record_type`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `res_model` | Char，必填 | 绑定的模型名，如 `pharaccount.account` |
| `name` | Char，必填 | 技术编码，同一模型内唯一 |
| `label` | Char，必填，可翻译 | 界面名称 |
| `sequence` | Integer | 排序 |
| `active` | Boolean | 停用后不可新建，已有记录保留 |
| `parent_id` | Many2one `record.type` | 父类型，用于继承（同一模型内） |
| `group_ids` | Many2many `res.groups` | 可以使用本类型的组（自身配置） |
| `allowed_group_ids` | 计算、存储 | 自身 + 父类型的组（并集） |
| `picklist_value_ids` | Many2many | 本类型可选的 picklist 值（自身配置） |
| `allowed_picklist_value_ids` | 计算、存储 | 自身 + 父类型（并集） |
| `view_id` | Many2one `ir.ui.view` | 本类型的表单视图，空则用模型默认表单 |
| `menu_ids` | One2many `ir.ui.menu` | 生成的菜单（由系统维护，只读） |
| `default_group_ids` | 反向 | 把本类型设为默认的组 |
| `description` | Text | 说明 |

约束：

- `(res_model, name)` 唯一；
- 父类型必须是同一个模型的类型；
- 不允许循环继承；
- `view_id` 必须是绑定模型的表单视图。

### 3.2 组默认类型 `record.type.default`

| 字段 | 类型 | 说明 |
|---|---|---|
| `group_id` | Many2one `res.groups`，必填 | 用户组 |
| `record_type_id` | Many2one `record.type`，必填 | 默认类型 |

约束：同一组、同一模型只能有一个默认类型；默认类型必须属于该组可用的类型。

### 3.3 Mixin `record.type.mixin`

抽象模型，被业务模型继承：

- `record_type_id`：Many2one `record.type`，必填（有默认值时自动填充）；
- `record_type_ids` 的域限制：只能选择当前模型、并且当前用户可用的类型；
- 重写 `default_get`：按当前用户的组选默认类型；
- 对 `record_type_id` 的变更做校验：已有记录切换到一个当前组不可用的类型时拒绝。

## 4. 权限模型

### 4.1 三层控制

1. **谁能用某个类型**：`allowed_group_ids`。用户至少属于其中一个组，才能选择或新建该类型的记录。
2. **能看到哪些记录**：`ir.rule`，域为 `[('record_type_id.allowed_group_ids', 'in', user.group_ids.ids)]`。
3. **能做什么操作**：仍由模型的 `ir.access.csv` 决定（读写创建删除），与类型无关。

### 4.2 空组的含义（需要确认）

Salesforce 中，没有分配给任何 Profile 的类型对用户不可见。建议采用同样的规则：**没有配置任何组的类型，对所有人都不可用**（管理员除外）。

现有 `pharaccount` 的规则是"空表示不限制"。两者取舍：

- 采用 Salesforce 规则更安全，但要求每个类型都要配置组；
- 保留现有规则方便迁移，但容易误开放。

建议采用 Salesforce 规则，并在 `pharaccount` 迁移时补齐组。

### 4.3 管理员

Odoo 的管理员组（`base.group_system`）不受类型限制，可以看到和操作所有类型。

## 5. 菜单模型

每个 `record.type` 生成一个菜单项：

- 菜单挂在模型的根菜单下，名称为类型的 `label`；
- 动作（`ir.actions.act_window`）的 `context` 为 `{'default_record_type_id': id}`，`domain` 为 `[('record_type_id', '=', id)]`；
- 菜单的 `groups` 为类型的 `allowed_group_ids`，没有权限的用户看不到菜单；
- 移动端：生成对应 `device_type` 的菜单，移动端菜单的 `device_type` 由 `mobile_web` 提供。

维护方式：

- 类型创建、修改、停用时，同步菜单（`_sync_menus`）；
- 不在类型上直接编辑菜单，菜单只读。

注意：`mobile_web` 的 `load_menus` 有已知问题（ormcache 未按设备区分），生成移动端菜单前需要先修复，否则 PC 菜单会出现在移动端列表中。

## 6. 视图（页面布局）

- 每个类型可以绑定自己的表单视图 `view_id`；
- 表单加载时，如果记录有类型且类型有 `view_id`，使用它，否则使用模型默认表单；
- 列表视图默认共用，类型用菜单的 domain 区分；
- 类型表单的字段可见性由视图决定，字段级权限不在本期范围。

## 7. 继承规则

沿用 `pharaccount` 已确认的规则：子类型的可用组和选项 = 父类型 ∪ 子类型自身配置。子类型不能删掉父类型已有的组和选项。

## 8. picklist 联动

- `pharaccount_picklist` 控件已经按类型过滤选项（`get_widget_options`）；
- 通用化后，控件接收 `record_type_id`，只显示 `allowed_picklist_value_ids` 中的选项；
- 类型变化时重新加载选项，已保存的不可选值保留并标记为禁用（沿用现有行为）。

## 9. 迁移 pharaccount

1. 新建 `record_type` 模块，实现上面的模型；
2. `pharaccount.record.type` 改为复用通用模型，或者保留模型但内部委托给通用模型（需要确认，见第 11 节）；
3. `pharaccount.account` 继承 `record.type.mixin`，`record_type_id` 指向通用类型；
4. 数据迁移：
   - 现有 `pharaccount.record.type` 记录复制到 `record.type`，`res_model = 'pharaccount.account'`；
   - 现有的 `group_ids`、`picklist_value_ids`、`parent_id` 原样保留；
   - 对没有组的类型，按第 4.2 节的决定补齐组，否则迁移后对所有人不可见。
5. 原有的 `pharaccount` 菜单（PC 和移动端的记录类型配置菜单）保留，新增的类型菜单挂在药店根菜单下。

## 10. 测试

- 继承：子类型的组和选项是并集，不允许循环；
- 权限：没有组的用户不能新建或切换到某类型，`ir.rule` 只返回有权的记录；
- 默认：每个组每个模型只有一个默认，且默认必须属于该组可用的类型；
- 菜单：类型创建后生成菜单，停用后菜单隐藏，权限不足时菜单不可见；
- 视图：类型绑定的视图被使用，未绑定时用默认视图；
- picklist：类型变化时选项正确过滤，已保存的不可选值保持不变；
- 迁移：`pharaccount` 现有数据迁移后可见性与迁移前一致。

## 11. 待确认的决定

1. **空组规则**：没有分配组的类型对所有人不可用（建议，接近 Salesforce），还是保留"空表示不限制"？
2. **pharaccount 的模型**：直接迁移到通用 `record.type`，还是保留 `pharaccount.record.type` 并委托给通用模型？建议前者，减少重复。
3. **菜单形式**：每个类型一个顶层菜单，还是放在模型根菜单下的子菜单？建议子菜单，避免菜单过多。
4. **Permission Set**：是否需要独立于用户组的授权？本期不做，除非你有这个需求。
5. **移动端菜单**：先修复 `mobile_web` 的 `load_menus` 缓存问题，还是先只做 PC 菜单？

确认以上几点后，我再按第 9 节的顺序实现，每一步都补测试。
