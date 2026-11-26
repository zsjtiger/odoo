# 通用 Record Type 设计

状态：设计稿，待确认后实现。

## 0. 概述

Record Type（记录类型）是一种通用的元数据能力，类似 `ir.model`、`ir.ui.view`、`ir.access` 这类元数据表：

- **模型层面**：创建一个模型时，可以选择"支持记录类型"。支持的模型，其记录会关联一条 `ir.record.type`（类型定义）。不支持的模型保持原样。
- **类型层面**：每个类型是一条元数据，配置它归属的模型、谁能使用、每个组对它有哪些操作权限、默认给哪些组、可选的菜单入口，以及可选的布局。
- **记录层面**：记录的权限由它所属的类型决定，走类型配置的权限。

药店（`pharaccount.account`）是第一个实例：它开启记录类型后，药店记录按"药店（总类）"、"连锁总店"、"单体药店"等类型区分权限。以后任何其他模型也可以用同样的方式开启。

## 1. 目标与非目标

目标：

1. 通用：任何模型都可以开启，不只是药店；包括界面创建的自定义模型和代码定义的模型。
2. 元数据驱动：类型的定义、权限、默认值、菜单都是数据库记录，可以在界面里配置，不需要改代码。
3. 权限走类型：记录的读、写、创建、删除权限，由类型决定。
4. 与框架一致：使用 Odoo 已有的访问控制表、默认值机制和菜单机制，不另建鉴权引擎。

非目标（本期不做）：

- 字段级权限（按类型隐藏或只读某个字段）；
- 按类型的审批流程；
- 类型之间的记录迁移（把记录从一个类型改到另一个类型只检查权限，不做批量迁移）；
- 单条记录在打开后切换布局（框架不支持，见 2.4）。

## 2. 框架依据

以下事实已在仓库中核对，设计以它们为前提。

### 2.1 访问控制是统一的 `ir.access` 表

`odoo/addons/base/models/ir_access/access.py` 第 25–35 行：`ir.access` 字段为 `model_id`、`group_id`、`operation`（`crud` 的子集）、`domain`、`active`。

- 对象级权限和记录级规则都存在这张表里；
- `group_id` 为空的行是**全局限制**，对所有用户生效，各行之间 AND；
- `group_id` 不为空的行是**授权**，同一用户的各组授权之间 OR（`access.py` 第 450–495 行）。

因此，记录级的"谁能看到哪些记录"，在这个框架里就是 `ir.access` 中带 `domain` 的行，不是另外的 `ir.rule` 表。

### 2.2 权限是 OR 授权 + AND 限制

对一条记录，用户能否执行某操作，取决于：

- 所有限制行（无组，AND）都通过；且
- 至少一条授权行（有组，OR）通过。

这点决定了 4.3 的设计：如果一个模型上某组已有"无域"的授权行，那么该组对所有记录都有权限，类型的域就失效了。

### 2.3 有效组包含传递继承

`odoo/addons/base/models/res_users/user_groups.py` 第 142–147 行：用户的有效组是 `all_group_ids`，包含 `implied_ids` 传递得到的组。授权判断使用有效组。

### 2.4 布局只能按动作选择

`odoo/addons/base/models/ir_ui_view/base.py` 第 260–300 行：表单视图由动作或上下文中的 `form_view_ref` 决定，不按单条记录切换。所以类型的布局只能在菜单（动作）层生效。

### 2.5 元数据模型可以在运行时创建字段

`odoo/addons/base/models/ir_model/model.py` 第 289、343 行：自定义模型（`_custom`）的字段 `state` 为 `manual`，即字段元数据可以在运行时创建。这是给界面创建模型加字段的基础。代码定义的模型不能靠元数据加字段，见第 4 节。

### 2.6 其他依据

- 菜单按组过滤，`load_menus` 缓存键为 `uid, debug, lang`，不含设备类型（`ir_ui_menu.py` 第 229–231 行）。移动端菜单生成前需要先修复。
- 任何非空的 `write` 都会更新 `write_date` 和 `write_uid`，不比较旧值（`orm/models/write.py` 第 221–243 行）。同步逻辑要避免无意义的写入。

## 3. 元数据模型

所有模型放在新模块 `record_type` 中。

### 3.1 `ir.model` 的扩展

在 `ir.model` 上增加：

| 字段 | 类型 | 说明 |
|---|---|---|
| `supports_record_type` | Boolean | 是否开启记录类型 |
| `record_type_field_id` | Many2one `ir.model.fields` | 指向模型上的类型字段（`record_type_id`） |

开启后，该模型的每条记录都有一个 `record_type_id`，它是该模型的必填字段（迁移期间可以暂时为空，见第 11 节）。

### 3.2 `ir.record.type`：类型定义

