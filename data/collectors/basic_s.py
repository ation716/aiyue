"""
本文件封装了股票、板块、资金流、涨停/跌停、实时行情和筹码分布等常用数据入口。

外层策略可以直接创建 `ChipDistributionAnalyzer` 后调用本类方法。
返回值尽量保持为 `pandas.DataFrame`，少量接口返回 `dict`、`list[dict]` 或原始对象。
"""

import json
import importlib
import os
import re
import time
from pathlib import Path

import tushare as ts
import akshare as ak
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from enum import Enum
try:
    import baostock as bs
except ImportError:  # pragma: no cover
    bs = None


class SecurityFileds(Enum):
    STOCK_CODE = "ts_code"
    TRADE_DATE = "trade_date"
    HISTORICAL_LOW = "his_low"
    HISTORICAL_HIGH = "his_high"
    COST_5TH_PERCENTILE = "cost_5pct"
    COST_15TH_PERCENTILE = "cost_15pct"
    COST_50TH_PERCENTILE = "cost_50pct"
    COST_85TH_PERCENTILE = "cost_85pct"
    COST_95TH_PERCENTILE = "cost_95pct"
    WEIGHTED_AVERAGE_COST = "weight_avg"
    WIN_RATE = "winner_rate"
    TURNOVER_RATE = '换手率'
    OPEN = 'open'
    CLOSE = 'close'
    HIGH = 'high'
    LOW = 'low'
    VOLUME = 'vol'   # 单位手
    AMOUNT = 'amount'  # 单位千元
    CHANGE = 'change'
    PCT_CHG = 'pct_chg'


