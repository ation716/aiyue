# 数据库功能使用文档

## 1. 文档用途

本文用于个人开发和调试时查阅数据库结构、字段口径、查询接口及已知限制。

内容分为五部分：

1. 数据库连接与表结构；
2. 字段单位和数据口径；
3. `DBConnector` 查询接口的使用方法；
4. 派生功能、注意事项和待确认项；
5. 数据源选择原则，避免把不完整的明细表当作历史全量事实。

数据库查询接口只读，不写入数据库；测试和调试只使用真实数据库数据，不构造人工、随机或模拟样本。

---

## 2. 数据库连接

- 数据库：`security`
- 类型：MySQL
- 地址：`127.0.0.1:3306`
- 当前表数量：6 张
- 连接实现：`data/connectors/db_connector.py`
- 连接类：`DBConnector`
- 依赖：`pandas`、`PyMySQL`

### 2.1 连接参数

构造函数：

```python
DBConnector(host=None, port=None, user=None, password=None, database=None)
```

参数来源优先级：

1. 构造函数显式传入的参数；
2. 环境变量；
3. 本机默认配置。

支持的环境变量：

| 环境变量 | 默认值 |
|---|---|
| `DB_HOST` | `127.0.0.1` |
| `DB_PORT` | `3306` |
| `DB_USER` | `root` |
| `DB_PASSWORD` | 本机默认配置中的密码 |
| `DB_NAME` | `security` |

推荐使用上下文管理器，自动关闭连接：

```python
from data.connectors.db_connector import DBConnector

with DBConnector() as db:
    daily = db.get_daily(
        symbols=["000001.SZ"],
        start_date="2026-09-01",
        end_date="2026-09-17",
    )
```

连接器建立连接后会设置 MySQL 会话为只读；每次查询结束后回滚事务，退出 `with` 时才关闭连接。不使用 `with` 时，需要自行调用 `db.close()`。

本文示例假定从项目根目录运行，或已将项目根目录加入 Python 导入路径。每日双时点统计使用 CTE 和 `LAG()`，要求 MySQL 8.0 或兼容这些语法的版本。

---

## 3. 表清单

| 表名 | 记录内容 | 当前使用情况 |
|---|---|---|
| `index_daily_kline` | 4 个指数的日 K 线：上证指数 `000001.SH`、科创综指 `000680.SH`、创业板指 `399006.SZ`、深证综指 `399106.SZ` | 当前没有封装专用查询接口；技术指标列暂未填充 |
| `stock_daily_kline_20220101_1314` | 股票日 K 线长表 | 后续测试和接口查询的主要数据源 |
| `stock_daily_kline_20230101_500` | 股票日 K 线短表，字段与长表相同 | 当前功能不使用 |
| `stock_concept_mapping` | 股票与概念的对应关系 | 用于概念成员和概念日线查询 |
| `limit_pool_daily` | 每日涨停、跌停、炸板明细 | 用于短线事件类查询和人工校验，不作为历史涨跌停全量来源 |
| `industry_pool_stat` | 按日期、行业汇总的涨停、跌停、炸板数量及强度 | 当前没有封装查询接口 |

股票概念映射表记录的是概念关系，不是完整行业成分表。`limit_pool_daily.industry` 只覆盖异动明细中的对象，也不能替代完整行业映射。

---

### 3.1 设计前必读：数据源与使用边界

- **历史涨跌停自行计算：** 使用日线长表，先明确参考价、限制比例、价格精度及特殊状态；当前主板算法及未完成项见第 7 节，不能直接推广到所有股票和日期。
- **异动表限短线用途：** `limit_pool_daily` 用于短线策略的事件明细查询；另可作为同范围校验来源，不作为完整历史涨跌停名单。无记录不等于未发生，日终名单不能验证开盘状态。
- **日线也需检查覆盖：** 使用前核对日期、代码和必要字段；缺失不补造、不默认置零，也不能仅凭缺记录反推停牌。
- **关系表不代表当日可交易名单：** 概念映射不等于行业全量成分，异动表的行业字段只覆盖其记录对象。
- **规则确认不等于验证通过：** 数据不足、特殊状态未处理或查询未跑通时，明确标记限制；读取代码修改后须用真实数据库只读验证，不以静态检查代替。
- **视图建立原则：** 只有在字段投影、统一过滤条件或稳定关联关系被多个接口重复使用时，才考虑建立轻量视图；不要把历史涨跌停推导、跨缺口参考值或复杂聚合直接固化为普通视图。先用 `EXPLAIN` 和真实只读查询确认性能，再决定是否创建。

