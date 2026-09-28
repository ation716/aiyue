"""每日轮询回测入口：只读真实日线，配置从实验档案读取，产出隔离落盘。"""
import argparse
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STRAT = "daily"


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def configuration(experiment):
    if not re.fullmatch(r"E\d{2,}", experiment):
        raise ValueError("实验编号格式无效")
    text = (ROOT / "traces/backtest.md").read_text(encoding="utf-8")
    sections = re.findall(r"^#{2,3} (E\d+)\b[^\n]*\n(.*?)(?=^#{2,3} |\Z)", text, re.M | re.S)
    selected = [body for number, body in sections if number == experiment]
    if len(selected) != 1:
        raise ValueError("档案必须有且仅有一个对应实验节")
    snapshots = re.findall(r"```json\s*(.*?)\s*```", selected[0], re.S)
    if len(snapshots) != 1:
        raise ValueError("实验节必须有且仅有一个配置快照")
    cfg = json.loads(snapshots[0])
    if cfg.get("experiment") != experiment or cfg.get("strat") != STRAT:
        raise ValueError("配置与实验编号不一致")
    return cfg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default="E06")
    args = parser.parse_args()

    import numpy as np
    import pandas as pd

    from data.connectors.db_connector import DBConnector
    from scoring.strategies import strategy1
    from backtest.daily_loop import run_daily
    from backtest.result_store import save_result_files

    cfg = configuration(args.experiment)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    directory = ROOT / "results" / STRAT / args.experiment / run_id
    directory.mkdir(parents=True, exist_ok=False)
    dump(directory / "config.json", cfg)

    metadata = {"run_id": run_id, "created_at": datetime.now().isoformat(),
                "python_version": platform.python_version(), "pandas_version": pd.__version__,
                "numpy_version": np.__version__, "daily_table": cfg["daily_table"],
                "config_sha256": hashlib.sha256(
                    json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                "assumption": "近似演示模式；日K代理成交，不是净真实可实现回报"}
    stage = "static_validation"
    try:
        for name in ["backtest/broker.py", "backtest/trading.py", "backtest/daily_loop.py",
                     "portfolio/allocate.py", "scoring/strategies/strategy1/choose.py"]:
            ast.parse((ROOT / name).read_text(encoding="utf-8"), filename=name)

        frame = None
        stage = "connect"
        with DBConnector() as db:
            stage = "daily"
            frame = db.get_daily(start_date=cfg["start"], end_date=cfg["end"])
        if frame is None or frame.empty:
            raise ValueError("未取得真实日线，停止而不补造")

        stage = "data_validation"
        frame = frame.rename(columns={"symbol": "ts_code"})
        frame["ts_code"] = frame.ts_code.astype(str).str.zfill(6)
        for column in ["open", "high", "low", "close", "vol", "turnover_rate", "outstanding_share"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame.duplicated(["ts_code", "trade_date"]).any():
            raise ValueError("日线存在重复主键")
        board = frame.ts_code.str.match(r"^(?:000|001|002|003|600|601|603|605)\d{3}$")
        frame = frame.loc[board].copy()
        frame["float_mv"] = frame.close * frame.outstanding_share
        invalid = frame[["open", "high", "low", "close"]].isna().any(axis=1) | frame.close.le(0)
        frame = frame.loc[~invalid].copy()
        calendar = pd.DatetimeIndex(sorted(frame.trade_date.unique()))
        if len(calendar) <= cfg["warmup_days"]:
            raise ValueError("真实数据不足以覆盖预热")
        if str(calendar[0].date()) != cfg["start"] and str(calendar[0].date()) < cfg["start"]:
            raise ValueError("真实数据起始早于配置区间")
        frame = frame.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        metadata.update({"actual_start": str(calendar[0].date()), "actual_end": str(calendar[-1].date()),
                         "calendar_days": len(calendar), "rows": len(frame),
                         "symbols": int(frame.ts_code.nunique()),
                         "warmup_end": str(calendar[cfg["warmup_days"] - 1].date()),
                         "first_execution_day": str(calendar[cfg["warmup_days"]].date())})
        dump(directory / "metadata.json", metadata)

        stage = "daily_loop"
        result = run_daily(frame, calendar, strategy1, cfg)
        if not result["equity"]:
            raise ValueError("回测未产生任何账户记录")
        for name in ("trades", "equity", "final"):
            dump(directory / f"{name}.json", result[name])
        stored = save_result_files(result, directory)
        print(json.dumps({"status": "passed", "run_id": run_id, "trades": len(result["trades"]),
                          "days": len(result["equity"]), "final_total": result["final"]["total"],
                          "stored": stored}, ensure_ascii=True))
    except Exception as error:
        dump(directory / "metadata.json", metadata)
        dump(directory / "error.json", {"status": "blocked", "stage": stage, "error_type": type(error).__name__,
                                        "message": "真实读取或验证失败；未生成成功结果，无自动重试、无替代数据。"})
        print(json.dumps({"status": "blocked", "run_id": run_id, "stage": stage,
                          "error_type": type(error).__name__}, ensure_ascii=True))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
