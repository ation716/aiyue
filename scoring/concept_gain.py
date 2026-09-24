"""概念日涨幅与窗口统计。仅依赖真实输入；本地日线缺口按停牌处理，概念整体无数据日按确认规则补值。

已确认默认使用当日流通市值加权，属于当日结束后的描述统计。
分层和环比仅为可选研究输出。
数据库读取发生在 load_concept_inputs / __main__，导入本模块不会连接数据库。
"""
from __future__ import annotations

from numbers import Integral
import numpy as np
import pandas as pd


KEYS = ["ts_code", "trade_date"]


def _dated(frame, required):
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"缺少字段: {sorted(missing)}")
    frame = frame.copy()
    if frame[list(required)].empty:
        return frame
    if frame[KEYS].isna().any().any():
        raise ValueError("代码和日期不能缺失")
    frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise").dt.normalize()
    if frame.duplicated(KEYS).any():
        raise ValueError("同一成员同一天存在重复记录")
    return frame


def load_concept_inputs(db, concepts, start_date, end_date, preheat_days=1):
    """读取接口1所需的真实输入，默认只预取目标区间前一个日期。

    preheat_days：接口1只计算日涨幅时的前置日期数量，默认1；不负责
    接口2的窗口预热。日期并集不是独立交易日历；价格复权版本必须由
    数据提供方保证一致。本地日线缺记录按停牌解释。
    """
    if not isinstance(preheat_days, Integral) or isinstance(preheat_days, bool) or preheat_days < 0:
        raise ValueError("preheat_days 必须为非负整数")
    db._dates(start_date, end_date)
    if start_date is None or end_date is None:
        raise ValueError("须明确起止日期")
    names = db._items(concepts)
    if not names:
        raise ValueError("须明确概念列表，不默认读取全部概念")
    members = db.get_concept_members(names)
    absent = set(names) - set(members.concept_name)
    if absent:
        raise ValueError(f"概念不存在或成员为空: {sorted(absent)}")
    calendar = db._query(
        "SELECT DISTINCT trade_date FROM " + db.DAILY +
        " WHERE trade_date <= %s ORDER BY trade_date", [end_date])
    dates = pd.DatetimeIndex(calendar.trade_date)
    first = dates.searchsorted(pd.Timestamp(start_date))
    dates = dates[max(0, first - preheat_days):]
    if dates.empty or not (dates >= pd.Timestamp(start_date)).any():
        raise ValueError("指定区间没有真实日期")
    daily = db.get_daily(members.ts_code.drop_duplicates().tolist(),
                         dates[0].date(), pd.Timestamp(end_date).date())
    if daily.empty:
        raise ValueError("真实日线为空，不生成替代数据")
    return members, daily, dates


