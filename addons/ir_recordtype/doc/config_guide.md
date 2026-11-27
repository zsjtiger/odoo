# 一个模型配置多个记录类型：详细配置说明

以 `pharaccount.account`（药店账户）为例，说明从开发者声明到管理员配置类型、权限、菜单、列表和表单的每一步。字段名、页面名和报错文字均与当前代码一致。

---

## 0. 名词

| 名词 | 含义 |
|---|---|
| 模型（Model） | 业务表，如药店账户 `pharaccount.account` |
| 记录类型（Record Type） | 模型下的一种分类，如药店、医院、医生，存于 `ir.record.type` |
| 类型权限 | 某个用户组对某个类型的读、写、新建、删除权限，存于 `ir.record.type.permission` |
| 类型默认 | 某个用户组新建记录时默认使用的类型，存于 `ir.record.type.default` |
| 访问行 | `ir.access` 中的一行；类型权限会自动生成它 |

---

## 1. 开发者：声明模型支持记录类型

文件：`addons/<模块>/models/<模型>.py`

```python
class PharaccountAccount(models.Model):
    _name = 'pharaccount.account'
    _description = 'Pharmacy Account'
    _record_type = True          # 声明：此模型支持记录类型
```

作用：模块升级后，框架自动给模型加字段 `record_type_id`（Many2one 到 `ir.record.type`）。
这一步只加字段，不会把字段放进视图。

模块的 `__manifest__.py` 必须依赖 `ir_recordtype`：

```python
'depends': ['base', 'ir_recordtype'],
```

---

## 2. 开发者：把字段放进列表、表单和搜索

在模型的视图 XML 中加入：

```xml
<!-- 列表：显示类型列 -->
<list>
    <field name="name"/>
    <field name="record_type_id"/>
</list>

<!-- 表单：显示类型字段 -->
<form>
    <sheet>
        <group>
            <field name="record_type_id"/>
        </group>
    </sheet>
</form>

<!-- 搜索：按类型分组 -->
<search>
    <filter name="group_record_type" string="记录类型"
            context="{'group_by': 'record_type_id'}"/>
</search>
```

不加这一步，用户在列表和表单里看不到类型。

---

## 3. 管理员：启用模型的记录类型

路径：**设置 → 技术 → 数据模型（Models）**，搜索 `pharaccount.account` 并打开。

1. 点击顶部按钮 **Enable Record Types**（未启用时显示）。
2. 系统依次检查，任一不通过则弹出错误并中止：
   - 模型类必须声明 `_record_type = True`，否则报错：
     *Model pharaccount.account must declare _record_type = True before record types can be enabled.*
   - 模型上不能有非管理员组的**无类型授权**。有则报错，列出这些授权（名称、组、操作），需要先删除，或改为绑定某个类型：
     *Before enabling record types, scope or delete these grants: ...*
3. 检查通过后：
   - 为管理员组生成一条授权（操作 crud，无域），管理员可见全部记录；
   - 模型标记为"支持记录类型"（`supports_record_type` 为真）。
4. 启用后，**Record Types** 区域显示该模型下的类型列表。

关闭：点击 **Disable Record Types**。如果仍有记录带类型，报错：
*Model ... still has N records with a record type. Record types cannot be disabled while they are in use.*
需要先把这些记录改为无类型或删除。关闭成功后，该模型的所有类型被停用。

---

## 4. 管理员：创建记录类型

路径：**设置 → 技术 → 记录类型（Record Types）** → 新建。

### 4.1 "General"（基本信息）页签

| 字段 | 必填 | 怎么填 | 说明 |
|---|---|---|---|
| 名称（name） | 是 | 如"医院" | 用户看到的名称，也是菜单名 |
| 编码（code） | 是 | 如 `hospital` | 同一模型内唯一 |
| 数据模型（model_id） | 是 | 选 `pharaccount.account` | 类型只能用于这个模型 |
| 序号（sequence） | 否 | 如 `40` | 数字小的排前面；也影响默认类型的选择 |
| 启用（active） | 否 | 勾选 | 不勾选则不能使用，菜单隐藏 |
| 父类型（parent_id） | 否 | 同模型的类型 | 只用于视图扩展链，**不继承权限**；不能与同模型的其他类型形成循环，父类型必须属于同一模型 |
| 菜单父级（menu_parent_id） | 否 | 如"主数据管理" | 该类型菜单挂在哪个菜单下；空则为顶层菜单 |