## 4. 字段与单位

### 4.1 指数日 K 线：`index_daily_kline`

共 29 个字段。

| 字段 | 含义 | 单位或格式 |
|---|---|---|
| `id` | 记录编号 | 自增整数 |
| `ts_code` | 带后缀的指数代码 | 字符串 |
| `symbol` | 不带后缀的代码 | 字符串，保留前导零 |
| `trade_date` | 交易日期 | `YYYY-MM-DD` |
| `open`, `high`, `low`, `close` | 开盘、最高、最低、收盘 | 指数点 |
| `pre_close` | 前收盘 | 指数点 |
| `change_amount` | 相比前收盘的变化量 | 指数点 |
| `pct_chg` | 涨跌幅 | 存储比例待确认 |
| `vol` | 成交量 | 股 |
| `amount` | 成交额 | 元 |
| `rsi24_ema`, `rsi12_ema`, `rsi6_ema` | EMA 方式 RSI | 无量纲，当前未填 |
| `turnover_rate` | 换手率 | 当前无数据，弃用 |
| `kdj_rsv`, `kdj_k`, `kdj_d`, `kdj_j` | KDJ 指标 | 无量纲，当前未填 |
| `mfi14` | 14 周期 MFI | 无量纲，当前未填 |
| `obv` | OBV 累计指标 | 无数据，弃用 |
| `rsi6`, `rsi12`, `rsi24` | RSI 指标 | 无量纲，当前未填 |
| `source` | 数据来源 | 字符串 |
| `created_at`, `updated_at` | 创建、更新时间 | 日期时间 |

RSI、KDJ、MFI 等指标后续由脚本计算，不写回数据库。`obv` 不参与后续使用。

### 4.2 股票日 K 线

以下两张表共用字段：

- `stock_daily_kline_20220101_1314`
- `stock_daily_kline_20230101_500`

| 字段 | 含义 | 单位或格式 |
|---|---|---|
| `id` | 记录编号 | 自增整数 |
| `ts_code` | 带后缀的代码 | 如 `000001.SZ` |
| `symbol` | 不带后缀的代码 | 如 `000001`，保留前导零 |
| `trade_date` | 交易日期 | `YYYY-MM-DD` |
| `open`, `high`, `low`, `close` | 开盘、最高、最低、收盘价 | 元/股，前复权 |
| `change_amount` | 涨跌额 | 元/股；长表当前为空，不使用 |
| `pct_chg` | 涨跌幅 | 长表当前为空，不使用；短表未确认 |
| `vol` | 成交量 | 手 |
| `amount` | 成交额 | 元 |
| `turnover_rate` | 换手率 | 长表为小数比例，例如 `0.2` 表示 `20%`；短表未确认 |
| `outstanding_share` | 流通股本 | 股 |
| `float_mv` | 流通市值估算值 | 元 |

当前功能统一使用长表，不自动把长表字段口径套用到短表。

### 4.3 概念映射：`stock_concept_mapping`

一条记录表示一个代码与一个概念的对应关系。一个代码属于多个概念时保留多条记录。

| 字段 | 含义 | 单位或格式 |
|---|---|---|
| `id` | 记录编号 | 自增整数 |
| `ts_code` | 带后缀的代码 | 字符串 |
| `symbol` | 不带后缀的代码 | 字符串 |
| `stock_name` | 名称 | 文本 |
| `concept_name` | 概念名称 | 同花顺概念 |
| `updated_at` | 更新时间 | 日期时间 |

