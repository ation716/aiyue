"""抓取指数日线，并写入精简的 MySQL 指数日线表。"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
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

INDEX_TABLE = "index_daily_kline"
DEFAULT_INDEX = "000001.SH"
DEFAULT_INDICES = ["000001.SH", "399106.SZ", "399006.SZ", "000680.SH"] # 上证指数 `000001.SH`、科创综指 `000680.SH`、创业板指 `399006.SZ`、深证综指 `399106.SZ`
DEFAULT_START_DATE = "20250101"
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")

# 注意 科创综指是 2025年1月20日 开始创建的，过早会没有数据 暂时找不到科创版数据

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


def _normalize_symbol(code: str) -> str:
    return normalize_ts_code(code).split(".", 1)[0]


def _normalize_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 8:
        raise ValueError(f"Invalid date value: {value!r}")
    return dt.datetime.strptime(digits, "%Y%m%d").date()


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


def _clean_volume(value: Any) -> int | None:
    """两类采集源的 volume 均按股数处理；拒绝非整数/负值，避免静默改变单位或精度。"""
    number = _clean_number(value)
    if number is None:
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError(f"成交量必须为非负整数股：{value!r}")
    return int(number)


def _require_identifier(value: str, label: str) -> str:
    if not value or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Invalid MySQL {label}: {value!r}")
    return value


def _import_pymysql():
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("PyMySQL is not installed") from exc
    return pymysql


class IndexKlineStore:
    """Minimal storage implementation required by this entry script."""

    def __init__(self, config, table_name: str | None = None, tables: MySQLTables | None = None):
        self.config = config
        self.tables = tables or MySQLTables.from_env()
        self.table_name = _require_identifier(table_name or self.tables.index_daily_kline, "table name")

    @property
    def database(self) -> str:
        return _require_identifier(self.config.database, "database")

    def connect(self, database: str | None = None):
        pymysql = _import_pymysql()
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=database,
            charset=self.config.charset,
            connect_timeout=self.config.connect_timeout,
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def ensure_schema(self) -> None:
        """仅新建八列精简表；旧表不自动删列，避免隐式清除历史数据。"""
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
                    f"""
                    CREATE TABLE IF NOT EXISTS `{self.table_name}` (
                        symbol CHAR(6) NOT NULL COMMENT '指数六位代码，不含交易所后缀',
                        trade_date DATE NOT NULL COMMENT '交易日期，YYYY-MM-DD',
                        open DECIMAL(10,2) NULL COMMENT '开盘点位，指数点，保留两位小数',
                        high DECIMAL(10,2) NULL COMMENT '最高点位，指数点，保留两位小数',
                        low DECIMAL(10,2) NULL COMMENT '最低点位，指数点，保留两位小数',
                        close DECIMAL(10,2) NULL COMMENT '收盘点位，指数点，保留两位小数',
                        vol BIGINT UNSIGNED NULL COMMENT '成交量，股；采集源 volume 原值不换算为手',
                        amount DECIMAL(24,2) NULL COMMENT '成交额，元；akshare 备用源不提供时记 NULL',
                        UNIQUE KEY uk_symbol_date (symbol, trade_date),
                        KEY idx_trade_date (trade_date)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            conn.commit()
        finally:
            conn.close()

    def upsert_daily_kline(self, df: pd.DataFrame) -> int:
        """按精简表写入指数日线：vol 为股，amount 为元。"""
        if df is None or df.empty:
            return 0
        columns = (
            "symbol", "trade_date", "open", "high", "low", "close", "vol", "amount",
        )
        rows = []
        for _, item in df.iterrows():
            code = item.get("ts_code") or item.get("symbol") or item.get("code")
            raw_date = item.get("date") or item.get("trade_date")
            if not code or raw_date is None:
                continue
            try:
                trade_date = _normalize_date(raw_date)
            except ValueError:
                continue
            rows.append((
                _normalize_symbol(str(code)), trade_date,
                _clean_number(item.get("open")), _clean_number(item.get("high")),
                _clean_number(item.get("low")), _clean_number(item.get("close")),
                _clean_volume(item.get("volume") or item.get("vol")),
                _clean_number(item.get("amount")),
            ))
        if not rows:
            return 0
        placeholders = ", ".join(["%s"] * len(columns))
        sql = (
            f"INSERT INTO `{self.table_name}` ({', '.join(columns)}) "
            f"VALUES ({placeholders}) ON DUPLICATE KEY UPDATE "
            "open=VALUES(open), high=VALUES(high), low=VALUES(low), "
            "close=VALUES(close), vol=VALUES(vol), "
            "amount=COALESCE(VALUES(amount), amount)"
        )
        conn = self.connect(database=self.database)
        try:
            with conn.cursor() as cursor:
                cursor.executemany(sql, rows)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return len(rows)


def _fetch_index_source(fetcher, attempts: int = 3, retry_seconds: float = 1.0) -> pd.DataFrame:
    """带有限重试的外部指数源请求；失败后抛出最后一次错误。"""
    last_error = None
    for attempt in range(attempts):
        try:
            result = fetcher()
            if result is not None and not result.empty:
                return result
            last_error = RuntimeError("source returned empty data")
        except Exception as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(retry_seconds)
    if last_error is not None:
        raise last_error
    return pd.DataFrame()


def _date_chunks(start: dt.date, end: dt.date, days: int = 365):
    current = start
    while current <= end:
        chunk_end = min(current + dt.timedelta(days=days - 1), end)
        yield current, chunk_end
        current = chunk_end + dt.timedelta(days=1)


def _fetch_index_daily_em(ak, source_symbol: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """分段取得 EM 指数日线，避免长区间请求导致响应不完整或被源拒绝。"""
    frames = []
    for chunk_start, chunk_end in _date_chunks(start, end):
        frame = _fetch_index_source(
            lambda: ak.stock_zh_index_daily_em(
                symbol=source_symbol,
                start_date=chunk_start.strftime("%Y%m%d"),
                end_date=chunk_end.strftime("%Y%m%d"),
            )
        )
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True)
    if "date" in result.columns:
        result = result.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    return result.reset_index(drop=True)


def fetch_index_daily_akshare(index_code: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError:
        return pd.DataFrame()
    code6, _, suffix = index_code.partition(".")
    source_symbol = f"{suffix.lower()}{code6}"
    amount_from_source = True
    source_label = "EM"
    try:
        df = _fetch_index_daily_em(ak, source_symbol, start, end)
    except Exception as em_exc:
        source_label = "TX"
        try:
            df = _fetch_index_source(lambda: ak.stock_zh_index_daily_tx(
                symbol=source_symbol,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            ))
            # TX 只有 amount 字段；该值实测与 EM 的 volume 对齐，作为成交量使用。
            if "volume" not in df.columns and "amount" in df.columns:
                df["volume"] = df["amount"]
            df["amount"] = None
            amount_from_source = False
        except Exception as tx_exc:
            source_label = "SINA"
            try:
                df = _fetch_index_source(lambda: ak.stock_zh_index_daily(symbol=source_symbol))
                amount_from_source = False
            except Exception as exc:
                print(f"WARN: akshare 获取 {index_code} 失败(EM={em_exc}; TX={tx_exc}; Sina={exc})")
                return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    if "volume" not in df.columns and "成交量" in df.columns:
        df = df.rename(columns={"成交量": "volume", "成交额": "amount"})
    if "volume" not in df.columns:
        df["volume"] = None
    if not amount_from_source or "amount" not in df.columns:
        df["amount"] = None
    df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))].copy()
    if df.empty:
        return pd.DataFrame()
    # 入库字段仅保留 OHLC、成交量与成交额；不在采集器里计算衍生指标。
    out = pd.DataFrame({
        "symbol": _normalize_symbol(index_code), "date": df["date"].dt.strftime("%Y-%m-%d"),
        "open": df["open"], "high": df["high"], "low": df["low"],
        "close": df["close"], "vol": df["volume"], "amount": df["amount"],
    })
    out.attrs["source"] = source_label
    return out


