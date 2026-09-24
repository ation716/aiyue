"""区间价格特征与真实数据调试入口。

本文件目前包含两部分：

1. ``FactorCalculator``：通用因子接口的预留骨架，尚未定义统一输入输出契约；
2. ``find_doubling_symbols``：按统一日期轴扫描每个代码的区间最低有效收盘值，
   识别在不超过指定窗口内达到倍数阈值的区间，并按冷却日数限制后续区间。

函数只接收调用方提供的 DataFrame 和日期轴，不补造缺失记录、不把缺失解释为
停牌，也不执行前向填充。文件底部的 ``__main__`` 仅用于连接真实数据库读取
日线和日期轴后查看结果，不写入数据库、不创建模拟数据；参数集中放在入口，
方便在 IDE 中断点检查中间变量。
"""
from collections import deque
from bisect import bisect_left
import pandas as pd


class FactorCalculator:
    def transform(self, data):
        raise NotImplementedError("请使用明确的特征方法；通用流程尚未实现")


def find_doubling_symbols(pf, start_date, end_date, window=60, threshold=2.0,
                          trading_dates=None, cooldown_days=5):
    """查找评估区间内、最近 window 个交易日窗口中曾达到指定倍数的对象。

    输入列：ts_code、trade_date、close。起点严格早于终点，窗口包含两端，
    两日期的日历位置差最多 window-1。终点在 [start_date, end_date] 内；
    起点可早于 start_date，因此调用方应提供至少 window-1 日预热数据。
    trading_dates 为完整且统一的交易日历；省略则使用 pf 的全部不同日期，
    仅作为近似日历，不能识别全体对象共同缺失的日期。
    同一对象按日期顺序记录首次达标区间，后续记录区间不相交。
    前一区间终点后跳过 cooldown_days 个统一交易日，再允许建立新区间起点；
    两段之间完整空出这些交易日，冷却日不能作为起点或终点。
    每次调用独立计数，预热期不触发；不执行事后最优区间选择。
    起点采用当时窗口最低有效 close，同价保留较早日期。
    缺失/非正 close 不参与比较，不补值，不推定停牌。此处无前向填充。
    """
    if not isinstance(pf, pd.DataFrame):
        raise TypeError("pf 必须是 pandas.DataFrame")
    required = {"ts_code", "trade_date", "close"}
    if not required.issubset(pf.columns):
        raise ValueError("缺少列：" + ", ".join(sorted(required - set(pf.columns))))
    if isinstance(window, bool) or not isinstance(window, int) or window < 2:
        raise ValueError("window 必须为至少 2 的整数")
    if isinstance(cooldown_days, bool) or not isinstance(cooldown_days, int) or cooldown_days < 0:
        raise ValueError("cooldown_days 必须为非负整数")
    threshold = float(threshold)
    if not 0 < threshold < float("inf"):
        raise ValueError("threshold 必须为有限正数")
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    if pd.isna(start) or pd.isna(end) or start > end:
        raise ValueError("起止日期无效")
    start, end = start.normalize(), end.normalize()
    df = pf[list(required)].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="raise").dt.normalize()
    if df["trade_date"].isna().any() or df["ts_code"].isna().any():
        raise ValueError("代码和日期不可为空")
    if df.duplicated(["ts_code", "trade_date"]).any():
        raise ValueError("同一代码与日期存在重复记录，请先确定去重口径")
    df["close"] = pd.to_numeric(df["close"], errors="raise")
    calendar = pd.DatetimeIndex(pd.to_datetime(
        df["trade_date"].unique() if trading_dates is None else list(trading_dates)
    )).normalize().unique().sort_values()
    if calendar.hasnans:
        raise ValueError("交易日历含空日期")
    positions = {day: i for i, day in enumerate(calendar)}
    df = df[df.trade_date <= end].copy()
    if not df.trade_date.isin(calendar).all():
        raise ValueError("输入记录日期不在指定交易日历内")
    df["position"] = df.trade_date.map(positions)
    columns = ["ts_code", "start_date", "end_date", "start_close", "end_close",
               "multiple", "calendar_days", "valid_close_days", "missing_close_days"]
    rows = []
    for code, group in df.groupby("ts_code", sort=True):
        group = group.sort_values("trade_date")
        minima = deque()
        last_trigger = None
        # 有效日期位置用于统计每次触发区间完整性，不把缺失当停牌。
        valid_positions = []
        for row in group.itertuples(index=False):
            p, day, value = int(row.position), row.trade_date, row.close
            while minima and minima[0][0] < p - window + 1:
                minima.popleft()
            if pd.isna(value) or not 0 < float(value) < float("inf"):
                continue
            value = float(value)
            valid_positions.append(p)
            # 新区间的起点必须越过上一段终点及完整冷却间隔。
            if last_trigger is not None and p <= last_trigger + cooldown_days:
                continue
            # 先比较再入队，确保不会在同一天自比较。
            if start <= day <= end and minima:
                origin = minima[0]
                multiple = value / origin[2]
                if multiple >= threshold:
                    count = len(valid_positions) - bisect_left(valid_positions, origin[0])
                    span = p - origin[0] + 1
                    rows.append(dict(ts_code=code, start_date=origin[1], end_date=day,
                                     start_close=origin[2], end_close=value, multiple=multiple,
                                     calendar_days=span, valid_close_days=count,
                                     missing_close_days=span-count))
                    last_trigger = p
                    minima.clear()
                    # 当前终点属于已完成区间，不得成为下一区间起点。
                    continue
            while minima and minima[-1][2] > value:
                minima.pop()
            minima.append((p, day, value))
    result = pd.DataFrame(rows, columns=columns)
    if not result.empty:
        result = result.sort_values(["ts_code", "end_date"]).reset_index(drop=True)
    result.attrs["calendar_source"] = "input_date_union" if trading_dates is None else "explicit"
    result.attrs["window"] = window
    result.attrs["threshold"] = threshold
    result.attrs["cooldown_days"] = cooldown_days
    result.attrs["partial_windows_allowed"] = True
    return result


