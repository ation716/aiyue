# E03配置登记

- 目的：按用户在原设计文档末尾的授权，继续使用真实数据库排查Q2、Q3及后续状态和测试覆盖问题；不修改业务口径。
- 唯一变更点：在E02 `current` 口径基础上新增只读诊断采集，不修改 scoring/concept_gain.py 计算实现；Q2成员范围不自行缩减，Q3缺口不自行认定为停牌。
- 配置：START=2026-01-05；END=2026-09-17；WINDOW=40；CONCEPT=AI应用；MV_TIMING=current；suspensions=None；RESEARCH_LAYERS=False；RESEARCH_COMPARISON=False；数据源为本机配置的security库、stock_concept_mapping、stock_daily_kline_20220101_1314；日历为长表日期并集；预热按入口读取函数。
- 只读限制：只查询真实数据，不写库、不构造数据、不删除数据；凭据不写入档案。
- 运行环境：VENV_PY隔离环境，pandas/numpy/pymysql已安装；代码SHA和环境在summary.json记录。
- 预期产出：unknown_members.json、gap_reappear.json、shown.json、calculated.json、summary.json。
- 状态：已闭环（真实诊断完成，Q2口径待用户确认；未修改业务代码）。
- 实际产出：results/concept_gain/E03/20260922_133500_000000/debug_remaining.py、unknown_members.json、gap_reappear.json、shown.json、calculated.json、summary.json。
- 结论：current下Q1保持解决；两方法目标各173行均suspension_status_unknown，5536成员日缺记录，32成员/173日期，非正活动记录为0；成员日变化有3114个但概念层整体阻断；gap_reappear为0；目标/预热窗口和累计有效值均0；首日index_value仍为1.0，Q7实际复现；无非有限值。Q2需在完整成员A与覆盖子集B之间确认。
- 后续动作：在原Markdown保留A/B选择，用户确认前不修改成员集合；Q3/Q6/Q8未触发，Q4入口已简化，Q5未触发实际误导，Q9无数值样本。