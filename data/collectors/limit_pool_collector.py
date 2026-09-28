"""Collect daily pool data and rebuild the industry aggregation."""

from __future__ import annotations

import datetime as dt
import math
import os
import re
import sys
import time
from typing import Any

import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from mysql_config import MySQLTables, make_mysql_config


POOL_TYPES = {"zt": "涨停", "dt": "跌停", "zb": "炸板"}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")

TRADE_DATE = None
BACKFILL_TRADING_DAYS = 30
BACKFILL_DAYS = 0
SKIP_EXISTING = True
SLEEP_SECONDS = 0.5


def normalize_ts_code(code: str) -> str:
    raw = str(code or "").strip().upper()
    if "." in raw:
        code6, suffix = raw.split(".", 1)
        return f"{code6.zfill(6)}.{suffix}"
    code6 = raw.zfill(6)
    if code6.startswith(("60", "68", "90")):
        return f"{code6}.SH"
    if code6.startswith(("43", "83", "87", "88")):
        return f"{code6}.BJ"
    return f"{code6}.SZ"


def _require_identifier(value: str, label: str) -> str:
    if not value or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Invalid MySQL {label}: {value!r}")
    return value


def _clean_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).replace(",", "").replace("%", "").strip()
    if text in ("", "None", "nan", "NaN", "-"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _clean_int(value: Any) -> int | None:
    num = _clean_number(value)
    return int(num) if num is not None else None


def _clean_str(value: Any, max_len: int) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:max_len] if text and text.lower() not in ("nan", "none") else None


def _clean_time(value: Any) -> str | None:
    text = str(value).strip().replace(":", "") if value is not None else ""
    return text[:8] if text and text.lower() not in ("nan", "none") else None


def _import_pymysql():
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("PyMySQL is not installed") from exc
    return pymysql