def calculate_concept_daily_returns(members, daily, calendar, *,
                                    method="equal", mv_timing="current", suspensions=None):
    """接口1：将成员日线聚合为概念日涨幅，返回供周期接口使用的明细表。

    本函数只处理内存中的真实输入，不连接数据库、不修改输入表。
    计算包括成员日涨幅、概念聚合和当前补值规则；不计算累计序列、
    固定窗口或环比。返回值可直接传入 calculate_concept_periods。

    Parameters
    ----------
    members : pandas.DataFrame
        成员映射，必需列为 concept_name、ts_code。两列不能有空值，
        映射不能为空；重复关系自动去重。使用传入映射，不还原历史成员。
    daily : pandas.DataFrame
        真实日线，必需列为 ts_code、trade_date、close；同一代码和日期
        必须唯一且标识非空。close 为收盘价，float_mv 为流通市值（元）。
        vol、amount 同时为正用于确认当日有交易活动；未提供明确正常
        状态时，缺少这些字段的成员不能参与。缺少 float_mv 不影响等权，
        但对应成员不能参加市值加权或分层。数值转换失败及非有限值按缺失处理。
        收盘价的复权一致性由调用方保证，本函数不执行复权。
    calendar : iterable of datetime-like
        统一日期轴，转成日期后必须非空、无缺失、唯一且严格递增。
        仅在此日期轴内对齐和计算；建议保留加载阶段的预热日期，
        在周期计算完成后再截取展示区间。
    mv_timing : {"current", "previous", None}, default "current"
        current：使用当日流通市值，属于当天结束后的描述统计。
        previous：使用前一统一日期的流通市值；不跨缺口前向填充市值。
        None：仍保留 float_mv 方法行，但值为空、状态为 method_undefined；
        仅在method=float_mv时输出该未定义状态；equal不依赖市值。
    suspensions : pandas.DataFrame or None, default None
        可选真实状态表，必需列为 ts_code、trade_date、is_suspended。
        同一代码和日期唯一，状态必须为非空布尔值：True 排除当天，
        False 明确当天正常。未列出的日期按 vol、amount 判定活动状态；
        True 与当日正成交记录冲突时抛出 ValueError。
    method : {"equal", "float_mv", "other"}, default "equal"
        equal：只输出等权；float_mv：只输出市值加权。
        other：预留方法，调用时抛出NotImplementedError，提示尚未定义。
        每次仅计算所选方法，不再支持research_layers旧分层开关。

    Returns
    -------
    pandas.DataFrame
        每个 concept_name、trade_date、method 一行，按这三列排序。
        daily_return：日涨幅，小数比例；不可计算且不能补值时为 NaN。
        daily_status：valid（真实聚合）、empty_members（无可用成员且
        未补出值）、method_undefined（配置未定义）、nonfinite_result
        （聚合结果非有限）或 imputed_ewm3（历史补值）。
        member_count：该方法当天真实参与成员数，补值不增加人数。
        member_scope：full_mapping 或 valid_subset，按参与数是否等于
        完整映射数确定；空集合也属于 valid_subset。
        imputation_method：补值时为 ewm3_return，否则为 None。
        imputation_source_count：补值参考的历史数量，上限3；未补值为0。
        attrs 中保留 method、mv_timing 和 limits 说明。

    Notes
    -----
    - B口径：每天按方法排除不可用成员，在有效子集中重新归一化。
      equal 求成员日涨幅均值；float_mv 用有限正市值加权。
    - 本地无日线记录按停牌解释；缺口日不参与，恢复日用日期轴内此前
      最近非空收盘衔接。当前收盘与参考收盘都须为正且当天状态正常。
      实现先前向填充非空收盘再检查正值，不会跳过中间的非正收盘。
    - 当前代码按方法的 empty_members 触发补值，不只限于整个概念
      无原始记录：字段不可用或研究空层也可能触发。这是Q7暂缓边界。
    - 补值取最近三个有限历史日结果做 EWM(span=3, adjust=False)；
      不足三个但有前值时沿用前值，没有历史时保留空值。历史可包含
      先前补值，也可能跳过无效日；不是严格紧邻的三个统一日期。
      前值回退也沿用 ewm3_return 标记。补值不删除或移动日期。

    Raises
    ------
    ValueError
        参数选项无效、输入必需列缺失、标识为空或重复、日期不合法，
        或显式停牌状态与正成交记录冲突等情况。字段数值不可用通常
        只排除对应成员，不等于整个调用报错。
    """
    if method not in ("equal", "float_mv", "other"):
        raise ValueError("method 仅支持 equal/float_mv/other")
    if method == "other":
        raise NotImplementedError("其他计算方法尚未定义")
    if mv_timing not in (None, "previous", "current"):
        raise ValueError("mv_timing 仅支持 None/previous/current")
    dates = pd.DatetimeIndex(pd.to_datetime(list(calendar))).normalize()
    if dates.empty or dates.hasnans or dates.has_duplicates or not dates.is_monotonic_increasing:
        raise ValueError("calendar 必须非空、唯一并严格递增")
    if not {"concept_name", "ts_code"}.issubset(members.columns):
        raise ValueError("成员关系缺少必要字段")
    mapping = members[["concept_name", "ts_code"]].drop_duplicates()
    if mapping.empty or mapping.isna().any().any():
        raise ValueError("成员关系为空或包含空标识")
    raw = _dated(daily, KEYS + ["close"])
    flags = None
    if suspensions is not None:
        flags = _dated(suspensions, KEYS + ["is_suspended"])
        if not flags.is_suspended.map(lambda x: isinstance(x, (bool, np.bool_))).all():
            raise ValueError("停牌状态必须为明确布尔值，不能填充未知值")
        flags = flags.set_index(KEYS).is_suspended

    records = []
    for concept, group in mapping.groupby("concept_name", sort=True):
        codes = group.ts_code.tolist()
        grid = pd.MultiIndex.from_product([codes, dates], names=KEYS)
        panel = raw.set_index(KEYS).reindex(grid)
        for column in ("close", "float_mv", "vol", "amount"):
            if column not in panel:
                panel[column] = np.nan
            panel[column] = pd.to_numeric(panel[column], errors="coerce")
            panel.loc[~np.isfinite(panel[column]), column] = np.nan
        activity = (panel.vol > 0) & (panel.amount > 0)
        state = pd.Series(pd.NA, index=grid, dtype="boolean")
        state.loc[activity] = False
        if flags is not None:
            supplied = flags.reindex(grid).astype("boolean")
            if (supplied.fillna(False) & activity).any():
                raise ValueError("停牌状态与正成交记录冲突")
            state.loc[supplied.notna()] = supplied.loc[supplied.notna()]
        panel["is_suspended"] = state
        previous_close = (panel.groupby(level="ts_code").close
                          .ffill().groupby(level="ts_code").shift(1))
        # 本地日线中，成员有记录但前一统一日期无记录时，按用户确认视为停牌。
        # 复牌日使用停牌前最后有效收盘；连续停牌日自身仍因当前状态未知而排除。
        panel["member_return"] = (panel.close / previous_close - 1).where(
            (panel.close > 0) & (previous_close > 0) &
            state.eq(False).fillna(False))
        # 复牌衔接使用当前日市值或前一统一日期市值，市值时点口径不变。
        panel["weight"] = (panel.groupby(level="ts_code").float_mv.shift(1)
                           if mv_timing == "previous" else panel.float_mv)
        methods = [method]
        for day, frame in panel.groupby(level="trade_date", sort=True):
            # B口径：缺记录和未知状态不当作停牌，仅排除当天不可用成员。
            active = frame.loc[frame.is_suspended.eq(False).fillna(False) &
                               np.isfinite(frame.member_return)]
            for method in methods:
                value, status = np.nan, "valid"
                selected = active
                if method != "equal":
                    selected = selected.loc[np.isfinite(selected.weight) & (selected.weight > 0)]
                if method != "equal" and mv_timing is None:
                    selected = selected.iloc[:0]
                    status = "method_undefined"
                else:
                    if selected.empty:
                        status = "empty_members"
                    elif method == "float_mv":
                        weights = selected.weight / selected.weight.max()
                        value = float((selected.member_return * (weights / weights.sum())).sum())
                    else:
                        value = float(selected.member_return.mean())
                if status == "valid" and not np.isfinite(value):
                    value, status = np.nan, "nonfinite_result"
                records.append({"concept_name": concept, "trade_date": day, "method": method,
                                "daily_return": value, "daily_status": status,
                                "member_count": len(selected),
                                "member_scope": "full_mapping" if len(selected) == len(codes) else "valid_subset"})
    result = pd.DataFrame(records)
    if not result.empty:
        result["imputation_method"] = None
        result["imputation_source_count"] = 0
        filled = []
        for _, block in result.groupby(["concept_name", "method"], sort=False):
            block = block.sort_values("trade_date").copy()
            history = []
            for row_index, row in block.iterrows():
                if row.daily_status == "empty_members":
                    previous = history[-1] if history else np.nan
                    if len(history) >= 3:
                        value = float(pd.Series(history[-3:]).ewm(span=3, adjust=False).mean().iloc[-1])
                        source_count = 3
                    elif np.isfinite(previous):
                        value = float(previous)
                        source_count = len(history)
                    else:
                        value = np.nan
                        source_count = 0
                    if np.isfinite(value):
                        block.at[row_index, "daily_return"] = value
                        block.at[row_index, "daily_status"] = "imputed_ewm3"
                        block.at[row_index, "imputation_method"] = "ewm3_return"
                        block.at[row_index, "imputation_source_count"] = source_count
                if np.isfinite(block.at[row_index, "daily_return"]):
                    history.append(float(block.at[row_index, "daily_return"]))
            filled.append(block)
        result = pd.concat(filled, ignore_index=True)
    output = result.sort_values(["concept_name", "trade_date", "method"]).reset_index(drop=True)
    output.attrs.update(method=method, mv_timing=mv_timing,
                        limits="本地缺口按停牌衔接；当前补值边界保持Q7实现；复权一致性由来源保证")
    return output


