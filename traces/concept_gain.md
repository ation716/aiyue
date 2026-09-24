
## E04 · 2026-09-22 · B口径真实验证

- 用户已在scoring/scoring.md确认“采用B，实现一下，完成后接着接下来的问题”；沿用真实只读调试授权。
- 唯一计算变更：聚合改为每日按方法有效成员子集，增加member_count/member_scope；其他累计、窗口、复牌衔接逻辑不变。
- 完整配置：START=2026-01-05；END=2026-09-17；WINDOW=40；CONCEPT=AI应用；MV_TIMING=current；suspensions=None；RESEARCH_LAYERS=False；RESEARCH_COMPARISON=False；方法equal/float_mv。统一日历为长表日期并集，预热81日期；库沿用本机security配置，表stock_concept_mapping及stock_daily_kline_20220101_1314；凭据不记录；仅SELECT和只读会话设置。
- 基准、资金、仓位、费用、画像、信号阈值、模拟长度和种子均不适用：仅描述统计和真实输入核对。
- SHA256：8ec42ccd77e8dc43f8295b89fd4918a3ec37629f85d546002afb7256d60273dd，未提交工作区。
- 运行环境：VENV_PY隔离环境；命令入口 results/concept_gain/E04/20260922_140400_352304/verify.py。
- 计划证据：summary.json、shown.json；逐目标日用真实日期配对，独立核对方法成员数、日结果、40日连乘、累计比值；无合成输入，不改变成员映射来构造边界。
- E04实际产出：results/concept_gain/E04/20260922_140400_352304/verify.py、shown.json、summary.json。日结果、目标窗口、累计比值各核对346条通过；每方法173日、18成员，valid_subset。状态：已闭环，仅本数据覆盖范围。

## E05 · 后续状态与数值保护验证（执行前登记）

- 沿用E04授权与完整配置：AI应用，2026-01-05至2026-09-17，WINDOW=40，current，suspensions=None，分层/环比False，B有效子集，预热81日；相同本机security库和两张来源表、只读会话、VENV_PY。交易模拟参数及合成参数均不适用。
- 差异：Q6新增window_status区分不足与断点；Q7新增index_status=anchor_only标识约定基值而不改变数值；Q8累计和窗口过滤非有限值。多个状态/保护变更一起记录，不声称单因素归因。Q3不改变，无真实停牌来源时不向前填价格。
- E05实际产出：results/concept_gain/E05/shown.json、summary.json。运行成功，日结果、目标窗口、累计比值各346条核对通过，两方法各173天、18成员；首日index_status=anchor_only。状态已闭环（实测范围内）；真实缺口、停复牌、极端溢出样本未覆盖。结论及Q3剩余边界已写回原Markdown。

## 静态说明

- 目的：复现 scoring/concept_gain.py 当前入口错误，定位 daily_status 的真实触发原因；不修改业务口径。
- 数据依赖：本机配置的 security 数据库；stock_concept_mapping 当前成员及 stock_daily_kline_20220101_1314 日线；日期并集来自该长表。
- 假设：当前默认市值时点为空导致第二方法未定义；未知成员可能阻断日计算。假设不等于实测结果。
- 限制：没有真实停牌状态表、没有历史成员还原，复权版本未经独立验证。本次不据此评价方法有效性。
- 参数见E01完整快照。主配置来自用户已修改的入口，不选新概念、不改窗口、不启用其他方法。
- 规则模板在当前工作区不存在，因此依据R2字段直接建档，不声称复制了不存在的模板。

## 台账

| 编号 | 日期 | 目的 | 变更点 | 产出 | 分析方式 | 结论 |
|---|---|---|---|---|---|---|
| E01 | 2026-09-22 | 只读复现并定位 | 首次调试；业务代码零修改 | results/concept_gain/E01/20260922_105335_589256/ | AI分析，用户明确授权 | 原入口失败：32个成员区间缺失使173天整体未知；第二方法未定义；定位闭环、修复待确认 |

## E01 · 2026-09-22 · 当前真实输入调试

