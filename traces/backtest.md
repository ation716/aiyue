### E04 · 2026-09-24 · 实现日 K 近似撮合与阶段账户状态

- **假设**：在仅有真实日 K 的前提下，完成单笔近似撮合和按阶段推进的账户状态结构，并验证现金、数量、T+1 和日终权益链路。
- **唯一变更点**：新增正式撮合层与时间推进层，独立于既有 demo；盘中采用用户确认的固定代理成交。
- **完整配置快照**（事后补记：本次在运行真实数据验证前未先建档，违反 G1；本节可信度低于常规记录，不得作为规范实验闭环依据）：
  - 数据模式：真实数据库只读日 K；不构造随机/人工样本
  - 近似演示模式：启用
  - 盘中路径/队列未知：固定代理成交，并写入假设标记
  - 阶段：OPEN → INTRADAY → CLOSE；同阶段先卖后买
  - T+1：买入当日不可卖；次日转为可卖数量
  - 费用：买卖双边，费率 0.0001，最低 5 元
  - 卖出税费：未确认，当前不计
  - 滑点：全局参数，默认 0；单位未确认，非零暂拒绝
  - 委托有效期：当日有效
  - 部分成交：不模拟；满足条件时全额成交
  - 买入整手：100
  - 初始现金：验证时 100000
  - 数据区间：2026-09-01 至 2026-09-03
  - 验证对象：000001
  - 预热：前一日 close 用作参考；测试未扩展策略信号
  - 数据表：T1 当前实际精简结构
  - 与上一实验的差异：无正式 bt 实验基线；新增正式接口实现，既有 demo 不变
- **数据源**：DB 真实只读查询；实际字段无 `ts_code` 与 `amount`，由适配前的 `DailyBar` 传入。
- **代码版本**：未提交，工作区改动见备注。
- **运行环境**：项目 `.venv` Python。
- **运行命令**：通过项目虚拟环境执行语法编译、DB 只读查询、单笔撮合和跨日阶段推进命令。
- **执行者**：AI 代跑，2026-09-24。
- **产出文件**：无正式结果目录产物；验证为终端返回和内存结果。
- **状态**：待分析
- **结论**：`broker.py` 与 `engine.py` 已由骨架改为可运行实现。真实日 K 单笔 OPEN 近似成交通过，费用为 5.00；跨日 BUY/SELL 阶段推进产生 2 笔成交，日终权益为 100000、99994、99986。结果仅证明接口链路与账务守恒，不能证明真实盘中可成交性或策略表现。后续需补费用细节、真实数据适配、测试断言和完整实验产物。
- **后续动作**：确认最低费用计费单位、卖出税费、滑点单位；再扩展费用模块和真实 T1 适配，不将本次验证标记为已闭环。
- **2026-09-24 设计补充（非本次实验结果，不回改上述配置与结论）**：用户随后确认不加入额外卖出税费，滑点参数以比例表示、默认仍为 0；对最低 5 元逐笔与按委托累计的差别要求举例解释，说明见模块设计稿。当前无部分成交，两种最低费用算法在本版结果一致；非零滑点如何作用于代理成交价尚未确认，E04 仍保持待分析。

### E05 · 2026-09-28 · 打通选股-配仓-三阶段交易的每日轮询链路

