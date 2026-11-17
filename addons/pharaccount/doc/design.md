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
| name | Char，必填 | 编码。父类型 `pharma`（药店），子类型 `pharmacy_chain_head`（连锁总店）、`pharmacy_chain_branch`（连锁门店）、`pharmacy_monomer`（单体药店） |
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
- 账户主表 `accounts.record_type` 指向 `pharaccount.record.type`，药店账户使用三个子类型之一。
- 查询"药店"时同时匹配父类型和子类型（vrux 中是 `record_type__name='pharma'` 或 `record_type__parent__name='pharma'`），即子类型自动属于父类型。

## 3. Picklist

第一个 picklist 已经在 vrux 中确定：`pharmacy_level`（药店级别），`multi_select=0`，`source=system`，选项为：

| 选项 name | 选项 label | order |
|---|---|---|
| A | A级 | 1 |
| B | B级 | 2 |
| C | C级 | 3 |
| D | D级 | 4 |

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

- 用户只能看到自己所属组可用的记录类型下的账户：`record_type_id.allowed_group_ids` 与用户的 `all_group_ids` 有交集。
- 记录类型没有配置任何组时，所有用户可见（与 picklist 选项的规则一致，空表示不限制）。

### 选项级过滤

- 下拉框选择时，只显示用户所属组有权限选择的选项，以及记录类型允许的选项的交集。

## 5. 账户主表 `pharaccount.account`

vrux 对应 `accounts`，只保留药店相关字段。

| 字段 | 类型 | 说明 |
|---|---|---|
| name | Char，必填，索引 | 名称 |
| alias | Char | 别名 |
| name_pinyin / pinyin | Char | 名称拼音（pinyin 无分隔符） |
| alias_pinyin / pinyin_with_separator | Text | 别名拼音、带分隔符的拼音 |
| address | Char | 地址 |
| geo_province / geo_city / geo_district | Char | 省、市、区 |
| telephone / mobile / email | Char | 联系方式 |
| description | Text | 备注 |
| creation_time | Date | 创建日期，默认当天 |
| last_called_on | Date | 最后拜访日期 |
| sales | Float | 销售额 |
| is_important / is_public | Boolean | 重要标记、公开标记 |
| authorized_packages | Char | 授权的产品包 |
| openid / openid_register_time | Char / Datetime | 微信 openid 及绑定时间 |
| account_distributer_code | Char | 经销商编码 |
| state_id | Many2one `pharaccount.account.state` | 状态（见下） |
| record_type_id | Many2one `pharaccount.record.type` | 记录类型，药店为 `pharma` 下的子类型 |
| pharmacy_level_id | Many2one `pharaccount.picklist.value`（控件 `pharaccount_picklist`） | 药店等级 |
| superior_id | Many2one `pharaccount.account`（自关联） | 上级药店 |
| headquarters_id | Many2one `pharaccount.account`（自关联） | 总部药店 |
| hospital_id | Many2one `pharaccount.account`（自关联） | 所属医院（可选） |
| agency_id / dealer_id | Many2one `pharaccount.account`（自关联） | 代理商、经销商 |
| active | Boolean | 启用/停用 |

状态 `pharaccount.account.state` 是独立配置表：name（唯一）、label、sequence、color、is_default、is_locked、description。第一版只有配置权限（`group_config`）可以维护，普通用户只读。

子表（员工、医院关联、库存、竞品）在下一步设计。

## 6. 已确认的答案

1. **继承规则：取并集。** 子类型的可用组和选项 = 父类型的 ∪ 子类型自己配置的。依据：vrux 查询药店时父子类型都会匹配。子类型不能删掉父类型已有的选项。
2. **picklist 选项：** `pharmacy_level` 为 A/B/C/D 四级，见第 3 节。依据：`server/scripts/metadata-backups/py/V003_201811051520_add_pharmacy_list.py`。
3. **导入导出：** 第一版只保留权限位（`group_manager` 上的 `allow_import`、`allow_export`），不实现导入导出功能。依据：第一版范围已经收窄为组权限和主表，导入导出是独立的功能。

以上三条是我根据代码给出的推荐答案，需要你最终确认。

## 7. 配置界面（PC 与移动端）

Odoo 没有按设备区分视图的机制，所以用两组菜单和动作区分：

| 菜单 | 视图 | 说明 |
|---|---|---|
| 药店（PC）→ 药店 | 列表 + 完整表单（分页签：区域、关联药店、经营、拼音、微信、备注） | 所有 `group_user` |
| 药店（PC）→ 配置 | 记录类型、下拉列表、账户状态的列表 + 表单 | `group_config` |
| 药店（移动端）→ 药店 | 卡片 + 精简表单（只保留常用字段） | 所有 `group_user` |
| 药店（移动端）→ 配置 | 记录类型、下拉列表、账户状态的卡片 + 表单 | `group_config` |

移动端表单通过 `ir.actions.act_window.view` 绑定到移动端动作，PC 表单默认使用 priority 16，移动端精简表单使用 priority 32，所以 PC 动作不会误用移动端表单。