- 授权：用户原话“我希望你自己调试，这次我给你授权访问”。仅本轮允许AI访问真实DB并执行只读调试，作为R2用户自行运行条款的一次性例外，不永久改写规则。
- 假设：复现当前入口行为，区分代码错误与待确认的数据口径。
- 唯一变更点：首次调试，没有前次运行；不改业务代码或参数。新增档案及调试证据采集属于观测，不改变计算。
- 完整配置：START=2026-01-05；END=2026-09-17；WINDOW=40；CONCEPT=AI应用；MV_TIMING=None；RESEARCH_LAYERS=False；RESEARCH_COMPARISON=False；suspensions=None；方法equal/float_mv（后者预期未定义）；预热最多81个前置日期；日历为长表日期并集；原入口断言rtol=1e-10/atol=1e-12。
- DB配置：沿用DBConnector环境变量或本机默认配置；凭据不记录、不输出；会话SET SESSION TRANSACTION READ ONLY，查询后rollback，最终close。只执行SELECT及会话只读设置，不写库。
- 不适用：画像、基准、初始资金、持仓上限、精英分位、最小放行数、费用/滑点、赔率倍数、高度阈值、低温禁买、事件载荷——本次仅聚合调试，不执行交易模拟；合成长度和种子不适用，禁止合成数据。
- 代码版本：当前未提交工作区；入口SHA256=c9e588825a961107ad69dff532a6af16bec535551b57a95efe180e97707cdb46。
- 运行环境：VENV_PY = C:/Users/28414/.workbuddy/binaries/python/envs/default/Scripts/python.exe；隔离安装pandas/numpy/pymysql，实际版本随证据记录。
- 运行入口：VENV_PY 执行 results/concept_gain/E01/20260922_105335_589256/debug_capture.py；该文件先通过runpy运行原入口，捕获异常栈中的真实DataFrame，在同一数据上输出诊断，无伪造输入、无第二次参数实验。
- 证据范围：原入口stdout/stderr/异常、运行环境与代码指纹、真实输入快照JSON、状态分布、首批失败对象记录、目标区间和预热窗口计数。诊断数量只用于定位，不转成计算筛选门槛。
- 产出目录（计划）：results/concept_gain/E01/20260922_105335_589256/；实际文件执行后逐项登记。
- 状态：已闭环（仅本次失败定位记录；问题修复与方法验证未完成）。
- 实际产出已登记：`results/concept_gain/E01/20260922_105335_589256/` 下 debug_capture.py、entry.log、summary.json、members.json、daily.json、calendar.json、calculated.json、shown.json、unknown_members.json。原入口实际失败，采集器正常结束不代表入口通过。
- 追加只读诊断计划（执行前记录）：使用上述真实成员的六位symbol在同一长表、同一预热起止范围查询实际ts_code及记录数，核查是否后缀不匹配；不改算法参数，不写数据库，产出 identifier_probe.json。
- 分析方式：AI分析（用户本轮要求）。
- 结论：原入口真实失败，异常为没有可验证的真实日结果。目标173天内equal全部为suspension_status_unknown，float_mv全部为method_undefined。50个映射成员中18个有254条/人日线，另外32个目标区间完全缺失，共5536成员日；同源按六位symbol复查仍只返回18个，未发现后缀匹配问题。不能认定缺失就是停牌。目标及预热有效窗口均0，数值测试未完成；独立173天状态重判无不一致。证据见summary.json、entry.log、unknown_members.json及追加的identifier_probe.json（实际已生成）。
- 运行环境实测：Python 3.13.14、pandas 3.0.6、numpy 2.5.3；PyMySQL发行包版本pip报1.2.0，模块__version__报2.2.8，保留原观测差异不推断用户IDE版本。依赖只安装到隔离环境。
- 后续动作：问题与Q2数据源／成员范围选择已写回 scoring/scoring.md 10.1，等待用户明确市值时点和成员计算范围，不为了得到非空值改变算法。业务代码未修改，数据库只读。
- 产出登记补充：identifier_probe.json为本次追加只读标识核查产物，已保存。

## E02 · 2026-09-22 · current精简入口只读验证

