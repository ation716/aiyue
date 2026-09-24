"""预处理流程编排接口。

本文件预留把清洗、指标和因子等步骤按明确顺序串联起来的统一入口。
当前尚未确认步骤注册、错误传播、输出结构和是否允许原地修改，因此只
保留流程接口；调用不会自动读取数据库或执行任何处理。
"""


class PreprocessingPipeline:
    """预处理流程的预留接口。"""

    def run(self, data):
        """执行已确认的预处理链并返回结果；当前未实现。"""
        raise NotImplementedError("This interface is not implemented.")