| 字段 | 类型 | 说明 |
|---|---|---|
| `model_id` | Many2one `ir.model`，必填，`ondelete='cascade'` | 所属模型，类型只能用于这个模型 |
| `code` | Char，必填 | 技术编码，`(model_id, code)` 唯一 |
| `name` | Char，必填，可翻译 | 界面名称 |
| `sequence` | Integer，默认 16 | 显示顺序 |
| `active` | Boolean，默认真 | 停用后不能新建或切换到该类型，已有记录保留可见性 |
| `mode` | Selection：`primary` / `extension` | 根类型为 primary，子类型为 extension |
| `parent_id` | Many2one `ir.record.type` | 父类型，必须与自身属于同一模型 |
| `permission_ids` | One2many `ir.record.type.permission` | 各组的操作权限（3.3） |
| `default_group_ids` | One2many `ir.record.type.default` | 对哪些组是默认（3.4） |
| `view_id` | Many2one `ir.ui.view`，可选 | 类型的布局（扩展视图，见第 9 节） |
| `access_ids` | One2many `ir.access`，只读 | 系统生成的访问行（第 5 节） |
| `menu_id` | Many2one `ir.ui.menu`，只读 | 系统生成的菜单（第 8 节） |
| `allowed_group_ids` | 计算、存储 | 自身与所有祖先在权限中出现的组的并集 |

约束：

- `(model_id, code)` 唯一；
- `parent_id.model_id` 必须等于 `model_id`；
- `mode = 'primary'` 时没有 `parent_id`，`mode = 'extension'` 时必须有；
- 沿 `parent_id` 不能循环；
- `view_id` 的模型必须等于 `model_id`，类型为表单。

### 3.3 `ir.record.type.permission`：类型对组的权限

| 字段 | 类型 | 说明 |
|---|---|---|
| `record_type_id` | Many2one `ir.record.type`，必填，`ondelete='cascade'` | 类型 |
| `group_id` | Many2one `res.groups`，必填，`ondelete='cascade'` | 组 |
| `perm_read` | Boolean | 能否读 |
| `perm_write` | Boolean | 能否写 |
| `perm_create` | Boolean | 能否新建 |
| `perm_unlink` | Boolean | 能否删除 |

约束：

- `(record_type_id, group_id)` 唯一；
- 至少有一个权限位为真，否则没有意义（约束报错）。

这张表是类型权限的唯一来源：每一行生成 `ir.access` 中的一条授权行（第 5 节），权限位决定 `operation` 的取值（`crud` 的子集）。

### 3.4 `ir.record.type.default`：每组默认类型

结构与 `ir.default` 相同，按"组 + 模型"保存一条：

| 字段 | 类型 | 说明 |
|---|---|---|
| `model_id` | Many2one `ir.model`，必填，`ondelete='cascade'` | 模型 |
| `group_id` | Many2one `res.groups`，必填，`ondelete='cascade'` | 组 |
| `record_type_id` | Many2one `ir.record.type`，必填，`ondelete='cascade'` | 默认类型 |

约束：

- `(model_id, group_id)` 唯一，即每组每模型只有一个默认；
- `record_type_id.model_id` 必须等于 `model_id`；
- `group_id` 必须属于该类型的 `allowed_group_ids`。

### 3.5 记录上的字段

支持记录类型的模型，都有字段 `record_type_id`：

- 类型：Many2one `ir.record.type`，`index=True`，`ondelete='restrict'`；
- 域：`[('model_id.model', '=', <模型名>), ('active', '=', True)]`，并叠加"当前用户可用"的过滤（由访问控制保证，见第 5 节）；
- 默认值：由 `default_get` 按第 6 节的规则给出。

## 4. 开启与关闭

### 4.1 界面创建的自定义模型

在界面创建模型时，勾选"支持记录类型"：

1. 创建 `ir.model`，`_custom` 为真；
2. 在该模型上创建字段元数据 `record_type_id`，`state = 'manual'`（依据 2.5）；
3. 设置 `supports_record_type = True`，并把 `record_type_field_id` 指向上一步的字段；
4. 可选：创建一个默认类型"默认"，权限为空（只有管理员能用，直到配置权限）。

### 4.2 代码定义的模型

代码模型不能靠元数据加字段，所以分两步：

1. 开发者在模型上继承 `record.type.mixin`。mixin 在代码中定义 `record_type_id` 字段和默认值逻辑；
2. 管理员在 `ir.model` 上勾选"支持记录类型"。这一步只打开行为（生成访问行、菜单），不增加字段。

如果模型没有继承 mixin 却勾选了开关，保存时报错："该模型没有记录类型字段，请先由开发者添加 `record.type.mixin`"。

