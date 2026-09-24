"""只读查询接口；直接运行可逐个调试。使用用户授权的本机默认连接配置，环境变量可覆盖。"""
import os
import re
from datetime import date
from decimal import Decimal
import pandas as pd
import pymysql


class DBConnector:
    DAILY = "stock_daily_kline_20220101_1314"
    COLUMNS = "ts_code,symbol,trade_date,open,high,low,close,change_amount,vol,amount,turnover_rate,outstanding_share,float_mv"

    def __init__(self, host=None, port=None, user=None, password=None, database=None):
        self.options = dict(host=host or os.getenv("DB_HOST", "127.0.0.1"),
                            port=int(port or os.getenv("DB_PORT", "3306")),
                            user=user or os.getenv("DB_USER", "root"),
                            password=password if password is not None else os.getenv("DB_PASSWORD", "root"),
                            database=database or os.getenv("DB_NAME", "security"),
                            charset="utf8mb4", connect_timeout=10, read_timeout=120)
        self.connection = None

    def connect(self):
        if self.connection is None or not self.connection.open:
            if self.options["password"] is None:
                raise ValueError("请设置 DB_PASSWORD 或传入 password")
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
        """返回长表日线，None 不限，[] 无对象；排除弃用的 pct_chg。"""
        clauses, params = self._dates(start_date, end_date)
        symbols = self._items(symbols)
        if symbols is not None:
            bare, full = [], []
            for symbol in symbols:
                symbol = symbol.upper()
                if re.fullmatch(r"\d{6}", symbol):
                    bare.append(symbol)
                elif re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", symbol):
                    full.append(symbol)
                else:
                    raise ValueError("代码应为六位数字或带 SH/SZ/BJ 后缀")
            clauses.append("(" + self._in("symbol", bare) + " OR " + self._in("ts_code", full) + ")")
            params.extend(bare + full)
        return self._query("SELECT " + self.COLUMNS + " FROM " + self.DAILY + self._where(clauses) + " ORDER BY ts_code,trade_date", params)

    def get_concept_members(self, concepts=None):
        """一个 DataFrame；同一对象的不同概念关系分别保留。"""
        names = self._items(concepts)
        clauses = [] if names is None else [self._in("concept_name", names)]
        return self._query("SELECT concept_name,ts_code,symbol,stock_name FROM stock_concept_mapping" + self._where(clauses) + " ORDER BY concept_name,ts_code", names or [])

    def get_concept_names(self):
        return self._query("SELECT DISTINCT concept_name FROM stock_concept_mapping ORDER BY concept_name")["concept_name"].tolist()

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
            df = self._query("SELECT m.concept_name," + columns + " FROM " + self.DAILY + " d JOIN stock_concept_mapping m ON d.ts_code=m.ts_code" + self._where(clauses) + " ORDER BY d.ts_code,d.trade_date", [name] + params)
            df.attrs["concept_name"] = name
            result.append(df)
        return result

    def get_events(self, event_types=None, start_date=None, end_date=None):
        """默认返回 zt、dt、zb 三张表；百分数值原样返回。"""
        kinds = self._items(event_types)
        if kinds is None:
            kinds = ["zt", "dt", "zb"]
        if any(k not in {"zt", "dt", "zb"} for k in kinds):
            raise ValueError("类型仅支持 zt/dt/zb")
        clauses, params = self._dates(start_date, end_date)
        result = []
        for kind in kinds:
            df = self._query("SELECT * FROM limit_pool_daily" + self._where(["pool_type=%s"] + clauses) + " ORDER BY trade_date,ts_code", [kind] + params)
            df.attrs["pool_type"] = kind
            result.append(df)
        return result

    def get_daily_market_counts(self, start_date, end_date):
        """每日两时点事后统计（MySQL 8+），不是开盘可用信号。

        仅统计主板代码前缀，vol/amount 正值仅作活跃记录过滤。
        参考价为每个代码当前日期之前最近一条有效 close，不要求该代码存在于统一日历紧邻前日。
        prev_trade_date 可用于识别跨越缺失日期的复牌参考；不补造缺失日记录。
        不查询 limit_pool_daily；该表仅可在调试入口通过 res5 作为人工校验参考。
        当前日线字段没有名称，不能从主数据源可靠排除 ST/*ST。
        """
        if start_date is None or end_date is None:
            raise ValueError("必须提供起始和结束日期")
        _, params = self._dates(start_date, end_date)
        sql = f"""
        WITH dates AS (
            SELECT DISTINCT trade_date FROM {self.DAILY}
            WHERE trade_date <= %s
        ), calendar AS (
            SELECT trade_date, LAG(trade_date) OVER (ORDER BY trade_date) AS prev_date
            FROM dates
        ), active AS (
            SELECT d.ts_code, d.trade_date, d.open, d.close,
              p.close AS prev_close, p.trade_date AS prev_trade_date
            FROM {self.DAILY} d
            LEFT JOIN {self.DAILY} p
              ON p.ts_code=d.ts_code AND p.trade_date=(
                SELECT p0.trade_date FROM {self.DAILY} p0
                WHERE p0.ts_code=d.ts_code AND p0.trade_date<d.trade_date
                  AND p0.close>0
                ORDER BY p0.trade_date DESC LIMIT 1
              )
            WHERE d.trade_date BETWEEN %s AND %s
              AND d.vol>0 AND d.amount>0
              AND SUBSTRING_INDEX(d.ts_code, '.', 1) REGEXP '^(000|001|002|003|600|601|603|605)'
        ), direction_counts AS (
            SELECT trade_date, COUNT(DISTINCT ts_code) AS active_count,
              COUNT(DISTINCT CASE WHEN prev_close>0 AND open>0 AND open>prev_close THEN ts_code END) AS open_up,
              COUNT(DISTINCT CASE WHEN prev_close>0 AND open>0 AND open<prev_close THEN ts_code END) AS open_down,
              COUNT(DISTINCT CASE WHEN prev_close>0 AND close>0 AND close>prev_close THEN ts_code END) AS close_up,
              COUNT(DISTINCT CASE WHEN prev_close>0 AND close>0 AND close<prev_close THEN ts_code END) AS close_down,
              COUNT(DISTINCT CASE WHEN prev_close>0 AND open>0 THEN ts_code END) AS open_valid,
              COUNT(DISTINCT CASE WHEN prev_close>0 AND close>0 THEN ts_code END) AS close_valid,
              COUNT(DISTINCT CASE WHEN prev_close>0 AND open>0 AND open >= ROUND(prev_close * 1.10, 2) THEN ts_code END) AS open_limit_up,
              COUNT(DISTINCT CASE WHEN prev_close>0 AND open>0 AND open <= ROUND(prev_close * 0.90, 2) THEN ts_code END) AS open_limit_down,
              COUNT(DISTINCT CASE WHEN prev_close>0 AND close>0 AND close >= ROUND(prev_close * 1.10, 2) THEN ts_code END) AS close_limit_up,
              COUNT(DISTINCT CASE WHEN prev_close>0 AND close>0 AND close <= ROUND(prev_close * 0.90, 2) THEN ts_code END) AS close_limit_down
            FROM active GROUP BY trade_date
        )
        SELECT c.trade_date, COALESCE(d.active_count,0) AS active_count,
          COALESCE(d.open_up,0) AS open_up, COALESCE(d.open_down,0) AS open_down,
          COALESCE(d.close_up,0) AS close_up, COALESCE(d.close_down,0) AS close_down,
          COALESCE(d.open_valid,0) AS open_valid, COALESCE(d.close_valid,0) AS close_valid,
          COALESCE(d.open_limit_up,0) AS open_limit_up, COALESCE(d.open_limit_down,0) AS open_limit_down,
          COALESCE(d.close_limit_up,0) AS close_limit_up, COALESCE(d.close_limit_down,0) AS close_limit_down
        FROM calendar c LEFT JOIN direction_counts d ON c.trade_date=d.trade_date
        WHERE c.trade_date BETWEEN %s AND %s ORDER BY c.trade_date
        """
        daily = self._query(sql, [params[1], params[0], params[1], params[0], params[1]])
        columns = ["trade_date", "snapshot", "up_count", "down_count", "limit_up_count",
                   "limit_down_count", "active_count", "direction_valid_count", "limit_count_status"]
        frames = []
        for snapshot in ("open", "close"):
            frame = daily[["trade_date", "active_count"]].copy()
            frame["snapshot"] = snapshot
            frame["up_count"] = daily[snapshot + "_up"]
            frame["down_count"] = daily[snapshot + "_down"]
            frame["direction_valid_count"] = daily[snapshot + "_valid"]
            frame["limit_up_count"] = daily[snapshot + "_limit_up"]
            frame["limit_down_count"] = daily[snapshot + "_limit_down"]
            frame["limit_count_status"] = "price_calculated_mainboard_only"
            frame["_order"] = 0 if snapshot == "open" else 1
            frames.append(frame)
        result = pd.concat(frames, ignore_index=True).sort_values(["trade_date", "_order"])
        result = result[columns].reset_index(drop=True)
        for col in columns[2:-1]:
            result[col] = result[col].astype("int64")
        result.attrs["usage"] = "事后统计；日终成交量额过滤不能用于开盘决策"
        result.attrs["calendar"] = "长表日期并集；非独立交易日历"
        result.attrs["limits"] = "开盘和收盘均按前收盘及主板10%限制比例计算；未查询日池"
        result.attrs["scope"] = "仅统计代码前缀000/001/002/003/600/601/603/605的主板对象；不单独识别ST/*ST"
        result.attrs["validation"] = "可用 res5 的 limit_pool_daily zt/dt 结果人工校验；接口本身不读取日池"
        return result

    def get_weekly(self, symbols=None, start_date=None, end_date=None):
        """自然周聚合，先截日期区间；换手率采用累计口径，非去重比例。"""
        columns = "ts_code,symbol,trade_date,open,high,low,close,vol,amount,turnover_rate".split(",")
        df = self.get_daily(symbols, start_date, end_date)
        if df.empty:
            return pd.DataFrame(columns=columns)
        df = df.sort_values(["ts_code", "trade_date"]).copy()
        df["week"] = df.trade_date.dt.to_period("W-SUN")
        def strict_sum(s):
            return s.sum(min_count=len(s))
        result = df.groupby(["ts_code", "week"], sort=True).agg(
            symbol=("symbol", lambda s: s.iloc[-1]),
            trade_date=("trade_date", "max"), open=("open", lambda s: s.iloc[0]),
            high=("high", lambda s: s.max(skipna=False)), low=("low", lambda s: s.min(skipna=False)),
            close=("close", lambda s: s.iloc[-1]), vol=("vol", strict_sum),
            amount=("amount", strict_sum), turnover_rate=("turnover_rate", strict_sum)
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
        # res1 = cn.get_daily('603221', '2026-07-23', '2026-08-23')
        # res2 = cn.get_concept_members(concept_test)
        res3 = cn.get_concept_names()
        # res4 = cn.get_concept_daily(concept_test, start, end)
        res5 = cn.get_events(event_types, start, end)
        # res6 = cn.get_weekly(symbol_test, start, end)
        # res7 = cn.get_daily_market_counts(start, end)  # 全部活跃对象，不受 symbol_test 限制
    # 在下面一行打断点，可查看 res1～res7；不打印、不执行对照测试。
    pass
