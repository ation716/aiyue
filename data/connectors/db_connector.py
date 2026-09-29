"""只读查询接口；直接运行可逐个调试。使用用户授权的本机默认连接配置，环境变量可覆盖。"""
import re
import sys
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import pandas as pd
import pymysql

try:
    from data.collectors.mysql_config import MySQLTables, make_mysql_config
except ModuleNotFoundError as exc:
    if exc.name not in {"data", "data.collectors"}:
        raise
    # 兼容直接执行本文件：python data/connectors/db_connector.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collectors"))
    from ..collectors.mysql_config import MySQLTables, make_mysql_config


class DBConnector:
    COLUMNS = "symbol,trade_date,open,high,low,close,vol,turnover_rate,outstanding_share"
    MARKET_STAT_COLUMNS = (
        "trade_date",
        "up_count",
        "down_count",
        "rescued_from_down_count",
        "down_limit_count",
        "up_limit_count",
        "up_break_count",
        "index_amount_total_yi",
    )
    INDEX_SYMBOLS = ("000001", "000680", "399006", "399106")
    MAIN_BOARD_SQL = "(symbol LIKE '60%%' OR symbol LIKE '000%%' OR symbol LIKE '001%%' OR symbol LIKE '002%%' OR symbol LIKE '003%%')"
    MAIN_BOARD_LIMIT_RATIO = Decimal("0.10")
    PRICE_TICK = Decimal("0.01")

    @property
    def DAILY(self):
        """兼容旧调用方的日线表访问方式；表名以实例配置为准。"""
        return self.tables.daily

    def __init__(self, host=None, port=None, user=None, password=None, database=None, tables=None):
        db_config = make_mysql_config(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
        )
        self.tables = MySQLTables(**tables) if isinstance(tables, dict) else (tables or MySQLTables.from_env())
        if not isinstance(self.tables, MySQLTables):
            raise TypeError("tables 必须是 MySQLTables 或包含对应字段的字典")
        self.options = dict(
            host=db_config.host,
            port=db_config.port,
            user=db_config.user,
            password=db_config.password,
            database=db_config.database,
            charset=db_config.charset,
            connect_timeout=db_config.connect_timeout,
            read_timeout=120,
        )
        self.connection = None

    def connect(self):
        if self.connection is None or not self.connection.open:
            if self.options["password"] is None:
                raise ValueError("请设置 MYSQL_PASSWORD 或传入 password")
            conn = pymysql.connect(**self.options)
            try:
                with conn.cursor() as cur:
                    cur.execute("SET SESSION TRANSACTION READ ONLY")
            except Exception:
                conn.close()
                raise
            self.connection = conn
        return self.connection

    def close(self):
        if self.connection is not None:
            conn = self.connection
            self.connection = None
            try:
                if conn.open:
                    conn.rollback()
            except (pymysql.MySQLError, OSError):
                pass
            finally:
                conn.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    @staticmethod
    def _items(values):
        if values is None:
            return None
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, (list, tuple)) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError("参数必须为字符串或字符串列表")
        return list(dict.fromkeys(v.strip() for v in values))

    @staticmethod
    def _dates(start, end, prefix=""):
        clauses, params = [], []
        parsed = []
        for value, op in ((start, ">="), (end, "<=")):
            if value is None:
                parsed.append(None)
                continue
            if isinstance(value, str):
                value = date.fromisoformat(value)
            if type(value) is not date:
                raise ValueError("日期须为 YYYY-MM-DD 或 datetime.date")
            parsed.append(value)
            clauses.append(prefix + "trade_date " + op + " %s")
            params.append(value)
        if all(parsed) and parsed[0] > parsed[1]:
            raise ValueError("起始日期晚于终止日期")
        return clauses, params

    @staticmethod
    def _where(clauses):
        return " WHERE " + " AND ".join(clauses) if clauses else ""

    @staticmethod
    def _in(column, values):
        return column + " IN (" + ",".join(["%s"] * len(values)) + ")" if values else "1=0"

    def _query(self, sql, params=()):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                df = pd.DataFrame.from_records(cur.fetchall(), columns=[c[0] for c in cur.description])
            for col in df.columns:
                if col == "trade_date":
                    df[col] = pd.to_datetime(df[col])
                elif any(isinstance(v, Decimal) for v in df[col].dropna().head(20)):
                    df[col] = pd.to_numeric(df[col])
            return df
        finally:
            try:
                if conn.open:
                    conn.rollback()
            except (pymysql.MySQLError, OSError):
                pass

    def get_daily(self, symbols=None, start_date=None, end_date=None):
        """返回长表日线，None 不限，[] 无对象；按六位 symbol 查询。"""
        clauses, params = self._dates(start_date, end_date)
        symbols = self._items(symbols)
        if symbols is not None:
            bare = []
            for symbol in symbols:
                symbol = symbol.upper()
                if re.fullmatch(r"\d{6}", symbol):
                    bare.append(symbol)
                elif re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", symbol):
                    bare.append(symbol.split(".", 1)[0])
                else:
                    raise ValueError("代码应为六位数字或带 SH/SZ/BJ 后缀")
            clauses.append(self._in("symbol", bare))
            params.extend(bare)
        return self._query("SELECT " + self.COLUMNS + " FROM " + self.DAILY + self._where(clauses) + " ORDER BY symbol,trade_date", params)

    def get_concept_members(self, concepts=None):
        """一个 DataFrame；同一对象的不同概念关系分别保留。"""
        names = self._items(concepts)
        clauses = [] if names is None else [self._in("concept_name", names)]
        return self._query("SELECT concept_name,symbol,stock_name FROM " + self.tables.concept_mapping + self._where(clauses) + " ORDER BY concept_name,symbol", names or [])

    def get_concept_names(self):
        return self._query("SELECT DISTINCT concept_name FROM " + self.tables.concept_mapping + " ORDER BY concept_name")["concept_name"].tolist()

    def get_concept_daily(self, concepts=None, start_date=None, end_date=None):
        """按概念返回列表，空表通过 attrs['concept_name'] 标识。"""
        self._dates(start_date, end_date)
        names = self._items(concepts)
        if names is None:
            names = self.get_concept_names()
        result = []
        for name in names:
            clauses, params = self._dates(start_date, end_date, "d.")
            clauses.insert(0, "m.concept_name=%s")
            columns = ",".join("d." + c for c in self.COLUMNS.split(","))
            df = self._query("SELECT m.concept_name," + columns + " FROM " + self.DAILY + " d JOIN " + self.tables.concept_mapping + " m ON d.symbol=m.symbol" + self._where(clauses) + " ORDER BY d.symbol,d.trade_date", [name] + params)
            df.attrs["concept_name"] = name
            result.append(df)
        return result

    def get_events(self, event_types=None, start_date=None, end_date=None):
        """异动统计 默认返回 zt、dt、zb 三张表；百分数值原样返回。"""
        kinds = self._items(event_types)
        if kinds is None:
            kinds = ["zt", "dt", "zb"]
        if any(k not in {"zt", "dt", "zb"} for k in kinds):
            raise ValueError("类型仅支持 zt/dt/zb")
        clauses, params = self._dates(start_date, end_date)
        result = []
        for kind in kinds:
            df = self._query("SELECT * FROM " + self.tables.limit_pool_daily + self._where(["pool_type=%s"] + clauses) + " ORDER BY trade_date,ts_code", [kind] + params)
            df.attrs["pool_type"] = kind
            result.append(df)
        return result

    def get_symbols_concept(self, symbols=None):
        """按六位 symbol 返回概念映射记录。"""
        symbols = self._items(symbols)
        clauses = [] if symbols is None else [self._in("symbol", symbols)]
        return self._query(
            "SELECT concept_name,symbol,stock_name FROM " + self.tables.concept_mapping
            + self._where(clauses) + " ORDER BY symbol,concept_name",
            symbols or [],
        )

    @staticmethod
    def _round_price_tick(value, tick=PRICE_TICK):
        """按价格最小单位四舍五入；统计口径为当前价格的近似比较。"""
        if value is None or pd.isna(value):
            return None
        value = Decimal(str(value))
        return (value / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick

    def _get_index_daily(self, start_date, end_date):
        clauses, params = self._dates(start_date, end_date)
        clauses.append(self._in("symbol", list(self.INDEX_SYMBOLS)))
        params.extend(self.INDEX_SYMBOLS)
        return self._query(
            "SELECT symbol,trade_date,vol,amount FROM "
            + self.tables.index_daily_kline
            + self._where(clauses)
            + " ORDER BY trade_date,symbol",
            params,
        )

    def get_index_daily_close(self, symbol="000001", start_date=None, end_date=None):
        """返回指定指数的日线收盘价，供相对表现退出规则使用。

        symbol 使用指数表中的六位代码，不带交易所后缀；返回 trade_date、symbol、close。
        该方法只读查询，不对缺失日期补值。
        """
        if start_date is None or end_date is None:
            raise ValueError("start_date 和 end_date 均不能为空")
        if not isinstance(symbol, str) or not re.fullmatch(r"\d{6}", symbol):
            raise ValueError("指数代码应为六位数字")
        clauses, params = self._dates(start_date, end_date)
        clauses.append("symbol=%s")
        params.append(symbol)
        return self._query(
            "SELECT symbol,trade_date,close FROM " + self.tables.index_daily_kline
            + self._where(clauses) + " ORDER BY trade_date",
            params,
        )

    def get_main_board_equal_weighted_change(self, start_date=None, end_date=None):
        """按日期返回主板对象等权平均涨幅。

        涨幅定义为 close / prev_close - 1，先按 symbol 取得前收，再按日期对有效对象
        做简单算术平均；不按成交量、流通规模或其他权重加权。返回值为小数比例，
        例如 0.012 表示 1.2%。区间第一天会向前读取数据以取得前收。
        """
        if start_date is None or end_date is None:
            raise ValueError("start_date 和 end_date 均不能为空")
        self._dates(start_date, end_date)
        start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
        end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
        previous_day = start - pd.Timedelta(days=7).to_pytimedelta()
        clauses, params = self._dates(previous_day, end)
        clauses.append(self.MAIN_BOARD_SQL)
        daily = self._query(
            "SELECT symbol,trade_date,close FROM " + self.DAILY
            + self._where(clauses) + " ORDER BY symbol,trade_date",
            params,
        )
        columns = ["trade_date", "main_board_equal_weighted_change"]
        if daily.empty:
            return pd.DataFrame(columns=columns)
        daily["trade_date"] = pd.to_datetime(daily["trade_date"])
        daily["prev_close"] = daily.groupby("symbol")["close"].shift(1)
        daily = daily[
            (daily["trade_date"].dt.date >= start)
            & (daily["trade_date"].dt.date <= end)
            & daily["prev_close"].notna()
            & daily["close"].notna()
            & (daily["prev_close"] != 0)
        ].copy()
        if daily.empty:
            return pd.DataFrame(columns=columns)
        daily["change"] = daily["close"] / daily["prev_close"] - 1
        return (
            daily.groupby(daily["trade_date"].dt.date, as_index=False)["change"]
            .mean()
            .rename(columns={"trade_date": "trade_date", "change": "main_board_equal_weighted_change"})
            .loc[:, columns]
        )

    def get_daily_market_statistics(self, start_date=None, end_date=None):
        """按日期返回主板价格统计及四个指数成交额汇总。

        上涨/下跌包含上下限对象；上下限和炸板/救回依据当前价格口径近似计算；
        特殊状态不单独排除。仅汇总指数 amount，按元换算为亿元；任一指数金额缺失则汇总金额为空。
        """
        if start_date is None or end_date is None:
            raise ValueError("start_date 和 end_date 均不能为空")
        self._dates(start_date, end_date)
        start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
        end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
        previous_day = start - pd.Timedelta(days=7).to_pytimedelta()
        daily_clauses, daily_params = self._dates(previous_day, end)
        daily_clauses.append(self.MAIN_BOARD_SQL)
        daily = self._query(
            "SELECT symbol,trade_date,high,low,close FROM "
            + self.DAILY
            + self._where(daily_clauses)
            + " ORDER BY symbol,trade_date",
            daily_params,
        )
        index_daily = self._get_index_daily(start, end)
        if daily.empty and index_daily.empty:
            return pd.DataFrame(columns=self.MARKET_STAT_COLUMNS)

        if not daily.empty:
            daily["trade_date"] = pd.to_datetime(daily["trade_date"])
            daily["prev_close"] = daily.groupby("symbol")["close"].shift(1)
            daily = daily[daily["trade_date"].dt.date >= start].copy()
            daily = daily[daily["prev_close"].notna()].copy()
            if not daily.empty:
                daily["up_limit_price"] = daily["prev_close"].map(
                    lambda value: self._round_price_tick(Decimal(str(value)) * (Decimal("1") + self.MAIN_BOARD_LIMIT_RATIO))
                )
                daily["down_limit_price"] = daily["prev_close"].map(
                    lambda value: self._round_price_tick(Decimal(str(value)) * (Decimal("1") - self.MAIN_BOARD_LIMIT_RATIO))
                )
                for column in ("high", "low", "close", "prev_close", "up_limit_price", "down_limit_price"):
                    daily[column] = pd.to_numeric(daily[column], errors="coerce")
                daily["is_up"] = daily["close"] > daily["prev_close"]
                daily["is_down"] = daily["close"] < daily["prev_close"]
                daily["is_down_limit"] = (daily["low"] <= daily["down_limit_price"]) & (daily["close"] <= daily["down_limit_price"])
                daily["is_rescued_from_down"] = (daily["low"] <= daily["down_limit_price"]) & (daily["close"] > daily["down_limit_price"])
                daily["is_up_limit"] = (daily["high"] >= daily["up_limit_price"]) & (daily["close"] >= daily["up_limit_price"])
                daily["is_up_break"] = (daily["high"] >= daily["up_limit_price"]) & (daily["close"] < daily["up_limit_price"])
                counts = daily.groupby(daily["trade_date"].dt.date).agg(
                    up_count=("is_up", "sum"),
                    down_count=("is_down", "sum"),
                    rescued_from_down_count=("is_rescued_from_down", "sum"),
                    down_limit_count=("is_down_limit", "sum"),
                    up_limit_count=("is_up_limit", "sum"),
                    up_break_count=("is_up_break", "sum"),
                ).reset_index(names="trade_date")
            else:
                counts = pd.DataFrame(columns=("trade_date", "up_count", "down_count", "rescued_from_down_count", "down_limit_count", "up_limit_count", "up_break_count"))
        else:
            counts = pd.DataFrame(columns=("trade_date", "up_count", "down_count", "rescued_from_down_count", "down_limit_count", "up_limit_count", "up_break_count"))

        if not index_daily.empty:
            index_daily["trade_date"] = pd.to_datetime(index_daily["trade_date"]).dt.date
            index_daily["amount"] = pd.to_numeric(index_daily["amount"], errors="coerce")
            index_summary = index_daily.groupby("trade_date", as_index=False).agg(
                index_amount_total=("amount", lambda series: series.sum(min_count=1)),
            )
            index_summary["index_amount_total_yi"] = index_summary["index_amount_total"] / 100000000
            index_summary = index_summary[["trade_date", "index_amount_total_yi"]]
        else:
            index_summary = pd.DataFrame(columns=("trade_date", "index_amount_total_yi"))

        result = counts.merge(index_summary, on="trade_date", how="left")
        count_columns = [
            "up_count", "down_count", "rescued_from_down_count",
            "down_limit_count", "up_limit_count", "up_break_count",
        ]
        for column in count_columns:
            if column not in result:
                result[column] = 0
            else:
                result[column] = result[column].fillna(0)
        if "index_amount_total_yi" not in result:
            result["index_amount_total_yi"] = pd.NA
        result = result[list(self.MARKET_STAT_COLUMNS)].sort_values("trade_date").reset_index(drop=True)
        count_columns = [
            "up_count", "down_count", "rescued_from_down_count",
            "down_limit_count", "up_limit_count", "up_break_count",
        ]
        for column in count_columns:
            result[column] = result[column].astype("Int64")
        return result

    def get_weekly(self, symbols=None, start_date=None, end_date=None):
        """自然周聚合；日线表没有 amount 时不虚构该列。"""
        columns = "symbol,trade_date,open,high,low,close,vol,turnover_rate".split(",")
        df = self.get_daily(symbols, start_date, end_date)
        if df.empty:
            return pd.DataFrame(columns=columns)
        df = df.sort_values(["symbol", "trade_date"]).copy()
        df["week"] = df.trade_date.dt.to_period("W-SUN")

        def strict_sum(series):
            return series.sum(min_count=len(series))

        result = df.groupby(["symbol", "week"], sort=True).agg(
            trade_date=("trade_date", "max"),
            open=("open", lambda s: s.iloc[0]),
            high=("high", lambda s: s.max(skipna=False)),
            low=("low", lambda s: s.min(skipna=False)),
            close=("close", lambda s: s.iloc[-1]),
            vol=("vol", strict_sum),
            turnover_rate=("turnover_rate", strict_sum),
        ).reset_index()
        return result[columns]


if __name__ == "__main__":
    # 六位代码或带后缀代码，字符串或列表；None 查询全部，[] 不选对象。
    symbol_test = ["000001.SZ"]
    # 日期包含两端；每日双时点统计要求起止日期均非 None。
    start = "2026-09-01"
    end = "2026-09-17"
    # 概念名称须与数据库一致；None 查询全部，[] 不选概念。
    concept_test = ["人工智能"]
    # zt 涨停、dt 跌停、zb 炸板；None 默认三类，[] 返回空列表。
    event_types = ["zt", "dt", "zb"]

    # 使用本机默认连接配置，环境变量可覆盖；退出 with 自动关闭连接。
    with DBConnector() as cn:
        # res1 = cn.get_daily("603221", "2026-08-21", "2026-08-24")
        # res2 = cn.get_concept_members(concept_test)
        # res3 = cn.get_concept_names()
        # res4 = cn.get_concept_daily(concept_test, start, end)
        # res5 = cn.get_events(event_types, start, end)
        # res6 = cn.get_weekly(symbol_test, start, end)
        # res7 = cn.get_daily_market_statistics(start_date=start, end_date=end)
        res7 = cn.get_main_board_equal_weighted_change(start_date=start, end_date=end)
    # 在下面一行打断点，可查看 res1～res6；不打印、不执行对照测试。
    pass
