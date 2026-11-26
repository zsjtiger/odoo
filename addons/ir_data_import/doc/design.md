# 数据导入设计方案（ir_data_import）

状态：设计草案，尚未实现。目标模块：`ir_data_import`，依赖 `base`、`ir_recordtype`。
试点模型：`pharaccount.account`（药店）。仅支持 Web 端，不做移动端导入。

## 1. 目标

- 每个模型有一个**导入**按钮，点击弹出导入框。
- 导入框可以**下载模板**（xlsx），也可以**上传**填好的文件。
- 每行带一个操作标记 `Action`：
  - `N`：新建（New）
  - `U`：更新（Update）
  - `D`：删除（Delete）
- 导入前**逐行校验**。有错误的行，把原因写到文件的 `Validation Error` 列，用户修正后重新上传。
- 导入权限由**模型或记录类型**决定：没有权限的用户看不到导入按钮，或者导入时被拒绝。

## 2. 范围

| 包含 | 不包含 |
|---|---|
| Web 端导入框、模板下载、校验、导入 | 移动端导入（不做） |
| xlsx 模板和结果文件 | 导入 csv 以外的格式（阶段 2 再考虑） |
| N / U / D 三种操作 | 导入计划、定时导入 |
| 与记录类型的权限联动 | 批量导入的后台任务（视数据量再定，不在本期） |

## 3. 导入权限配置

### 3.1 模型级开关

新增模型 `ir.data.import.permission`，每行是一个组对一个模型的导入权限：

| 字段 | 说明 |
|---|---|
| `model_id` | 模型 |
| `group_id` | 用户组 |
| `perm_import` | 允许导入（上传并执行） |
| `perm_template` | 允许下载模板（默认与导入相同，可单独关闭） |

约束：同一组、同一模型唯一；至少一个权限勾选。

### 3.2 与记录类型的联动

导入时，每一行的类型（有记录类型的模型）都要经过 `ir.record.type` 的已有检查：

| 操作 | 检查 |
|---|---|
| N | 目标类型对当前用户有 `create` 权限 |
| U | 原记录类型有 `write` 权限；如果修改了类型，新类型也要有 `write` 或 `create` 权限 |
| D | 记录所属类型有 `unlink` 权限 |

这些检查复用 `ir.record.type._can_use(operation)`，不新造规则。

### 3.3 导入按钮的显示

- 服务端方法 `ir.data.import.get_import_info(model_name)` 返回 `{can_import, can_template, record_types}`。
- 列表视图的工具栏按钮只在 `can_import` 为真时显示。按钮的显示只是体验，真正的校验在服务端。

## 4. 模板

### 4.0 模板配置（需要一张表）

模板的内容需要配置，所以需要两张表：模板和模板列。

**`ir.data.import.template`（模板）**

| 字段 | 说明 |
|---|---|
| `name` | 名称，如"药店导入模板" |
| `model_id` | 模型，如 `pharaccount.account` |
| `record_type_id` | 可选。有值时，模板只用于该记录类型，列和必填规则按类型定；空表示通用模板 |
| `active` | 是否启用 |
| `column_ids` | 模板列 |
| `match_by` | Many2one 的匹配方式：`name`（默认）或 `xmlid` |
| `include_example` | 下载时是否带一行样例数据 |

约束：同一模型、同一记录类型（或都为空）只能有一个启用的模板。

**`ir.data.import.template.column`（模板列）**

| 字段 | 说明 |
|---|---|
| `template_id` | 所属模板 |
| `sequence` | 列的顺序 |
| `field_id` | 字段（`ir.model.fields`） |
| `header` | 表头显示的中文标签，如"药店名称" |
| `required_on_create` | N 操作时是否必填（不填则由字段本身的 required 决定） |
| `example` | 样例值，只用于下载模板 |
| `help` | 填写说明，写入 Help 工作表 |

约束：同一模板中，同一字段只能出现一次；字段必须属于模板的模型；不能选择用户无读写权限的字段。

### 4.0.1 没有配置时

- 如果没有配置启用的模板，系统**自动生成**：列为模型中用户有读写权限、且非计算、非 One2many/Many2many 的字段，按字段名排序，表头用字段标签。
- 配置了模板后，只使用模板中的列；自动生成只作为兜底，不与配置混用。

### 4.0.2 配置的界面和权限

