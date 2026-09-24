ask:
我不需要 calculate_concept_periods 这个函数了，你设计的太差了，我现在确定如何识别波动，有没有方法或者文献，贴在这个文档里，我研究一下

### AI回复：可用于识别波动与爆发阶段的方法、文献和建议路线（2026-09-23）

已按你的要求，不再把 `calculate_concept_periods` 作为后续主流程。当前先整理“怎样识别波动、怎样定位爆发阶段”的方法，暂不修改代码。

## 一、先区分三个问题

“识别波动”其实可能包含三个不同目标，不能用一个函数全部代替：

1. **波动有多大**：给每天或每个窗口一个波动强度数值；
2. **什么时候开始明显变大**：定位波动水平发生变化的日期；
3. **什么时候称为爆发**：在波动变大之外，还要定义持续时间、变化幅度或影响范围。

建议后续拆成：

```text
概念日涨幅
    ↓
波动度量：每天得到 volatility_value
    ↓
变化点识别：得到 change_date
    ↓
爆发区间识别：得到 burst_start / burst_end / burst_level
```

## 二、常见方法对比

### 方法1：滚动标准差或滚动绝对变化

对日涨幅 `r_t`，在最近L个交易日内计算：

```text
rolling_std_t = std(r_(t-L+1), ..., r_t)
rolling_abs_t = mean(abs(r_(t-L+1)), ..., abs(r_t))
```

**适合：** 第一版探索、画图、快速找到高波动区间。

**优点：** 最容易解释，计算量小，适合先确认数据形态。

**缺点：** 窗口长度L需要选择；极端值会明显影响标准差；它能告诉你“这一段波动较大”，但不能严格说明爆发从哪一天开始。

对当前概念指数研究，建议先同时看：

- `abs(daily_return)`：当天变化强度；
- `rolling_mean(abs(daily_return), L)`：近期平均变化强度；
- `rolling_std(daily_return, L)`：近期离散程度。

### 方法2：EWMA波动

给近期日变化更高权重：

```text
a_t = lambda * a_(t-1) + (1-lambda) * r_t^2
volatility_t = sqrt(a_t)
```

也可以使用指数加权的 `abs(r_t)`。

**适合：** 希望波动指标对新变化更敏感，不想等整个滚动窗口换完。

**优点：** 对突然放大的变化反应快，指标连续，不会因为窗口边界突然跳变。

**缺点：** lambda或span需要确定；前期值受初始值影响；仍然只是波动强度估计，不自动给出爆发区间。

### 方法3：ATR或高低价范围

如果概念层有可靠的高、低、收数据，可以使用：

```text
TR_t = max(high-low, abs(high-previous_close), abs(low-previous_close))
ATR_t = rolling_mean(TR_t, L)
```

**适合：** 有完整高低价数据，且关心日内振幅而不只是收盘变化。

**当前限制：** 目前概念接口的核心输入是成员聚合后的日涨幅。如果没有定义概念层的高、低价聚合方式，不建议直接把成员ATR平均后当作概念ATR。第一版优先使用概念日涨幅序列。

### 方法4：ARCH/GARCH系列

ARCH/GARCH把波动视为随时间变化的条件方差，例如GARCH(1,1)：

```text
sigma_t^2 = omega + alpha * epsilon_(t-1)^2 + beta * sigma_(t-1)^2
```

常见扩展包括：

- EGARCH：允许正负变化对波动影响不对称；
- TGARCH/GJR-GARCH：显式区分负向与正向冲击；
- APARCH：同时估计变化幅度和幂次。

**适合：** 波动建模、预测未来波动、研究波动持续性和不对称性。

**不适合作为第一版爆发日期识别器的原因：** 参数估计、分布假设和模型诊断都更复杂；模型输出的是条件波动估计，不天然等于“爆发开始日”；概念日结果若样本短、缺口多或含补值，拟合稳定性会受影响。

### 方法5：方差变化点检测

