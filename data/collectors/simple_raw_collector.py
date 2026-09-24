# -*- coding: utf-8 -*-
import datetime as dt
import time
import akshare as ak
import pandas as pd
import pymysql

# 导入现有的数据库配置读取方法
from mysql_config import make_mysql_config


def init_database_and_table(conn: pymysql.connections.Connection, db_name: str, table_name: str):
    """
    初始化数据库和数据表。只负责创建包含原始日线信息的表，不搞复杂的逻辑。

    参数:
        conn: pymysql 数据库连接对象
        db_name: 数据库名称
        table_name: 要创建的表名
    """
    with conn.cursor() as cursor:
        # 1. 创建数据库
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci")
    
    # 切换到目标数据库
    conn.select_db(db_name)

    # 2. 创建干净的数据表
    create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS `{table_name}` (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            ts_code VARCHAR(16) NOT NULL COMMENT '带有后缀的代码，如 000001.SZ',
            symbol VARCHAR(8) NOT NULL COMMENT '纯数字代码，如 000001',
            trade_date DATE NOT NULL COMMENT '交易日期',
            open DECIMAL(12,4) NULL COMMENT '开盘价',
            high DECIMAL(12,4) NULL COMMENT '最高价',
            low DECIMAL(12,4) NULL COMMENT '最低价',
            close DECIMAL(12,4) NULL COMMENT '收盘价',
            change_amount DECIMAL(12,4) NULL COMMENT '涨跌额',
            pct_chg DECIMAL(10,4) NULL COMMENT '涨跌幅百分比',
            vol DECIMAL(20,4) NULL COMMENT '成交量（手）',
            amount DECIMAL(20,4) NULL COMMENT '成交额（元）',
            turnover_rate DECIMAL(10,4) NULL COMMENT '换手率（百分比）',
            outstanding_share DECIMAL(20,2) NULL COMMENT '流通股本（股）',
            float_mv DECIMAL(26,4) NULL COMMENT '流通市值（元），估算值',
            UNIQUE KEY uk_code_date (ts_code, trade_date),
            KEY idx_trade_date (trade_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """
    with conn.cursor() as cursor:
        cursor.execute(create_table_sql)
        
        # 兼容处理：检查字段是否已存在，没有就加上
        cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
        existing_cols = {row[0] for row in cursor.fetchall()}
        for col_name, col_def in [
            ("outstanding_share", "DECIMAL(20,2) NULL"),
            ("float_mv", "DECIMAL(26,4) NULL")
        ]:
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE `{table_name}` ADD COLUMN `{col_name}` {col_def}")
    conn.commit()


def get_main_board_symbols() -> list[str]:
    """
    获取全市场所有的股票，并只筛选出 A股主板的股票。
    主板规则：沪市以 60 开头；深市以 000, 001, 002, 003 开头。

    返回:
        list[str]: 例如 ['600000', '000001', ...]
    """
    # 这个接口能一次性拿到 A股所有的 [代码, 名称]
    info_df = ak.stock_info_a_code_name()
    main_board_symbols = []

    for code in info_df["code"]:
        code_str = str(code).zfill(6)
        # 过滤主板
        if code_str.startswith("60") or code_str.startswith(("000", "001", "002", "003")):
            main_board_symbols.append(code_str)

    return sorted(list(set(main_board_symbols)))


def fetch_daily_kline(symbol: str, start_date: str, end_date: str, max_retries: int = 3) -> pd.DataFrame:
    """
    获取某一只股票的日线级别 K线数据（含换手率）。包含自动重试机制。

    参数:
        symbol: 六位纯数字股票代码，例如 '600000'
        start_date: 开始日期，格式 'YYYYMMDD'
        end_date: 结束日期，格式 'YYYYMMDD'
        max_retries: 失败时的最大重试次数
    
    返回:
        pd.DataFrame: 包含量价及换手率的原始数据。如果查不到数据则返回空 DataFrame。
    """
    for attempt in range(max_retries):
        try:
            # 使用 sina 数据源
            prefixed_symbol = f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}"
            df = ak.stock_zh_a_daily(
                symbol=prefixed_symbol,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"
            )
            return df
        except Exception as e:
            print(f"    [警告] 获取 {symbol} 失败 ({e})。正在进行第 {attempt + 1}/{max_retries} 次重试...")
            if attempt < max_retries - 1:
                # 如果是网络被远端强行断开，强制休息长一点的时间（3秒），再试效果更好
                time.sleep(3)
            else:
                print(f"    [错误] {symbol} 达到最大重试次数，放弃获取该股票。")
    return pd.DataFrame()


def batch_insert_klines(conn: pymysql.connections.Connection, table_name: str, symbol: str, df: pd.DataFrame):
    """
    将获取到的 DataFrame 批量插入到 MySQL 中。
    使用 ON DUPLICATE KEY UPDATE 语法，确保不会插入重复的日期数据。

    参数:
        conn: pymysql 数据库连接对象
        table_name: 目标表名
        symbol: 股票代码
        df: 通过 fetch_daily_kline 获取到的原始 dataframe
    """
    if df is None or df.empty:
        return

    # 生成带后缀的 ts_code (用于做唯一主键)
    ts_code = f"{symbol}.SH" if symbol.startswith("6") else f"{symbol}.SZ"

    # 将 dataframe 转为可以直接写库的 List[Tuple]
    records = []
    for _, row in df.iterrows():
        # ak.stock_zh_a_daily (新浪源) 返回的字段名为英文
        trade_date_raw = row.get("date")
        if not trade_date_raw:
            continue
        trade_date = pd.to_datetime(trade_date_raw).date()
        
        # 提取字段并转换为浮点数，遇到非数字（比如空导致提取为 None）将其设为 None 以便存入 MySQL 的 NULL
        def safe_float(val):
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        open_p = safe_float(row.get("open"))
        high_p = safe_float(row.get("high"))
        low_p = safe_float(row.get("low"))
        close_p = safe_float(row.get("close"))
        
        # Sina 接口原生可能不带涨跌幅，设为 None (后期可用 Pandas 补全)
        change_amount = None
        pct_chg = None
        
        vol = safe_float(row.get("volume"))
        amount = safe_float(row.get("amount"))
        turnover_rate = safe_float(row.get("turnover"))  # Sina接口的换手率列名通常为 turnover

        # 提取流通股本（单位：股）
        outstanding_share = safe_float(row.get("outstanding_share"))
        
        # 用当天的收盘价乘以流通股本，得出当天的流通市值
        float_mv = None
        if outstanding_share is not None and close_p is not None:
            float_mv = outstanding_share * close_p

        records.append((
            ts_code, symbol, trade_date, open_p, high_p, low_p, close_p,
            change_amount, pct_chg, vol, amount, turnover_rate,
            outstanding_share, float_mv
        ))

    if not records:
        return

    # 构建批量插入的 SQL 语句
    sql = f"""
        INSERT INTO `{table_name}` 
        (ts_code, symbol, trade_date, open, high, low, close, change_amount, pct_chg, vol, amount, turnover_rate, outstanding_share, float_mv)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE 
            open=VALUES(open), high=VALUES(high), low=VALUES(low), close=VALUES(close),
            change_amount=VALUES(change_amount), pct_chg=VALUES(pct_chg),
            vol=VALUES(vol), amount=VALUES(amount), turnover_rate=VALUES(turnover_rate),
            outstanding_share=VALUES(outstanding_share), float_mv=VALUES(float_mv)
    """

    with conn.cursor() as cursor:
        cursor.executemany(sql, records)
    conn.commit()


def run(start_date: str = "20230101", duration: int = 500, table_name: str = None, sleep_time: float = 0.3):
    """
    一键运行：收集主板所有股票的日线原始数据并入库。

    参数:
        start_date: 起始查询的日期，格式要求为 'YYYYMMDD'。例如 '20230101'。
        duration: 需要向后推多少个交易日。比如 500 代表拿从起始日期开始算约 500 天的数据。
        table_name: 写入的数据库表名。如果留空不传，将自动拼接为 `stock_daily_kline_{start_date}_{duration}`。
        sleep_time: 每次请求之间的间隔时间（秒）。默认 0.3 秒以防反爬。
    """
    # 1. 推算时间范围
    start_dt = dt.datetime.strptime(start_date, "%Y%m%d").date()
    # 按照 1 个交易日 ≈ 1.45 个自然日粗略折算时间跨度（多算5天作为缓冲）
    natural_days_to_add = int(duration * 1.5) + 5
    end_dt = start_dt + dt.timedelta(days=natural_days_to_add)
    end_date_str = end_dt.strftime("%Y%m%d")

    # 确定表名
    if not table_name:
        table_name = f"stock_daily_kline_{start_date}_{duration}"

    print(f"=== 启动极简入库程序 ===")
    print(f"查询起点: {start_date}")
    print(f"预计终点: {end_date_str} (基于 {duration} 交易日换算)")
    print(f"目标表名: {table_name}")

    # 2. 从已有配置文件建立数据库连接
    db_config = make_mysql_config()
    conn = pymysql.connect(
        host=db_config.host,
        port=db_config.port,
        user=db_config.user,
        password=db_config.password,
        database=None, # 先连全局，初始化建库后再切入
        charset="utf8mb4"
    )

    try:
        # 初始化表结构
        init_database_and_table(conn, db_config.database, table_name)
        print(f"表 {table_name} 构建完毕/已存在。")

        # 3. 抓取主板清单
        print("正在从 Akshare 拉取 A股主板清单...")
        symbols = get_main_board_symbols()
        total_stocks = len(symbols)
        print(f"成功筛选出主板股票共 {total_stocks} 只。开始入库...")

        # 4. 循环请求并插入
        for index, symbol in enumerate(symbols, 1):
            # 获取行情 dataframe
            df = fetch_daily_kline(symbol, start_date=start_date, end_date=end_date_str)
            
            # 插入数据库
            rows_inserted = len(df) if df is not None else 0
            batch_insert_klines(conn, table_name, symbol, df)
            
            print(f"[{index}/{total_stocks}] {symbol} 完毕，有效数据 {rows_inserted} 行")
            
            # 控制频率，防止东方财富接口封禁 IP
            time.sleep(sleep_time)

        print("=== 完美运行结束 ===")

    finally:
        # 不管中间出不出错，最后一定安全关闭连接
        conn.close()


if __name__ == "__main__":
    # 调用示例：只拉取从 2023年1月1日 往后的 500 个交易日数据
    # 它将自动建一张纯粹原始数据表: stock_daily_kline_20230101_500
    run(start_date="20220101", duration=1314)