### 4.4 每日异动明细：`limit_pool_daily`

共 20 个字段。

| 字段 | 含义 | 单位或格式 |
|---|---|---|
| `id` | 记录编号 | 自增整数 |
| `pool_type` | 数据池类型 | `zt`、`dt`、`zb` |
| `trade_date` | 事件日期 | `YYYY-MM-DD` |
| `ts_code` | 带后缀的代码 | 字符串 |
| `name` | 名称 | 文本 |
| `industry` | 所属行业 | 文本，仅覆盖异动明细对象 |
| `pct_chg` | 涨跌幅 | 百分数值，`10` 表示 `10%` |
| `close` | 最新价 | 元/股，前复权 |
| `limit_price` | 涨停价 | 元/股，表注释说明主要用于炸板池 |
| `turn` | 换手率 | 百分数值，`10` 表示 `10%` |
| `amount` | 成交额 | 元 |
| `float_mv` | 流通市值 | 元 |
| `total_mv` | 总市值 | 元 |
| `limit_up_cnt` | 连板数；跌停池旧注释另说明连续跌停数 | 次数 |
| `break_cnt` | 炸板次数或开板次数 | 次 |
| `first_limit_time`, `last_limit_time` | 首次、最后封板时间 | `HHMMSS` |
| `seal_money` | 封板资金或封单资金 | 元 |
| `created_at`, `updated_at` | 创建、更新时间 | 日期时间 |

`pool_type` 含义：

- `zt`：涨停池；
- `dt`：跌停池；
- `zb`：炸板池。

### 4.5 行业统计：`industry_pool_stat`

共 11 个字段。

| 字段 | 含义 | 单位或格式 |
|---|---|---|
| `id` | 记录编号 | 自增整数 |
| `trade_date` | 统计日期 | `YYYY-MM-DD` |
| `industry` | 行业名称 | 文本 |
| `zt_cnt`, `dt_cnt`, `zb_cnt` | 涨停、跌停、炸板数量 | 家 |
| `zt_codes`, `dt_codes`, `zb_codes` | 对应代码列表 | 逗号分隔文本 |
| `strength` | 行业强度 | 分；`2 * zt_cnt + zb_cnt - 2 * dt_cnt` |
| `updated_at` | 更新时间 | 日期时间 |

---

## 5. `DBConnector` 查询接口

### 5.1 通用参数规则

日期参数支持：

- `YYYY-MM-DD` 字符串；
- `datetime.date`；
- `None` 表示该边界不限。

日期区间包含起止日期。起始日期晚于结束日期时抛出 `ValueError`。

代码参数支持：

- 六位代码，例如 `000001`；
- 带后缀代码，例如 `000001.SZ`；
- 字符串或字符串列表。

空列表表示不选择任何对象。重复代码或名称会自动去重。查询结果中的 `trade_date` 转为 pandas 日期类型，数据库 `Decimal` 数值转为 pandas 数值类型；原始单位和比例口径不自动转换。

### 5.2 查询股票日线：`get_daily`

```python
get_daily(symbols=None, start_date=None, end_date=None)
```

用途：查询长表日 K 线。

返回：一个 pandas DataFrame，包含：

```text
ts_code, symbol, trade_date, open, high, low, close,
change_amount, vol, amount, turnover_rate,
outstanding_share, float_mv
```

说明：

- 查询源固定为 `stock_daily_kline_20220101_1314`；
- 不返回已弃用的 `pct_chg`；
- 按 `ts_code, trade_date` 升序排列；
- `symbols=None` 时查询全部代码，可能占用较多内存；
- 建议调试时同时限制代码和日期区间。

示例：

```python
daily = db.get_daily(
    symbols=["000001.SZ"],
    start_date="2026-09-01",
    end_date="2026-09-17",
)
```

### 5.3 查询概念成员：`get_concept_members`

```python
get_concept_members(concepts=None)
```

用途：查询概念与代码的对应关系。

返回字段：

```text
concept_name, ts_code, symbol, stock_name
```

说明：

