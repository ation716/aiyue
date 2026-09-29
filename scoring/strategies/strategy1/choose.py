"""策略一：均线穿越 + 中位数 + 短周期回落，移植自已验证的 demo 候选逻辑。

与既有 demo 的差异只在接入形式：本模块按调用方传入的「截至当日」数据切片取值，
不自行读取数据库，也不使用当日之后的信息。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def choose(day, daily, calendar, params, account):
    """返回 {symbol: {"buy": 触发价, "other": 说明}}，以及 {"symbol": {"sell": 触发价, "vol": 手}}。

    入参：
    - day：当前统一交易日
    - daily：截至 day 的真实长表日线（含 day）
    - calendar：统一日期轴
    - params：策略参数
    - account：账户快照，含 hold、money、max_positions 等
    """
    position = int(calendar.get_loc(day))
    if position < params["warmup_days"]:
        return {}, {}
    prior = calendar[position - 1]

    window = params["window"]
    frames = []
    for code, group in daily.groupby("ts_code", sort=True):
        g = group.sort_values("trade_date").set_index("trade_date")
        close = g.close.where(np.isfinite(g.close) & g.close.gt(0))
        valid = close.dropna()
        mean = valid.rolling(window, min_periods=window).mean()
        median = valid.rolling(window, min_periods=window).median()
        change = close / close.shift(params["change_days"]) - 1
        current, previous = close.get(day), close.get(prior)
        if current is None or previous is None or not np.isfinite(current) or not np.isfinite(previous):
            continue
        m_today, mp_today = mean.get(day), median.get(day)
        m_prior = mean.get(prior)
        c5 = change.get(day)
        if any(v is None or not np.isfinite(v) for v in (m_today, mp_today, m_prior, c5)):
            continue
        size = g[params["size_field"]].get(day)
        turn = g.turnover_rate.get(day)
        if size is None or not np.isfinite(size) or size <= params["size_min"]:
            continue
        if turn is None or not np.isfinite(turn) or turn < 0:
            continue
        if previous <= m_prior and current > m_today and mp_today < m_today * params["median_ratio"] \
                and c5 > params["change_min"]:
            frames.append({"ts_code": code, "turnover_rate": turn, params["size_field"]: size,
                           "close": current})
    # 卖出信号只依赖当前持仓与价格，与当日是否有买入候选无关。
    sell = _sell_signals(account, params)
    if not frames:
        return {}, sell

    ranked = pd.DataFrame(frames).sort_values(
        ["turnover_rate", params["size_field"]], ascending=[False, True], kind="stable")
    held = set(account["hold"])
    slots = max(0, params["max_positions"] - len(held))
    buy = {}
    for row in ranked.itertuples():
        if row.ts_code in held or len(buy) >= slots:
            continue
        buy[row.ts_code] = {"buy": str(round(row.close * params["buy_ratio"], 2)),
                            "other": {"turnover_rate": float(row.turnover_rate), "close": float(row.close)}}
    return buy, sell


def _sell_signals(account, params):
    """按相对基准表现、绝对止盈止损和持有天数生成卖出信号。"""
    sell = {}
    benchmark_price = params.get("benchmark_price", {})
    benchmark_entry_price = params.get("benchmark_entry_price", {})
    benchmark_symbol = params.get("benchmark_symbol", "000001")
    benchmark_enabled = bool(params.get("benchmark_enabled", False))
    for symbol, record in account["hold"].items():
        price = params.get("close_price", {}).get(symbol)
        cost = float(record["cost_price"])
        if price is None or cost <= 0:
            continue
        price = float(price)
        gain = price / cost - 1
        held_days = params.get("held_days", {}).get(symbol, 0)

        relative_gain = None
        relative_reason = None
        entry_benchmark = benchmark_entry_price.get(symbol)
        current_benchmark = benchmark_price.get(benchmark_symbol)
        if benchmark_enabled and entry_benchmark is not None and current_benchmark is not None and float(entry_benchmark) > 0:
            benchmark_gain = float(current_benchmark) / float(entry_benchmark) - 1
            relative_gain = gain - benchmark_gain
            if relative_gain <= -float(params.get("relative_stop_loss", 0.08)):
                relative_reason = "relative_stop_loss"
            elif relative_gain >= float(params.get("relative_take_profit", 0.10)):
                relative_reason = "relative_take_profit"

        absolute_reason = None
        if gain >= float(params["take_profit"]):
            absolute_reason = "take_profit"
        elif gain <= -float(params["stop_loss"]):
            absolute_reason = "stop_loss"
        elif held_days >= params["hold_days"]:
            absolute_reason = "hold_days"

        reason = relative_reason or absolute_reason
        if reason:
            other = {"gain": gain, "held_days": held_days, "sell_reason": reason}
            if relative_gain is not None:
                other["relative_gain"] = relative_gain
            sell[symbol] = {"sell": str(round(price, 2)), "vol": record["vol"], "other": other}
    return sell