- 授权：用户在此前只读调试授权基础上要求继续执行；限当前模块，不改数据库、不处理Q2。
- 与E01差异：计算时点None改为current；入口同时去除了综合测试及主动报错，因此正常退出不得解释成数值验证通过。多处入口变化如实记录。
- 数据源：同E01的本机配置security库，stock_concept_mapping及stock_daily_kline_20220101_1314；基准不适用，仅作描述统计；日历为长表日期并集，预热最多81个前置日期。
- 完整配置：START=2026-01-05；END=2026-09-17；WINDOW=40；CONCEPT=AI应用；MV_TIMING=current；RESEARCH_LAYERS=False；RESEARCH_COMPARISON=False；suspensions=None；方法equal/float_mv。画像、资金、仓位、费用、信号阈值、模拟数据长度及种子全部不适用，本次不执行交易模拟。
- 代码版本：未提交工作区，SHA256=650ca83d9a27d81caf090de6c61d9fdfe805e4b6eda1db1161fb3b0c187c1f1c。
- 运行环境：VENV_PY隔离环境，DBConnector会话只读，凭据不输出。
- 运行方式：VENV_PY使用runpy.run_path执行scoring/concept_gain.py，run_name=__main__；读取返回的result/shown并归档，不修改入口。
- 实际产出已登记：results/concept_gain/E02/20260922_114800_660834/ 下 result.json、shown.json、summary.json，均已生成。
- 状态：已闭环（仅Q1配置验证，不代表数值方法通过）。
- 分析方式：AI分析（用户要求继续调试）。
- 结论：入口正常返回result 508行、shown 346行；method_undefined为0。两方法目标区间各173行均为suspension_status_unknown，有效日及窗口均0。Q1配置问题已解决，Q2仍阻断结果。
- 后续动作：实测结果已写回原Markdown；等待用户确认Q2口径，不更改成员集合。

## E09 · 2026-09-22 · 评估成员映射查询与分段耗时

- **假设**：当前调试异常发生在成员映射读取阶段；需要区分连接建立、成员映射查询、日线读取和本地计算的耗时，不能仅凭超时堆栈判断根因。
- **唯一变更点**：E08 → E09 仅增加只读耗时与查询计划诊断；不修改计算口径、不写入数据库、不构造输入。
- **完整配置**：目标概念=AI应用；START=2026-01-05；END=2026-09-17；WINDOW=40；MV_TIMING=current；suspensions=None；RESEARCH_LAYERS=False；RESEARCH_COMPARISON=False；方法=equal/float_mv；概念成员与日线均来自现有真实数据源；仅只读查询。
- **数据源**：本机默认DB连接配置；成员映射表及日线长表；不记录凭据。
- **代码版本**：未提交工作区；执行前记录相关代码摘要或SHA256。
- **运行环境**：用户授权的本机Python环境；不使用人工样本。
- **计划查询**：成员映射原始查询、去除排序的对照查询、日期范围查询；如数据库权限允许，执行只读执行计划查询；不执行结构修改。
- **计划计时**：连接建立；成员映射查询完整返回；无排序对照；日线查询；接口1；接口2。
- **产出**：results/concept_gain/E09/<run_id>/ 下的耗时、行数、异常和执行计划记录。
- **状态**：已闭环（连接与查询耗时已完成实测；数据库服务端响应异常仍待外部处理）。
- **分析方式**：AI分析。
- **结论**：连接建立约0.012—0.042秒；带排序成员查询约30.004秒超时；去排序成员查询约30.004秒超时；计数查询约30.004秒超时；只读执行计划查询约30.013秒超时。排序、返回行数和本地计算尚不能作为根因；当前只能定位到查询读取阶段，不能确认具体索引或服务端等待原因。证据为results/concept_gain/E09/query_timing.json。
- **后续动作**：由数据库服务端或连接链路继续检查；恢复响应后再做执行计划和日线查询分段评估。