def _load_tushare_token_from_local_config():
    """
    从本地私有配置模块读取 Tushare token。

    参数示例:
    无

    返回值示例:
    "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    None
    """
    candidates = (
        ("skl_predict.local_config", ("TUSHARE_TOKEN", "tushare_token", "TOKEN")),
        ("st_operator.config", ("TUSHARE_TOKEN", "tushare_token", "TOKEN")),
    )
    for module_name, attr_names in candidates:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for attr_name in attr_names:
            value = getattr(module, attr_name, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _load_legacy_tushare_token_from_source():
    """
    从旧模块源码中提取兼容用的默认 Tushare token。

    参数示例:
    无

    返回值示例:
    "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    None
    """
    source_path = Path(__file__).resolve().parent.parent / "st_operator" / "security_data.py"
    if not source_path.exists():
        return None
    try:
        text = source_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    match = re.search(r'token\s*=\s*["\']([^"\']+)["\']', text)
    if match:
        token = match.group(1).strip()
        if token:
            return token
    return None


class ChipDistributionAnalyzer:
    def __init__(self, token=None):
        """
        初始化 Tushare Pro API。

        参数示例:
        token = None

        返回值示例:
        返回 `None`。
        """
        # 构造函数可能在 token 校验或 Tushare 初始化阶段抛异常；
        # 先初始化析构函数会访问的状态，避免出现二次 AttributeError。
        self._bs_logged_in = False
        if token is None:
            token = (
                os.getenv("TUSHARE_TOKEN")
                or _load_tushare_token_from_local_config()
                or _load_legacy_tushare_token_from_source()
            )
        if not token:
            raise RuntimeError(
                "TUSHARE_TOKEN is not configured; pass token explicitly or set the "
                "environment variable. You can also create skl_predict/local_config.py "
                "or use the legacy token embedded in st_operator/security_data.py."
            )
        self.pro = ts.pro_api(token)

    def __del__(self):
        """
        对象销毁时登出 baostock

        参数示例:
        无

        返回值示例:
        返回 `None`。
        """
        if getattr(self, "_bs_logged_in", False) and bs is not None:
            bs.logout()

    def _bs_login(self):
        """
        内部方法：登录 baostock（仅登录一次）

        参数示例:
        无

        返回值示例:
        返回 `None`。
        """
        if bs is None:
            raise RuntimeError("baostock 未安装，无法调用 get_daily_bs")
        if not self._bs_logged_in:
            lg = bs.login()
            if lg.error_code != '0':
                raise Exception(f"baostock 登录失败: {lg.error_msg}")
            self._bs_logged_in = True

    def normal_ts_code(self, ts_code):
        """
        将 6 位纯数字股票代码标准化为 tushare 格式（带交易所后缀）。

        参数示例:
        ts_code = "600000.SH"

        返回值示例:
        返回值取决于底层接口。
        """
        if ts_code.startswith('60'):
            return ts_code + '.SH'
        elif ts_code.startswith('00'):
            return ts_code + '.SZ'
        else:
            return ts_code

    def get_daily_tu(self, ts_code, start_date, end_date):
        """
        通过 tushare 获取个股日线行情数据。支持多个股票，逗号间隔

        参数示例:
        ts_code = "600000.SH"
        start_date = "20240101"
        end_date = "20240131"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        ts_code = ts_code if len(ts_code) > 6 else self.normal_ts_code(ts_code)
        df = self.pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        return df

    def get_all_pec(self, ts_code, start_date, end_date):
        """
        获取个股详细筹码分布（每个价位的持仓占比）。有积分限制，推荐使用 get_big_fund

        参数示例:
        ts_code = "600000.SH"
        start_date = "20240101"
        end_date = "20240131"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        ts_code = ts_code if len(ts_code) > 6 else self.normal_ts_code(ts_code)
        df = self.pro.cyq_chips(ts_code=ts_code, start_date=start_date, end_date=end_date)
        return df

    def get_stock_chip_distribution(self, ts_code, start_date, end_date):
        """
        获取个股筹码分布关键指标（成本分位、获利盘等）。有积分限制，推荐使用 get_big_fund

        参数示例:
        ts_code = "600000.SH"
        start_date = "20240101"
        end_date = "20240131"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        ts_code = ts_code if len(ts_code) > 6 else self.normal_ts_code(ts_code)
        df = self.pro.cyq_perf(ts_code=ts_code, start_date=start_date, end_date=end_date)
        return df

    def get_stock_chip_akshare(self, ts_code, qfq=""):
        """
        通过 akshare 获取个股筹码分布数据。

        参数示例:
        ts_code = "600000.SH"
        qfq = ""

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        return ak.stock_cyq_em(symbol=ts_code, adjust=qfq)

    def get_stock_chip_distribute_detail(self, ts_code, start_date, end_date):
        """
        获取详细筹码分布（每个价位的持仓占比，与 get_all_pec 相同接口）。

        参数示例:
        ts_code = "600000.SH"
        start_date = "20240101"
        end_date = "20240131"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        ts_code = ts_code if len(ts_code) > 6 else self.normal_ts_code(ts_code)
        df = self.pro.cyq_chips(ts_code=ts_code, start_date=start_date, end_date=end_date)
        return df

    def get_stock_basic(self, ts_code):
        """
        获取股票基本信息（代码和所属行业）。

        参数示例:
        ts_code = "600000.SH"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        ts_code = ts_code if len(ts_code) > 6 else self.normal_ts_code(ts_code)
        df = self.pro.stock_basic(ts_code=ts_code, fields='ts_code,industry')
        return df

    def get_report_rc(self, ts_code, report_date=None, start_date=None, end_date=None):
        """
        获取券商研报预测数据。

        参数示例:
        ts_code = "600000.SH"
        report_date = "20240101"
        start_date = "20240101"
        end_date = "20240131"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        if report_date is None:
            df = self.pro.report_rc(ts_code=ts_code, start_date=start_date, end_date=end_date)
        else:
            df = self.pro.report_rc(ts_code=ts_code, report_date=report_date)
        return df

    def get_realtime_tick(self, ts_code):
        """
        获取个股实时行情快照。

        参数示例:
        ts_code = "600000.SH"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        df = ts.realtime_quote(ts_code=ts_code)
        return df

    def get_daily_ak(self, symbol, start_date, end_date):
        """
        通过 akshare 获取个股日线行情（不复权）。

        参数示例:
        symbol = "600000"
        start_date = "20240101"
        end_date = "20240131"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        if symbol.endswith(".SH"):
            symbol = symbol.replace(".SH", "")
            symbol = "sh" + symbol
        elif symbol.endswith(".SZ"):
            symbol = symbol.replace(".SZ", "")
            symbol = "sz" + symbol
        # df=ak.stock_zh_a_hist_tx(
        #     symbol=symbol,
        #     start_date=start_date,
        #     end_date=end_date,
        #     adjust=""
        # )
        df = ak.stock_zh_a_daily(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            adjust=""
        )
        return df

    def get_daily_limit_up(self, date):
        """
        获取指定日期的涨停股票池数据。

        参数示例:
        date = "20260902"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        column_mapping = {
            '序号': 'serial_number',
            '代码': 'symbol',
            '名称': 'name',
            '涨跌幅': 'change_percent',
            '最新价': 'latest_price',
            '成交额': 'turnover',
            '流通市值': 'circulating_market_cap',
            '总市值': 'total_market_cap',
            '换手率': 'turnover_rate',
            '封板资金': 'sealing_capital',
            '首次封板时间': 'first_sealing_time',
            '最后封板时间': 'last_sealing_time',
            '炸板次数': 'board_broken_times',
            '涨停统计': 'limit_up_stats',
            '连板数': 'continuous_boards',
            '所属行业': 'industry'
        }
        df = ak.stock_zt_pool_em(date=date)
        df = df.copy()
        existing_columns = {col: column_mapping[col] for col in df.columns if col in column_mapping}
        df.rename(columns=existing_columns, inplace=True)
        return df

    def get_main_business_th(self, symbol):
        """
        通过同花顺接口获取个股主营业务信息。

        参数示例:
        symbol = "600000"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        if symbol.endswith(".SH"):
            symbol = symbol.replace(".SH", "")
        if symbol.endswith(".SZ"):
            symbol = symbol.replace(".SZ", "")
        return ak.stock_zyjs_ths(symbol=symbol)

    def get_main_business_dc(self, symbol):
        """
        通过东财接口获取个股主营构成数据。

        参数示例:
        symbol = "600000"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        if symbol.endswith(".SH"):
            symbol = symbol.replace(".SH", "")
        if symbol.endswith(".SZ"):
            symbol = symbol.replace(".SZ", "")
        return ak.stock_zygc_em(symbol=symbol)

    def get_emotion(self):
        """
        获取市场情绪数据（乐股接口）。

        参数示例:
        无

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        return ak.stock_market_activity_legu()

    def get_limit_up(self, date):
        """
        获取指定日期涨停股票池（原始列名，中文）。

        参数示例:
        date = "20260902"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        return ak.stock_zt_pool_em(date=date)

    def get_strong(self, date):
        """
        获取指定日期强势股票池（连续涨停或高位强势股）。

        参数示例:
        date = "20260902"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        return ak.stock_zt_pool_strong_em(date=date)

    def get_price_crush(self, date):
        """
        获取指定日期炸板股票池（曾涨停但未封住的股票）。

        参数示例:
        date = "20260902"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        return ak.stock_zt_pool_zbgc_em(date=date)

    def get_limit_down(self, date):
        """
        获取指定日期跌停股票池。

        参数示例:
        date = "20260902"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        return ak.stock_zt_pool_dtgc_em(date=date)

    def get_daily_info(self, symbol):
        """
        获取全球财经快讯（CLS 财联社）。

        参数示例:
        symbol = "600000"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        return ak.stock_info_global_cls(symbol=symbol)

    def get_daily_jgcyd(self, symbol):
        """
        获取个股机构参与度数据（东财接口）。

        参数示例:
        symbol = "600000"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        return ak.stock_comment_detail_zlkp_jgcyd_em(symbol=symbol)

    def get_fund(self, symbol):
        """
        获取个股资金流向数据（akshare 接口）。

        参数示例:
        symbol = "600000"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        market = 'sh' if symbol.startswith('6') else 'sz'
        return ak.stock_individual_fund_flow(symbol, market=market)

    def get_daily_bs(self, symbol, start_date, end_date, adjustflag='3', frequency='d'):
        """
        通过 baostock 获取个股日线数据（支持复权）。

        参数示例:
        symbol = "600000"
        start_date = "20240101"
        end_date = "20240131"
        adjustflag = "3"
        frequency = None

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        if bs is None:
            raise RuntimeError("baostock 未安装，无法调用 get_daily_bs")
        # 登录
        self._bs_login()

        # 标准化股票代码为 baostock 格式：sh.600000 或 sz.000001
        code = symbol.upper()
        if code.endswith('.SH'):
            code = code.replace('.SH', '')
            bs_code = f"sh.{code}"
        elif code.endswith('.SZ'):
            code = code.replace('.SZ', '')
            bs_code = f"sz.{code}"
        else:
            # 6位数字，根据首位判断市场
            if code.startswith('6'):
                bs_code = f"sh.{code}"
            else:
                bs_code = f"sz.{code}"

        # 日期格式转换：20240101 -> 2024-01-01
        start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
        end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

        # 请求数据
        rs = bs.query_history_k_data_plus(
            code=bs_code,
            fields="date,open,high,low,close,volume,amount,adjustflag",
            start_date=start,
            end_date=end,
            frequency=frequency,
            adjustflag=adjustflag
        )

        # 将结果转为 DataFrame
        data_list = []
        while rs.next():
            data_list.append(rs.get_row_data())
        if not data_list:
            return pd.DataFrame()  # 无数据时返回空 DataFrame

        df = pd.DataFrame(data_list, columns=rs.fields)
        # 转换数据类型
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        return df

    #-------------------------------------板块数据-----------------------------------

    def get_industry_spot(self,symbol:str):
        """
        获取板块资金流入

        参数示例:
        symbol = "600000"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        return ak.stock_board_industry_spot_em(symbol=symbol)

    def get_industry_index_ths(self,symbol,start,end):
        """
        通过同花顺获取板块指数 同花顺概念板块

        参数示例:
        symbol = "600000"
        start = "20240101"
        end = "20240131"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        # ak.stock_board_industry_index_ths(symbol="元件", start_date="20240101", end_date="20240718")
        return ak.stock_board_industry_index_ths(symbol=symbol, start_date=start, end_date=end)

    def get_industry_concept_ths(self,symbol,start,end):
        """
        获取同花顺板块概念指数

        参数示例:
        symbol = "600000"
        start = "20240101"
        end = "20240131"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        # ak.stock_board_concept_index_ths(symbol="阿里巴巴概念", start_date="20200101", end_date="20250321")
        return ak.stock_board_concept_index_ths(symbol,start,end)

    def get_industry_concept_info_ths(self,symbol):
        """
        获取同花顺概念板块当日数据

        参数示例:
        symbol = "600000"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        # stock_board_concept_info_ths_df = ak.stock_board_concept_info_ths(symbol="阿里巴巴概念")
        return ak.stock_board_concept_info_ths(symbol=symbol)

    def get_all_industry_info_ths(self):
        """
        获取同花顺各个板块的行情数据 非同花顺概念

        参数示例:
        无

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        return ak.stock_board_industry_summary_ths()

    def get_industry_concept_em(self):
        """
        获取东方财富概念板块当日数据

        参数示例:
        无

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        return ak.stock_board_concept_name_em()

    def get_industry_concept_cons_em(self,symbol):
        """
        获取东方财富概念成分股

        参数示例:
        symbol = "600000"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        # ak.stock_board_concept_cons_em(symbol="融资融券")
        return ak.stock_board_concept_cons_em(symbol=symbol)

    def get_industry_concept_hist_em(self,symbol,period,start,end,adjust):
        """
        获取东方财富指数历史数据

        参数示例:
        symbol = "600000"
        period = "daily"
        start = "20240101"
        end = "20240131"
        adjust = ""

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        # ak.stock_board_concept_hist_em(symbol="绿色电力", period="daily", start_date="20220101", end_date="20250227",adjust="")
        return ak.stock_board_concept_hist_em(symbol=symbol, period=period, start_date=start, end_date="20250227", adjust="")

    def get_industry_concept_tick_em(self,symbol,period):
        """
        获取东方财富概念股分时

        参数示例:
        symbol = "600000"
        period = "daily"

        返回值示例:
        返回 `pd.DataFrame` 或标准化后的结构化对象。
        """
        # ak.stock_board_concept_hist_min_em(symbol="长寿药", period="1")
        return ak.stock_board_concept_hist_min_em(symbol=symbol, period=period)



if __name__ == '__main__':
    analyzer = ChipDistributionAnalyzer()
    symbol_sh = '600000'
    symbol_sz = '000001'
    ts_code_sh = '600000.SH'
    ts_code_sz = '000001.SZ'
    start = '20260801'
    end = '20260820'
    date = '20260824'
    #
    # print("=== normal_ts_code ===")
    # print(analyzer.normal_ts_code('600000'))   # 600000.SH
    # print(analyzer.normal_ts_code('000001'))   # 000001.SZ
    #
    # print("\n=== get_daily_tu ===")
    # df = analyzer.get_daily_tu(symbol_sz, start, end)
    # print(df.head())

    # print("\n=== get_all_pec ===")
    # df = analyzer.get_all_pec(ts_code_sz, start, end)
    # print(df.head())
    #
    # print("\n=== get_stock_chip_distribution ===")
    # df = analyzer.get_stock_chip_distribution(symbol_sz, start, end)
    # print(df.head())
    #
    # print("\n=== get_stock_chip_akshare ===")
    # df = analyzer.get_stock_chip_akshare(symbol_sz)
    # print(df.head())
    #
    # print("\n=== get_stock_chip_distribute_detail ===")
    # df = analyzer.get_stock_chip_distribute_detail(ts_code_sz, start, end)
    # print(df.head())
    #
    # print("\n=== get_stock_basic ===")
    # df = analyzer.get_stock_basic(ts_code_sz)
    # print(df)
    #
    # print("\n=== get_report_rc ===")
    # df = analyzer.get_report_rc(ts_code_sz, start_date=start, end_date=end)
    # print(df.head())
    #
    # print("\n=== get_realtime_tick ===")
    # df = analyzer.get_realtime_tick(ts_code_sz)
    # print(df)
    #
    # print("\n=== get_daily_ak ===")
    # df = analyzer.get_daily_ak(symbol_sh, start, end)
    # print(df.head())
    #
    # print("\n=== get_daily_limit_up ===")
    # df = analyzer.get_daily_limit_up(date)
    # print(df.head())
    #
    # print("\n=== get_main_business_th ===")
    # df = analyzer.get_main_business_th(symbol_sz)
    # print(df.head())
    #
    # print("\n=== get_main_business_dc ===")
    # df = analyzer.get_main_business_dc(symbol_sz)
    # print(df.head())
    #
    # print("\n=== get_emotion ===")
    # df = analyzer.get_emotion()
    # print(df)
    #
    # print("\n=== get_limit_up ===")
    df = analyzer.get_limit_up(date)
    # print(df.head())
    #
    # print("\n=== get_strong ===")
    # df = analyzer.get_strong(date)
    # print(df.head())
    #
    # print("\n=== get_price_crush ===")
    # df = analyzer.get_price_crush(date)
    # print(df.head())
    #
    # print("\n=== get_limit_down ===")
    # df = analyzer.get_limit_down(date)
    # print(df.head())
    #
    # print("\n=== get_daily_jgcyd ===")
    # df = analyzer.get_daily_jgcyd(symbol_sz)
    # print(df.head())
    #
    # print("\n=== get_fund ===")
    # df = analyzer.get_fund(symbol_sh)
    # print(df.head())
    # df=ak.stock_board_concept_name_ths()
    # _path = os.path.join(os.path.dirname(__file__), '..', 'data','basic','industry_concept')
    # df.to_csv(f'{_path}', index=False, encoding='utf-8-sig')
    # df=analyzer.get_industry_concept_ths('储能',start,end)
    # df=analyzer.get_industry_concept_em()
    # df=analyzer.get_all_industry_info_ths()
    time.sleep(2)
    # print
