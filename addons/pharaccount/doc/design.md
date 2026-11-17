# pharaccount 设计文档（第一版）

参考 vrux（ChinaSFA）的 `accounts`、`object_record_types`、`picklists` / `picklist_values`、`roles` 及其关联表。

## 1. 范围

- 药店（pharmacy）账户主表及其关联表。
- 记录类型（record type），支持继承。
- Picklist，作为独立控件，供模型配置使用。
- 用户组权限，用户可属于多个组。
- 不做：记录级动态角色（`dynamic_record_roles`，如主办人、协办人）。
- 暂不做：选项级联（`depending_on`），第一版模型中只留扩展位置。

## 2. 记录类型（record type）

vrux 对应：`object_record_types`、`record_type_to_record_type_relations`。

### 模型 `pharaccount.record.type`

| 字段 | 类型 | 说明 |
|---|---|---|
| name | Char，必填 | 编码，药店为 `pharma`（对应 vrux 的 `record_type__name='pharma'`） |
| label | Char，必填 | 界面名称 |
| sequence | Integer | 显示顺序 |
| parent_id | Many2one `pharaccount.record.type` | 父记录类型，用于继承 |
| child_ids | One2many（反向） | 子记录类型 |
| code_prefix | Char | 编码前缀，可选 |
| active | Boolean | 启用/停用 |
| group_ids | Many2many `res.groups` | 哪些组可以使用这个记录类型（对应 `role_to_object_record_types`） |
| picklist_value_ids | Many2many `pharaccount.picklist.value` | 这个记录类型可用的选项（对应 `object_record_type_to_picklist_values`） |

### 继承规则

- 子记录类型继承父记录类型的 `group_ids` 和 `picklist_value_ids`；子类型自己配置的值与父类型取并集。
- 不允许循环继承（约束检查）。
- 账户主表 `accounts.record_type` 指向 `pharaccount.record.type`，药店账户固定为 `pharma`（或其子类型）。

## 3. Picklist

vrux 对应：`picklists`、`picklist_values`、`role_to_picklist_values`。

### 模型

**`pharaccount.picklist`**（下拉框定义）

| 字段 | 类型 | 说明 |
|---|---|---|
| name | Char，必填，唯一 | 编码，如 `pharmacy_level` |
| label | Char，必填 | 界面名称 |
| description | Text | 说明 |
| value_ids | One2many | 选项 |

**`pharaccount.picklist.value`**（下拉选项）

| 字段 | 类型 | 说明 |
|---|---|---|
| picklist_id | Many2one，必填 | 所属下拉框 |
| name | Char，必填 | 编码 |
| label | Char，必填 | 界面名称 |
| sequence | Integer | 排序 |
| is_disabled | Boolean | 停用后不再出现在选择列表中 |
| value | Char | 实际存储的值，第一版统一存为字符串 |
| group_ids | Many2many `res.groups` | 哪些组可以选择这个选项（对应 `role_to_picklist_values`） |
| depends_on | 预留 | 级联依赖，第一版不实现 |

### 作为独立控件

- 新增 Odoo 字段控件 `pharaccount_picklist`，用于在视图中显示和选择下拉选项。
- 控件从 `pharaccount.picklist` 读取选项，并按当前用户的组过滤。
- 模型配置时可以指定某个字段使用哪个 picklist，例如 `pharmacy_level` 字段 → picklist `pharmacy_level`。
- 第一版只做单选；多选和级联后续再做。

## 4. 用户组权限

vrux 对应：`roles`、`role_to_object_permissions`、`orion_users.role`（一个用户一个角色，本版改为多组）。

### 组

- 使用 Odoo 原生的 `res.groups`，用户通过 `res.users.groups_id` 属于多个组。
- 第一版定义 3 个组：
  - `pharaccount.group_user`：查看和编辑药店账户。
  - `pharaccount.group_manager`：在 user 的基础上可以删除、导入、导出，并管理配置。
  - `pharaccount.group_config`：可以修改记录类型和 picklist 配置。

### 对象级权限

用 `ir.model.access.csv` 按组配置，对应 vrux 的 `role_to_object_permissions`：

| 组 | 模型 | read | create | write | unlink |
|---|---|---|---|---|---|
| group_user | pharaccount.account | 1 | 1 | 1 | 0 |
| group_manager | pharaccount.account | 1 | 1 | 1 | 1 |
| group_user | pharaccount.record.type | 1 | 0 | 0 | 0 |
| group_config | pharaccount.record.type | 1 | 1 | 1 | 1 |
| group_user | pharaccount.picklist / .value | 1 | 0 | 0 | 0 |
| group_config | pharaccount.picklist / .value | 1 | 1 | 1 | 1 |

导入、导出在第一版通过 `group_manager` 的权限控制，不单独建字段。

### 记录级规则（ir.rule）

- 用户只能看到自己所属组可用的记录类型下的账户：
  `record_type_id.group_ids` 与用户的 `groups_id` 有交集。
- 没有任何组可用的记录类型，只有 `group_config` 能看到。

### 选项级过滤

- 下拉框选择时，只显示用户所属组有权限选择的选项，以及记录类型允许的选项的交集。

## 5. 账户主表 `pharaccount.account`

vrux 对应 `accounts`，只保留药店相关字段。

| 字段 | 类型 | 说明 |
|---|---|---|
| name | Char，必填 | 名称 |
| alias | Char | 别名 |
| address | Char | 地址 |
| telephone / mobile | Char | 联系方式 |
| email | Char | 邮箱 |
| record_type_id | Many2one `pharaccount.record.type` | 记录类型，药店为 `pharma` |
| pharmacy_level | Many2one `pharaccount.picklist.value`（控件 `pharaccount_picklist`） | 药店等级 |
| superior_id | Many2one `pharaccount.account`（自关联） | 上级药店 |
| headquarters_id | Many2one `pharaccount.account`（自关联） | 总部药店 |
| hospital_id | Many2one `pharaccount.account`（自关联） | 所属医院（可选） |
| agency_id / dealer_id | Many2one `pharaccount.account`（自关联） | 代理商、经销商 |
| description | Text | 备注 |
| last_called_on | Date | 最后拜访日期 |
| active | Boolean | 启用/停用 |

子表（员工、医院关联、库存、竞品）在下一步设计。

## 6. 待确认

1. 继承时的取并集规则是否合适，还是子类型应该覆盖父类型？
2. `pharmacy_level` 等 picklist 的具体选项，需要从 vrux 的数据里导出。
3. 第一版是否需要导入、导出的功能，还是只保留权限位？