- **假设**：在实现选股模块、配仓模块与三阶段交易接口后，能用真实日线跑通「每日轮询 → 选股 → 配仓 → 执行 → 账户更新」的端到端链路，账户状态按设计稿的 hold / money / money_in_using / unexecuted_order 结构返回；不预设盈利，只验证链路与账户守恒。
- **唯一变更点**：相对 E04，新增每日轮询执行层与选股、配仓模块，并引入买入意愿函数；撮合规则本身（涨跌停代理、三阶段、T+1、费用口径）沿用 E04 已登记口径，不改动。
- **完整配置快照**：
```json
{
  "strat": "daily", "experiment": "E05",
  "start": "2026-01-05", "end": "2026-09-23",
  "daily_table": "stock_daily_kline_20260101_200",
  "data_mode": "real_db_only",
  "calendar": "主板日线区间日期并集（过滤后生成）",
  "prefixes": ["000", "001", "002", "003", "600", "601", "603", "605"],
  "initial_cash": "200000", "lot_size": 100,
  "max_positions": 8, "min_cash": "3000", "budget_rate": "1",
  "warmup_days": 61, "window": 60, "median_ratio": 0.9,
  "change_days": 5, "change_min": -0.05,
  "size_field": "float_mv", "size_min": 2000000000,
  "buy_ratio": 0.995, "take_profit": 0.10, "stop_loss": 0.10, "hold_days": 10,
  "fee_rate": "0.0001", "min_fee": "5", "slippage": "0",
  "phases": ["OPEN", "INTRADAY", "CLOSE"],
  "approximate_mode": true,
  "limit_ratio": "不适用：撮合层内联 1.10/0.90 近似限制价，未读取该键",
  "price_tick": "不适用：撮合层固定 ROUND_HALF_UP 两位，未读取该键",
  "size_semantics": "close×outstanding_share 的流通市值估算，非总市值",
  "st_policy": "未按名称排除；数据源无可靠历史状态，结果须标注该局限",
  "strategy_module": "scoring.strategies.strategy1",
  "allocation_module": "portfolio.allocate.allocation"
}
```
- **数据源**：DB 只读长表 `stock_daily_kline_20260101_200`，字段 `symbol,trade_date,open,high,low,close,vol,turnover_rate,outstanding_share`；无 `amount`、无 `ts_code`、无 `float_mv`，流通市值由 `close×outstanding_share` 估算；不写库。
- **代码版本**：未提交，工作区改动见备注。
- **运行环境**：项目 `.venv`（Python 3.12.10）。
- **运行命令**：`.venv/Scripts/python.exe scripts/run_daily_loop.py --experiment E05`
- **执行者**：AI 代跑，2026-09-28 10:10–10:22（含多轮修复重跑；最终成功 run_id 见产出）。
- **产出文件**：`results/daily/E05/20260928_111656_101066/`（config.json、metadata.json、trades.json、equity.json、final.json）。此前 6 次尝试均为失败/中间态，保留不删：`20260928_101641_498812`（失败）、`20260928_101710_022754`（失败）、`20260928_103239_584153`（链路通但含 3 个账务缺陷）、`20260928_105354_540756`（断言失败）、`20260928_110422_238329` 与 `20260928_111019_298882`（修复账务但卖出未解耦）。
- **状态**：已闭环
- **结论**：链路已打通，账户守恒（无负现金、无负占用）。最终产 12 笔成交（7 买 5 卖），初始现金 200000，期末总资产 206556.28，全区间 total 在 138744.56–206556.28 波动。期末持仓 002636（22 手，成本 78.52）、002068（1 手，成本 10.14）；成本价已按「股」摊入佣金（002068：10.09 价 + 5 元最低佣金）。已核实并修复 5 处账务/信号缺陷：① 可卖量按手与撮合按股不一致，导致卖单全被 `T1_OR_INSUFFICIENT_POSITION` 拒绝、持仓卡死；② 成本价按手数摊致 `gain` 恒为 −0.99；③ 卖出款同时入 cash 与 deferred 造成重复入账；④ 尾盘未释放 deferred；⑤ 选股模块 `frames` 为空时连坐丢弃卖出信号，致止损止盈被吞。结果只证明模块链接与账务守恒，不证明策略有效性或可盈利；候选信号在本区间极稀疏（177 日内仅 15 日有候选，单日最多 2 只），策略表现不具代表性。
- **后续动作**：候选过于稀疏需在策略层调整（放宽 `median_ratio` / `change_min` 或改信号）后另立实验；`portfolio/allocate.py` 的 `buy_willingness` 与等分预算口径待用户确认；`industry` 字段暂缺来源；`daily_loop` 逐日全表切片为 O(n²)（单次约 5 分钟），后续可预计算滚动统计优化。

### E06 · 2026-09-28 · 持久化成交明细与绘制权益曲线

- **假设**：在不改变 E05 选股、配仓和交易逻辑的前提下，把真实运行结果额外保存为 CSV，并使用同一权益序列生成 Matplotlib PNG 曲线，便于后续核查与可视化。
- **唯一变更点**：E05 → E06 仅新增结果存储与 Matplotlib 绘图层；不改变 E05 的行情读取、策略、配仓、撮合和账户计算。
- **完整配置快照**：
```json
{
  "strat": "daily", "experiment": "E06",
  "start": "2026-01-05", "end": "2026-09-23",
  "daily_table": "stock_daily_kline_20260101_200",
  "data_mode": "real_db_only",
  "calendar": "主板日线区间日期并集（过滤后生成）",
  "prefixes": ["000", "001", "002", "003", "600", "601", "603", "605"],
  "initial_cash": "200000", "lot_size": 100,
  "max_positions": 8, "min_cash": "3000", "budget_rate": "1",
  "warmup_days": 61, "window": 60, "median_ratio": 0.9,
  "change_days": 5, "change_min": -0.05,
  "size_field": "float_mv", "size_min": 2000000000,
  "buy_ratio": 0.995, "take_profit": 0.10, "stop_loss": 0.10, "hold_days": 10,
  "fee_rate": "0.0001", "min_fee": "5", "slippage": "0",
  "phases": ["OPEN", "INTRADAY", "CLOSE"],
  "approximate_mode": true,
  "result_storage": ["trades.csv", "equity.csv", "final.json", "equity_curve.png"],
  "plot_library": "matplotlib",
  "limit_ratio": "不适用：撮合层内联 1.10/0.90 近似限制价，未读取该键",
  "price_tick": "不适用：撮合层固定 ROUND_HALF_UP 两位，未读取该键",
  "size_semantics": "close×outstanding_share 的流通市值估算，非总市值",
  "st_policy": "未按名称排除；数据源无可靠历史状态，结果须标注该局限",
  "strategy_module": "scoring.strategies.strategy1",
  "allocation_module": "portfolio.allocate.allocation"
}
```
- **数据源**：沿用 E05，DB 只读长表；不写库、不构造数据。
- **代码版本**：未提交，工作区改动见备注。
- **运行环境**：项目 `.venv`（Python 3.12.10），新增依赖 `matplotlib 3.11.2`。
- **运行命令**：`.venv/Scripts/python.exe scripts/run_daily_loop.py --experiment E06`
- **执行者**：AI 代跑，2026-09-28 11:46–11:52。
- **产出文件**：`results/daily/E06/20260928_114634_137525/`（`config.json`、`metadata.json`、`trades.json`、`equity.json`、`final.json`、`trades.csv`、`equity.csv`、`equity_curve.png`）。
- **状态**：已闭环
- **结论**：真实只读数据运行通过，177 个交易日生成 177 行 `equity.csv`、12 行 `trades.csv`，PNG 图像文件大小 193131 字节；期末总资产 206556.28，与 E05 原始 JSON 结果一致，说明新增存储和绘图层没有改变回测计算。CSV 已保存交易日期、阶段、方向、symbol、成交价、手数、股数、费用、委托编号和撮合标记；权益 CSV 已保存可用现金、使用中现金、估值、总资产、持有数量、每日买卖数和持仓快照。绘图使用 Matplotlib Agg 后端，包含总资产/现金/估值、累计变化和回撤三部分。该图只用于结果检查，不代表可实现的实际回报。
- **后续动作**：如果后续需要跨多次运行比较，可再增加基准曲线、交易标记和按 symbol 的单独图层；本次不改变 E05 策略参数。

