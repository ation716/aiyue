"""每日轮询回测入口：只读真实日线，配置从实验档案读取，产出隔离落盘。"""
import argparse
import ast
from datetime import datetime
import hashlib
import importlib
import json
from pathlib import Path
import platform
import re
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STRAT = "daily"
# PyCharm 右键直接运行时使用这个实验；切换实验只需修改这一行。
DEFAULT_EXPERIMENT = "E11"


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def configuration(experiment):
    if not re.fullmatch(r"E\d{2,}", experiment):
        raise ValueError("实验编号格式无效")

    # 正式运行配置放在 experiments/<EXP_ID>/config.json，便于 PyCharm 直接调试。
    config_path = ROOT / "experiments" / experiment / "config.json"
    if config_path.is_file():
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        # 兼容尚未迁移的旧实验：从追溯档案读取配置快照。
        text = (ROOT / "traces/backtest.md").read_text(encoding="utf-8")
        sections = re.findall(r"^#{2,3} (E\d+)\b[^\n]*\n(.*?)(?=^#{2,3} |\Z)", text, re.M | re.S)
        selected = [body for number, body in sections if number == experiment]
        if len(selected) != 1:
            raise ValueError("实验配置文件不存在，且追溯档案必须有且仅有一个对应实验节")
        snapshots = re.findall(r"```json\s*(.*?)\s*```", selected[0], re.S)
        if len(snapshots) != 1:
            raise ValueError("实验节必须有且仅有一个配置快照")
        cfg = json.loads(snapshots[0])

    if cfg.get("experiment") != experiment or cfg.get("strat") != STRAT:
        raise ValueError("配置与实验编号不一致")
    return cfg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default=DEFAULT_EXPERIMENT)
    args = parser.parse_args()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    directory = ROOT / "results" / STRAT / args.experiment / run_id
    directory.mkdir(parents=True, exist_ok=False)
    stage = "startup"
    metadata = {"run_id": run_id, "created_at": datetime.now().isoformat(),
                "experiment": args.experiment, "root": str(ROOT)}
    print(json.dumps({"status": "started", "run_id": run_id, "stage": stage,
                      "directory": str(directory)}, ensure_ascii=True), flush=True)
    try:
        stage = "imports"
        import numpy as np
        import pandas as pd

        from data.connectors.db_connector import DBConnector
        from backtest.daily_loop import run_daily
        from backtest.result_store import save_result_files

        stage = "configuration"
        cfg = configuration(args.experiment)
        strategy_module_name = cfg.get("strategy_module", "scoring.strategies.strategy1")
        strategy = importlib.import_module(strategy_module_name)
        if not hasattr(strategy, "choose"):
            raise ValueError(f"策略模块缺少 choose：{strategy_module_name}")
        dump(directory / "config.json", cfg)
        metadata.update({"python_version": platform.python_version(),
                         "pandas_version": pd.__version__, "numpy_version": np.__version__,
                         "daily_table": cfg["daily_table"],
                         "config_sha256": hashlib.sha256(
                             json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                         "assumption": "近似演示模式；日K代理成交，不是净真实可实现回报"})
        dump(directory / "metadata.json", metadata)
        print(json.dumps({"status": "started", "run_id": run_id, "stage": stage,
                          "directory": str(directory)}, ensure_ascii=True), flush=True)
        strategy_file = Path(strategy.__file__).resolve()
        for name in ["backtest/broker.py", "backtest/trading.py", "backtest/daily_loop.py",
                     "portfolio/allocate.py", str(strategy_file.relative_to(ROOT))]:
            ast.parse((ROOT / name).read_text(encoding="utf-8"), filename=name)

        frame = None
        stage = "connect"
        print(json.dumps({"status": "running", "run_id": run_id, "stage": stage}, ensure_ascii=True), flush=True)
        # 实验节指定逻辑日线表；连接实例仍由 MYSQL_* 环境变量提供。
        with DBConnector(tables={"daily": cfg["daily_table"]}) as db:
            stage = "daily"
            print(json.dumps({"status": "running", "run_id": run_id, "stage": stage,
                              "table": db.tables.daily, "start": cfg["start"], "end": cfg["end"]},
                             ensure_ascii=True), flush=True)
            frame = db.get_daily(start_date=cfg["start"], end_date=cfg["end"])
            benchmark_frame = None
            if cfg.get("benchmark_enabled"):
                benchmark_frame = db.get_index_daily_close(
                    symbol=cfg.get("benchmark_symbol", "000001"),
                    start_date=cfg["start"],
                    end_date=cfg["end"],
                )
        if frame is None or frame.empty:
            raise ValueError("未取得真实日线，停止而不补造")
        print(json.dumps({"status": "running", "run_id": run_id, "stage": stage,
                          "rows": len(frame)}, ensure_ascii=True), flush=True)

        stage = "data_validation"
        print(json.dumps({"status": "running", "run_id": run_id, "stage": stage}, ensure_ascii=True), flush=True)
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
        print(json.dumps({"status": "running", "run_id": run_id, "stage": stage,
                          "rows": len(frame), "days": len(calendar),
                          "symbols": int(frame.ts_code.nunique())}, ensure_ascii=True), flush=True)
        log_path = ROOT / "logs" / f"{STRAT}_{args.experiment}_{run_id}.log"
        result = run_daily(frame, calendar, strategy, cfg, log_path=log_path,
                           benchmark_daily=benchmark_frame)
        if not result["equity"]:
            raise ValueError("回测未产生任何账户记录")
        for name in ("trades", "equity", "order_log", "final"):
            dump(directory / f"{name}.json", result[name])
        stored = save_result_files(result, directory)
        stored["trade_log"] = str(log_path)
        print(json.dumps({"status": "passed", "run_id": run_id, "trades": len(result["trades"]),
                          "days": len(result["equity"]), "final_total": result["final"]["total"],
                          "stored": stored}, ensure_ascii=True))
    except Exception as error:
        metadata.update({"failed_stage": stage, "error_type": type(error).__name__,
                         "error_detail": str(error)})
        dump(directory / "metadata.json", metadata)
        dump(directory / "error.json", {"status": "blocked", "stage": stage, "error_type": type(error).__name__,
                                        "error_detail": str(error),
                                        "traceback": traceback.format_exc(),
                                        "message": "真实读取或验证失败；未生成成功结果，无自动重试、无替代数据。"})
        print(json.dumps({"status": "blocked", "run_id": run_id, "stage": stage,
                          "error_type": type(error).__name__, "error_detail": str(error),
                          "directory": str(directory)}, ensure_ascii=True), flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
