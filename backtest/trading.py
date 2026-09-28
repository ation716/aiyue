"""三阶段交易接口：账户状态用字典承载，撮合规则复用已确认的 broker。

约定：
- 本层数量单位统一为「手」，仅在调用撮合层时换算为整数股。
- 未成交委托由本接口自动结转到下一阶段；调用方只需在本阶段提交新委托。
- 尾盘结束后未成交委托作废，其占用现金全额释放。
- 同一阶段卖出所得不在本阶段用于买入，阶段末再释放到可用现金。
- 撮合仍要求委托生成日早于执行日，本层不做例外。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .broker import Broker, DailyBar, ExecutionContext, Order, PHASES, money, number

SIDES = ("buy", "sell")


@dataclass(frozen=True)
class TradeContext:
    """单日行情上下文；bars 与 prev_close 都只含当日可见数据。"""

    trade_date: date
    bars: dict[str, DailyBar]
    prev_close: dict[str, Decimal]


@dataclass
class AccountState:
    """账户状态；数量以「手」计，价格与现金以元计。"""

    cash: Decimal = Decimal("0")      # 可直接使用的可用现金
    reserved: Decimal = Decimal("0")  # 未成交买单占用现金，即 money_in_using
    deferred: Decimal = Decimal("0")  # 本阶段卖出所得，下一阶段才可用
    hold: dict[str, dict] = field(default_factory=dict)
    unexecuted: list[dict] = field(default_factory=list)

    @property
    def cash_total(self) -> Decimal:
        return self.cash + self.reserved + self.deferred

    def market_value(self, prices: dict[str, Decimal]) -> Decimal:
        total = Decimal("0")
        for symbol, record in self.hold.items():
            price = prices.get(symbol)
            if price is not None:
                total += price * Decimal(record["vol"]) * record["lot_size"]
        return money(total)

    def snapshot(self, phase: str) -> dict:
        """按用户指定结构导出账户状态。"""
        return {
            "hold": {
                symbol: {
                    "cost_price": str(record["cost_price"]),
                    "industry": record["industry"],
                    "vol": record["vol"],
                }
                for symbol, record in sorted(self.hold.items())
            },
            "money": str(money(self.cash)),
            "money_in_using": str(money(self.reserved)),
            # 只导出委托对外字段，内部记账字段（下划线前缀）不进入快照。
            "unexecuted_order": {item["order_id"]: {k: v for k, v in item.items() if not k.startswith("_")}
                                 for item in self.unexecuted},
            "phase": phase,
            "deferred_cash": str(money(self.deferred)),
        }


def _cost_upper_bound(price: Decimal, vol: int, lot_size: int, fee_rate: Decimal, min_fee: Decimal) -> Decimal:
    """买单现金占用上限：成交额 + 佣金；按触发价估算，成交价不高于触发价时不会超支。"""
    amount = money(price * Decimal(vol) * lot_size)
    return amount + money(max(min_fee, money(amount * fee_rate)))


def execute(pre_trade_order, phase, context: TradeContext, account: AccountState, config) -> dict:
    """执行一个阶段的委托。

    入参：
    - pre_trade_order：本阶段新提交的委托，每项含
      order_id、symbol、side（buy/sell）、price（触发价）、vol（手）
    - phase：OPEN / INTRADAY / CLOSE
    - context：TradeContext
    - account：AccountState，原地更新
    - config：需含 lot_size、fee_rate、min_fee、slippage

    返回：{"phase", "fills", "rejects", "account"}
    """
    if phase not in PHASES:
        raise ValueError(f"交易时间必须是 {PHASES} 之一")
    lot_size = int(config["lot_size"])
    fee_rate = number(config["fee_rate"])
    min_fee = number(config["min_fee"])
    slippage = number(config["slippage"])

    # 上一阶段未成交委托先结转，与本阶段新委托合并；同阶段固定先卖后买。
    pending = [dict(item) for item in account.unexecuted] + [dict(item) for item in pre_trade_order]
    account.unexecuted = []
    pending.sort(key=lambda item: 0 if item["side"] == "sell" else 1)

    broker = Broker()
    fills, rejects, kept = [], [], []

    for item in pending:
        symbol, side = item["symbol"], item["side"]
        vol = int(item["vol"])
        if side not in SIDES or vol <= 0:
            prev_reserved = number(item["_reserved"]) if item.get("_reserved") else Decimal("0")
            if prev_reserved > 0:
                account.reserved -= prev_reserved
                account.cash += prev_reserved
            rejects.append({"order_id": item.get("order_id"), "symbol": symbol, "side": side,
                            "reason": "INVALID_ORDER"})
            continue
        record = account.hold.get(symbol)
        sellable = 0
        if side == "sell":
            # 持仓与当日买入量以「手」记账，撮合层以「股」比较，此处统一换算。
            lots = max(0, int(record["vol"]) - int(record.get("today_bought_vol", 0))) if record else 0
            sellable = lots * lot_size
        trigger = number(item["price"])

        # 买单现金占用跨阶段保持：首次按上限占用，结转时沿用同一金额，不重复占用。
        hold_back = Decimal("0")
        if side == "buy":
            carry = number(item["_reserved"]) if item.get("_reserved") else Decimal("0")
            if carry > 0:
                hold_back = carry
            else:
                hold_back = _cost_upper_bound(trigger, vol, lot_size, fee_rate, min_fee)
                if hold_back > account.cash:
                    rejects.append({"order_id": item.get("order_id"), "symbol": symbol, "side": side,
                                    "reason": "INSUFFICIENT_CASH"})
                    kept.append(dict(item, _reserved=str(hold_back)))
                    continue
                account.cash -= hold_back
                account.reserved += hold_back
                item["_reserved"] = str(hold_back)

        order = Order(order_id=item["order_id"], ts_code=symbol, trade_date=context.trade_date,
                      side="BUY" if side == "buy" else "SELL", phase=phase,
                      trigger_price=trigger, quantity=vol * lot_size,
                      generated_date=item["generated_date"], earliest_phase=item.get("earliest_phase", "OPEN"),
                      valid_until=context.trade_date, plan_id=item.get("plan_id"))
        # 只把本笔委托自己的占用加回，其他未成交委托占用的现金不可见。
        ctx = ExecutionContext(available_cash=account.cash + hold_back, sellable_qty=sellable,
                               fee_rate=fee_rate, min_fee=min_fee, slippage=slippage,
                               approximate_mode=True, lot_size=lot_size)
        receipt = broker.execute(order, context.bars.get(symbol), ctx)

        if receipt.status != "FILLED":
            # 未成交：占用现金留在 reserved，随委托结转到下一阶段。
            rejects.append({"order_id": order.order_id, "symbol": symbol, "side": side,
                            "reason": receipt.reason_code})
            kept.append(item)
            continue

        value = money(receipt.fill_price * receipt.filled_qty)
        if side == "buy":
            account.reserved -= hold_back                      # 释放本笔占用
            account.cash += hold_back - value - receipt.fees   # 占用改为实际成本
            prior_vol = int(record["vol"]) if record else 0     # 手
            new_vol = prior_vol + vol                           # 手
            prior_shares = prior_vol * lot_size
            new_shares = new_vol * lot_size
            # 成本价按「股」摊；已是整手，new_shares 为整百股。
            total_cost = (record["cost_price"] * prior_shares + value + receipt.fees
                          if prior_vol else value + receipt.fees)
            account.hold[symbol] = {
                "cost_price": money(total_cost / Decimal(new_shares)),
                "industry": item.get("industry", record["industry"] if record else None),
                "vol": new_vol,
                "lot_size": lot_size,
                "today_bought_vol": (int(record.get("today_bought_vol", 0)) if record else 0) + vol,
                "entry_index": (record.get("entry_index") if record and record.get("entry_index") is not None
                                else item.get("entry_index")),
            }
        else:
            # 同阶段卖出所得只入 deferred，阶段末统一释放到可用现金，避免重复入账。
            account.deferred += value - receipt.fees
            left = int(record["vol"]) - vol
            if left:
                account.hold[symbol] = dict(record, vol=left)
            else:
                del account.hold[symbol]
        fills.append({"order_id": order.order_id, "symbol": symbol, "side": side, "phase": phase,
                      "price": str(receipt.fill_price), "vol": vol, "quantity": receipt.filled_qty,
                      "fee": str(receipt.fees), "flags": list(receipt.assumption_flags)})

    if phase == "CLOSE":
        # 尾盘结束：未成交委托作废，其占用现金全额释放。
        for item in kept:
            if item["side"] == "buy" and item.get("_reserved"):
                release = number(item["_reserved"])
                account.cash += release
                account.reserved -= release
        kept = []
    # 尾盘是最后阶段，卖出所得次日可用；非尾盘则在阶段末释放到下一阶段。
    account.cash += account.deferred
    account.deferred = Decimal("0")

    account.unexecuted = kept
    if account.cash < 0 or account.reserved < 0 or account.deferred < 0:
        raise AssertionError("现金守恒失败")
    return {"phase": phase, "fills": fills, "rejects": rejects, "account": account.snapshot(phase)}


def settle_day(account: AccountState) -> None:
    """日终结算：当日买入次日起可卖。"""
    for record in account.hold.values():
        record["today_bought_vol"] = 0