### E07 · 2026-09-28 · 服务器大数据源重跑流程准备

- **假设**：代码与实验配置提交后，在服务器设置独立的只读数据库连接，通过同一入口读取服务器上的更大日线表并重新生成结果；本地小库结果不作为服务器结果输入。
- **唯一变更点**：不改变策略、配仓、撮合和绘图逻辑；仅增加服务器环境配置模板、依赖声明和数据库配置加载能力，并让入口真正使用实验配置的 `daily_table`。
- **完整配置快照**：
```json
{
  "strat": "daily", "experiment": "E07",
  "start": "2026-01-05", "end": "2026-09-23",
  "daily_table": "stock_daily_kline_20260101_200",
  "data_mode": "real_db_only",
  "calendar": "主板日线区间日期并集（过滤后生成）",
  "prefixes": ["000", "001", "002", "003", "600", "601", "603", "605"],
  "initial_cash": "200000", "lot_size": 100,
  "max_positions": 8, "min_cash": "3000", "budget_rate": "1",
  "warmup_days": 61, "window": 60, "median_ratio": 0.9,
  "change_days": 5, "change_min": -0.05,
  "size_field": "float_mv", "size_min": 2000000000,
  "buy_ratio": 0.995, "take_profit": 0.10, "stop_loss": 0.10, "hold_days": 10,
  "fee_rate": "0.0001", "min_fee": "5", "slippage": "0",
  "phases": ["OPEN", "INTRADAY", "CLOSE"],
  "approximate_mode": true,
  "result_storage": ["trades.csv", "equity.csv", "final.json", "equity_curve.png"],
  "plot_library": "matplotlib",
  "limit_ratio": "不适用：撮合层内联 1.10/0.90 近似限制价，未读取该键",
  "price_tick": "不适用：撮合层固定 ROUND_HALF_UP 两位，未读取该键",
  "size_semantics": "close×outstanding_share 的流通市值估算，非总市值",
  "st_policy": "未按名称排除；数据源无可靠历史状态，结果须标注该局限",
  "strategy_module": "scoring.strategies.strategy1",
  "allocation_module": "portfolio.allocate.allocation",
  "server_db": "由服务器 .env 提供，不写入档案"
}
```
服务器侧连接差异为 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USER`、`MYSQL_PASSWORD`、`MYSQL_DATABASE` 和实际日线表名，由服务器未提交的 `.env` 提供；密码不写入本档案。
- **数据源**：服务器端真实只读数据库；数据表名由 E07 的 `daily_table` 指定，数据库连接由服务器 `.env` 提供。
- **代码版本**：待提交。
- **运行环境**：服务器项目虚拟环境；依赖由 `requirements.txt` 安装。
- **运行命令**：`.venv/bin/python scripts/run_daily_loop.py --experiment E07`（服务器按实际解释器路径调整）。
- **执行者**：待服务器运行后登记。
- **产出文件**：服务器运行后回填；`results/` 被 Git 忽略，不通过代码提交传输。
- **状态**：待运行
- **结论**：本地已完成入口配置加载和真实只读查询验证；服务器大库尚未运行，不能提前推断服务器结果。
- **后续动作**：提交代码和 E07 档案；服务器拉取后复制 `.env.example` 为 `.env`，填写服务器数据库连接，安装依赖，先做字段/日期/行数预检，再执行 E07；运行后回填实际产出路径和结果。
