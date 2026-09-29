"""配仓模块：把选股结果转成每只对象的买入占比与手数。

返回结构与设计稿一致：
{symbol: {"buy": 触发价, "proportion": 占比, "vol": 手数, "other": ...}}
- proportion 为该对象占「当前可用现金」的比例，同一批买入合计不超过 1。
- vol 为买入量，单位手，按触发价与费用上限向下取整到整手。

单标的集中度上限（max_single_weight，占总资产比例）：
- 该对象允许占用的市值上限 = 总资产 × max_single_weight，本次可买市值 = 上限 − 已占市值。
- 买入量同时受「等分预算」与「市值上限」约束，取两者中更小的一手数量，按整手向下取整。
- 市值上限按成交市值直接约束（不含费用），保证买入后「已占市值 + 本次买入市值」不超上限；
  因此任一标的占总资产比重恒 ≤ max_single_weight。
- 候选等分预算被上限压掉的部分顺延给尚未定量的后续候选；所有候选都顶到上限后，
  剩余额度留在可用现金，不突破上限加仓。
- 上限按总资产计算，与可用现金占总资产的比例无关，不会因现金占比低而被放大。
- 未配置该键、或值 ≤ 0 时完全保持原有等分行为。"""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from backtest.broker import money, number

# 计算单标的可用预算时的兜底下限（元），低于此值不再尝试买入。
MIN_BUDGET = Decimal("0.01")


def lots_within_budget(price, budget, lot_size, fee_rate, min_fee):
    """预算内可买的最大手数（向下取整整手）。

    口径与原实现等价：成交额加佣金不超过预算，且最低佣金按「不触发」处理，
    即满足 net + fee(net) ≤ budget 的整手数量。
    入参：price 触发价、budget 该对象本次预算（元）、lot_size 每手股数、
    fee_rate 佣金率、min_fee 最低佣金。
    """
    if price <= 0 or budget <= 0 or lot_size <= 0:
        return 0
    net = money(budget) / (Decimal("1") + fee_rate)
    net -= min_fee                                # 先按最低佣金预留，等价于原来的 budget − min_fee
    if net <= 0:
        return 0
    return int((net / (money(price * lot_size))).to_integral_value(ROUND_DOWN))


def deal_cost(price, vol, lot_size, fee_rate, min_fee):
    """一手数的买入总成本：成交额 + 佣金（不低于最低佣金），按分取整。"""
    amount = money(price * Decimal(vol) * lot_size)
    return money(amount + max(min_fee, money(amount * fee_rate)))


def buy_willingness(cash, total_assets, slots):
    """买入意愿：可用现金占总资产比例与可新增对象数共同决定，返回 0~1。

    两个条件同时约束：现金占比越高、空位越多，意愿越高；无空位或现金过少则为 0。
    """
    if slots <= 0 or total_assets <= 0:
        return 0.0
    cash_ratio = float(cash / total_assets)
    slot_ratio = min(1.0, slots / 3.0)          # 空位足够时不再继续放大意愿
    return max(0.0, min(1.0, cash_ratio * slot_ratio))


def single_slot_cap(total_assets, current_value, single_weight):
    """单标的允许占用的市值上限 = 总资产 × 单标的比例 − 该对象当前市值。

    口径直接约束「成交市值」，不掺入费用，保证买入后
    （已占市值 + 本次买入市值）≤ 总资产 × single_weight 恒成立。

    入参：
    - total_assets：总资产 = 可用现金 + 持仓市值
    - current_value：该对象当前市值，未持有时传 0
    - single_weight：单标的占总资产比例上限，0~1

    返回 None 表示该比例未启用（由调用方按未启用处理）；
    返回 0 表示已满配，本次不再加仓，但额度仍可顺延给其他候选。
    """
    if single_weight <= 0 or total_assets <= 0:
        return None
    return single_weight * total_assets - current_value


def lots_within_cap(price, market_cap, lot_size):
    """在成交市值上限内可买的最大手数（向下取整整手）。"""
    if price <= 0 or market_cap <= 0 or lot_size <= 0:
        return 0
    return int((market_cap / (price * lot_size)).to_integral_value(ROUND_DOWN))


def allocation(buy_list, account, config, willingness=None):
    """按可用现金和买入意愿分配仓位。

    入参：
    - buy_list：选股返回的 {symbol: {"buy": 价, ...}}
    - account：含 money（可用现金）、hold、market_value 的账户快照
    - config：需含 lot_size、fee_rate、min_fee、max_positions、min_cash；
      可选 max_single_weight（单标的占总资产比例上限，<=0 或缺失表示不限制）
    - willingness：0~1；None 时按 buy_willingness 计算
    """
    cash = number(account["money"])
    lot_size = int(config["lot_size"])
    fee_rate = number(config["fee_rate"])
    min_fee = number(config["min_fee"])
    budget_rate = number(config.get("budget_rate", "1"))
    # 单标的占总资产比例上限；未配置或 <= 0 时不做任何集中度约束。
    single_weight = number(config.get("max_single_weight", "0"))
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
    total_assets = cash + number(account.get("market_value", "0"))
    usable = money(cash * budget_rate * Decimal(str(willingness)))
    remaining = usable                  # 尚未分配的预算；被上限压掉的部分顺延给后面的候选
    prices = account.get("price") or {}

    result, used = {}, Decimal("0")
    pending = list(candidates)
    while pending:
        symbol, detail = pending.pop(0)
        price = number(detail["buy"])
        if price <= 0:
            continue
        # 当前该对象已占市值：只用可见收盘价估算，价格缺失时保守取 0。
        record = account["hold"].get(symbol) or {}
        last_price = prices.get(symbol)
        current_value = (money(number(last_price) * Decimal(int(record.get("vol", 0))) * lot_size)
                         if last_price is not None else Decimal("0"))
        # 按当前候选数重新等分剩余预算；这也是原实现的算法，只是这里每轮用剩余额度重算。
        share = remaining / len(pending + [(symbol, detail)])
        # 该对象本次可买市值上限：总资产×比例 减去已占市值，再受等分预算与剩余预算约束。
        cap = single_slot_cap(total_assets, current_value, single_weight)
        budget = share if cap is None else max(min(share, cap), Decimal("0"))
        budget = min(budget, remaining)
        if budget <= MIN_BUDGET:
            # 额度不足一元：不消耗额度，顺延给后面的候选。
            continue
        vol = lots_within_budget(price, budget, lot_size, fee_rate, min_fee)
        if cap is not None:
            # 上限直接约束成交市值：买入市值不得超过「总资产×比例 − 已占市值」。
            vol = min(vol, lots_within_cap(price, max(cap, Decimal("0")), lot_size))
        if vol <= 0:
            # 该对象在额度或上限内连一手都买不进：额度不消耗，直接顺延给后面的候选。
            continue
        cost = deal_cost(price, vol, lot_size, fee_rate, min_fee)
        result[symbol] = {"buy": detail["buy"], "proportion": float((cost / cash).quantize(Decimal("0.0001"), ROUND_HALF_UP)),
                          "vol": vol, "other": dict(detail.get("other", {}), plan_cost=str(cost))}
        used += cost
        remaining = usable - used        # 被上限压掉的额度自动留给后面的候选
    info = {"available_cash": str(money(cash)), "willingness": round(willingness, 4),
            "slots": slots, "allocated": str(money(used))}
    if remaining > 0:
        # 预算未被用满：多为上限截断或整手取整余量，剩余留在可用现金不强行用满。
        info["unallocated"] = str(money(remaining))
    if single_weight > 0:
        info["max_single_weight"] = str(config.get("max_single_weight"))
    return result, info