- 菜单：**设置 → 技术 → 数据导入 → 导入模板**（只有 `base.group_system` 或新的"导入配置"组能看到）。
- 表单：模板头的字段 + 行的可编辑列表。字段选择器只显示当前模型的字段。
- 在模板表单中提供"预览"按钮，生成一份样例 xlsx 下载，便于检查。
- 修改模板不影响已经上传、尚未确认的导入作业，作业保存的是校验时使用的模板版本号（`template_version` 字段，每次修改加 1）。

### 4.0.3 与记录类型的关系

- 有记录类型的模型：可以建通用模板，也可以为某个记录类型单独建模板。导入时，`Record Type` 列决定使用哪个模板的列；若该类型没有专用模板，使用通用模板。
- 同一个文件中如果混有多种类型，列以文件表头为准，每行的类型按 `Record Type` 列单独校验；必填规则按每行的类型取。

### 4.0.4 下载 Excel 的样式配置

样式属于模板的配置，存在模板表和模板列表中，不写死在代码里。

**模板级（`ir.data.import.template`）**

| 字段 | 说明 | 默认 |
|---|---|---|
| `sheet_name` | 工作表名称 | 模型名称 |
| `header_font_color` | 表头字体颜色（十六进制） | `#FFFFFF` |
| `header_fill_color` | 表头背景色 | `#0E7C86` |
| `header_bold` | 表头加粗 | 是 |
| `header_height` | 表头行高（点） | 24 |
| `freeze_header` | 冻结表头 | 是 |
| `show_gridlines` | 显示网格线 | 是 |
| `action_fill_color` | `Action` 列的背景色（区分操作标记） | `#FFF2CC` |
| `required_fill_color` | 必填列表头的背景色（覆盖 `header_fill_color`） | `#C0392B` |
| `show_help_sheet` | 是否生成 Help 工作表 | 是 |
| `help_sheet_name` | Help 工作表名称 | `Help` |

**列级（`ir.data.import.template.column`）**

| 字段 | 说明 | 默认 |
|---|---|---|
| `column_width` | 列宽（字符数） | 按标签长度，最少 12 |
| `number_format` | 数字或日期的显示格式，如 `0.00`、`yyyy-mm-dd` | 按字段类型 |
| `align` | 对齐：左 / 中 / 右 | 文本左，数字右 |
| `dropdown` | 是否生成下拉框：Selection、Boolean、Many2one（取名称列表）| Selection 和 Boolean 为是 |
| `hidden` | 隐藏列（仍保留在文件中，用于 ID 等） | 否 |
| `locked` | 锁定列，工作表保护时不可编辑 | 否 |
| `header_note` | 表头批注（鼠标悬停提示），内容为填写说明 | 来自 `help` |

**生效规则**

- 下载时按模板的样式生成；没有配置模板时使用上表的默认值。
- 颜色必须是 `#RRGGBB` 格式，保存时校验，错误则拒绝保存。
- `dropdown` 的选项来自字段的 Selection 标签，或 Many2one 的名称列表（最多 500 项，超过则不生成下拉框，提示改用 ID）。
- `Validation Error` 列（结果文件）固定为红色表头，不受模板样式影响。
- 结果文件保留模板中的列宽和表头样式，便于用户继续使用。

**界面**

- 模板表单中增加"样式"页签，包含模板级样式字段；行列表中增加样式列。
- 提供"预览"按钮，立即生成一份样例 xlsx 下载，用于确认样式。

### 4.1 列

| 列 | 说明 |
|---|---|
| `Action` | 第一列，取值 N / U / D，见第 5 节 |
| `ID` | 数据库 id，或外部 id（xmlid）。U 和 D 必填；N 留空 |
| `字段列` | 字段的技术名作为表头，表头下一行写中文标签（如 `name` / `名称`） |
| `Record Type` | 启用了记录类型的模型才有，填类型编码（如 `hospital`） |
| `Validation Error` | 只在下载的结果文件中出现，上传时忽略 |

字段列只包含**当前用户有读写权限**的字段，不把用户看不到的字段放进模板。

### 4.2 值的填写规则

| 字段类型 | 填写方式 |
|---|---|
| Char / Text | 文本 |
| Integer / Float / Monetary | 数字 |
| Boolean | `是` / `否`，或 `1` / `0` |
| Date / Datetime | `YYYY-MM-DD` / `YYYY-MM-DD HH:MM:SS` |
| Selection | 选项的标签（中文或英文），服务端转换为值 |
| Many2one | 名称（唯一匹配，见 4.3），或外部 id |
| One2many / Many2many | 不支持，需要单独的导入 |

### 4.3 Many2one 的匹配

