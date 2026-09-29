"""策略二：热度、量能、价格区间与流通市值过滤。

规则来源：scoring/strategies/strategy2/s2_design.md。
只使用调用方传入的截至当前交易日数据，不自行读取数据库。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


DEFAULTS = {
    "s2_turnover_window": 7,
    "s2_breakout_window": 15,
    "s2_breakout_min": 0.07,
    "s2_volume_windows": (7, 30, 60),
    "s2_price_window": 252,
    "s2_high_low_ratio": 1.35,
    "s2_float_mv_min": 22_000_000_000,
    "s2_float_mv_max": 500_000_000_000,
    "s2_max_hold_days": 12,
    "s2_extended_hold_days": 18,
    "s2_limit_up_ratio": 0.10,
    "s2_post_limit_dd": 0.06,
    "s2_post_limit_gain_window": 5,
    "s2_loss_limit": 0.088,
}


def _param(params, name):
    return params.get(name, DEFAULTS[name])


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _series(group, column):
    if column not in group:
        return pd.Series(index=group.index, dtype="float64")
    return pd.to_numeric(group[column], errors="coerce")


def _limit_up_events(group, limit_up_ratio):
    """返回每个交易日是否收盘达到近似首板涨停。"""
    close = _series(group, "close")
    previous = close.shift(1)
    # 撮合层使用两位价格的 1.10/0.90 近似限制价；这里保持同一近似口径。
    threshold = (previous * (1.0 + float(limit_up_ratio))).round(2)
    return close.ge(threshold) & previous.gt(0) & close.notna()


def _post_limit_status(group, day, entry_index, params):
    """判断入场后是否出现首板，以及涨停后是否仍满足延长持有条件。

    ``单日回撤小于 6`` 按百分比解释为：涨停日之后至当前，任一单日收盘跌幅均未达到 -6%；
    ``5 日累计涨幅为正`` 按当前收盘相对五个交易日前收盘的变化解释。
    """
    limit_ratio = _param(params, "s2_limit_up_ratio")
    indexed = group.reset_index(drop=True)
    events = _limit_up_events(indexed, limit_ratio)
    day_positions = indexed.index[indexed["trade_date"].eq(day)].tolist()
    if not day_positions:
        return False, False, None
    current_pos = day_positions[-1]
    entry_pos = max(0, int(entry_index or current_pos))
    event_positions = [p for p in range(entry_pos + 1, current_pos + 1) if bool(events.iloc[p])]
    if not event_positions:
        return False, False, None
    event_pos = event_positions[0]
    if current_pos <= event_pos:
        return True, True, event_pos

    close = _series(indexed, "close")
    daily_change = close / close.shift(1) - 1
    after_changes = daily_change.iloc[event_pos + 1:current_pos + 1].dropna()
    max_single_day_dd = float(after_changes.min()) if not after_changes.empty else 0.0
    gain_window = int(_param(params, "s2_post_limit_gain_window"))
    start = current_pos - gain_window
    cumulative_gain = np.nan
    if start >= 0 and close.iloc[start] > 0 and pd.notna(close.iloc[current_pos]):
        cumulative_gain = float(close.iloc[current_pos] / close.iloc[start] - 1)
    qualifies = max_single_day_dd > -float(_param(params, "s2_post_limit_dd")) and np.isfinite(cumulative_gain) and cumulative_gain > 0
    return True, bool(qualifies), event_pos


def _sell_signals(account, daily, day, calendar, params):
    """按累计亏损、12/18 日持有规则生成卖出信号。"""
    sell = {}
    close_price = params.get("close_price", {})
    current_position = int(calendar.get_loc(day))
    for symbol, record in account["hold"].items():
        price = _number(close_price.get(symbol))
        cost = _number(record.get("cost_price"))
        if price is None or cost is None or cost <= 0:
            continue
        gain = price / cost - 1.0
        held_days = int(params.get("held_days", {}).get(symbol, 0))
        reason = None
        if gain <= -float(_param(params, "s2_loss_limit")):
            reason = "cumulative_loss"
        else:
            history = daily[daily.ts_code.eq(symbol)].sort_values("trade_date")
            # entry_index 是统一日历位置；策略历史切片可能缺少停牌日，
            # 因此按当前 symbol 的可见记录和已持有交易日反推入场位置。
            entry_index = max(0, len(history) - 1 - held_days)
            has_limit_up, extension_ok, event_pos = _post_limit_status(
                history, day, entry_index, params
            )
            max_hold = int(_param(params, "s2_extended_hold_days")) if has_limit_up and extension_ok else int(_param(params, "s2_max_hold_days"))
            if has_limit_up and event_pos is not None and current_position > event_pos and not extension_ok:
                reason = "post_limit_condition"
            elif held_days >= max_hold:
                reason = "extended_hold_days" if max_hold > int(_param(params, "s2_max_hold_days")) else "max_hold_days"
        if reason:
            sell[symbol] = {
                "sell": str(round(price, 2)),
                "vol": record["vol"],
                "other": {"gain": gain, "held_days": held_days, "sell_reason": reason},
            }
    return sell


def _candidate(group, day, params):
    group = group.sort_values("trade_date").reset_index(drop=True)
    close = _series(group, "close")
    high = _series(group, "high")
    low = _series(group, "low")
    turn = _series(group, "turnover_rate")
    volume = _series(group, "vol")
    current = group.index[group.trade_date.eq(day)].tolist()
    if not current:
        return None
    pos = current[-1]
    current_close = _number(close.iloc[pos])
    if current_close is None or current_close <= 0:
        return None

    turn_window = int(_param(params, "s2_turnover_window"))
    breakout_window = int(_param(params, "s2_breakout_window"))
    w7, w30, w60 = _param(params, "s2_volume_windows")
    if pos + 1 < max(turn_window, w60):
        return None
    avg_turn = turn.iloc[:pos + 1].tail(turn_window).mean()
    close_change = close.iloc[:pos + 1] / close.iloc[:pos + 1].shift(1) - 1
    recent_breakout = close_change.iloc[:pos + 1].tail(breakout_window).gt(float(_param(params, "s2_breakout_min"))).any()
    avg7 = volume.iloc[:pos + 1].tail(int(w7)).mean()
    avg30 = volume.iloc[:pos + 1].tail(int(w30)).mean()
    avg60 = volume.iloc[:pos + 1].tail(int(w60)).mean()
    price_window = int(_param(params, "s2_price_window"))
    high_window = high.iloc[:pos + 1].tail(price_window).dropna()
    low_window = low.iloc[:pos + 1].tail(price_window).dropna()
    yearly_high = high_window.max() if not high_window.empty else np.nan
    yearly_low = low_window.min() if not low_window.empty else np.nan
    float_mv = _number(group.loc[pos].get(params.get("size_field", "float_mv")))

    if not np.isfinite(avg_turn) or avg_turn <= 5:
        return None
    if not recent_breakout or not all(np.isfinite(v) for v in (avg7, avg30, avg60)) or not (avg7 > avg30 > avg60):
        return None
    if not np.isfinite(yearly_high) or not np.isfinite(yearly_low) or yearly_low <= 0 or yearly_high > yearly_low * float(_param(params, "s2_high_low_ratio")):
        return None
    if float_mv is None or not (float(_param(params, "s2_float_mv_min")) <= float_mv <= float(_param(params, "s2_float_mv_max"))):
        return None
    return {"close": current_close, "turnover_rate": float(avg_turn), "avg_vol_7": float(avg7),
            "avg_vol_30": float(avg30), "avg_vol_60": float(avg60), "float_mv": float(float_mv),
            "year_high": float(yearly_high), "year_low": float(yearly_low)}


def choose(day, daily, calendar, params, account):
    """返回策略二的 buy / sell 委托规划。"""
    position = int(calendar.get_loc(day))
    if position < int(params.get("warmup_days", 60)):
        return {}, {}

    sell = _sell_signals(account, daily, day, calendar, params)
    frames = []
    for symbol, group in daily.groupby("ts_code", sort=True):
        candidate = _candidate(group, day, params)
        if candidate is not None:
            frames.append({"ts_code": symbol, **candidate})
    if not frames:
        return {}, sell

    ranked = pd.DataFrame(frames).sort_values(["turnover_rate", "float_mv"], ascending=[False, True], kind="stable")
    held = set(account["hold"])
    slots = max(0, int(params["max_positions"]) - len(held))
    buy = {}
    for row in ranked.itertuples():
        if row.ts_code in held or len(buy) >= slots:
            continue
        price = float(row.close) * float(params.get("buy_ratio", 0.995))
        buy[row.ts_code] = {
            "buy": str(round(price, 2)),
            "other": {"turnover_rate_7": row.turnover_rate, "avg_vol_7": row.avg_vol_7,
                       "avg_vol_30": row.avg_vol_30, "avg_vol_60": row.avg_vol_60,
                       "float_mv": row.float_mv, "year_high": row.year_high, "year_low": row.year_low},
        }
    return buy, sell
