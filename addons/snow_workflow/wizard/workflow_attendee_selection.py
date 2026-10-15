from crossnow import models


class WorkflowAttendeeSelection(models.TransientModel):
    """
        本model对应加签窗口，只有一个字段，在snow.common中以继承形式覆盖此模型
    """
    _name = 'snow.workflow.attendee.selection'
    _description = 'Workflow Attendee Selection'