- `concepts=None` 查询全部概念；
- 传入字符串或字符串列表可限制概念名称；
- 同一代码属于多个概念时保留多行；
- 按 `concept_name, ts_code` 升序排列。

示例：

```python
members = db.get_concept_members(["人工智能"])
```

### 5.4 查询概念名称：`get_concept_names`

```python
get_concept_names()
```

返回：按名称排序的 Python `list`。

示例：

```python
concept_names = db.get_concept_names()
```

### 5.5 查询概念日线：`get_concept_daily`

```python
get_concept_daily(concepts=None, start_date=None, end_date=None)
```

用途：查询一个或多个概念对应的长表日线。

返回：一个列表，列表中每个概念对应一个 DataFrame。

说明：

- `concepts=None` 时先读取全部概念名称，再逐个查询；
- 返回顺序与传入概念顺序一致；未传入时按数据库名称排序；
- 每个 DataFrame 的 `attrs["concept_name"]` 记录概念名称；
- 无匹配时仍保留该概念的空 DataFrame；
- 同一代码属于多个概念时，会在不同概念结果中重复出现；
- 全部概念查询可能产生大量重复数据，应谨慎使用。

示例：

```python
concept_frames = db.get_concept_daily(
    concepts=["人工智能"],
    start_date="2026-09-01",
    end_date="2026-09-17",
)
for frame in concept_frames:
    print(frame.attrs["concept_name"])
    print(frame.head())
```

### 5.6 查询每日异动：`get_events`

```python
get_events(event_types=None, start_date=None, end_date=None)
```

用途：查询 `limit_pool_daily` 中的每日异动明细。

支持类型：

- `zt`
- `dt`
- `zb`

返回：一个列表，每种类型对应一个 DataFrame。

说明：

- `event_types=None` 时默认返回 `[zt, dt, zb]`；
- 每个 DataFrame 的 `attrs["pool_type"]` 记录类型；
- `pct_chg` 和 `turn` 保持数据库中的百分数值，不自动除以 100；
- 传入不支持的类型时抛出 `ValueError`。

示例：

```python
event_frames = db.get_events(
    event_types=["zt", "dt"],
    start_date="2026-09-01",
    end_date="2026-09-17",
)
for frame in event_frames:
    print(frame.attrs["pool_type"])
    print(frame.head())
```

### 5.7 查询每日双时点统计：`get_daily_market_counts`

```python
get_daily_market_counts(start_date, end_date)
```

用途：按日期返回开盘、收盘两个时点的方向计数和异动计数。

返回：一个 DataFrame，每个有效日期两行，顺序为 `open`、`close`。

| 字段 | 含义 |
|---|---|
| `trade_date` | 统计日期 |
| `snapshot` | 时点，`open` 或 `close` |
| `up_count` | 上涨数量 |
| `down_count` | 下跌数量 |
| `limit_up_count` | 涨停数量 |
| `limit_down_count` | 跌停数量 |
| `active_count` | 通过活跃记录过滤的数量 |
| `direction_valid_count` | 有有效参考收盘价和当前价格的数量 |
| `limit_count_status` | 涨跌停计数的状态说明 |

计算方法：

- 先按 `vol > 0 AND amount > 0` 过滤长表记录；
- 统一使用长表日期并集；
- 前一日参考价使用全表日期轴中紧邻前一交易日的 `close`；
- 开盘方向比较当日 `open` 与前一日 `close`；
- 收盘方向比较当日 `close` 与前一日 `close`；
- 相等不计入上涨或下跌；
- 日期参数一般可省略，但 `get_daily_market_counts` 的起止日期均必须提供；当前连接器不接受 `datetime.datetime` 或 `pandas.Timestamp` 作为日期参数，请先转为 `datetime.date`；
- 前一日缺少该代码记录、参考价为空或非正、当前比较价为空或非正时，不计方向，不回溯到更早记录；
- 按 `trade_date` 和 `ts_code` 去重；
- 收盘涨跌停数量与当日 `limit_pool_daily` 的 `zt`、`dt` 明细关联后计数；
- 日期轴中当日没有对象通过活跃过滤时仍返回两行；区间没有长表日期时返回固定列名空表，不补自然日。

