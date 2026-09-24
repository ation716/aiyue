我现在设计一个量化策略系统，需要完成以下实现

需要分模块完成

1. 数据连接系统，数据获取与入库，
2. 拿取数据，做数据预处理，如指标计算等
3. 各个维度评分
4. 选股，根据各个维度的评分，选择合适的标的
5. 分仓
6. 计算收益

因此先为我创建这些文档吧

aiyue/
│
├── config/                          # 【配置层】全局配置
│   ├── __init__.py
│   ├── settings.py                  # 数据库、路径、API密钥等
│   └── logging_config.py            # 日志配置
│
├── data/                            # 【数据层】
│   ├── __init__.py
│   ├── connectors/                  # 模块1: 数据连接系统
│   │   ├── __init__.py
│   │   ├── base_connector.py        # 抽象基类
│   │   ├── data_connector.py        # AKShare数据源，Tushare数据源 
│   │   └── db_connector.py          # 数据库连接（MySQL/PostgreSQL）
│   │
│   ├── storage/                     # 数据入库
│   │   ├── __init__.py
│   │   ├── models.py                # ORM模型（SQLAlchemy）
│   │   ├── dao.py                   # 数据访问对象
│   │   └── schema.sql               # 建表SQL
│   │
│   ├── raw/                         # 原始数据落地（csv/parquet缓存）
│   │   ├── daily/
│   │   ├── financial/
│   │   └── minute/
│   │
│   └── processed/                   # 预处理后数据
│       ├── factors/
│       └── indicators/
│
├── preprocessing/                   # 【模块2: 数据预处理】
│   ├── __init__.py
│   ├── cleaner.py                   # 缺失值、异常值、复权处理
│   ├── indicators.py                # 技术指标计算（MA/MACD/RSI/BOLL等）
│   ├── factors.py                   # 因子计算（动量/波动/估值/成长）
│   └── pipeline.py                  # 预处理流程编排
│
├── scoring/                         # 【模块3: 多维度评分】
│   ├── __init__.py
│   ├── base_scorer.py               # 评分基类
│   ├── technical_scorer.py          # 技术面评分
│   ├── fundamental_scorer.py        # 基本面评分
│   ├── sentiment_scorer.py          # 情绪/资金面评分
│   ├── momentum_scorer.py           # 动量评分
│   └── composite_scorer.py          # 综合评分（加权融合）
│
├── selection/                       # 【模块4: 选股】
│   ├── __init__.py
│   ├── filters.py                   # 基础过滤（ST、停牌、次新）
│   ├── ranker.py                    # 排序选股
│   ├── selector.py                  # 选股策略（TopN/阈值/分层）
│   └── universe.py                  # 股票池管理
│
├── portfolio/                       # 【模块5: 分仓】
│   ├── __init__.py
│   ├── position_sizer.py            # 仓位计算（等权/风险平价/凯利）
│   ├── allocator.py                 # 资金分配
│   ├── rebalancer.py                # 调仓逻辑
│   └── risk_control.py              # 风控（止损/最大回撤/行业上限）
│
├── backtest/                        # 【模块6: 收益计算/回测】
│   ├── __init__.py
│   ├── engine.py                    # 回测引擎主循环
│   ├── broker.py                    # 模拟撮合、手续费、滑点
│   ├── performance.py               # 收益指标（年化/夏普/最大回撤）
│   ├── report.py                    # 回测报告生成
│   └── visualizer.py                # 净值曲线、回撤图
│
├── strategies/                      # 策略实现（组合以上模块）
│   ├── __init__.py
│   ├── base_strategy.py
│   └── multi_factor_strategy.py
│
├── utils/                           # 工具层
│   ├── __init__.py
│   ├── logger.py
│   ├── date_utils.py                # 交易日历
│   ├── decorators.py                # 计时、重试
│   └── helpers.py
│
├── scripts/                         # 可执行脚本
│   ├── init_db.py                   # 初始化数据库
│   ├── update_data.py               # 每日数据更新
│   ├── run_backtest.py              # 运行回测
│   └── run_daily.py                 # 每日实盘信号
│
├── tests/                           # 单元测试
│   ├── test_connectors.py
│   ├── test_indicators.py
│   ├── test_scoring.py
│   └── test_backtest.py
│
├── notebooks/                       # 研究/探索
│   └── research.ipynb
│
├── logs/                            # 日志输出
├── output/                          # 结果输出（回测报告、图表）
│   ├── reports/
│   └── figures/
│
├── requirements.txt
├── .gitignore
├── README.md
└── main.py                          # 系统入口















































现在完善数据库的功能，数据库需要修改数据库在 本地 mysql security 中， 有四个表，