药店（`pharaccount.account`）属于这种情况。

### 4.3 关闭

- 如果模型上仍有记录引用类型，不允许关闭，只能停用类型；
- 关闭后，生成的访问行和菜单被删除，字段保留（不删数据）；
- 自定义模型上的字段元数据不删除，只把开关设为假。

## 5. 权限：从类型生成访问行

### 5.1 生成规则

对每条 `ir.record.type.permission`，生成一条 `ir.access`：

| `ir.access` 字段 | 值 |
|---|---|
| `model_id` | 类型的 `model_id` |
| `group_id` | 权限行的 `group_id` |
| `operation` | 由权限位组成，如读写创建为 `crud` 的子集 `cru` |
| `domain` | `[('record_type_id', '=', <类型 id>)]` |
| `active` | 类型启用时为真 |

由于 2.2 的 OR 语义，一个用户能对某记录执行某操作，当且仅当存在一条授权行，它的组与用户的有效组有交集、操作包含该操作、域匹配该记录。

### 5.2 与对象级授权的关系（关键）

如果某组在该模型上已有一条**无域**的授权行（例如常见的 `access_xxx_user,...,group_user,crud`），那么该组对所有记录都有权限，类型的域完全失效。

因此，**开启记录类型后，模型上对各组的无域授权必须被类型授权取代**：

- 开启时检查该模型上所有无域的授权行，列出涉及的组，要求管理员确认后删除或改为类型授权；
- 之后模型上对非管理员组的授权，只能通过类型授权产生；
- 管理员组保留无域授权（或单独的管理员规则），用于绕过。

这一点是在 2.2 的框架规则下必须处理的，否则开启后权限看起来没有生效。

### 5.3 没有任何类型授权的记录

如果一条记录的类型没有任何授权行，非管理员对它没有任何权限（OR 的结果为空，见 2.2）。这意味着：

- 新类型如果忘了配权限，它的记录对非管理员不可见，这是有意的，与 Salesforce 中"未分配给 Profile 的类型不可用"一致；
- 需要确认（见第 12 节第 1 条）。

### 5.4 管理员

框架不会让 `base.group_system` 自动绕过访问控制。开启记录类型时，为管理员组生成一条无域授权行（`operation = crud`），确保管理员能看到所有记录。

### 5.5 停用类型

- 停用类型时，它的访问行设为不活动（`active = False`），已有记录因此失去该类型的授权；
- 所以停用不等于"保留可见"。如果希望停用后仍然可见，需要由管理员明确决定，不做默认值。

这一点与早期草稿不同。待确认，见第 12 节。

## 6. 默认类型

按 `ir.default` 的方式选取：

1. 取当前用户的有效组（2.3）；
2. 在 `ir.record.type.default` 中查找这些组对该模型的默认；
3. 多个组给出不同默认时，取 `sequence` 最小的类型；
4. 没有默认时，取用户有权使用的第一个类型（按 `sequence`）；
5. 没有任何可用类型时，不设默认值，保存时由校验报错。

只使用有权使用的类型作为默认，避免默认值指向用户无法使用的类型。

## 7. 继承

与 `ir.ui.view` 的扩展视图一致：

- 子类型只能增加权限，不能减少父类型的组；
- `allowed_group_ids` 是自身与所有祖先的并集，存储在子类型上；
- 生成访问行时，子类型的行只对自身的权限配置生成，父类型的权限通过 `allowed_group_ids` 计算得到，二者的合并在 5.1 的域匹配中完成。

实现上有两种做法，待确认（第 12 节）：

- 做法 A：子类型为父类型的每条权限也生成访问行（冗余，但查询简单）；
- 做法 B：子类型的域写成 `record_type_id in <父子类型 id 列表>`（查询简单，权限行少，父类型修改时需要重算域）。

## 8. 菜单与动作：生成

每个类型生成一个菜单和一个窗口动作：

| 项 | 值 |
|---|---|
| 菜单父级 | 模型的根菜单（由模型所在模块提供，没有则放在"记录类型"下） |
| 菜单名称 | 类型的 `name` |
| 菜单组 | 类型权限中有读权限的组（菜单可见性与访问一致） |
| 菜单 `sequence` | 类型的 `sequence` |
| 动作 `res_model` | 模型 |
| 动作 `domain` | `[('record_type_id', '=', <类型 id>)]` |
| 动作 `context` | `{'default_record_type_id': <类型 id>}` |
| 动作 `view_id` | 类型的 `view_id`，没有则用模型默认表单 |

同步函数 `_sync_menus()` 必须幂等，只写入真正变化的字段（依据 2.6）。

停用的类型，菜单设为不活动，不删除。

移动端：`load_menus` 缓存不区分设备（2.6），在修复前不为移动端生成菜单。