- **假设**：按用户最新确认，本地统一日期轴中成员无日线记录即解释为停牌；停牌后的首条有效记录使用停牌前最后有效收盘。
- **唯一变更点**：E06 → E07 仅修改成员日变化的前收盘选择，由相邻日期收盘改为按成员向前填充后的上一条有效收盘；停牌日仍不参与聚合；B口径及其他参数不变。
- **完整配置**：START=2026-07-01；END=2026-09-17；WINDOW=40；CONCEPT=AI应用；WINDOW_SIZE=40；MV_TIMING=current；suspensions=None；RESEARCH_LAYERS=False；RESEARCH_COMPARISON=False；方法equal/float_mv；统一日历来自主行情长表日期并集；真实数据库只读；不构造样本。
- **数据源**：本机security数据源；成员映射表与主行情长表；只执行SELECT和只读会话设置。
- **代码版本**：未提交工作区；执行后代码SHA256=3a2efab1ec5c7ae6b7a3b932c0648b192938b306cfdac6867a4977850c601f9b。
- **运行环境**：VENV_PY隔离环境；先执行py_compile，再用真实数据库运行验证。
- **运行命令**：已执行真实只读验证；概念级验证及603221边界验证命令记录于本次会话产物说明。
- **实际产出**：results/concept_gain/E06/20260922_170125_000000/shown_after_gap_rule.json、summary_after_gap_rule.json、focus_603221_after_gap_rule.json。
- **状态**：已闭环。
- **分析方式**：AI分析。
- **结论**：概念级真实计算生成276行结果，目标区间114行，两种方法均为daily_status=valid、window_status=valid，每天18个有效成员。603221边界验证中，08-03至08-05及08-11至08-17为空集合；08-06使用07-31收盘，日变化约0.099467；08-18使用08-10收盘，日变化约0.100110。实现符合用户确认的缺口停牌及复现日衔接口径。
- **后续动作**：Q3完成，继续下一项问题；若后续补充真实状态表，仍需检查其与本地缺口规则的优先级和冲突校验。


- **假设**：603221在2026-07-31之后存在连续无日线记录；验证当前实现是否在缺失日排除该成员，并在缺失后的首个有效日不使用停牌前最后收盘价跨缺口计算。
- **唯一变更点**：E05 → E06 只增加真实对象603221的边界核对；不修改计算逻辑、不提供人工停牌状态、不构造样本。
- **完整配置**：START=2026-07-01；END=2026-09-17；WINDOW=40；CONCEPT=AI应用；MV_TIMING=current；suspensions=None；RESEARCH_LAYERS=False；RESEARCH_COMPARISON=False；方法equal/float_mv；统一日历来自主日线长表；预热按入口规则读取。
- **数据源**：本机security数据源；成员映射表与主行情长表；只读会话；凭据不记录。
- **代码版本**：未提交工作区；以执行前评分模块文件SHA256登记。
- **运行环境**：VENV_PY隔离环境。
- **运行命令**：待用户执行；本节先登记配置，遵循实验追溯门禁。
- **计划产出**：results/concept_gain/E06/<run_id>/raw_603221.json、shown_603221.json、summary.json。
- **状态**：已闭环（仅本次真实缺口核对；未改变业务逻辑）。
- **分析方式**：AI分析。
- **实际产出**：results/concept_gain/E06/20260922_170125_000000/raw_603221.json、raw_603221_detail.json、gap_603221.json。
- **结论**：真实主行情长表中，603221在2026-07-31之后并非一直无记录，而是出现多个缺口：2026-08-03至2026-08-05，以及2026-08-11至2026-08-17；2026-08-06、2026-08-07、2026-08-10和2026-08-18之后均有记录。当前数据源未提供可靠停复牌状态，且映射表中未找到603221对应的概念关系，因此本次不能把缺口正式标记为停牌，也不能生成概念聚合结果。
- **对当前逻辑的判断**：按真实日期轴补齐后，2026-08-06和2026-08-18虽然有当日记录，但其紧邻前一统一日期没有close，`previous_close`为空，成员日变化为空；不会把2026-07-31或2026-08-10的close跨缺口带到复现首日。2026-08-07及之后在连续有记录的情况下，才从前一统一日期的有效close计算。这个行为符合“不跨未知缺口”的保守口径。
- **后续动作**：Q3当前无需改代码。若要把2026-08-06或2026-08-18认定为复现首日并纳入统计，必须补充可信的逐日状态来源，并明确是否使用缺口前最后有效close；同时需要该对象存在有效概念映射后再做概念级验证。

## E12 · 2026-09-23 · Matplotlib基值1000折线

