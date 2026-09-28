"""日 K 近似撮合；只消费传入的真实行情，不访问数据库。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Literal

CENT = Decimal("0.01")
PHASES = ("OPEN", "INTRADAY", "CLOSE")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def number(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError("数值必须有限")
        return result
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("数值无效") from exc


@dataclass(frozen=True)
class DailyBar:
    ts_code: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    prev_close: Decimal | None
    vol: Decimal | None = None
    amount: Decimal | None = None
    rule_status: str = "UNKNOWN"  # 历史 ST/特殊状态不可从前复权价可靠推知


@dataclass(frozen=True)
class Order:
    order_id: str
    ts_code: str
    trade_date: date
    side: Literal["BUY", "SELL"]
    phase: Literal["OPEN", "INTRADAY", "CLOSE"]
    trigger_price: Decimal
    quantity: int
    generated_date: date
    earliest_phase: str = "OPEN"
    valid_until: date | None = None
    plan_id: str | None = None


@dataclass(frozen=True)
class ExecutionContext:
    available_cash: Decimal
    sellable_qty: int
    fee_rate: Decimal = Decimal("0.0001")
    min_fee: Decimal = Decimal("5")
    slippage: Decimal = Decimal("0")
    approximate_mode: bool = False
    lot_size: int = 100


@dataclass(frozen=True)
class ExecutionResult:
    order_id: str
    status: Literal["FILLED", "REJECTED", "EXPIRED"]
    filled_qty: int = 0
    fill_price: Decimal | None = None
    fees: Decimal = Decimal("0")
    reason_code: str | None = None
    assumption_flags: tuple[str, ...] = ()


def mock_trading(order: Order, bar: DailyBar | None, ctx: ExecutionContext) -> ExecutionResult:
    """整单触价代理；无盘中路径、队列或阶段成交量推断。"""
    def reject(reason: str, expired: bool = False) -> ExecutionResult:
        return ExecutionResult(order.order_id, "EXPIRED" if expired else "REJECTED", reason_code=reason)

    if not ctx.approximate_mode:
        return reject("APPROXIMATE_MODE_REQUIRED")
    try:
        slip = number(ctx.slippage)
    except ValueError:
        return reject("INVALID_ACCOUNT_OR_FEE")
    if slip != 0:
        return reject("SLIPPAGE_UNIT_UNCONFIRMED")
    if order.side not in ("BUY", "SELL") or order.phase not in PHASES:
        return reject("INVALID_ORDER")
    if order.earliest_phase not in PHASES or order.phase not in PHASES[PHASES.index(order.earliest_phase):]:
        return reject("SIGNAL_NOT_AVAILABLE")
    if order.generated_date >= order.trade_date:
        return reject("SIGNAL_NOT_AVAILABLE")  # 第一版只接收前一日期已生成的计划
    if order.valid_until is not None and order.valid_until != order.trade_date:
        return reject("INVALID_VALIDITY")  # 第一版只允许当日委托
    if bar is None:
        return reject("MISSING_BAR")
    if bar.trade_date != order.trade_date or bar.ts_code != order.ts_code:
        return reject("BAR_MISMATCH")
    try:
        o, h, l, c = (number(getattr(bar, field)) for field in ("open", "high", "low", "close"))
        prior = number(bar.prev_close)
        trigger = number(order.trigger_price)
        cash = number(ctx.available_cash)
        rate, minimum = number(ctx.fee_rate), number(ctx.min_fee)
    except ValueError:
        return reject("INVALID_BAR_OR_PARAMETER")
    if min(o, h, l, c, prior, trigger) <= 0 or l > h or not l <= o <= h or not l <= c <= h:
        return reject("INVALID_BAR_OR_PARAMETER")
    if cash < 0 or rate < 0 or minimum < 0 or ctx.sellable_qty < 0 or ctx.lot_size <= 0:
        return reject("INVALID_ACCOUNT_OR_FEE")
    if not isinstance(order.quantity, int) or isinstance(order.quantity, bool) or order.quantity <= 0:
        return reject("INVALID_QUANTITY")
    if order.side == "BUY" and order.quantity % ctx.lot_size:
        return reject("INVALID_LOT")
    if order.side == "SELL" and order.quantity > ctx.sellable_qty:
        return reject("T1_OR_INSUFFICIENT_POSITION")

    up = money(prior * Decimal("1.10"))
    down = money(prior * Decimal("0.90"))
    flags = ("APPROX_ADJUSTED_LIMIT", "FULL_FILL_ASSUMED", "RULE_STATUS_" + bar.rule_status)
    if order.side == "BUY" and trigger >= up:
        return reject("ORDER_AT_OR_ABOVE_UP_LIMIT")
    if order.side == "SELL" and trigger <= down:
        return reject("ORDER_AT_OR_BELOW_DOWN_LIMIT")
    if order.phase == "INTRADAY":
        if not l < trigger < h:
            return reject("NOT_TRIGGERED")
        # 收盘封在近似限制价时，日 K 无法确认队列；仍按用户确认的固定代理成交。
        px = trigger
        flags += ("INTRADAY_PATH_AND_QUEUE_UNKNOWN",)
    else:
        px = o if order.phase == "OPEN" else c
        if (order.side == "BUY" and px > trigger) or (order.side == "SELL" and px < trigger):
            return reject("NOT_TRIGGERED")
        flags += ("AUCTION_PRICE_PROXY",)
    if order.side == "BUY" and px >= up:
        return reject("UP_LIMIT_BLOCK")
    if order.side == "SELL" and px <= down:
        return reject("DOWN_LIMIT_BLOCK")
    fee = money(max(minimum, money(px * order.quantity) * rate))
    if order.side == "BUY" and money(px * order.quantity) + fee > cash:
        return reject("INSUFFICIENT_CASH")
    return ExecutionResult(order.order_id, "FILLED", order.quantity, px, fee, assumption_flags=flags)


class Broker:
    """无状态单笔撮合器；账户变更由时间推进层完成。"""

    def execute(self, order: Order, bar: DailyBar | None, context: ExecutionContext) -> ExecutionResult:
        return mock_trading(order, bar, context)
