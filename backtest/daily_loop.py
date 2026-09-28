"""每日轮询回测：选股 → 配仓 → 三阶段交易 → 账户更新。

流程（每个统一交易日一次）：
1. 检查可用现金与持股数，计算买入意愿；
2. 调用选股模块拿到 buy / sell；
3. 把 buy 交给配仓模块，得到每只对象的占比与手数；
4. 与 sell 合并成 pre_trade_order，按阶段调用交易接口；
5. 日终按当日收盘价估值，记录账户状态。

所有计算只使用当日及以前的数据；当日生成的信号在下一交易日才执行。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from backtest.broker import DailyBar, money, number
from backtest.trading import AccountState, TradeContext, execute, settle_day
from portfolio.allocate import allocation, buy_willingness

PHASES = ("OPEN", "INTRADAY", "CLOSE")
LOT = 100


def build_bar(row, prev_close, lot_size=LOT) -> DailyBar:
    return DailyBar(ts_code=row["ts_code"], trade_date=row["trade_date"], open=number(row["open"]),
                    high=number(row["high"]), low=number(row["low"]), close=number(row["close"]),
                    prev_close=prev_close, vol=number(row["vol"]) if row.get("vol") is not None else None,
                    rule_status="UNKNOWN")


def _append_trade_log(log_handle, message):
    """Write one human-readable event to the optional .log file."""
    if log_handle is None:
        return
    log_handle.write(message + "\n")
    log_handle.flush()


def _format_orders(orders):
    if not orders:
        return "[]"
    return json.dumps(orders, ensure_ascii=False, default=str, indent=2)


def run_daily(daily, calendar, strategy, config, log_path=None):
    """按统一日历逐日轮询。

    入参：
    - daily：真实长表日线，需含 ts_code、trade_date、open/high/low/close/vol、turnover_rate、size 字段
    - calendar：统一日期轴
    - strategy：模块对象，提供 choose(day, daily, calendar, params, account)
    - config：策略与账户参数
    """
    lot_size = int(config["lot_size"])
    account = AccountState(cash=number(config["initial_cash"]))
    log_handle = None
    if log_path is not None:
        log_file = Path(log_path)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_file.open("a", encoding="utf-8")
        _append_trade_log(log_handle, f"[{datetime.now().isoformat(timespec='seconds')}] RUN_START")
    by_day = {d: g for d, g in daily.groupby("trade_date")}
    closes, trades, equity, order_log = {}, [], [], []
    pending_orders = []          # 由上一交易日收盘信号生成的委托，当日执行
    signal_generated = None

    for index, day in enumerate(calendar):
        current = by_day.get(day)
        if current is None:
            continue
        prev_day = calendar[index - 1] if index else None
        prev_rows = by_day.get(prev_day)
        prev_close = ({} if prev_rows is None
                      else {r.ts_code: number(r.close) for r in prev_rows.itertuples() if r.close and r.close > 0})
        bars = {r.ts_code: build_bar({"ts_code": r.ts_code, "trade_date": day, "open": r.open,
                                      "high": r.high, "low": r.low, "close": r.close,
                                      "vol": getattr(r, "vol", None)}, prev_close.get(r.ts_code))
                for r in current.itertuples()}

        # 当日收盘价先用于产信号与估值口径的记录，成交仍只用日线代理规则。
        for r in current.itertuples():
            if r.close and r.close > 0:
                closes[r.ts_code] = number(r.close)

        # 前一日生成的委托在今日三阶段内执行。
        context = TradeContext(trade_date=day, bars=bars, prev_close=prev_close)
        phase_results = []
        for phase in PHASES:
            orders = pending_orders if phase == "OPEN" else []
            submitted = [dict(order) for order in orders]
            item = execute(orders, phase, context, account, config)
            item["date"] = str(day)
            phase_results.append(item)
            order_log.append({
                "date": str(day),
                "phase": phase,
                "submitted_orders": submitted,
                "fills": list(item["fills"]),
                "rejects": list(item["rejects"]),
                "unexecuted_order": item["account"]["unexecuted_order"],
                "money": item["account"]["money"],
                "money_in_using": item["account"]["money_in_using"],
            })
        settle_day(account)
        pending_orders = []

        # 阶段结束后按当日收盘价估值，再生成下一交易日的信号。
        market_value = account.market_value(closes)
        account_row = {
            "date": str(day), "money": str(money(account.cash)),
            "money_in_using": str(money(account.reserved)),
            "hold": account.snapshot("EOD")["hold"],
            "market_value": str(market_value),
            "total": str(money(account.cash_total + market_value)),
            "hold_count": len(account.hold), "buys": 0, "sells": 0,
        }
        day_fills = []
        for item in phase_results:
            account_row["buys"] += sum(1 for f in item["fills"] if f["side"] == "buy")
            account_row["sells"] += sum(1 for f in item["fills"] if f["side"] == "sell")
            for fill in item["fills"]:
                fill_row = dict(fill, date=str(day))
                trades.append(fill_row)
                day_fills.append(fill_row)
        equity.append(account_row)
        # 按需求：尾盘结束后，当天有成交时才写成交明细。
        if day_fills:
            _append_trade_log(
                log_handle,
                f"[{datetime.now().isoformat(timespec='seconds')}] TRADE_FILLED "
                f"trade_date={day} report_point=AFTER_CLOSE\n{_format_orders(day_fills)}",
            )

        if index + 1 >= len(calendar):
            break
        # 选股与配仓：用截至今日的数据，产出交给下一交易日执行。
        snapshot = {"hold": account.hold, "money": str(money(account.cash)),
                    "market_value": str(market_value), "total": str(money(account.cash_total + market_value))}
        params = dict(config, close_price=dict(closes),
                      held_days={s: index - (r.get("entry_index") or index) for s, r in account.hold.items()})
        buy, sell = strategy.choose(day, daily[daily.trade_date <= day], calendar, params, snapshot)
        next_day = calendar[index + 1]
        next_rows = by_day.get(next_day)
        valid = set() if next_rows is None else set(next_rows.ts_code)
        planned_orders = []
        if buy:
            plan, _info = allocation(buy, snapshot, config)
            for symbol, detail in plan.items():
                if symbol in valid:
                    planned_orders.append({"order_id": f"{day:%Y%m%d}-{symbol}-B", "symbol": symbol,
                                           "side": "buy", "price": detail["buy"], "vol": detail["vol"],
                                           "generated_date": day, "entry_index": index + 1})
        for symbol, detail in sell.items():
            if symbol in valid:
                planned_orders.append({"order_id": f"{day:%Y%m%d}-{symbol}-S", "symbol": symbol,
                                       "side": "sell", "price": detail["sell"], "vol": detail["vol"],
                                       "generated_date": day})
        pending_orders.extend(planned_orders)
        if planned_orders:
            _append_trade_log(
                log_handle,
                f"[{datetime.now().isoformat(timespec='seconds')}] ORDER_PLANNED "
                f"trade_date={day} execute_date={next_day}\n{_format_orders(planned_orders)}",
            )

    if log_handle is not None:
        _append_trade_log(log_handle, f"[{datetime.now().isoformat(timespec='seconds')}] RUN_END")
        log_handle.close()

    return {"trades": trades, "equity": equity, "order_log": order_log,
            "final": equity[-1] if equity else None}
