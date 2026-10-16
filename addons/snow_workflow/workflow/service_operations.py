# -*- coding: utf-8 -*-
"""
服务任务的操作注册表与脚本引擎.

服务任务的 operator 中的 name 必须是此处注册的操作名 (设计器与保存校验都以此为准).
操作函数的签名: operation(params, task_data) -> JSON 字符串, 结果写入 resultVariable.
params 的每一项是 {'value': 求值后的结果}.
"""
import json

from odoo import _
from odoo.exceptions import UserError

from ..gluon.bpmn.PythonScriptEngine import PythonScriptEngine
from .exceptions import SnowWorkflowValidationError

SERVICE_OPERATIONS = {}

# write_record 可写的字段类型: 普通标量与 many2one; 系统字段与 x2many 不允许
WRITABLE_FIELD_TYPES = {'char', 'text', 'integer', 'float', 'boolean', 'date', 'datetime',
                        'selection', 'many2one'}
SYSTEM_FIELDS = {'id', 'create_uid', 'create_date', 'write_uid', 'write_date', 'active'}


def check_writable_field(env, model, name):
    """
    流程写入业务记录的字段必须是: 存储的普通字段 (非计算), 不是系统字段, 类型为标量或 many2one.
    设计器保存与运行时写入共用此检查.
    """
    field = env[model]._fields.get(name)
    if field is None:
        raise UserError(_("The field “%(field)s” does not exist on %(model)s.", field=name, model=model))
    if not field.store or field.compute or name in SYSTEM_FIELDS or field.type not in WRITABLE_FIELD_TYPES:
        raise UserError(_("The field “%(field)s” of %(model)s cannot be written by a workflow.",
                          field=name, model=model))


def service_operation(name):
    def register(func):
        SERVICE_OPERATIONS[name] = func
        return func
    return register


@service_operation('evaluate')
def _evaluate(params, task_data):
    """计算一个表达式, 结果即为 resultVariable 的值 (参数 value)"""
    return json.dumps(params['value']['value'], default=str)


@service_operation('write_record')
def _write_record(params, task_data):
    """把参数写入流程关联的业务记录 (task_data 中的 model / record)"""
    env = task_data.get('script_env')
    model = task_data.get('model')
    record_id = task_data.get('record')
    if env is None or not model or not record_id:
        raise SnowWorkflowValidationError('write_record needs the business record of the workflow')
    values = {name: param['value'] for name, param in params.items()}
    for name in values:
        check_writable_field(env, model, name)
    env[model].sudo().browse(record_id).write(values)
    return json.dumps(True)


class SnowScriptEngine(PythonScriptEngine):
    """引擎的脚本环境: 条件表达式与脚本任务用 Python 求值, 服务任务调用上面注册的操作"""

    def call_service(self, operation_name, operation_params, task_data):
        operation = SERVICE_OPERATIONS.get(operation_name)
        if operation is None:
            raise SnowWorkflowValidationError(f'Unknown service operation: {operation_name}')
        return operation(operation_params, task_data)