示例：

```python
counts = db.get_daily_market_counts(
    start_date="2026-09-01",
    end_date="2026-09-17",
)
print(counts.to_string(index=False))
print(counts.attrs)
```

### 5.8 查询周线：`get_weekly`

```python
get_weekly(symbols=None, start_date=None, end_date=None)
```

用途：把日线聚合为自然周数据。

返回字段：

```text
ts_code, symbol, trade_date, open, high, low, close,
vol, amount, turnover_rate
```

聚合规则：

- 先按日期区间截取日线，再按自然周聚合；
- `trade_date` 为该周最后一条有效记录日期；
- `open` 取周内第一条记录；
- `close` 取周内最后一条记录；
- `high` 取最高值；
- `low` 取最低值；
- `vol`、`amount` 求和；
- `turnover_rate` 按日值求和，表示累计换手口径，不是去重后的周换手比例；
- 含缺失值的累计字段保留缺失，不补零；
- 暂不返回流通股本和市值。

示例：

```python
weekly = db.get_weekly(
    symbols=["000001.SZ"],
    start_date="2026-09-01",
    end_date="2026-09-17",
)
```

---

## 6. 60 日价格翻倍筛选

实现位置：`preprocessing/factors.py`

函数：

```python
find_doubling_symbols(
    pf,
    start_date,
    end_date,
    window=60,
    threshold=2.0,
    trading_dates=None,
    cooldown_days=5,
)
```

### 6.1 输入与输出

输入 DataFrame 至少需要以下字段：

```text
ts_code, trade_date, close
```

计算使用收盘价。同一 `ts_code` 同一日期存在重复记录时抛出错误。

返回结果按 `ts_code, end_date` 排序。同一代码可以返回多条触发记录，每条记录包含触发日期、区间起点、价格、倍数和区间完整性信息；没有命中时返回固定列名的空表。

### 6.2 计算口径

- 每个评估终点考察最近 `window` 个统一交易日；
- 默认窗口为 60 个交易日，包含起止日期；
- 只寻找严格早于触发日的最低有效收盘价；
- 收盘价倍数达到 `threshold` 即记录，默认阈值为 `2.0`；
- 已经触发后，即使后续回落，也保留历史触发记录；
- 冷却期是**同一代码的两个完整记录区间之间的空白交易日数**，不是两次触发日期之间的间隔；
- 记录上一段后清空最低价候选。其终点之后完整跳过 `cooldown_days` 个统一交易日，再从下一交易日开始建立新区间起点；
- 默认 `cooldown_days=5`：上一段终点的位置为 `e`，下一段起点 `s` 必须满足 `s - e - 1 >= 5`；终点和起点本身不算间隔；
- 新起点必须严格早于新终点，因此第 6 个交易日只能开始积累新区间，最早第 7 个交易日才可能触发；
- `cooldown_days=0` 时仍不允许区间相交或共用端点，但允许两段日期相邻；
- 采用按时间顺序首次达标即记录的贪心方式，已记录区间不事后延长，也不求最大倍数或最多区间组合；
- 缺失、空值和非正收盘价不参与计算，不补零、不前向填充。

### 6.3 调用示例

```python
from data.connectors.db_connector import DBConnector
from preprocessing.factors import find_doubling_symbols

with DBConnector() as db:
    pf = db.get_daily(
        start_date="2026-01-01",
        end_date="2026-09-17",
    )

result = find_doubling_symbols(
    pf,
    start_date="2026-06-01",
    end_date="2026-09-17",
    window=60,
    threshold=2.0,
    cooldown_days=5,
)
```

### 6.4 使用注意

- 起始评估日期之前最好提供最多 59 个交易日的预热数据；
- 不传 `trading_dates` 时，函数使用输入 DataFrame 的日期并集作为近似日历；
- 输入日期不在指定日历内时会报错；
- 单个代码自身的最近 60 条记录不能替代统一交易日历；
- 分段调用时，冷却状态不会跨调用继承；
- 该函数只负责从 DataFrame 计算特征，不负责数据库查询。