def calculate_concept_periods(daily_returns, window_size=40, *, research_comparison=False):
    """接口2：根据接口1的日结果计算累计序列和固定长度窗口。

    只计算内存中的输入，不访问数据库、不重新聚合成员、不再次补值，
    也不修改传入的DataFrame。“周期”在这里指窗口统计，不是阶段识别。

    Parameters
    ----------
    daily_returns : pandas.DataFrame
        接口1的非空完整返回值，保留预热日期，不要先截取目标区间。
        必需列：concept_name、trade_date、method、daily_return、daily_status。
        概念/日期/方法组合须非空且唯一；日结果使用小数比例。
        各组应保留统一日期轴，包括结果为空的日期。本函数会排序，
        但不会检查或补齐被调用方删除的日期；窗口实际按各组行数计数。
    window_size : int, default 40
        固定窗口长度，须为正整数且不能为布尔值。
        每个日期使用截至当日的最近 window_size 行，不跳过空值凑数。
    research_comparison : bool, default False
        False：只计算累计和当前窗口。
        True：额外输出前一个等长窗口及两窗口的差值；前窗口是当前
        window_return 向后移动 window_size 行，不是前一天的窗口。

    Returns
    -------
    pandas.DataFrame
        保留输入列，增加或更新下列字段，按概念、日期、方法排序：
        index_value：累计统计序列，首行设为1（方法未定义时为空）。
        index_status：anchor_only、valid、unavailable 或 nonfinite_result。
        window_return：窗口内 (1 + daily_return) 连乘后减1，小数比例。
        window_size：本次窗口长度。
        window_status：valid、window_insufficient、window_contains_invalid_day
        或 nonfinite_result。
        status：日状态不是valid时优先保留日状态，否则采用窗口状态；
        不综合累计状态，因此不能仅用这一列判断所有输出是否可用。
        research_comparison=True 时另有 previous_window_return 和
        research_spread，后者为当前窗口减前窗口，不是两者的比值。
        attrs 继承输入属性，并记录 research_comparison。

    Notes
    -----
    - 按 concept_name、method 分组独立计算，不把不同方法串起来。
    - 累计首行只作归一化锚点，不计入首行日变化。之后从第二行连乘；
      遇到NaN后不重启累计。窗口直接使用原始日结果，不由累计值反算，
      因此在缺口离开窗口后可以恢复，而累计仍可能为空。
    - 输入中已有的补值会参与连乘。当前窗口和累计的valid只表示数值
      可用，并不表示窗口全为真实观测；尚未增加补值数量传播字段。
    - 非有限输出转为空并尝试标记原因；NaN仍按不可用处理。
    - 当前不足窗口判定用零基行号 < window_size；首个完整窗口若含
      无效值，也可能仍标为window_insufficient。这是现有实现边界。
    - 必须先计算再截取展示区间；提前截取会丢失预热并改变累计起点。

    Raises
    ------
    ValueError
        窗口长度无效、输入为空或缺必需列、日期不合法、键为空或重复。
        日结果应直接使用接口1的数值列，本函数不额外清洗字符串数值。
    """
    # if not isinstance(window_size, Integral) or isinstance(window_size, bool) or window_size < 1:
    #     raise ValueError("window_size 必须为正整数")
    # required = {"concept_name", "trade_date", "method", "daily_return", "daily_status"}
    # if not required.issubset(daily_returns.columns) or daily_returns.empty:
    #     raise ValueError("须传入接口1的非空完整返回值")
    # result = daily_returns.copy()
    # result["trade_date"] = pd.to_datetime(result.trade_date, errors="raise").dt.normalize()
    # keys = ["concept_name", "trade_date", "method"]
    # if result[keys].isna().any().any() or result.duplicated(keys).any():
    #     raise ValueError("概念/日期/方法须非空且唯一")
    # blocks = []
    # for _, block in result.groupby(["concept_name", "method"], sort=False):
    #     block = block.sort_values("trade_date").copy()
    #     returns = block.daily_return
    #     # 第一日期仅作为归一化锚点；之后遇缺口不重启累计序列。
    #     factors = 1 + returns
    #     factors.iloc[0] = (np.nan if block.daily_status.iloc[0] == "method_undefined" else 1.0)
    #     raw_index = factors.cumprod(skipna=False)
    #     index_overflow = raw_index.notna() & ~np.isfinite(raw_index)
    #     block["index_value"] = raw_index.where(np.isfinite(raw_index))
    #     block["index_status"] = np.where(index_overflow, "nonfinite_result",
    #                                       np.where(raw_index.isna(), "unavailable", "valid"))
    #     if pd.notna(block["index_value"].iloc[0]):
    #         block.loc[block.index[0], "index_status"] = "anchor_only"
    #     # 不重启累计序列；完整连续窗口可在缺口之后恢复。
    #     raw_window = (1 + returns).rolling(window_size, min_periods=window_size).apply(np.prod, raw=True) - 1
    #     window_overflow = raw_window.notna() & ~np.isfinite(raw_window)
    #     block["window_return"] = raw_window.where(np.isfinite(raw_window))
    #     block["window_size"] = window_size
    #     insufficient = np.arange(len(block)) < window_size
    #     block["window_status"] = np.where(window_overflow, "nonfinite_result",
    #         np.where(block.window_return.notna(), "valid",
    #                  np.where(insufficient, "window_insufficient", "window_contains_invalid_day")))
    #     block["status"] = np.where(block.daily_status.ne("valid"), block.daily_status, block.window_status)
    #     if research_comparison:
    #         block["previous_window_return"] = block.window_return.shift(window_size)
    #         block["research_spread"] = block.window_return - block.previous_window_return
    #     blocks.append(block)
    # output = pd.concat(blocks, ignore_index=True).sort_values(
    #     ["concept_name", "trade_date", "method"]).reset_index(drop=True)
    # output.attrs.update(daily_returns.attrs)
    # output.attrs["research_comparison"] = research_comparison
    # return output