- 默认按 `name_search` 精确匹配名称。
- 匹配到 0 个：错误 `未找到 XXX`。
- 匹配到多个：错误 `XXX 匹配到多个记录，请改用 ID`。
- 也允许填外部 id（`module.xmlid`）。

### 4.4 下载模板的文件

- 第一个工作表：模板，表头 + 样例行（可选）。
- 第二个工作表 `Help`：每个字段的类型、是否必填、Selection 的可选值、Many2one 的说明。

## 5. 操作标记

| Action | 含义 | 必填 | 失败的典型原因 |
|---|---|---|---|
| `N` | 新建一条记录 | 必填的字段 | 缺少必填项、没有 create 权限、类型不允许 |
| `U` | 按 ID 更新 | `ID` | ID 不存在、没有 write 权限、字段值无效 |
| `D` | 按 ID 删除 | `ID` | ID 不存在、没有 unlink 权限、记录被其他记录引用 |
| 空 | 不允许 | — | `Action 必须为 N、U 或 D` |

决定：**空的 Action 报错，不默认为 N**。避免误操作。

- 同一个文件里，同一个 ID 出现多次：报错 `ID XX 在文件中重复出现`。
- 删除（D）优先于同文件中的其他操作的顺序由用户决定，系统按行号顺序执行。

## 6. 校验流程

分三步，全部在一个事务中完成，最后决定是否提交。

```
上传文件
  → 1. 解析：表头、Action、ID、类型转换、Many2one 匹配（不写数据库）
  → 2. 逐行执行：每行一个 savepoint，执行 create / write / unlink，捕获异常
  → 3. 汇总：有错误的行写入 Validation Error；全部通过则允许确认导入
  → 用户确认 → 重新执行（或保留第 2 步的结果）→ 提交
```

要点：

- **逐行 savepoint**：一行的异常不影响其他行，错误能准确归到该行。`cr.savepoint()` 已在 ORM 中使用。
- **不直接用 `load()`**：`Model.load()` 只支持创建和更新，不支持删除，也不处理行级的记录类型。它的结构（ids 与 messages）可以参考，但本功能自己写循环。
- **预览不落库**：第 2 步结束后执行 `rollback` 到导入前的状态，把结果文件返回给用户。确认导入时再执行一遍。
- **对约束的检查**：`create/write` 会触发模型的 `_check_*` 约束，错误信息直接取异常的文字。
- **大文件**：超过 `N` 行（默认 2000）拒绝导入，提示分批（阶段 3 改为后台任务）。

### 6.1 自定义校验

校验分三层，客户按需要选择，简单的不用写代码。

**第 1 层：模型约束（已有）**

`required`、`_sql_constraints`、`models.Constraint`、`@api.constrains`。这些在逐行执行 create/write 时自动触发，错误文字直接写入 `Validation Error`。大多数规则应放在这一层，因为界面、API、导入都受同样的约束。

**第 2 层：声明式规则（配置，不写代码）**

新增 `ir.data.import.rule`，由管理员在界面配置：

| 字段 | 说明 |
|---|---|
| `model_id` | 模型 |
| `record_type_id` | 可选，只对该类型的行生效 |
| `action` | 适用的操作：N、U、D 或组合 |
| `domain` | 行必须满足的条件，例如 `[('telephone', '!=', False)]` |
| `message` | 不满足时写入 `Validation Error` 的文字 |
| `sequence` | 执行顺序 |
| `active` | 是否启用 |

例：药店导入时要求电话或手机至少填一个：

- `domain`：`['|', ('telephone', '!=', False), ('mobile', '!=', False)]`
- `message`：`电话和手机至少填写一项`

实现要点：

- 只接受 domain，不接受任意 Python 表达式，避免配置被用来执行代码。
- 规则在行的值上检查：对 N，检查导入后的值；对 U，检查合并后的值（原记录的值加上文件中的修改）。
- 规则的字段必须在模型中存在，并对当前用户可读，保存时校验。

**第 3 层：代码钩子（开发者编写）**

客户的模块继承模型，覆盖约定的方法。框架在每行的 savepoint 中调用，不影响其他行。

```python
from odoo import models, _
from odoo.exceptions import ValidationError


class PharaccountAccount(models.Model):
    _inherit = 'pharaccount.account'

    def _import_validate_row(self, action, vals, record=None):
        """Called for every imported row (action 'N', 'U' or 'D').

        vals: the values from the file (for 'U' only the changed fields).
        record: the existing record for 'U' and 'D', empty for 'N'.
        Raise ValidationError to reject the row; the message goes to Validation Error.
        """
        super()._import_validate_row(action, vals, record)
        if action == 'N' and vals.get('geo_province') == '北京' and not vals.get('geo_city'):
            raise ValidationError(_('北京的药店必须填写城市'))
```

