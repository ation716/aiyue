"""指标计算接口。

本文件预留从已清洗数据计算技术或统计指标的统一入口。当前尚未确定
指标名称、输入列、窗口、预热规则及缺失值口径，因此只保留接口，不执行
任何计算，也不对输入数据做隐式补值或过滤。
"""


class IndicatorCalculator:
    """指标计算器的预留接口。"""

    def transform(self, data):
        """根据已确认的指标契约计算并返回结果；当前未实现。"""
        raise NotImplementedError("This interface is not implemented.")