# def calculate_concept_returns(members, daily, calendar, window_size=40, *,
#                               method="equal", mv_timing="current", suspensions=None,
#                               research_comparison=False):
#     """兼容旧调用；新调用建议分别使用日涨幅接口和周期接口。"""
#     daily_returns = calculate_concept_daily_returns(
#         members, daily, calendar, method=method, mv_timing=mv_timing,
#         suspensions=suspensions)
#     return calculate_concept_periods(
#         daily_returns, window_size, research_comparison=research_comparison)


def plot_concept_daily_returns(day_result, start_date=None, end_date=None,
                               output_path=None, *, base_value=1000, show=True):
    """使用Matplotlib绘制累计折线，保存PNG并返回路径，不查询数据库。

    首个展示日期设为base_value（默认1000），从第二个展示日期开始
    按前值*(1+daily_return)连乘；首日日变化不计入，属于展示归一化。
    不改接口1原始数据。未补出的空值中断累计，不跳过或填0。
    补值以橙色圆点标记。每个概念/方法独立子图。
    start_date/end_date仅筛展示区间；output_path默认outputs/concept_daily.png。
    show=True用于本地调试弹出绘图窗口；无界面验证时传False。
    """
    from pathlib import Path
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    if not np.isfinite(base_value) or base_value <= 0:
        raise ValueError("base_value必须为有限正数")
    frame = day_result.copy()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    if start_date is not None:
        frame = frame.loc[frame.trade_date >= pd.Timestamp(start_date)]
    if end_date is not None:
        frame = frame.loc[frame.trade_date <= pd.Timestamp(end_date)]
    if frame.empty:
        raise ValueError("展示区间没有日结果")
    groups = list(frame.groupby(["concept_name", "method"]))
    with plt.rc_context({"font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
                         "axes.unicode_minus": False}):
        fig, axes = plt.subplots(len(groups), 1, figsize=(12, 4.8*len(groups)), squeeze=False,
                                 constrained_layout=True, facecolor="white")
        for ax, ((concept, method), group) in zip(axes.flat, groups):
            group = group.sort_values("trade_date")
            returns = pd.to_numeric(group.daily_return, errors="coerce")
            factors = (1 + returns).where(np.isfinite(returns))
            factors.iloc[0] = np.nan if group.daily_status.iloc[0] == "method_undefined" else 1.0
            curve = base_value * factors.cumprod(skipna=False)
            curve = curve.where(np.isfinite(curve))
            ax.plot(group.trade_date, curve, color="#b6323e", linewidth=1.8, label="累计曲线")
            ax.axhline(base_value, color="#8792a2", linestyle="--", linewidth=.9, label=f"起点 {base_value:g}")
            imputed = group.daily_status.eq("imputed_ewm3") & curve.notna()
            if imputed.any():
                ax.scatter(group.loc[imputed, "trade_date"], curve.loc[imputed], color="#d78b12", s=24, label="使用补值", zorder=3)
            finite = curve.dropna()
            if len(finite):
                ax.annotate(f"{finite.iloc[-1]:.2f}", (group.loc[finite.index[-1], "trade_date"], finite.iloc[-1]),
                            xytext=(-8, 10), textcoords="offset points", ha="right")
            ax.set_title(f"{concept} · {method} · 累计变化（起点 {base_value:g}）", loc="left", fontsize=14)
            ax.set_ylabel("归一化累计值")
            ax.set_xlabel("日期；首个展示日为锚点，从下一日起连乘")
            locator = mdates.AutoDateLocator(minticks=4, maxticks=9)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            ax.tick_params(axis="x", labelrotation=20)
            ax.grid(alpha=.22)
            ax.spines[["top", "right"]].set_visible(False)
            ax.legend(loc="best", frameon=False)
        path = Path(output_path) if output_path is not None else Path(__file__).resolve().parents[1] / "outputs" / "concept_daily.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=160, facecolor="white")
        if show:
            plt.show()
        else:
            plt.close(fig)
    return path


