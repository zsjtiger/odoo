# -*- coding: utf-8 -*-
"""
服务任务的操作注册表与脚本引擎.

服务任务的 operator 中的 name 必须是此处注册的操作名 (设计器与保存校验都以此为准).
操作函数的签名: operation(params, task_data) -> JSON 字符串, 结果写入 resultVariable.
params 的每一项是 {'value': 求值后的结果}.
"""
import json

from ..gluon.bpmn.PythonScriptEngine import PythonScriptEngine
from .exceptions import SnowWorkflowValidationError

SERVICE_OPERATIONS = {}


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
    env[model].sudo().browse(record_id).write(values)
    return json.dumps(True)


class SnowScriptEngine(PythonScriptEngine):
    """引擎的脚本环境: 条件表达式与脚本任务用 Python 求值, 服务任务调用上面注册的操作"""

    def call_service(self, operation_name, operation_params, task_data):
        operation = SERVICE_OPERATIONS.get(operation_name)
        if operation is None:
            raise SnowWorkflowValidationError(f'Unknown service operation: {operation_name}')
        return operation(operation_params, task_data)