把“爆发”看成波动水平发生结构变化，直接寻找变化点：

- ICSS / CUSUM of squares：检测方差发生变化的位置；
- CUSUM：检测均值或尺度的累积偏移；
- PELT：在多个变化点场景下，用代价函数和惩罚项寻找分段；
- Binary Segmentation / Wild Binary Segmentation：递归搜索多个变化点。

**适合：** 目标是回答“波动从哪一天开始进入新阶段”。

**优点：** 结果直接给出候选变化日期；可以把一条序列切成低波动段、高波动段和恢复段。

**缺点：** 需要选择代价函数、最小段长度和惩罚项；极端单日变化可能被误认成阶段变化；事后识别和实时识别的结果可能不同。

### 方法6：状态切换模型

使用隐含状态表示低波动、中波动、高波动，例如两状态或三状态Markov Switching模型：

```text
状态0：低波动
状态1：高波动
状态随日期按转移概率变化
```

**适合：** 研究不同波动状态的持续时间、转移概率和状态循环。

**优点：** 能输出每个日期属于各状态的概率，而不是只有一个硬切点。

**缺点：** 模型估计更复杂；状态数量、分布假设和初始值会影响结果；状态标签需要事后解释，不能直接把“状态1”叫作爆发。

### 方法7：分位数阈值或极端事件累计

不拟合复杂模型，使用历史分布的高分位阈值：

```text
shock_t = 1(abs(r_t) > historical_quantile)
stress_t = EWMA(shock_t)
```

当 `stress_t` 连续超过阈值时，定义为高波动阶段。

**适合：** 需要规则透明、容易回溯、容易在入口调试的方法。

**优点：** 解释直接，参数少；可以区分单日异常和持续性爆发；适合先做候选事件标记。

**缺点：** 分位数使用全历史数据时可能产生未来信息；实时版本必须使用当日以前的滚动历史；阈值在不同阶段可能不稳定。

## 三、最值得优先研究的文献

### 1. 波动聚集与条件方差

- **Engle, R. F. (1982)**, *Autoregressive Conditional Heteroscedasticity with Estimates of the Variance of United Kingdom Inflation*, Econometrica, 50, 987–1008。ARCH的基础论文，适合了解为什么大变化往往跟随大变化、小变化往往跟随小变化。
- **Bollerslev, T. (1986)**, *Generalized Autoregressive Conditional Heteroskedasticity*, Journal of Econometrics, 31, 307–327。GARCH基础论文，用较少参数描述波动持续性。
- **Nelson, D. B. (1991)**, *Conditional Heteroskedasticity in Asset Returns: A New Approach*, Econometrica, 59, 347–370。EGARCH及不对称波动的重要文献。
- **Ding, Z., Granger, C. W., & Engle, R. F. (1993)**, *A Long Memory Property of Stock Market Returns and a New Model*, Journal of Empirical Finance, 1, 83–106。研究绝对变化和波动持续性的长记忆特征。

### 2. 方差变化与变化点

- **Inclán, C., & Tiao, G. C. (1994)**, *Use of Cumulative Sums of Squares for Retrospective Detection of Changes of Variance*, Journal of the American Statistical Association, 89, 913–923。ICSS方法的基础文献，直接针对方差变化检测。
- **Bai, J., & Perron, P. (1998)**, *Estimating and Testing Linear Models with Multiple Structural Changes*, Econometrica, 66, 47–78。多结构变化估计与检验的经典文献，适合研究多个阶段边界。
- **Bai, J., & Perron, P. (2003)**, *Computation and Analysis of Multiple Structural Change Models*, Journal of Applied Econometrics, 18, 1–22。继续讨论多变化点的计算和分析。
- **Killick, R., Fearnhead, P., & Eckley, I. A. (2012)**, *Optimal Detection of Changepoints with a Linear Computational Cost*, Journal of the American Statistical Association, 107, 1590–1598。提出PELT，适合较长序列中寻找多个变化点，DOI：`10.1080/01621459.2012.737745`。
- **Fryzlewicz, P. (2014)**, *Wild Binary Segmentation for Multiple Change-Point Detection*, The Annals of Statistics, 42, 2243–2281。适合多个局部变化点和非均匀阶段长度的场景，DOI：`10.1214/14-AOS1245`。