class LimitPoolStore:
    def __init__(self, config=None, tables: MySQLTables | None = None):
        self.config = config or make_mysql_config()
        self.tables = tables or MySQLTables.from_env()
        self.pool_table = _require_identifier(self.tables.limit_pool_daily, "pool table")
        self.stat_table = _require_identifier(self.tables.industry_pool_stat, "industry stat table")

    @property
    def database(self) -> str:
        return _require_identifier(self.config.database, "database")

    def connect(self, database: str | None = None):
        pymysql = _import_pymysql()
        return pymysql.connect(
            host=self.config.host, port=self.config.port, user=self.config.user,
            password=self.config.password, database=database,
            charset=self.config.charset, connect_timeout=self.config.connect_timeout,
            autocommit=False, cursorclass=pymysql.cursors.DictCursor,
        )

    def ensure_schema(self) -> None:
        database = self.database
        server_conn = self.connect(database=None)
        try:
            with server_conn.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{database}` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
                )
            server_conn.commit()
        finally:
            server_conn.close()

        conn = self.connect(database=database)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""CREATE TABLE IF NOT EXISTS `{self.pool_table}` (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        pool_type VARCHAR(4) NOT NULL,
                        trade_date DATE NOT NULL,
                        ts_code VARCHAR(16) NOT NULL,
                        name VARCHAR(32) NULL,
                        industry VARCHAR(64) NULL,
                        pct_chg DECIMAL(10,4) NULL,
                        close DECIMAL(12,4) NULL,
                        limit_price DECIMAL(12,4) NULL,
                        turn DECIMAL(10,4) NULL,
                        amount DECIMAL(20,2) NULL,
                        float_mv DECIMAL(20,2) NULL,
                        total_mv DECIMAL(20,2) NULL,
                        limit_up_cnt INT NULL,
                        break_cnt INT NULL,
                        first_limit_time VARCHAR(8) NULL,
                        last_limit_time VARCHAR(8) NULL,
                        seal_money DECIMAL(20,2) NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY uk_type_date_code (pool_type, trade_date, ts_code),
                        KEY idx_trade_date (trade_date),
                        KEY idx_industry (industry)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cursor.execute(
                    f"""CREATE TABLE IF NOT EXISTS `{self.stat_table}` (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        trade_date DATE NOT NULL,
                        industry VARCHAR(64) NOT NULL,
                        zt_cnt INT NOT NULL DEFAULT 0,
                        dt_cnt INT NOT NULL DEFAULT 0,
                        zb_cnt INT NOT NULL DEFAULT 0,
                        zt_codes TEXT NULL,
                        dt_codes TEXT NULL,
                        zb_codes TEXT NULL,
                        strength INT NOT NULL DEFAULT 0,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY uk_date_industry (trade_date, industry),
                        KEY idx_trade_date (trade_date)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            conn.commit()
        finally:
            conn.close()

    def upsert_pool(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        columns = (
            "pool_type", "trade_date", "ts_code", "name", "industry", "pct_chg",
            "close", "limit_price", "turn", "amount", "float_mv", "total_mv",
            "limit_up_cnt", "break_cnt", "first_limit_time", "last_limit_time",
            "seal_money",
        )
        placeholders = ", ".join(["%s"] * len(columns))
        updates = ", ".join(f"{c}=VALUES({c})" for c in columns[3:])
        sql = (
            f"INSERT INTO `{self.pool_table}` ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {updates}, updated_at=CURRENT_TIMESTAMP"
        )
        values = [tuple(row.get(c) for c in columns) for row in rows]
        conn = self.connect(database=self.database)
        try:
            with conn.cursor() as cursor:
                cursor.executemany(sql, values)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return len(values)

    def get_existing_dates(self) -> set[dt.date]:
        conn = self.connect(database=self.database)
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT DISTINCT trade_date FROM `{self.pool_table}`")
                rows = cursor.fetchall()
        finally:
            conn.close()
        return {row["trade_date"] for row in rows}

    def rebuild_industry_stat(self, trade_date: dt.date) -> dict[str, int]:
        conn = self.connect(database=self.database)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT industry, pool_type, ts_code FROM `{self.pool_table}` "
                    "WHERE trade_date = %s AND industry IS NOT NULL",
                    (trade_date,),
                )
                rows = cursor.fetchall()
        finally:
            conn.close()

        stat: dict[str, dict[str, list[str]]] = {}
        for row in rows:
            industry = str(row["industry"])
            pool_type = str(row["pool_type"])
            bucket = stat.setdefault(industry, {"zt": [], "dt": [], "zb": []})
            if pool_type in bucket:
                bucket[pool_type].append(str(row["ts_code"]))
        values = []
        for industry, bucket in stat.items():
            codes = {key: ",".join(sorted(bucket[key])) or None for key in ("zt", "dt", "zb")}
            strength = 2 * len(bucket["zt"]) + len(bucket["zb"]) - 2 * len(bucket["dt"])
            values.append((
                trade_date, industry, len(bucket["zt"]), len(bucket["dt"]),
                len(bucket["zb"]), codes["zt"], codes["dt"], codes["zb"], strength,
            ))

        conn = self.connect(database=self.database)
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"DELETE FROM `{self.stat_table}` WHERE trade_date = %s", (trade_date,))
                if values:
                    cursor.executemany(
                        f"INSERT INTO `{self.stat_table}` "
                        "(trade_date, industry, zt_cnt, dt_cnt, zb_cnt, zt_codes, dt_codes, zb_codes, strength) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        values,
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {"industry_rows": len(values), "total_stocks": len(rows)}


def _parse_date(value) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return dt.datetime.strptime(digits, "%Y%m%d").date()


def _recent_trading_days(end: dt.date, n: int) -> list[dt.date]:
    import akshare as ak
    try:
        cal = ak.tool_trade_date_hist_sina()
        dates = sorted({_parse_date(value) for value in cal["trade_date"].tolist()})
        return [value for value in dates if value <= end][-n:]
    except Exception as exc:
        print(f"WARN: 交易日历获取失败({exc})，退回工作日估算")
        out = []
        cur = end
        while len(out) < n:
            if cur.weekday() < 5:
                out.append(cur)
            cur -= dt.timedelta(days=1)
        return list(reversed(out))


def _to_rows(df: pd.DataFrame, pool_type: str, trade_date: dt.date) -> list[dict]:
    if df is None or df.empty:
        return []
    rows = []
    for _, item in df.iterrows():
        code = str(item.get("代码", "")).strip()
        if not code:
            continue
        rows.append({
            "pool_type": pool_type, "trade_date": trade_date,
            "ts_code": normalize_ts_code(code), "name": _clean_str(item.get("名称"), 32),
            "industry": _clean_str(item.get("所属行业"), 64),
            "pct_chg": _clean_number(item.get("涨跌幅")), "close": _clean_number(item.get("最新价")),
            "limit_price": _clean_number(item.get("涨停价")), "turn": _clean_number(item.get("换手率")),
            "amount": _clean_number(item.get("成交额")), "float_mv": _clean_number(item.get("流通市值")),
            "total_mv": _clean_number(item.get("总市值")),
            "limit_up_cnt": _clean_int(item.get("连板数", item.get("连续跌停"))),
            "break_cnt": _clean_int(item.get("炸板次数", item.get("开板次数"))),
            "first_limit_time": _clean_time(item.get("首次封板时间")),
            "last_limit_time": _clean_time(item.get("最后封板时间")),
            "seal_money": _clean_number(item.get("封板资金", item.get("封单资金"))),
        })
    return rows


def fetch_all_pools(trade_date: dt.date) -> dict[str, list[dict]]:
    import akshare as ak
    date_str = trade_date.strftime("%Y%m%d")
    result = {}
    fetchers = {
        "zt": ("涨停池", lambda: ak.stock_zt_pool_em(date=date_str)),
        "dt": ("跌停池", lambda: ak.stock_zt_pool_dtgc_em(date=date_str)),
        "zb": ("炸板池", lambda: ak.stock_zt_pool_zbgc_em(date=date_str)),
    }
    for pool_type, (label, fetch) in fetchers.items():
        try:
            rows = _to_rows(fetch(), pool_type, trade_date)
            result[pool_type] = rows
            print(f"{label} {date_str}: {len(rows)} 条")
        except Exception as exc:
            print(f"WARN: {label} {date_str} 获取失败({exc})")
            result[pool_type] = []
        time.sleep(SLEEP_SECONDS)
    return result


def collect_one_day(store: LimitPoolStore, trade_date: dt.date) -> dict:
    pools = fetch_all_pools(trade_date)
    all_rows = pools["zt"] + pools["dt"] + pools["zb"]
    written = store.upsert_pool(all_rows) if all_rows else 0
    stat = store.rebuild_industry_stat(trade_date) if all_rows else {"industry_rows": 0, "total_stocks": 0}
    return {"date": trade_date, "zt": len(pools["zt"]), "dt": len(pools["dt"]),
            "zb": len(pools["zb"]), "written": written, **stat}


def main() -> int:
    store = LimitPoolStore()
    try:
        store.ensure_schema()
    except Exception as exc:
        print(f"ERROR: 建表失败 {exc}")
        return 1
    end = _parse_date(TRADE_DATE) or dt.date.today()
    if BACKFILL_TRADING_DAYS > 0:
        dates = _recent_trading_days(end, BACKFILL_TRADING_DAYS)
    elif BACKFILL_DAYS > 0:
        dates = sorted({end - dt.timedelta(days=i) for i in range(BACKFILL_DAYS)})
    else:
        dates = [end]
    if SKIP_EXISTING and dates:
        existing = store.get_existing_dates()
        missing = [value for value in dates if value not in existing]
        print(f"回补范围 {len(dates)} 天，已存在 {len(dates) - len(missing)} 天，待补 {len(missing)} 天")
        dates = missing
    print(f"开始采集三类池数据，共 {len(dates)} 个日期")
    for trade_date in dates:
        print(f"\n===== {trade_date} =====")
        result = collect_one_day(store, trade_date)
        print(f"写入 {result['written']} 行，行业统计 {result['industry_rows']} 个行业"
              f"（zt{result['zt']}/dt{result['dt']}/zb{result['zb']}）")
    print("\n完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
