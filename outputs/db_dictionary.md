# DB 数据字典（只读核验版）

> 核验时间：2026-09-21T13:19:01+08:00。
> 来源：本机 DB 元数据及只读聚合查询；未修改表结构或数据。

## 连接与范围

- 本机：127.0.0.1:3306；版本：9.3.0；字符集：utf8mb4。
- 凭据不写入本文。会话设置为只读，单条聚合查询限时 20 秒。
- 当前账号可见对象数：6；原稿列出 5 张，本次另确认 T5。
- 字段以表内顺序编号 F01、F02 等表示；真实字段和表名对照保存在结构映射代码中。
- 默认值为空的元数据不能单独区分“未声明默认值”和“显式 DEFAULT NULL”。

## 实际覆盖汇总

| 表 | 精确行数 | 起始日期 | 结束日期 | 日期数 | 对象数 |
|---|---:|---|---|---:|---:|
| T1 | 3546891 | 2022-01-04 | 2026-09-17 | 1142 | 3196 |
| T2 | 4568 | 2022-01-04 | 2026-09-17 | 1142 | 4 |
| T3 | 16226 | 不适用 | 不适用 | 不适用 | 4150 |
| T4 | 1555602 | 2023-01-03 | 2025-01-24 | 501 | 3139 |
| T5 | 674 | 2026-08-28 | 2026-09-17 | 14 | 不适用 |
| T7 | 1390 | 2026-08-28 | 2026-09-17 | 15 | 768 |

## T1 字段与约束

| 字段代号 | 语义标识 | 类型 | 可空 | 默认值 | 键标记 | 附加属性 |
|---|---|---|---|---|---|---|
| F01 | id | bigint | NO | 未提供/NULL | PRI | auto_increment |
| F02 | ts_code | varchar(16) | NO | 未提供/NULL | MUL | — |
| F03 | symbol | varchar(8) | NO | 未提供/NULL | — | — |
| F04 | tx_date | date | NO | 未提供/NULL | MUL | — |
| F05 | open | decimal(12,4) | YES | 未提供/NULL | — | — |
| F06 | high | decimal(12,4) | YES | 未提供/NULL | — | — |
| F07 | low | decimal(12,4) | YES | 未提供/NULL | — | — |
| F08 | close | decimal(12,4) | YES | 未提供/NULL | — | — |
| F09 | change_amount | decimal(12,4) | YES | 未提供/NULL | — | — |
| F10 | pct_chg | decimal(10,4) | YES | 未提供/NULL | — | — |
| F11 | vol | decimal(20,4) | YES | 未提供/NULL | — | — |
| F12 | amount | decimal(20,4) | YES | 未提供/NULL | — | — |
| F13 | turnover_rate | decimal(10,4) | YES | 未提供/NULL | — | — |
| F14 | outstanding_share | decimal(20,2) | YES | 未提供/NULL | — | — |
| F15 | float_mv | decimal(26,4) | YES | 未提供/NULL | — | — |

### 已确认键结构

- K01：普通检索键；BTREE；字段顺序：F04。
- K02：主键；BTREE；字段顺序：F01。
- K03：唯一键；BTREE；字段顺序：F02, F04。
- 已声明外键数：0。

## T2 字段与约束

