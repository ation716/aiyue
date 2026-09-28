"""配仓模块：把选股结果转成每只对象的买入占比与手数。

返回结构与设计稿一致：
{symbol: {"buy": 触发价, "proportion": 占比, "vol": 手数, "other": ...}}
- proportion 为该对象占「当前可用现金」的比例，同一批买入合计不超过 1。
- vol 为买入量，单位手，按触发价与费用上限向下取整到整手。
"""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from backtest.broker import money, number


def buy_willingness(cash, total_assets, slots):
    """买入意愿：可用现金占总资产比例与可新增对象数共同决定，返回 0~1。

    两个条件同时约束：现金占比越高、空位越多，意愿越高；无空位或现金过少则为 0。
    """
    if slots <= 0 or total_assets <= 0:
        return 0.0
    cash_ratio = float(cash / total_assets)
    slot_ratio = min(1.0, slots / 3.0)          # 空位足够时不再继续放大意愿
    return max(0.0, min(1.0, cash_ratio * slot_ratio))


def allocation(buy_list, account, config, willingness=None):
    """按可用现金和买入意愿分配仓位。

    入参：
    - buy_list：选股返回的 {symbol: {"buy": 价, ...}}
    - account：含 money（可用现金）、hold、market_value 的账户快照
    - config：需含 lot_size、fee_rate、min_fee、max_positions、min_cash
    - willingness：0~1；None 时按 buy_willingness 计算
    """
    cash = number(account["money"])
    lot_size = int(config["lot_size"])
    fee_rate = number(config["fee_rate"])
    min_fee = number(config["min_fee"])
    budget_rate = number(config.get("budget_rate", "1"))
    if cash < number(config["min_cash"]):
        return {}, {"reason": "CASH_BELOW_MINIMUM", "available_cash": str(money(cash))}

    held = set(account["hold"])
    slots = max(0, int(config["max_positions"]) - len(held))
    candidates = [(s, d) for s, d in buy_list.items() if s not in held][:slots]
    if not candidates:
        return {}, {"reason": "NO_SLOT_OR_CANDIDATE", "available_cash": str(money(cash))}

    if willingness is None:
        total = cash + number(account.get("market_value", "0"))
        willingness = buy_willingness(cash, total, slots)
    usable = money(cash * budget_rate * Decimal(str(willingness)))
    per = usable / len(candidates)

    result, used = {}, Decimal("0")
    for symbol, detail in candidates:
        price = number(detail["buy"])
        if price <= 0:
            continue
        # 手数向下取整，确保成交额加佣金不超过该对象预算。
        per_lot = money(price * lot_size)
        vol = int((per / (per_lot + max(min_fee, money(per_lot * fee_rate)))).to_integral_value(ROUND_DOWN))
        if vol <= 0:
            continue
        cost = money(money(price * vol * lot_size) + max(min_fee, money(money(price * vol * lot_size) * fee_rate)))
        result[symbol] = {"buy": detail["buy"], "proportion": float((cost / cash).quantize(Decimal("0.0001"))),
                          "vol": vol, "other": dict(detail.get("other", {}), plan_cost=str(cost))}
        used += cost
    return result, {"available_cash": str(money(cash)), "willingness": round(willingness, 4),
                    "allocated": str(money(used)), "slots": slots}