保存后，系统自动生成动作和菜单（见第 5 节）。

### 4.2 "Permissions"（权限）页签

可编辑列表，每行是一个组：

| 列 | 说明 |
|---|---|
| Group（group_id） | 用户组，如 `Pharmacy Account / User` |
| Read（perm_read） | 能读取该类型的记录；也是菜单显示的条件 |
| Write（perm_write） | 能修改 |
| Create（perm_create） | 能新建 |
| Unlink（perm_unlink） | 能删除 |

规则：

- 每行至少勾选一项，否则报错：*A permission must allow at least one operation.*
- 同一个组只能有一行；
- 保存后，系统为每行生成一条 `ir.access` 授权，操作字符串由勾选项组成（读、写、新建、删除依次为 r、u、c、d 的组合，如读写新建为 `cru`），域为 `[('record_type_id', '=', 本类型id)]`；
- 没有任何读权限的组，对该类型的记录无权限，菜单也不显示。

示例（医院类型）：

| Group | Read | Write | Create | Unlink |
|---|---|---|---|---|
| Pharmacy Account / User | ✔ | ✔ | ✔ | |
| Pharmacy Account / Manager | ✔ | ✔ | ✔ | ✔ |

### 4.3 "Access Rows"（访问行）页签

只读，显示该类型生成的授权行，用于核对，不在这里改。

### 4.4 "Menus"（菜单）页签

只读，显示生成的窗口动作（Action）。菜单本身通过"菜单父级"设置。

### 4.5 "Defaults"（默认）页签

每行表示"某组默认使用本类型"：

| 列 | 说明 |
|---|---|
| Group（group_id） | 用户组 |
| Model（model_id） | 隐藏列，应自动等于类型的模型 |

约束：

- 同一组、同一模型只能有一条默认；
- 默认类型必须已经授权给该组，否则报错：*The default type must be granted to the group first.* 所以先在"Permissions"加该组，再设默认。

> 已知问题：新建默认行时，隐藏的"模型"列没有自动填值，保存会报"模型必填"。在修复前，默认只能通过代码或数据设置（见第 9 节）。

---

## 5. 自动生成的动作和菜单

保存类型时（创建，或修改名称、序号、启用、菜单父级），系统自动生成或更新：

**窗口动作（ir.actions.act_window）**

| 项 | 值 |
|---|---|
| 名称 | 类型名称 |
| 模型 | `pharaccount.account` |
| 视图 | 列表、表单 |
| 域（domain） | `[('record_type_id', '=', 类型id)]` |
| 上下文（context） | `{'default_record_type_id': 类型id}` |

**菜单（ir.ui.menu）**

| 项 | 值 |
|---|---|
| 名称 | 类型名称 |
| 父级 | 类型的"菜单父级"（空则顶层） |
| 序号 | 类型的序号 |
| 动作 | 上面的窗口动作 |
| 可见组 | 有读权限的组，外加管理员 |
| 启用 | 类型启用，且至少有一个读权限组 |

效果：

- 从该菜单打开，列表只显示该类型的记录；
- 从该菜单新建，记录自动是该类型；
- 没有读权限的类型，菜单保持停用，界面上看不到。

**删除类型**：如果仍有记录使用该类型，报错：*Record type ... is used by N records and cannot be deleted. Deactivate it instead.* 应改为停用。

---

## 6. 类型的表单视图（可选）

目的：同一模型，不同类型显示不同字段（例如医生不显示药店级别）。

做法：

1. 进入 **设置 → 技术 → 用户界面 → 视图（Views）**，新建视图：
   - 模型：`pharaccount.account`；
   - 类型：Form；
   - 继承视图（inherit_id）：模型的默认表单（如 `pharaccount.view_pharaccount_account_form`）；
   - 模式（mode）：extension；
   - 架构（arch）：只写与默认表单的差异，如隐藏某个字段；
   - **记录类型（record_type_id）**：选择目标类型。