| 字段代号 | 语义标识 | 类型 | 可空 | 默认值 | 键标记 | 附加属性 |
|---|---|---|---|---|---|---|
| F01 | id | bigint | NO | 未提供/NULL | PRI | auto_increment |
| F02 | ts_code | varchar(16) | NO | 未提供/NULL | MUL | — |
| F03 | symbol | varchar(8) | NO | 未提供/NULL | MUL | — |
| F04 | tx_date | date | NO | 未提供/NULL | MUL | — |
| F05 | open | decimal(12,4) | YES | 未提供/NULL | — | — |
| F06 | high | decimal(12,4) | YES | 未提供/NULL | — | — |
| F07 | low | decimal(12,4) | YES | 未提供/NULL | — | — |
| F08 | close | decimal(12,4) | YES | 未提供/NULL | — | — |
| F09 | pre_close | decimal(12,4) | YES | 未提供/NULL | — | — |
| F10 | change_amount | decimal(12,4) | YES | 未提供/NULL | — | — |
| F11 | pct_chg | decimal(10,4) | YES | 未提供/NULL | — | — |
| F12 | vol | decimal(20,4) | YES | 未提供/NULL | — | — |
| F13 | amount | decimal(20,4) | YES | 未提供/NULL | — | — |
| F14 | rsi24_ema | decimal(10,4) | YES | 未提供/NULL | — | — |
| F15 | rsi12_ema | decimal(10,4) | YES | 未提供/NULL | — | — |
| F16 | rsi6_ema | decimal(10,4) | YES | 未提供/NULL | — | — |
| F17 | turnover_rate | decimal(10,4) | YES | 未提供/NULL | — | — |
| F18 | kdj_rsv | decimal(10,4) | YES | 未提供/NULL | — | — |
| F19 | kdj_k | decimal(10,4) | YES | 未提供/NULL | — | — |
| F20 | kdj_d | decimal(10,4) | YES | 未提供/NULL | — | — |
| F21 | kdj_j | decimal(10,4) | YES | 未提供/NULL | — | — |
| F22 | mfi14 | decimal(10,4) | YES | 未提供/NULL | — | — |
| F23 | obv | decimal(24,4) | YES | 未提供/NULL | — | — |
| F24 | rsi6 | decimal(10,4) | YES | 未提供/NULL | — | — |
| F25 | rsi12 | decimal(10,4) | YES | 未提供/NULL | — | — |
| F26 | rsi24 | decimal(10,4) | YES | 未提供/NULL | — | — |
| F27 | source | varchar(32) | NO | unknown | — | — |
| F28 | created_at | datetime | NO | CURRENT_TIMESTAMP | — | DEFAULT_GENERATED |
| F29 | updated_at | datetime | NO | CURRENT_TIMESTAMP | — | DEFAULT_GENERATED on update CURRENT_TIMESTAMP |

### 已确认键结构

- K01：普通检索键；BTREE；字段顺序：F03。
- K02：普通检索键；BTREE；字段顺序：F04。
- K03：主键；BTREE；字段顺序：F01。
- K04：唯一键；BTREE；字段顺序：F02, F04。
- 已声明外键数：0。

## T3 字段与约束

| 字段代号 | 语义标识 | 类型 | 可空 | 默认值 | 键标记 | 附加属性 |
|---|---|---|---|---|---|---|
| F01 | id | bigint | NO | 未提供/NULL | PRI | auto_increment |
| F02 | ts_code | varchar(16) | NO | 未提供/NULL | MUL | — |
| F03 | symbol | varchar(8) | NO | 未提供/NULL | — | — |
| F04 | symbol_name | varchar(32) | YES | 未提供/NULL | — | — |
| F05 | cpt_name | varchar(64) | NO | 未提供/NULL | MUL | — |
| F06 | updated_at | datetime | NO | CURRENT_TIMESTAMP | — | DEFAULT_GENERATED on update CURRENT_TIMESTAMP |

### 已确认键结构

- K01：普通检索键；BTREE；字段顺序：F05。
- K02：普通检索键；BTREE；字段顺序：F02。
- K03：主键；BTREE；字段顺序：F01。
- K04：唯一键；BTREE；字段顺序：F02, F05。
- 已声明外键数：0。

## T4 字段与约束

| 字段代号 | 语义标识 | 类型 | 可空 | 默认值 | 键标记 | 附加属性 |
|---|---|---|---|---|---|---|
| F01 | id | bigint | NO | 未提供/NULL | PRI | auto_increment |
| F02 | ts_code | varchar(16) | NO | 未提供/NULL | MUL | — |
| F03 | symbol | varchar(8) | NO | 未提供/NULL | — | — |
| F04 | tx_date | date | NO | 未提供/NULL | MUL | — |
| F05 | open | decimal(12,4) | YES | 未提供/NULL | — | — |
| F06 | high | decimal(12,4) | YES | 未提供/NULL | — | — |
| F07 | low | decimal(12,4) | YES | 未提供/NULL | — | — |
| F08 | close | decimal(12,4) | YES | 未提供/NULL | — | — |
| F09 | change_amount | decimal(12,4) | YES | 未提供/NULL | — | — |
| F10 | pct_chg | decimal(10,4) | YES | 未提供/NULL | — | — |
| F11 | vol | decimal(20,4) | YES | 未提供/NULL | — | — |
| F12 | amount | decimal(20,4) | YES | 未提供/NULL | — | — |
| F13 | turnover_rate | decimal(10,4) | YES | 未提供/NULL | — | — |
| F14 | outstanding_share | decimal(20,2) | YES | 未提供/NULL | — | — |
| F15 | float_mv | decimal(26,4) | YES | 未提供/NULL | — | — |

### 已确认键结构

- K01：普通检索键；BTREE；字段顺序：F04。
- K02：主键；BTREE；字段顺序：F01。
- K03：唯一键；BTREE；字段顺序：F02, F04。
- 已声明外键数：0。

## T5 字段与约束