## 9. 布局（可选）

- 类型可以绑定一个 `ir.ui.view`，`mode = 'extension'`，`inherit_id` 为模型的默认表单，只写与默认布局的差异；
- 布局通过菜单动作生效（2.4）；
- 通过其他入口打开的记录，使用模型默认表单；
- 同一记录从不同菜单打开，布局可能不同，这是框架的限制。

## 10. 扩展点：领域特有的选项

药店的 picklist 选项限制、其他模型的类似限制，都不属于通用能力，通过扩展点实现：

- 通用模块提供钩子：`ir.record.type` 上可以挂接领域模块的扩展模型（例如 `pharaccount.record.type.picklist`，关联类型与选项）；
- 通用模块不认识这些扩展，只保证类型、权限、默认、菜单、布局正确；
- 领域模块在类型创建、修改时同步自己的扩展数据。

这样，通用能力不包含 pharaccount 的业务概念。

## 11. 药店作为第一个实例

1. 实现通用模块后，`pharaccount.account` 继承 `record.type.mixin`，并在 `ir.model` 上开启；
2. 把 `pharaccount.record.type` 的数据迁移到 `ir.record.type`：
   - `model_id` 为 `pharaccount.account`；
   - `parent_id`、`active` 保持；
   - 原来的 `group_ids` 转为 `ir.record.type.permission`，权限位为读、写、创建、删除（与原来的组一致，见药店设计的权限表）；
   - 原来的 `picklist_value_ids` 通过扩展点（第 10 节）保留；
3. 开启时处理 5.2：pharaccount 的 `access_pharaccount_account_user` 是无域授权，必须替换为类型授权，否则类型域失效。这是迁移的关键步骤；
4. 迁移中 `pharaccount.account.record_type_id` 映射到新类型；没有组的类型按第 12 节的决定补齐，否则迁移后非管理员看不到；
5. 把 `record_type_id` 改为必填；
6. 旧的 `pharaccount.record.type` 保留一个版本只读，然后删除。

迁移中的写入会更新 `write_date` 和 `write_uid`（2.6），需要在迁移说明中记录。

## 12. 需要确认的决定

1. **没有授权的类型**：对非管理员完全不可见（5.3，本设计的默认），还是允许所有人使用？
2. **停用类型后的可见性**：停用后已有记录对原来的组是否仍可见？本设计默认不可见（5.5），这与早期草稿不同。
3. **继承的实现**：做法 A（冗余访问行）还是做法 B（域中包含父子类型列表）（第 7 节）？
4. **开启时的无域授权**：开启记录类型时，对非管理员组的无域授权是自动删除，还是要求管理员逐个确认（5.2）？建议逐个确认。
5. **界面创建模型时的字段**：创建自定义模型时，`record_type_id` 字段是否必须，还是可以开关？
6. **移动端**：修复 `mobile_web` 缓存键（2.6）后再做移动端菜单，还是本期只做 PC？
7. **菜单位置**：类型菜单放在模型根菜单下（建议），还是单独的"记录类型"顶层菜单？

## 13. 测试

- 元数据：`(model_id, code)` 唯一；父子同模型；循环检测；`view_id` 模型一致；权限行至少一位；`(model, group)` 默认唯一；默认组属于类型的组；
- 开启与关闭：界面模型自动生成字段；代码模型未继承 mixin 时报错；有记录时不能关闭；关闭后访问行被删除、字段保留；
- 权限：生成的访问行与权限位一致；有授权的组能按位操作；无授权的组对记录无权限；管理员能看到全部；
- 无域授权检查（5.2）：开启时能列出无域授权的组；取代后类型域生效；
- 停用（5.5）：访问行失效；菜单隐藏；已有记录的行为与 12 第 2 条决定一致；
- 默认（6）：只选用户有权的类型；多组冲突时取 `sequence` 最小；
- 菜单（8）：生成、停用、组过滤、幂等；
- 布局（9）：菜单动作使用类型视图，其他入口使用默认视图；
- 迁移（11）：迁移前后，每个用户可见的记录数一致。

## 14. 实现顺序

1. `record_type` 模块：`ir.record.type`、权限行、默认行，附约束测试；
2. `ir.model` 扩展与 `record.type.mixin`，实现开启和关闭（第 4 节），附测试；
3. 访问行生成与无域授权检查（第 5 节），附测试；
4. 默认类型（第 6 节）；
5. 菜单与动作（第 8 节）；
6. 布局（第 9 节）；
7. 扩展点（第 10 节），并把 pharaccount 的 picklist 接入；
8. pharaccount 迁移（第 11 节）；
9. 移动端菜单（第 8 节），等 `mobile_web` 缓存问题修复后。

每一步单独提交，并跑对应测试。