if __name__ == "__main__":
    # 用户自行执行；执行前按追溯规则登记配置。本段不构造测试样本。
    # 支持直接运行本文件；常规导入不改 sys.path。
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from data.connectors.db_connector import DBConnector

    # 当前入口只做断点调试：先加载真实数据，再执行一行主计算。
    # START / END：目标日期区间；WINDOW：窗口长度，默认40个交易日。
    # CONCEPT：本次要调试的概念名称；只读真实映射，不构造成员。
    # MV_TIMING：市值取值时点。current=当日流通市值（本项目已确认）；
    #            previous=前一交易日流通市值；None=不计算市值加权。
    # METHOD：equal=仅等权；float_mv=仅市值加权；other=尚未定义。
    # PREHEAT_DAYS：默认额外读取前1个统一日期；窗口初期允许不足。
    # RESEARCH_COMPARISON：是否输出相邻窗口差值；False=关闭。
    START, END, WINDOW = "2026-01-05", "2026-09-17", 40
    CONCEPT = "AI应用"
    MV_TIMING = "current"
    METHOD = "equal"
    PREHEAT_DAYS = 1
    RESEARCH_COMPARISON = False

    with DBConnector() as db:
        members, daily, calendar = load_concept_inputs(db, [CONCEPT], START, END, preheat_days=PREHEAT_DAYS)
    # members=成员映射；daily=真实日线；calendar=含预热的统一日期轴。
    # suspensions：可选真实状态表，含ts_code/trade_date/is_suspended；None=不提供。
    # result含预热；shown仅目标区间。在shown赋值行断点可看result，单步后看shown。
    # 入口不输出、不做断言；函数保留必要校验，按B口径记录实际参与成员。
    day_result = calculate_concept_daily_returns(members, daily, calendar, method=METHOD, mv_timing=MV_TIMING, suspensions=None)
    result = calculate_concept_periods(day_result, WINDOW, research_comparison=RESEARCH_COMPARISON)
    # Matplotlib折线图：首个展示日归一化为1000，保存PNG并显示窗口。
    # chart_path = plot_concept_daily_returns(day_result, START, END, base_value=1000)