### 3. 状态切换与阶段识别

- **Hamilton, J. D. (1989)**, *A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle*, Econometrica, 57, 357–384。Markov状态切换模型的经典文献。
- **Hamilton, J. D. (1994)**, *Time Series Analysis*。系统介绍状态空间、Markov切换和时间序列建模。
- **Haas, M., Mittnik, S., & Paolella, M. S. (2004)**, *A New Approach to Markov-Switching GARCH Models*, Journal of Financial Econometrics, 2, 493–530。把状态切换与GARCH波动建模结合起来，适合后续深入研究，但不建议作为第一版实现起点。

### 4. 变化点与波动识别的综述入口

- **Killick, R., & Eckley, I. A. (2014)**, *changepoint: An R Package for Changepoint Analysis*, Journal of Statistical Software, 58(3), 1–19，DOI：`10.18637/jss.v058.i03`。适合先了解变化点方法的实现分类和工具结构。
- **Fengler, M., Jäger, B., & Okhrin, O. (2025)**, *Locally Adaptive Modeling of Unconditional Heteroskedasticity*。讨论局部方差变化点检测和广义似然比方法，SSRN：`https://ssrn.com/abstract_id=5323772`。属于较新的工作，适合作为扩展阅读，不应直接当作已验证的项目方案。

## 四、结合当前需求的推荐顺序

我建议不要一开始就上GARCH或Markov Switching，而按下面顺序研究：

### 第一步：只做可视化和基础度量

从接口1的 `daily_return` 生成：

```text
abs_return
rolling_abs_return
rolling_std
ewma_volatility
```

先观察不同参数下高波动区间是否稳定，确认“爆发”在肉眼上是否具有持续性。

### 第二步：加入变化点检测

优先比较：

1. ICSS/CUSUM of squares：专门看方差变化；
2. PELT：寻找多个阶段切点；
3. 分位数阈值：作为透明规则基线。

三种方法对同一条概念指数序列给出的日期，可以互相对照，但不能把某一种方法的结果直接当成事实标签。

### 第三步：定义爆发，而不是只定义高波动

一个可研究的“爆发”标签至少需要同时满足：

```text
波动水平明显高于过去基准
+ 持续达到最小天数
+ 变化幅度或累计影响达到要求
```

这样可以避免把单日异常误判为爆发。具体阈值、最小持续天数和是否要求方向性，需要研究后再确认。

### 第四步：样本外验证

如果最终要把爆发标签用于后续 `score` 或 `strat`，必须区分：

- **事后识别**：允许使用整个历史区间，适合研究历史阶段；
- **当时可见识别**：每个日期只能使用当日及之前数据，适合评估真实可用性。

同一个变化点方法，在这两种口径下可能得到不同日期。必须在结果中保留识别时点，避免把事后标签当成当时可获得的信号。

## 五、当前建议结论

现阶段最适合你的不是继续扩展原周期接口，而是：

1. 保留接口1，只负责每日概念日涨幅；
2. 新建一个很简单的概念指数接口，基数默认1000；
3. 先输出基础波动序列，不急于定义“爆发”；
4. 用ICSS、PELT、分位数阈值三类方法做研究对照；
5. 研究后再确定唯一的爆发定义；
6. 确定定义后，再单独实现爆发区间识别接口。

这样可以先把“指数怎么生成”和“爆发怎么定义”分开，避免再次把多个研究问题揉进一个函数。

**说明：** 上述论文信息来自公开检索结果及经典文献索引；正式引用前建议再核对出版社页面、DOI和原文版本。当前仅写入研究资料，未修改业务代码、未查询数据库、未执行实验。