| 字段代号 | 语义标识 | 类型 | 可空 | 默认值 | 键标记 | 附加属性 |
|---|---|---|---|---|---|---|
| F01 | id | bigint | NO | 未提供/NULL | PRI | auto_increment |
| F02 | tx_date | date | NO | 未提供/NULL | MUL | — |
| F03 | sector | varchar(64) | NO | 未提供/NULL | — | — |
| F04 | zt_cnt | int | NO | 0 | — | — |
| F05 | dt_cnt | int | NO | 0 | — | — |
| F06 | zb_cnt | int | NO | 0 | — | — |
| F07 | zt_codes | text | YES | 未提供/NULL | — | — |
| F08 | dt_codes | text | YES | 未提供/NULL | — | — |
| F09 | zb_codes | text | YES | 未提供/NULL | — | — |
| F10 | strength | int | NO | 0 | — | — |
| F11 | updated_at | datetime | NO | CURRENT_TIMESTAMP | — | DEFAULT_GENERATED on update CURRENT_TIMESTAMP |

### 已确认键结构

- K01：普通检索键；BTREE；字段顺序：F02。
- K02：主键；BTREE；字段顺序：F01。
- K03：唯一键；BTREE；字段顺序：F02, F03。
- 已声明外键数：0。

## T7 字段与约束

| 字段代号 | 语义标识 | 类型 | 可空 | 默认值 | 键标记 | 附加属性 |
|---|---|---|---|---|---|---|
| F01 | id | bigint | NO | 未提供/NULL | PRI | auto_increment |
| F02 | pool_type | varchar(4) | NO | 未提供/NULL | MUL | — |
| F03 | tx_date | date | NO | 未提供/NULL | MUL | — |
| F04 | ts_code | varchar(16) | NO | 未提供/NULL | — | — |
| F05 | name | varchar(32) | YES | 未提供/NULL | — | — |
| F06 | sector | varchar(64) | YES | 未提供/NULL | MUL | — |
| F07 | pct_chg | decimal(10,4) | YES | 未提供/NULL | — | — |
| F08 | close | decimal(12,4) | YES | 未提供/NULL | — | — |
| F09 | limit_price | decimal(12,4) | YES | 未提供/NULL | — | — |
| F10 | turn | decimal(10,4) | YES | 未提供/NULL | — | — |
| F11 | amount | decimal(20,2) | YES | 未提供/NULL | — | — |
| F12 | float_mv | decimal(20,2) | YES | 未提供/NULL | — | — |
| F13 | total_mv | decimal(20,2) | YES | 未提供/NULL | — | — |
| F14 | lmt_up_cnt | int | YES | 未提供/NULL | — | — |
| F15 | break_cnt | int | YES | 未提供/NULL | — | — |
| F16 | first_limit_time | varchar(8) | YES | 未提供/NULL | — | — |
| F17 | last_limit_time | varchar(8) | YES | 未提供/NULL | — | — |
| F18 | seal_money | decimal(20,2) | YES | 未提供/NULL | — | — |
| F19 | created_at | datetime | NO | CURRENT_TIMESTAMP | — | DEFAULT_GENERATED |
| F20 | updated_at | datetime | NO | CURRENT_TIMESTAMP | — | DEFAULT_GENERATED on update CURRENT_TIMESTAMP |

### 已确认键结构

- K01：普通检索键；BTREE；字段顺序：F06。
- K02：普通检索键；BTREE；字段顺序：F03。
- K03：主键；BTREE；字段顺序：F01。
- K04：唯一键；BTREE；字段顺序：F02, F03, F04。
- 已声明外键数：0。

## 已发现的口径问题与后续核验

- T1/T4 的结构注释将 amt 标为元、vol 标为手；T2 的注释只给出常见单位，不能据此保证实际导入单位一致。T7 的 amt 注释为元。尚未检查导入代码。
- T3 结构含 cpt 映射和更新时间，没有独立的 sector 字段，也没有生效/失效日期列；不能仅凭当前结构恢复历史有效期。
- T1/T4 的字段结构需结合实际数据来源确认 adj 口径；本次未查询逐行差异、缺失率或异常值。
- T2 的对象数来自实际去重计数；覆盖集合重叠与汇总完整性仍未验证，不能直接累加解释为全量。
- T5 是 sector 汇总结构；T7 是 ev 明细结构。本次未验证两表聚合一致性。
- COLUMN_KEY 中 MUL 不等于已声明外键；复合唯一键以各表键结构为准。
- 各表统计是逐条只读查询，并非跨表同一快照；并发更新可能造成时点差异。
- 本次没有创建或运行实验；不据此给出业务效果结论。
