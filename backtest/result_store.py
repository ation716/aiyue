"""Persist daily backtest results and render an equity chart."""
from __future__ import annotations

import csv
import json
from pathlib import Path


TRADE_FIELDS = [
    "date", "phase", "side", "symbol", "price", "vol", "quantity", "fee", "order_id", "flags"
]
ORDER_LOG_FIELDS = [
    "date", "phase", "submitted_orders", "fills", "rejects", "unexecuted_order",
    "money", "money_in_using"
]
EQUITY_FIELDS = [
    "date", "money", "money_in_using", "market_value", "total", "hold_count", "buys", "sells", "hold"
]


def _json_default(value):
    return str(value)


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            output = dict(row)
            if "flags" in output and isinstance(output["flags"], (list, tuple)):
                output["flags"] = json.dumps(output["flags"], ensure_ascii=False)
            if "hold" in output and isinstance(output["hold"], dict):
                output["hold"] = json.dumps(output["hold"], ensure_ascii=False, sort_keys=True)
            for field in ("submitted_orders", "fills", "rejects", "unexecuted_order"):
                if field in output and isinstance(output[field], (list, dict)):
                    output[field] = json.dumps(output[field], ensure_ascii=False, default=_json_default, sort_keys=True)
            writer.writerow({field: output.get(field, "") for field in fields})


def save_result_files(result: dict, directory: str | Path) -> dict[str, str]:
    """Save machine-readable CSV/JSON files and a Matplotlib equity chart.

    The input must be the result returned by ``run_daily``. No data is created;
    the chart is rendered only from the supplied trades/equity rows.
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    trades = list(result.get("trades", []))
    equity = list(result.get("equity", []))

    trade_path = target / "trades.csv"
    order_log_path = target / "order_log.csv"
    order_log_json_path = target / "order_log.json"
    equity_path = target / "equity.csv"
    final_path = target / "final.json"
    chart_path = target / "equity_curve.png"

    order_log = list(result.get("order_log", []))
    _write_csv(trade_path, trades, TRADE_FIELDS)
    _write_csv(order_log_path, order_log, ORDER_LOG_FIELDS)
    order_log_json_path.write_text(
        json.dumps(order_log, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8"
    )
    _write_csv(equity_path, equity, EQUITY_FIELDS)
    final_path.write_text(
        json.dumps(result.get("final"), ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    plot_equity(equity, chart_path)
    return {
        "trades_csv": str(trade_path),
        "order_log_csv": str(order_log_path),
        "order_log_json": str(order_log_json_path),
        "equity_csv": str(equity_path),
        "final_json": str(final_path),
        "equity_chart": str(chart_path),
    }


def plot_equity(equity: list[dict], destination: str | Path) -> None:
    """Render total value, cumulative return, cash/market value and drawdown."""
    if not equity:
        raise ValueError("equity 不能为空，无法绘图")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from datetime import datetime

    dates = [datetime.fromisoformat(str(row["date"]).replace("Z", "+00:00")) for row in equity]
    totals = [float(row["total"]) for row in equity]
    cash = [float(row["money"]) for row in equity]
    market = [float(row["market_value"]) for row in equity]
    initial = totals[0]
    returns = [(value / initial - 1.0) * 100.0 for value in totals]
    peaks = []
    peak = totals[0]
    for value in totals:
        peak = max(peak, value)
        peaks.append(peak)
    drawdown = [(value / high - 1.0) * 100.0 if high else 0.0 for value, high in zip(totals, peaks)]

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    figure, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True, constrained_layout=True)
    figure.suptitle("Daily Backtest Equity Curve", fontsize=16)

    axes[0].plot(dates, totals, color="#c62828", linewidth=1.8, label="Total")
    axes[0].plot(dates, cash, color="#1565c0", linewidth=1.0, label="Cash")
    axes[0].plot(dates, market, color="#ef6c00", linewidth=1.0, label="Market value")
    axes[0].set_ylabel("Value")
    axes[0].grid(alpha=0.25)
    axes[0].legend(loc="best")

    axes[1].plot(dates, returns, color="#6a1b9a", linewidth=1.8)
    axes[1].axhline(0, color="#777", linewidth=0.8)
    axes[1].set_ylabel("Return (%)")
    axes[1].grid(alpha=0.25)

    axes[2].fill_between(dates, drawdown, 0, color="#2e7d32", alpha=0.35)
    axes[2].plot(dates, drawdown, color="#2e7d32", linewidth=1.2)
    axes[2].set_ylabel("Drawdown (%)")
    axes[2].grid(alpha=0.25)
    axes[2].xaxis.set_major_locator(mdates.AutoDateLocator())
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    figure.autofmt_xdate()

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=160, format="png")
    plt.close(figure)