if __name__ == "__main__":
    import sys
    from pathlib import Path
    # 支持 IDE 直接运行；核心计算仍只接收 DataFrame。
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from data.connectors.db_connector import DBConnector

    START_DATE = "2026-07-01"
    END_DATE = "2026-09-17"
    WINDOW = 60
    THRESHOLD = 2.0  # 可手动修改倍数
    COOLDOWN_DAYS = 5  # 两个记录区间之间完整空出的交易日数
    SYMBOLS = None  # None 查询长表全部对象；也可传真实代码列表

    # 使用本机默认连接配置，也可设置 DB_PASSWORD 覆盖。数据与日历均来自实际数据库。
    with DBConnector() as db:
        calendar_pf = db._query(
            "SELECT DISTINCT trade_date FROM stock_daily_kline_20220101_1314 "
            "WHERE trade_date <= %s ORDER BY trade_date", [END_DATE])
        calendar = pd.DatetimeIndex(calendar_pf["trade_date"])
        if calendar.empty:
            raise ValueError("数据库中没有所需日期，停止调试")
        start = pd.Timestamp(START_DATE)
        end = pd.Timestamp(END_DATE)
        if start > end:
            raise ValueError("起始日期晚于终止日期")
        before = calendar[calendar < start]
        warmup = before[-(WINDOW - 1):]
        if len(warmup) < WINDOW - 1:
            print("注意：数据库预热日期不足，首段窗口不完整。")
        load_start = warmup[0] if len(warmup) else start
        calendar = calendar[calendar >= load_start]
        if not ((calendar >= start) & (calendar <= end)).any():
            raise ValueError("评估区间没有实际日期，停止调试")
        pf = db.get_daily(SYMBOLS, load_start.date(), end.date())
    if pf.empty:
        raise ValueError("实际查询无数据，停止调试；不使用模拟数据替代")
    result = find_doubling_symbols(pf, START_DATE, END_DATE, WINDOW, THRESHOLD,
                                   trading_dates=calendar, cooldown_days=COOLDOWN_DAYS)
    print("来源：本机数据库长表；日历为全表日期并集，不是独立交易日历。")
    print("区间：", START_DATE, END_DATE, "输入记录：", len(pf), "命中数：", len(result))
    print(result.to_string(index=False))
    if result.empty:
        print("实际区间无命中，无法验证相邻记录间隔；不视为该项测试通过。")
    else:
        checked_pairs = 0
        for code, records in result.groupby("ts_code", sort=True):
            start_pos = calendar.get_indexer(pd.DatetimeIndex(records["start_date"]))
            end_pos = calendar.get_indexer(pd.DatetimeIndex(records["end_date"]))
            assert (start_pos >= 0).all() and (end_pos >= 0).all(), code
            assert (end_pos > start_pos).all(), code
            assert (end_pos - start_pos + 1 <= WINDOW).all(), code
            assert (records["multiple"] >= THRESHOLD).all(), code
            if len(records) > 1:
                gaps = start_pos[1:] - end_pos[:-1] - 1
                assert (gaps >= COOLDOWN_DAYS).all(), (code, gaps)
                checked_pairs += len(gaps)
        print("真实结果区间边界检查通过；已核对相邻区间对数：", checked_pairs)
        if not checked_pairs:
            print("没有同一代码的多段命中，间隔检查缺少实际覆盖，需调整真实数据区间。")

