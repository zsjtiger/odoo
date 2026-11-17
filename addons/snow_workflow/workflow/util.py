from .status import WorkflowStatus


class SnowWorkflowRecordUtil(object):
    """
    将task对象与workflow对象的属性, 填充到对应的record_data中
    """
    def __init__(self, env, bpmn_workflow_engine):
        self.env = env
        self.bpmn_workflow_engine = bpmn_workflow_engine

    def create_task_record_static_data(self, task):
        """
        同时适用于task表与task_history表
        """
        return {
            'task_xml_id': task.get_name(),
            'task_xml_name': task.get_description(),
            'wf_task_json': self.bpmn_workflow_engine.save_task_obj_to_json_str(task),
            'wf_task_spec_json': self.bpmn_workflow_engine.save_task_obj_spec_to_json_str(task)
        }

    def create_task_history_record_static_data(self, task_id, task):
        """
        创建task_history表数据
        """
        return {
            'wf_task': task_id,
            'task_xml_id': task.get_name(),
            'task_xml_name': task.get_description(),
            'wf_task_json': self.bpmn_workflow_engine.save_task_obj_to_json_str(task),
            'wf_task_spec_json': self.bpmn_workflow_engine.save_task_obj_spec_to_json_str(task)
        }

    def create_execution_record_static_data(self, workflow_instance, sub_workflow):
        status_info = WorkflowStatus(workflow_instance, self.env, sub_workflow).compute_execution_status()
        main_workflow = sub_workflow._get_outermost_workflow()
        return {
            'wf_json': self.bpmn_workflow_engine.save_workflow_obj_to_json_str(main_workflow),
            'is_complete': sub_workflow.is_completed(),
            'status': status_info.get('status'),
            'status_owner': status_info.get('status_owner')
        }