def fetch_index_daily(index_code: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    try:
        import baostock as bs  # 包 stock 才有成交额，新浪财经没有
    except ImportError:
        return fetch_index_daily_akshare(index_code, start, end)

    login = bs.login()
    if getattr(login, "error_code", "0") != "0":
        return fetch_index_daily_akshare(index_code, start, end)
    try:
        code = normalize_ts_code(index_code)
        code6, suffix = code.split(".", 1)
        bs_code = f"{'sh' if suffix == 'SH' else 'sz'}.{code6}"
        rs = bs.query_history_k_data_plus(
            code=bs_code,
            fields="date,open,high,low,close,volume,amount,adjustflag",
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            frequency="d",
            adjustflag="3",
        )
        data = []
        while rs.next():
            data.append(rs.get_row_data())
        if not data:
            return fetch_index_daily_akshare(index_code, start, end)
        raw = pd.DataFrame(data, columns=rs.fields)
        for col in ("open", "high", "low", "close", "volume", "amount"):
            raw[col] = pd.to_numeric(raw[col], errors="coerce")
    finally:
        bs.logout()

    out = pd.DataFrame({
        "symbol": _normalize_symbol(code), "date": raw["date"],
        "open": raw["open"], "high": raw["high"], "low": raw["low"],
        "close": raw["close"], "vol": raw["volume"], "amount": raw["amount"],
    })
    out.attrs["source"] = "BAOSTOCK"
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="指数日 K 入库")
    parser.add_argument("--index", default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--user", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--ask-password", action="store_true")
    parser.add_argument("--database", default=None)
    return parser


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    return _normalize_date(value)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.all:
        indices = DEFAULT_INDICES
    elif args.index:
        indices = [normalize_ts_code(x) for x in str(args.index).replace("，", ",").split(",") if x.strip()]
    else:
        indices = DEFAULT_INDICES
    end = _parse_date(args.end_date) or dt.date.today()
    start = _parse_date(args.start_date) or (end - dt.timedelta(days=args.days))
    print(f"拉取指数 {', '.join(indices)} 日 K: {start} ~ {end}")
    password = getpass.getpass("MySQL password: ") if args.ask_password else args.password
    config = make_mysql_config(
        host=args.host, port=args.port, user=args.user,
        password=password, database=args.database,
    )
    store = IndexKlineStore(config=config)
    try:
        store.ensure_schema()
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    ok = True
    for index_code in indices:
        df = fetch_index_daily(index_code, start, end)
        if df.empty:
            print(f"WARN: {index_code} 无数据")
            ok = False
            continue
        if df.attrs.get("source") not in {"EM", "BAOSTOCK"}:
            print(f"WARN: {index_code} 未取得可靠成交额来源，未写入")
            ok = False
            continue
        if "amount" not in df.columns or df["amount"].isna().any():
            print(f"WARN: {index_code} 成交额缺失，未写入；请使用提供真实 amount 的数据源")
            ok = False
            continue
        if df["vol"].isna().any():
            print(f"WARN: {index_code} 成交量缺失，未写入")
            ok = False
            continue
        rows = store.upsert_daily_kline(df)
        print(f"{index_code}: 写入/更新 {rows} 行")
    print(f"完成: 写入表 {config.database}.{INDEX_TABLE}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
