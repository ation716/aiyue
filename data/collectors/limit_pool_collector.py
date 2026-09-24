"""
本文件负责每日采集 A 股涨停/跌停/炸板数据（含行业信息）并入库 + 分行业统计。

数据源：akshare 东财三个池（自带「所属行业」字段）：
- 涨停池 ak.stock_zt_pool_em(date)
- 跌停池 ak.stock_zt_pool_dtgc_em(date)
- 炸板池 ak.stock_zt_pool_zbgc_em(date)

⚠️ 关键约束：三个接口都只能回溯最近约 30 个交易日，无法回补历史。因此本脚本应
每日运行一次做增量积累；首次运行可用 BACKFILL_DAYS 尝试回填最近 N 个交易日。

用法：改下面「采集配置」区，然后在 PyCharm 里直接 Run 本文件即可（无需命令行参数）。
"""

from __future__ import annotations

import datetime as dt
import os
import sys

import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
for _path in (CURRENT_DIR, ROOT_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from limit_pool_store import LimitPoolStore, normalize_ts_code

# ==================== 采集配置（直接改这里，PyCharm Run 即可） ====================
TRADE_DATE = None               # 采集结束日：None=今天；或 "2026-09-14"
BACKFILL_TRADING_DAYS = 30      # 批量回填最近 N 个交易日（>0 时从 TRADE_DATE 往前补 N 个交易日；受数据源 ~30 天约束）
BACKFILL_DAYS = 0               # 兼容旧逻辑：按自然日回填（0=关闭）。BACKFILL_TRADING_DAYS 优先于本项
SKIP_EXISTING = True            # 跳过数据库里已存在的日期，做幂等缺口补齐（重跑不重复拉取）
SLEEP_SECONDS = 0.5             # 每次接口调用后的等待秒数（避免触发限频）
# ==================================================================================


def _parse_date(value) -> dt.date:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return dt.datetime.strptime(digits, "%Y%m%d").date()


def _recent_trading_days(end: dt.date, n: int) -> list[dt.date]:
    """
    返回 end 及之前的最近 n 个交易日（含 end，若 end 非交易日则取之前最近的一个）。

    优先用 akshare 官方交易日历；若日历获取失败，退回「周一至周五」估算。
    """
    import akshare as ak

    try:
        cal = ak.tool_trade_date_hist_sina()
        raw = cal["trade_date"].tolist()
        dates: list[dt.date] = []
        for d in raw:
            if isinstance(d, dt.datetime):
                dates.append(d.date())
            elif isinstance(d, dt.date):
                dates.append(d)
            else:
                dates.append(_parse_date(d))
        dates = sorted(set(dates))
        candidates = [d for d in dates if d <= end]
        return candidates[-n:]
    except Exception as exc:
        print(f"WARN: 交易日历获取失败({exc})，退回工作日(周一~周五)估算")
        out: list[dt.date] = []
        cur = end
        while len(out) < n:
            if cur.weekday() < 5:  # 0=周一 ... 4=周五
                out.append(cur)
            cur -= dt.timedelta(days=1)
        return list(reversed(out))


def _to_rows(df: pd.DataFrame, pool_type: str, trade_date: dt.date) -> list[dict]:
    """
    把 akshare 返回的 DataFrame 清洗成统一的行字典列表。

    三个池字段不完全一致，这里统一映射；没有的字段填 None。
    """
    if df is None or df.empty:
        return []
    rows: list[dict] = []
    for _, r in df.iterrows():
        code = str(r.get("代码", "")).strip()
        if not code:
            continue
        ts_code = normalize_ts_code(code)
        rows.append({
            "pool_type": pool_type,
            "trade_date": trade_date,
            "ts_code": ts_code,
            "name": _clean(r.get("名称")),
            "industry": _clean(r.get("所属行业")),
            "pct_chg": _num(r.get("涨跌幅")),
            "close": _num(r.get("最新价")),
            "limit_price": _num(r.get("涨停价")),
            "turn": _num(r.get("换手率")),
            "amount": _num(r.get("成交额")),
            "float_mv": _num(r.get("流通市值")),
            "total_mv": _num(r.get("总市值")),
            "limit_up_cnt": _int(r.get("连板数", r.get("连续跌停"))),
            "break_cnt": _int(r.get("炸板次数", r.get("开板次数"))),
            "first_limit_time": _time(r.get("首次封板时间")),
            "last_limit_time": _time(r.get("最后封板时间")),
            "seal_money": _num(r.get("封板资金", r.get("封单资金"))),
        })
    return rows


def _num(v):
    if v is None:
        return None
    try:
        import math
        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    s = str(v).replace(",", "").replace("%", "").strip()
    if s in ("", "None", "nan", "NaN", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None


def _clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return s[:64] if s and s.lower() not in ("nan", "none") else None


def _time(v):
    if v is None:
        return None
    s = str(v).strip().replace(":", "")
    return s[:8] if s and s.lower() not in ("nan", "none") else None


def fetch_all_pools(trade_date: dt.date) -> dict[str, list[dict]]:
    """拉取某日的涨停/跌停/炸板三池，返回 {pool_type: [rows]}。"""
    import akshare as ak
    date_str = trade_date.strftime("%Y%m%d")
    result: dict[str, list[dict]] = {}

    fetchers = {
        "zt": ("涨停池", lambda: ak.stock_zt_pool_em(date=date_str)),
        "dt": ("跌停池", lambda: ak.stock_zt_pool_dtgc_em(date=date_str)),
        "zb": ("炸板池", lambda: ak.stock_zt_pool_zbgc_em(date=date_str)),
    }
    for pool_type, (label, fetch) in fetchers.items():
        try:
            df = fetch()
            rows = _to_rows(df, pool_type, trade_date)
            result[pool_type] = rows
            print(f"{label} {date_str}: {len(rows)} 只")
        except Exception as exc:
            msg = str(exc)
            if "只能获取最近" in msg or "30" in msg:
                print(f"WARN: {label} {date_str} 超出回溯范围（{msg}）")
            else:
                print(f"WARN: {label} {date_str} 获取失败({exc})")
            result[pool_type] = []
        import time
        time.sleep(SLEEP_SECONDS)
    return result


def collect_one_day(store: LimitPoolStore, trade_date: dt.date) -> dict:
    """采集单日数据并入库 + 统计。"""
    pools = fetch_all_pools(trade_date)
    all_rows = pools["zt"] + pools["dt"] + pools["zb"]
    written = store.upsert_pool(all_rows) if all_rows else 0
    stat = store.rebuild_industry_stat(trade_date) if all_rows else {"industry_rows": 0, "total_stocks": 0}
    return {
        "date": trade_date,
        "zt": len(pools["zt"]),
        "dt": len(pools["dt"]),
        "zb": len(pools["zb"]),
        "written": written,
        **stat,
    }


def main() -> int:
    store = LimitPoolStore()
    try:
        store.ensure_schema()
    except Exception as exc:
        print(f"ERROR: 建表失败 {exc}")
        return 1

    end = _parse_date(TRADE_DATE) or dt.date.today()

    # 1) 决定需要采集的日期范围
    if BACKFILL_TRADING_DAYS > 0:
        dates = _recent_trading_days(end, BACKFILL_TRADING_DAYS)
    elif BACKFILL_DAYS > 0:
        # 兼容旧逻辑：按自然日回溯
        dates = sorted({end - dt.timedelta(days=i) for i in range(BACKFILL_DAYS)})
    else:
        dates = [end]

    # 2) 幂等缺口补齐：跳过库里已有的日期
    if SKIP_EXISTING and dates:
        existing = store.get_existing_dates()
        missing = [d for d in dates if d not in existing]
        print(f"回补范围 {len(dates)} 天，已存在 {len(dates) - len(missing)} 天，待补 {len(missing)} 天")
        dates = missing

    print(f"开始采集涨停/跌停/炸板数据，共 {len(dates)} 个日期")
    for trade_date in dates:
        print(f"\n===== {trade_date} =====")
        result = collect_one_day(store, trade_date)
        print(f"写入 {result['written']} 行，行业统计 {result['industry_rows']} 个行业"
              f"（涨停{result['zt']}/跌停{result['dt']}/炸板{result['zb']}）")

    print("\n完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
