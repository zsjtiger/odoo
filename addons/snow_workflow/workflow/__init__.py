# 在已完成页面展示的所有类型，self_submit_approve并没有审批节点，自审批时的特殊插入数据处理
MY_APPROVED_TASKS_TYPE = ['self_submit_approve', 'approve_execution', 'group_approve_execution_or',
                          'group_approve_execution_and']
APPROVE_EXECUTION_TASKS = ['approve_execution', 'group_approve_execution_or', 'group_approve_execution_and']
GROUP_APPROVE_EXECUTION_TASKS = ['group_approve_execution_or', 'group_approve_execution_and']
STATUS_MAPPING = {'approve_draft': '草稿', 'approve_pending': '审批中', 'reject': '已拒绝', 'pass': '已通过',
                  'suspending': '已挂起', 'withdraw': '已撤回'}
