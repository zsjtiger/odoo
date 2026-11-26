# 药店的数据导入配置

药店（`pharaccount.account`）已接入数据导入（`ir_data_import`）。完整设计见 `ir_data_import/doc/design.md`；本文件只说明药店的配置。

## 入口

药店列表的齿轮菜单中有"导入"。向导可以选择记录类型，并提供模板下载和上传。

## 权限

- 数据文件 `data/ir_data_import_data.xml` 为药店用户组（`group_user`）和管理组（`group_manager`）各授予导入权限和模板下载权限。该文件为 noupdate，升级时不会覆盖已改过的权限。
- 具体某个记录类型是否允许导入，由记录类型上的 `allow_import` 和记录类型权限上的 `allow_import` 决定（见 `ir_recordtype/doc/import.md`）。

## 模板

- 数据文件中有一套"药店导入模板"：中文表头，药店名称必填，电话、手机、省、市、地址、药店级别、重要标记，并带一条示例行。
- 没有配置的模板（如某个记录类型没有专用模板）回退到自动生成的通用模板。
- 拼音字段（`name_pinyin`、`pinyin`、`alias_pinyin`、`pinyin_with_separator`）由系统计算，不放入模板；模型通过 `_import_exclude` 声明。

## 记录类型

- 导入的 Record Type 列使用记录类型的编码（如 `hospital`、`pharma`），下拉框列出所有类型。
- 向导中选择的记录类型，用于下载该类型的模板，并作为未填写类型的新建行的默认类型。
