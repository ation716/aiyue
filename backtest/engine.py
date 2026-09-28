"""按真实日 K 日期推进账户；不生成计划或行情，不写数据库。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable

from .broker import Broker, DailyBar, ExecutionContext, ExecutionResult, Order, PHASES, money, number


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: Decimal
    approximate_mode: bool = False
    fee_rate: Decimal = Decimal("0.0001")
    min_fee: Decimal = Decimal("5")
    slippage: Decimal = Decimal("0")
    lot_size: int = 100
    max_stale_days: int | None = None


@dataclass
class Position:
    quantity: int = 0
    sellable_qty: int = 0
    today_bought_qty: int = 0
    last_price: Decimal | None = None
    valuation_date: date | None = None


@dataclass
class BacktestResult:
    orders: list[dict] = field(default_factory=list)
    fills: list[dict] = field(default_factory=list)
    account_snapshots: list[dict] = field(default_factory=list)
    position_snapshots: list[dict] = field(default_factory=list)
    daily_nav: list[dict] = field(default_factory=list)
    plans: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    config: BacktestConfig | None = None


class BacktestEngine:
    """当日三阶段；本阶段卖出所得在下一阶段释放。"""

    def __init__(self, broker: Broker | None = None):
        self.broker = broker or Broker()

    def run(self, data: Iterable[DailyBar], strategy: Iterable[Order], config: BacktestConfig) -> BacktestResult:
        """strategy 是预生成订单序列，必须携带生成时点；本层不读取未来信号。"""
        cash = number(config.initial_cash)
        if cash < 0 or not config.approximate_mode or number(config.slippage) != 0:
            raise ValueError("仅支持显式近似模式和零滑点；初始现金须非负")
        if config.lot_size <= 0 or number(config.fee_rate) < 0 or number(config.min_fee) < 0:
            raise ValueError("费用及整手参数无效")
        bars: dict[tuple[date, str], DailyBar] = {}
        for bar in data:
            key = (bar.trade_date, bar.ts_code)
            if key in bars:
                raise ValueError(f"日 K 重复: {key}")
            bars[key] = bar
        dates = sorted({day for day, _ in bars})
        orders: dict[tuple[date, str], list[Order]] = {}
        seen: set[str] = set()
        for order in strategy:
            if order.order_id in seen:
                raise ValueError(f"委托编号重复: {order.order_id}")
            seen.add(order.order_id)
            orders.setdefault((order.trade_date, order.phase), []).append(order)
        if any(day not in dates for day, _ in orders):
            raise ValueError("订单日期必须位于提供的真实日 K 日期轴；不能补造日期")
        result = BacktestResult(config=config)
        positions: dict[str, Position] = {}
        # 现金余额含本阶段卖出所得；available 不包含本阶段待释放部分。
        for day in dates:
            for pos in positions.values():
                pos.sellable_qty += pos.today_bought_qty
                pos.today_bought_qty = 0
            for phase in PHASES:
                available = cash
                deferred = Decimal("0")
                phase_orders = orders.get((day, phase), [])
                # 固定同阶段先卖后买；现金仍延迟释放，不根据结果改变计划顺序。
                phase_orders = sorted(phase_orders, key=lambda order: 0 if order.side == "SELL" else 1)
                for order in phase_orders:
                    pos = positions.get(order.ts_code, Position())
                    ctx = ExecutionContext(available_cash=available, sellable_qty=pos.sellable_qty,
                                           fee_rate=config.fee_rate, min_fee=config.min_fee,
                                           slippage=config.slippage, approximate_mode=config.approximate_mode,
                                           lot_size=config.lot_size)
                    receipt = self.broker.execute(order, bars.get((day, order.ts_code)), ctx)
                    result.orders.append({"date": day, "phase": phase, "order": order, "result": receipt,
                                          "plan_id": order.plan_id})
                    if order.plan_id is not None:
                        result.plans.append({"plan_id": order.plan_id, "order_id": order.order_id,
                                             "generated_date": order.generated_date, "status": receipt.status})
                    if receipt.status == "FILLED":
                        value = money(receipt.fill_price * receipt.filled_qty)
                        if order.side == "BUY":
                            deduction = value + receipt.fees
                            cash -= deduction
                            available -= deduction
                            pos.quantity += receipt.filled_qty
                            pos.today_bought_qty += receipt.filled_qty
                            pos.last_price = receipt.fill_price
                            pos.valuation_date = day
                            positions[order.ts_code] = pos
                        else:
                            proceeds = value - receipt.fees
                            cash += proceeds
                            deferred += proceeds
                            pos.quantity -= receipt.filled_qty
                            pos.sellable_qty -= receipt.filled_qty
                            if not pos.quantity:
                                del positions[order.ts_code]
                        result.fills.append({"date": day, "phase": phase, "order_id": order.order_id,
                                             "ts_code": order.ts_code, "side": order.side,
                                             "quantity": receipt.filled_qty, "price": receipt.fill_price,
                                             "amount": value, "fee": receipt.fees,
                                             "flags": receipt.assumption_flags})
                    if cash < 0 or available < 0 or any(p.sellable_qty < 0 or p.quantity != p.sellable_qty + p.today_bought_qty for p in positions.values()):
                        raise AssertionError("账户现金或数量守恒失败")
                    self._snapshot(result, day, phase, cash, available, deferred, positions, order.order_id)
                self._snapshot(result, day, phase, cash, cash, Decimal("0"), positions, "PHASE_END")
            total_value = Decimal("0")
            stale = 0
            for code, pos in positions.items():
                bar = bars.get((day, code))
                if bar is not None:
                    try:
                        closing = number(bar.close)
                        if closing > 0:
                            pos.last_price = closing
                            pos.valuation_date = day
                    except ValueError:
                        pass
                if pos.last_price is None:
                    raise ValueError(f"缺少可用估值价: {day} {code}")
                is_stale = pos.valuation_date != day
                stale += int(is_stale)
                if is_stale and config.max_stale_days is not None and (day - pos.valuation_date).days > config.max_stale_days:
                    raise ValueError(f"估值价超过允许的陈旧期: {day} {code}")
                total_value += pos.quantity * pos.last_price
                result.position_snapshots.append({"date": day, "phase": "EOD", "ts_code": code,
                                                  "quantity": pos.quantity, "sellable_qty": pos.sellable_qty,
                                                  "today_bought_qty": pos.today_bought_qty,
                                                  "valuation_price": pos.last_price, "stale_price": is_stale})
            if stale:
                result.warnings.append(f"{day}: {stale} 个持仓使用陈旧估值")
            result.daily_nav.append({"date": day, "cash": cash, "market_value": total_value,
                                     "total": cash + total_value, "stale_positions": stale,
                                     "approximate": True})
        return result

    @staticmethod
    def _snapshot(result: BacktestResult, day: date, phase: str, cash: Decimal, available: Decimal,
                  deferred: Decimal, positions: dict[str, Position], after: str) -> None:
        result.account_snapshots.append({"date": day, "phase": phase, "sequence": len(result.account_snapshots),
                                         "after": after, "cash_total": cash, "available_cash": available,
                                         "deferred_cash": deferred})
        for code, pos in positions.items():
            result.position_snapshots.append({"date": day, "phase": phase, "sequence": len(result.account_snapshots) - 1,
                                              "after": after, "ts_code": code, "quantity": pos.quantity,
                                              "sellable_qty": pos.sellable_qty, "today_bought_qty": pos.today_bought_qty})
