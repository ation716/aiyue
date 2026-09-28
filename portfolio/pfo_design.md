ask: 
先这样建立模型：
1. 选几个 symbol 买入和怎么分配仓位是没有关系的
2. 选几个受到风险和收益同时影响，也和资金体量有关，也和市场有关，短线情绪有关，选股策略有关
3. 怎么分配仓位也与风险和预期收益有关，也和当前仓位有关


为了快速验证其他模块，我最终设计成 3 个接口，
stock_keep 持股数量，接受 kwargs，这个根据交易策略，总持仓为 8，如果还有持仓股，需要用 8-持仓股；
position_managent 仓位管理，接受 kwargs，返回所有仓位可用仓位均可买入，根据可用仓位，对于传入的 symbol_list, 选出 stock_keep 返回的持股数量，然后再均分剩余仓位
ultimate_distribute 最终分配，依次调用 stock_keep 和 position_managent 返回结果

---

## 选股与分仓接口补充（2026-09-24；建议，待确认）

为避免上层模块直接生成不可追溯的交易数量，建议把流程拆成三层：

1. **选股策略层**：输出候选信号，只表达选择对象、方向、生成时间和排序依据。
2. **分仓层**：结合当时账户快照、可用现金、可卖数量和分仓规则，输出预算/目标数量计划。
3. **订单转换层**：根据已确定的执行日期、阶段、触发价和费用预留，把计划转换为回测引擎可消费的 `Order`。

### 1. 选股策略最终返回值

建议正式契约为 `list[CandidateSignal]`，而不是 `list[str]`：

```python
@dataclass(frozen=True)
class CandidateSignal:
    signal_id: str
    ts_code: str
    generated_date: date
    side: Literal["BUY", "SELL"]
    rank: int | None = None
    score: Decimal | None = None
    reason: str = ""
```

选股策略只表达“选谁、方向、何时产生、为什么”，不返回最终买入股数、成交价或费用。

### 2. 分仓模块最终返回值

建议正式契约为 `AllocationPlan`，其中每个对象一条 `AllocationItem`：

```python
@dataclass(frozen=True)
class AllocationItem:
    plan_id: str
    signal_id: str
    ts_code: str
    side: Literal["BUY", "SELL"]
    generated_date: date
    trade_date: date
    phase: Literal["OPEN", "INTRADAY", "CLOSE"]
    budget: Decimal | None = None
    target_quantity: int | None = None

@dataclass(frozen=True)
class AllocationPlan:
    plan_id: str
    generated_date: date
    items: tuple[AllocationItem, ...]
    unallocated_cash: Decimal
```

分仓层返回的是预算计划，不是已成交结果。`BUY` 主要填写 `budget`，由订单转换层根据参考价、整手规则和费用预留计算数量；`SELL` 主要填写 `target_quantity`，最终仍受当时可卖数量限制。未分配余额保留在 `unallocated_cash` 中，无候选时返回空 `items`，不伪造计划。

### 3. 对现有三个 demo 接口的处理

现有 `stock_keep`、`position_managent`、`ultimate_distribute` 可以保留作为快速验证接口，但建议改变最终返回语义：

- `stock_keep`：返回可新增对象数量，继续使用 `max_positions - held_count` 的结果。
- `position_managent`：内部可继续均分，但输出应逐步从 `{ts_code: cash}` 迁移为 `AllocationPlan`；旧字典只作为兼容适配结果。
- `ultimate_distribute`：负责组织候选信号、账户快照和分仓规则，返回完整 `AllocationPlan`，不要直接返回裸字典。

第一版如果仍想保持最小实现，可以先让 `position_managent` 返回 `dict[str, Decimal]`，但必须在边界处明确它是“买入预算映射”，并由适配函数补充信号编号、日期、方向和计划编号。正式接入回测引擎前再切换到结构化对象。

### 4. 当前不应提前固定的事项

以下内容仍需确认，不能由本建议自动变成实现规则：

- 选股层是否只负责买入候选，卖出是否完全交给退出/风控模块。
- 分仓第一版是剩余可用现金等分，还是按 score、风险预算或其他权重分配。
- 执行阶段和触发价由选股层、分仓层还是独立订单转换层产生。
- 是否支持同日阶段重新计算计划；若支持，必须以当时可见的账户和数据重新生成，而不是沿用全天固定计划。

只有用户确认上述口径后，才把这些结构接入正式代码；在此之前不修改现有 demo 算法，也不改变回测引擎的 `Iterable[Order]` 输入契约。
返回结果