职责划分：

- `data/`：读取数据库原始数据；
- `preprocessing/`：从日线派生特征；
- `selection/`：根据特征执行筛选；
- `scoring/`：把特征转换为评分。

---

## 7. 每日双时点统计的限制

`get_daily_market_counts` 是基于日线数据的历史统计接口，同时返回每个交易日的 `open`、`close` 两行。它使用当日最终日线记录和成交字段，因此不是对应时点可直接使用的实时信号。

### 7.1 数据源与统计范围

- 接口只读取 `stock_daily_kline_20220101_1314`，不读取 `limit_pool_daily` 生成计数；
- 统计范围限制为主板代码前缀 `000`、`001`、`002`、`003`、`600`、`601`、`603`、`605`；
- 当前有效记录条件为 `vol > 0 AND amount > 0`；
- 当日没有记录的代码不会进入统计；
- 接口不计算、确认或返回停牌状态，也不能把缺失记录全部解释为停牌。

### 7.2 方向与限制数量

两个时点均使用同一套价格比较规则：

- `open` 行使用当日 `open`；
- `close` 行使用当日 `close`；
- 参考值为该代码当前日期之前最近一条 `close > 0` 的有效记录，不再强制要求位于统一日期轴的紧邻前一日；
- `up_count` 使用当前价格严格大于参考值；
- `down_count` 使用当前价格严格小于参考值；
- `limit_up_count` 使用当前价格 `>= ROUND(prev_close * 1.10, 2)`；
- `limit_down_count` 使用当前价格 `<= ROUND(prev_close * 0.90, 2)`；
- 当前版本按主板统一 `10%` 比例、价格最小单位 `0.01` 和两位小数处理；
- 前复权价格、特殊状态或限制比例变化可能使固定比例计算与真实限制状态不完全一致。

结果属性中的 `limit_count_status` 为：

```text
price_calculated_mainboard_only
```

这表示数量由价格规则计算，且只覆盖上述主板代码范围，不表示已经完成特殊状态排除或外部名单校验。

### 7.3 停牌日缺记录与复牌日参考值

如果某代码在某天没有日线记录，该天自然不会进入接口结果；这不等于接口识别出了停牌。复牌后重新出现记录时，接口会尝试回溯此前最近一条有效 `close` 作为参考值，不补造缺失日期，也不把缺失值填成零。

没有任何历史有效参考值的记录不参与方向和限制数量计算。跨缺口使用最近有效参考值只能解决参考值查找问题，不能保证所有复牌场景的真实限制状态都能由固定比例还原。

### 7.4 与 `limit_pool_daily` 的关系

`limit_pool_daily` 不参与 `get_daily_market_counts` 的计算。它仍由调试入口的 `res5` 返回，作用是供人工抽取同一日期、同一主板范围的 `zt`、`dt` 记录进行校验。当前尚未完成这项同范围逐日校验，因此不能把接口结果描述为已与该表一致。

### 7.5 统计结果的解释边界

- `up_count` 与 `limit_up_count` 可能重叠；
- `down_count` 与 `limit_down_count` 可能重叠；
- 四项数量不能相加得到总对象数；
- `open` 行同样使用当日最终 `vol` 和 `amount` 过滤，因此包含事后信息；
- 方向或限制数量少于活跃记录数时，可能是参考值、当前价格或有效性条件不足，不应直接解释为停牌数量。

### 7.6 当前实现的验证状态

最近有效参考值的 SQL 已改为按代码回溯最近一条 `close > 0` 的记录，但连续两次真实只读调用均被 `SIGTERM` 终止，尚未取得该版本的运行结果。当前仍需完成：

1. 在真实数据库上确认该查询的性能和返回结果；
2. 排除 `ST`、`*ST` 对象，或补充能够可靠识别名称状态的数据来源；
3. 用 `limit_pool_daily` 做同范围、同日期的主板结果校验。

---
## 8. 已确认口径与待确认项

### 8.1 已确认