框架提供的钩子：

| 钩子 | 调用时机 | 用途 |
|---|---|---|
| `_import_validate_row(action, vals, record)` | 每行，savepoint 内 | 行级的复杂规则，需要查询其他数据时使用 |
| `_import_validate_file(rows)` | 文件解析后、逐行执行前 | 跨行的规则，例如同一文件中名称重复、同一 ID 重复 |
| `_import_after_row(action, record)` | 每行执行成功后 | 记录日志、触发其他操作（只在确认导入时调用，预览不调用） |

规则：

- 钩子中的异常一律转为该行的 `Validation Error`；其他异常视为系统错误，中止整个导入并记录到导入作业。
- 钩子必须可以在预览和确认中重复执行，不能有外部副作用（如发送邮件），外部副作用放在 `_import_after_row` 且只在确认时执行。
- 钩子的代码随模块发布，由开发者维护；界面上不能编辑。

**执行顺序**

```
解析文件 → _import_validate_file（文件级）
  → 逐行 savepoint:
      数据类型转换 → 第 2 层规则 → _import_validate_row（代码钩子）
      → create / write / unlink → 第 1 层约束（在 create/write 时触发）
  → 有错误则写 Validation Error；全部通过才允许确认
```

**给客户的交付方式**

- 第 2 层：客户管理员在界面自己配置，无需开发。
- 第 3 层：作为客户模块的一部分交付，写明每条规则对应的业务要求，并附测试。

**测试**

每条规则至少一个通过和一个失败的测试：构造一个文件，断言失败行的 `Validation Error` 文字正确，成功行为空。

## 7. 结果文件

- 输入的 xlsx 原样保留所有列，并在最后追加 `Validation Error` 列。
- 有错误的行：该列写入原因，多个原因用 `; ` 分隔。
- 没有错误的行：该列为空。
- 文件名：`<模型>_import_<时间>_result.xlsx`，作为附件保存，用户可以下载。
- 文件开头加一行汇总说明（或在 Help 表写明）：`共 120 行，成功 118，失败 2`。

示例（结果文件的 `Validation Error` 列）：

| Action | ID | name | telephone | Validation Error |
|---|---|---|---|---|
| N |  | 示例药店A | 010-1 |  |
| N |  |  | 010-2 | name：必填 |
| U | 41 | 示例单体药店 | 13800000000 |  |
| U | 999 | 示例药店 |  | ID 999 不存在 |
| D | 42 |  |  | 无删除权限（记录类型：医院） |

## 8. 确认导入

- 只有当所有行都没有错误时，才显示"确认导入"。
- 选项（待确认，见第 12 节）：`全部成功才导入`（推荐）或 `导入成功的行`。
- 确认导入时，**再次校验**（防止校验后数据已被他人修改），然后提交。
- 导入完成后显示结果：新建 N 条、更新 U 条、删除 D 条。

## 8.1 同步与异步

**结论：两种都支持，由行数自动选择，同一套校验引擎。**

| 方式 | 适用 | 特点 |
|---|---|---|
| 同步 | 行数 ≤ 阈值（默认 300 行） | 上传后直接返回校验结果，用户立即看到错误 |
| 异步 | 行数 > 阈值 | 上传后立即返回作业编号，后台执行，界面显示进度，完成后通知 |

阈值为系统参数 `ir_data_import.sync_max_rows`，管理员可改。

### 8.1.1 引擎只有一个

同步和异步都调用同一个函数 `_run_import_job(job, mode)`，区别只在于谁调用它、怎样分批：

- **校验**（预览）和**确认导入**都走这个函数。
- 逐行的 savepoint、第 2 层规则、第 3 层钩子的执行顺序完全一致，保证"预览通过，确认也通过"。

### 8.1.2 同步路径

```
上传 → 创建作业（state=validating）→ 在请求中执行校验 → 返回结果
确认 → 在请求中执行导入 → 返回结果
```

- 请求超时时间内完成（300 行以内通常几秒）。
- 不能超时：校验和导入都设置超时保护，超过 60 秒自动转为异步。

### 8.1.3 异步路径

```
上传 → 创建作业（state=queued）→ 触发 ir.cron → 返回作业编号
ir.cron 每次处理一批（默认 200 行）→ 更新作业的进度 → 本批未完成则再次触发
全部完成 → state=validated 或 done → 通知用户
```