- 用户明确改用Matplotlib折线、起点1000，以画出图验收；替换HTML绘图，不改接口1。展示约定首个目标日设1000，从第二日起连乘；保留历史HTML不删除。
- 完整配置：AI应用，START=2026-01-05，END=2026-09-17，method=equal，mv_timing=current，suspensions=None，preheat_days=1，base_value=1000；不调用周期接口，不模拟数据，不写库。沿用真实只读验证授权。
- 环境VENV_PY，Matplotlib安装于既有隔离环境。执行MPLBACKEND=Agg下runpy主入口，保存PNG后检查图像。工作区未提交。
- 实际产出：outputs/concept_daily.png，1920×768，115767字节；PNG完整性检查通过。
- 2026-09-22续作核对（保留原标题日期，不视为实际执行时间）：使用Agg执行runpy主入口，仅将plt.show替换为空操作以便保留Figure检查；未改业务输入。day_result共174行，目标区间173点；折线首值1000.0，末值945.4505281473815。独立逐行递推与实际Line2D数据173点全部一致（rtol=1e-12），均为有限值。本区间补值0条，未覆盖补值/空值分支。
- 代码SHA256：b4814d5b914a5973def7f159906204406d73aa422542684b934f97b413787544；环境VENV_PY，matplotlib 3.11.2，未提交工作区。
- 分析方式：AI技术核对（延续用户要求画图验收）；结论：真实输入已完成PNG绘制，起点与递推数值验证通过，未写库、未生成模拟数据。图像读取接口不支持目视检查，不宣称已检查字体和布局。
- 状态：技术验证已完成，待用户视觉验收。后续动作：展示PNG，请用户检查实际视觉效果；不变更日计算公式。

## E11 · 2026-09-23 · 接口1真实日结果绘图

- 用户要求入口末尾用day_result画图；仅增加展示，不改数值逻辑。默认equal、current、AI应用、START=2026-01-05、END=2026-09-17、preheat_days=1、WINDOW=40、research_comparison=False、suspensions=None。沿用真实只读加载授权，禁止人工数据；其他模拟参数不适用。
- 数据源：现有DBConnector成员映射和日线；运行环境VENV_PY，未提交工作区。
- 运行方式：runpy.run_path执行现有主入口；核对day_result目标区间和生成HTML。计划产出outputs/concept_daily.html，使用真实结果、排除前置日期。
- 状态：真实入口执行完成，day_result 174行，目标区间图表已生成（28762字节）。实际产出outputs/concept_daily.html；分析方式AI。未宣称补值及空值绘图分支均有真实覆盖；本轮不改变公式。

## E10 · 2026-09-23 · 单模式与一天前置数据验证

- 授权：用户确认默认equal、other提示未定义、默认多取一天；沿用修改数据库读取代码后主动真实只读验证授权。
- 差异：加载由2L+1变为preheat_days=1，日接口由双方法及分层变为单模式；两项变化，不作单因素性能归因。
- 配置：AI应用，2026-01-05至2026-09-17，preheat_days=1，window_size=40，current，suspensions=None，research_comparison=False；分别equal和float_mv，other仅检查拒绝调用。来源及连接沿用DBConnector，不写库，不改结构；其他模拟参数不适用。
- 环境：VENV_PY，未提交工作区；脚本运行时保存代码SHA256。
- 命令：VENV_PY results/concept_gain/E10/verify.py。
- 计划产出：同目录summary.json，记录真实查询/计算耗时、模式、日期范围、独立聚合核对、异常；无人工业务数据。
- 状态：本次真实验证完成；此前超时根因仍未解决。分析方式：AI核对。
- 实际产出：results/concept_gain/E10/verify.py、summary.json。加载0.149630秒，3132行，前置日期1个；equal 0.096541秒、float_mv 0.151174秒，各174行（173 valid、1 empty_members）。独立日聚合346条通过，默认equal一致，other拒绝成功，接口2调用正常。窗口数值未作独立全量核对，补值边界未覆盖。
- 结论及下一步：当前样本单模式及一天预取通过；保持默认equal，不推断旧超时已修复；长缺口及补值暂缓边界保留。