- 数据库为本机 MySQL `security`；
- 当前维护 6 张表；
- 后续接口测试使用 `stock_daily_kline_20220101_1314` 长表；
- 股票价格使用前复权价格，单位为元/股；
- 长表成交量单位为手，成交额单位为元；
- 长表 `pct_chg` 当前为空，不使用；
- 长表 `change_amount` 当前为空，不使用；
- 长表 `turnover_rate` 使用小数比例；
- `limit_pool_daily.pct_chg` 和 `turn` 使用百分数值；
- 指标由脚本计算，不写回数据库；
- `obv` 无数据，弃用；
- 概念查询使用 `stock_concept_mapping`，不把异动表行业字段当作完整行业成分；
- 每日双时点统计需要同时返回 `open` 和 `close` 两行；
- 双时点限制数量均按价格、最近有效参考值、主板 `10%` 比例和两位小数规则计算；
- `limit_pool_daily` 只用于外部人工校验，不是该接口的计算来源；
- 停牌状态不由现有接口计算，缺失记录不自动等同于停牌；
- 用户要求排除 `ST` 和 `*ST`，该要求属于待实现的过滤条件，不能误记为当前代码已完成；
- 调试和测试不得构造人工、随机或模拟数据。

### 8.2 待确认或后续检查

- 最近有效参考值 SQL 的真实运行结果及性能；
- `ST`、`*ST` 的可靠识别字段和排除实现；
- `limit_pool_daily` 与接口结果在同日期、同主板范围内的逐日校验；
- `index_daily_kline.pct_chg` 的具体存储比例；
- 指数成交量的具体汇总范围；
- 长表实际覆盖的完整代码范围；
- 短表当前是否仍有数据，以及短表百分比字段的实际口径；
- 是否能获得可靠的开盘时点快照和限制价格来源。

---

## 9. 调试入口

`data/connectors/db_connector.py` 文件末尾的 `if __name__ == "__main__":` 用于直接查看真实数据库返回结果。入口保持短小：配置区、连接、每个接口调用一次；不打印、不做断言、不主动抛出调试流程异常。运行时可在 `res1`～`res7` 行设置断点查看变量。

通用配置：

```python
symbol_test = ["000001.SZ"]
start = "2026-09-01"
end = "2026-09-17"
concept_test = ["人工智能"]
event_types = ["zt", "dt", "zb"]
```

对应结果变量：

| 变量 | 接口 | 返回 |
|---|---|---|
| `res1` | `get_daily` | 日线 DataFrame |
| `res2` | `get_concept_members` | 概念成员 DataFrame |
| `res3` | `get_concept_names` | 概念名称列表 |
| `res4` | `get_concept_daily` | 概念日线 DataFrame 列表 |
| `res5` | `get_events` | 异动 DataFrame 列表 |
| `res6` | `get_weekly` | 周线 DataFrame |
| `res7` | `get_daily_market_counts` | 每日开盘、收盘两行的统计 DataFrame |

注意：`res7` 查询区间内长表的全部活跃对象，不受 `symbol_test` 限制。概念名称必须使用数据库中的实际名称，否则对应结果为空表或空列表。调试入口仍只读取真实数据，不构造替代样本。

---

## 10. 历史变更索引

本节只保留功能文档需要知道的历史结论，不复制问答原文。完整问题、回复、验证记录和未决事项统一维护在 `database_design.md`。

- 2026-09-22：修正 60 日翻倍筛选的冷却期定义。现为同一代码的完整记录区间不得相交，两段之间至少空出 `cooldown_days` 个统一交易日；详细口径见第 6.2 节。
- 2026-09-22：调试入口简化为通用配置、连接和接口调用，结果通过断点查看；详细接口映射见第 9 节。
- 2026-09-22：每日双时点统计改为只从长表按价格计算，限制在主板代码范围，外部异动表仅保留人工校验用途；当前验证状态见第 7.6 节。
- 2026-09-22：最近有效参考值的实现尚未完成真实运行验证；名称状态排除和同范围外部校验仍待处理。