要点：

- **分批**：每批在独立事务中提交。批次之间的失败只影响那一批，不回滚已完成的批次。异步下"全部成功才导入"的规则需要特别处理：见 8.1.4。
- **触发**：使用 `ir.cron._trigger()` 让作业立即执行，不等待固定周期。作业完成后不再触发。
- **进度**：作业记录的 `processed_rows` / `total_rows` 字段，界面每 5 秒刷新一次（或通过总线推送）。
- **通知**：完成时在作业上发消息，并通过总线通知用户，点击打开作业。
- **取消**：用户可以取消排队或进行中的作业；取消后，已提交的批次不回滚，状态标记为 `cancelled`，并说明已导入的行数。这一点需要在界面上明确提示。
- **断点恢复**：ir.cron 失败时，作业保持在 `running` 状态，记录失败的批次号；管理员可以点"重试"从该批次继续。
- **并发**：同一模型同时只允许一个导入作业执行中，其他作业排队，避免数据冲突。

### 8.1.4 "全部成功才导入"在异步下的处理

- 异步的**校验阶段**先完整跑一遍（分批，但只做校验、不写库），全部通过才进入导入阶段。
- 导入阶段分批写库。如果导入阶段中途失败，按"导入成功的行"处理：已写入的批次保留，失败批次记录错误，作业标记 `partial`。
- 因此异步的"全部成功才导入"是**校验层面的保证**：只要校验通过，导入阶段出错的概率很小；导入阶段出错时，作业明确标记为 `partial`，不假装全部成功。

### 8.1.5 作业状态

| 状态 | 含义 |
|---|---|
| `draft` | 已上传，未开始 |
| `queued` | 异步排队中 |
| `validating` | 校验中（同步或异步） |
| `validated` | 校验完成，等待确认 |
| `importing` | 导入中 |
| `done` | 全部完成 |
| `partial` | 部分完成（导入阶段中途失败） |
| `failed` | 系统错误，未完成 |
| `cancelled` | 用户取消 |

## 9. 数据模型

新增 `ir.data.import.job`，记录每一次导入，便于追踪和审计：

| 字段 | 说明 |
|---|---|
| `user_id` | 操作人 |
| `model_id` | 模型 |
| `state` | `draft`（已上传未校验）、`validated`（已校验，未确认）、`done`（已导入）、`failed`（失败）|
| `source_file` | 上传的原始文件（附件）|
| `result_file` | 带 Validation Error 的结果文件（附件）|
| `total_rows` / `processed_rows` / `error_rows` / `created` / `updated` / `deleted` | 计数，`processed_rows` 用于异步进度 |
| `mode` | `sync` 或 `async` |
| `failed_batch` | 失败的批次号，用于重试 |
| `create_date` | 时间 |

## 10. 安全

- 没有 `perm_import` 的用户：不能上传，服务端直接拒绝。
- D 操作需要 `unlink` 权限，并且在界面上要求二次确认。
- 上传的文件类型只允许 xlsx（以及 csv，阶段 2）。
- 文件大小限制（默认 10 MB）和行数限制（默认 2000 行）。
- 导出的单元格如果以 `= + - @` 开头，前面加 `'`，防止公式注入。
- 每次导入写入 `ir.data.import.job`，可以追溯。

## 11. 实施阶段

1. **阶段 1（先做）**：权限模型、模板下载、N / U / D、逐行校验、结果文件、Web 端导入框。以 `pharaccount.account` 为试点，包括记录类型列。
2. **阶段 2**：csv 支持、Many2one 按外部 id 匹配、导入作业的查看界面、把功能推广到其他模型。
3. 大文件后台执行、进度显示：视阶段 1、2 的使用情况再决定，不排期。
4. 移动端导入：不做。

## 12. 决策

| 问题 | 决定 |
|---|---|
| 移动端导入 | 不做 |
| 试点模型 | `pharaccount.account` |
| 有错误时的处理 | **待确认**，暂按推荐：全部成功才导入 |
| 空的 Action | **待确认**，暂按推荐：报错，不默认为 N |
| U / D 的匹配键 | **待确认**，暂按推荐：数据库 ID，并支持外部 ID |

## 13. 与现有代码的关系

- 基础：ORM 的 `create / write / unlink` 和 `_check_*` 约束。
- 记录类型：`ir.record.type._can_use`、`ir.record.type.permission`。
- 没有现成的数据导入，`base_import_module` 只用于安装模块，不相关。
- 生成 xlsx 使用 xlsxwriter（已安装）。