2. 类型的动作会自动使用该表单。通过其他入口打开的记录，仍使用默认表单。

校验规则：记录类型视图必须是该模型的表单视图，否则报错：*Record type views must be form views.*

> 已知问题：视图表单界面目前没有"记录类型"字段，类型表单也没有"视图"页签，因此第 6 步无法在界面完成，只能通过代码或数据文件设置 `ir.ui.view.record_type_id`。这是待补的界面。

---

## 7. 用户视角：新建时的默认类型

用户新建记录时，类型按以下顺序确定：

1. 从某个类型的菜单新建：类型由上下文 `default_record_type_id` 指定；
2. 从其他入口新建：先取用户所在组在"默认"中指定的类型；
3. 没有组默认时，取用户可用的第一个类型（按序号）；
4. 仍然没有，类型为空。

---

## 8. 运行时的权限规则

- **读取**：只能看到有读权限的类型的记录。
- **修改类型字段**：把记录改到某个类型，需要当前用户对目标类型有写或新建权限，否则报错：*You are not allowed to write records of type ...*（新建时为 create）。目标类型未启用时报错：*Record type ... is inactive.*
- **删除**：需要该记录类型上的删除权限。
- **无匹配授权**：如果用户所在组对该模型没有任何授权行，搜索会报"无权限访问"；如果有授权但都不匹配，搜索返回空列表。

---

## 9. 完整示例：药店、医院、医生

### 步骤

1. **开发者**：`pharaccount.account` 声明 `_record_type = True`；列表、表单、搜索加入类型字段（第 1、2 节）；升级模块。
2. **管理员**：进入"数据模型"，打开 `pharaccount.account`，点 **Enable Record Types**（第 3 节）。
3. **管理员**：创建三个类型（第 4.1 节）：

   | 名称 | 编码 | 序号 | 菜单父级 |
   |---|---|---|---|
   | 药店 | pharma | 1 | 主数据管理 |
   | 医院 | hospital | 40 | 主数据管理 |
   | 医生 | doctor | 50 | 主数据管理 |

4. **管理员**：为每个类型配置权限（第 4.2 节）：
   - 普通用户组：读、写、新建；
   - 管理组：读、写、新建、删除。
5. **管理员**：设置默认（第 4.5 节）：普通用户组默认药店。若默认页签无法保存，按第 9 节的已知问题处理。
6. **管理员**：把"示例医院"的类型改为"医院"（在药店列表中编辑该账户）。

### 结果

- 用户进入"药店（PC）"，在"主数据管理"下看到药店、医院、医生三个菜单；
- 每个菜单只显示对应类型的账户；
- 从菜单新建，记录自动是该类型；
- 没有读权限的类型（如连锁总店）菜单不显示。

---

## 10. 检查清单

- [ ] 模型类有 `_record_type = True`，模块依赖 `ir_recordtype`，升级成功；
- [ ] 列表、表单、搜索中有记录类型字段；
- [ ] 数据模型页面显示"已启用记录类型"；
- [ ] 每个类型至少有一个读权限组；
- [ ] 类型的"访问行"页签能看到对应的授权行；
- [ ] 类型的菜单在对应的父菜单下，名称正确；
- [ ] 用一个业务用户登录，能看到有权限的菜单，看不到无权限的；
- [ ] 从类型菜单新建的记录，类型字段正确。

---

## 11. 已知问题汇总

| 问题 | 影响 | 当前处理 |
|---|---|---|
| 类型表单"默认"页签新建行时模型列未自动填值 | 无法在界面保存默认 | 通过代码或数据设置 `ir.record.type.default` |
| 类型表单没有"视图"页签 | 无法在界面设置类型表单 | 通过代码设置 `ir.ui.view.record_type_id` |
| 视图表单没有"记录类型"字段 | 同上 | 同上 |
| 列表、表单、搜索需要开发者手动加字段 | 新模型需要改视图 | 按第 2 节添加 |
| 动作按菜单决定视图 | 同一记录从不同入口打开，布局可能不同 | 设计限制 |

建议优先修复前两项，使管理员可以完全在界面上配置。
