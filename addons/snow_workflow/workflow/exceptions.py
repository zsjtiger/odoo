class SnowWorkflowBaseException(Exception):
    """
    整个模块内的Base Exception
    """
    pass


class SnowWorkflowEngineBaseException(SnowWorkflowBaseException):
    """
    engines模块内的基础异常
    """
    pass


class SnowWorkflowEngineNoXmlStringError(SnowWorkflowEngineBaseException):
    """
    engine的XML String 为空
    """
    pass


class SnowWorkflowEngineNoJsonStringError(SnowWorkflowEngineBaseException):
    """
    engine的Json String 为空
    """
    pass


class SnowWorkflowValidationError(SnowWorkflowBaseException):
    """
    BPMN XML 配置异常
    """
    pass


class SnowWorkflowAttendeeNoUserError(SnowWorkflowBaseException):
    """
    TaskAttendee找不到
    """
    pass


class SnowWorkflowAttendeeLaneAnalyzeError(SnowWorkflowBaseException):
    """
    泳道解析失败，扩展用，最终要抛Validation异常
    """
    pass


class SnowWorkflowStatusAnalyzeError(SnowWorkflowBaseException):
    """
    状态计算失败
    """
    pass


class SnowWorkflowRuntimeError(SnowWorkflowBaseException):
    """
    运行时错误
    """
    pass
