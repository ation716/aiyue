"""数据清洗接口。

本文件定义清洗阶段的最小扩展协议，预留给后续确认输入字段、缺失值处理、
重复记录处理和输出字段之后的具体实现。当前没有实际清洗逻辑，也不会自动
删除、填充或改写传入数据。
"""


class DataCleaner:
    """数据清洗器的预留接口；具体规则由下游调用方确认后实现。"""

    def transform(self, data):
        """对输入数据执行清洗并返回结果；当前未实现。"""
        raise NotImplementedError("This interface is not implemented.")
