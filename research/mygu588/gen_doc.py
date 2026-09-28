# -*- coding: utf-8 -*-
"""由 fields_condType1.json 生成接口勘察记录 Markdown。"""
import io
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
rows = json.load(io.open(os.path.join(BASE, 'fields_condType1.json'), encoding='utf-8'))
fmap = {r['field']: r for r in rows}

L = []
L.append('# mygu588.cn 高级查询接口勘察记录')
L.append('')
L.append('勘察日期：2026-09-28　站点：https://mygu588.cn（丰谷图文，历史集合竞价数据查询）')
L.append('')
L.append('## 1. 鉴权机制（关键）')
L.append('')
L.append('站点为**页面级鉴权**，不是全局共享会话。要点：')
L.append('')
L.append('1. 需先在 `/arena/`（策略广场）完成微信扫码登录，会话落库。')
L.append('2. 请求 `/vipquery/` 及所有 XHR 接口时，**必须同时具备**：')
L.append('   - `Cookie: csrftoken=...; sessionid=...`（`sessionid` 为 HttpOnly 会话凭证，JS 不可读）')
L.append('   - `Referer: https://mygu588.cn/vipquery/`（服务端校验来源，缺失则回退到登录页）')
L.append('3. 所有接口路径**必须以 `/` 结尾**，否则返回 301 重定向。')
L.append('4. `/vipquery`（无尾斜杠）会跳登录页；`/vipquery/` 且带 Referer 才返回 Vue SPA。')
L.append('')
L.append('登录态校验：`GET /strategy/check-login/` → `{"success": true, "logged_in": true, "userid": "<脱敏>"}`')
L.append('')
L.append('> 排查提示：`document.cookie` 只能看到 `csrftoken`，看不到 `sessionid`（HttpOnly）。')
L.append('> 取凭证需从 F12 → Application → Cookies 面板，或直接用 Network 的 Copy as cURL。')
L.append('')

L.append('## 2. 接口清单')
L.append('')
L.append('| 接口 | 方法 | 功能 | 备注 |')
L.append('|---|---|---|---|')
L.append('| `/vipquery/` | GET | 高级查询页（Vue SPA） | 页面注入 `window.__INITIAL_PARAMS__`、`window.__INITIAL_COND_NAME__` |')
L.append('| `/fields/?condType=N` | GET | 字段定义表 | condType=1 返回 161 字段，含公式与取值范围 |')
L.append('| `/dates/?tb=N` | GET | 可用竞价日期列表 | tb=1 对应高级查询数据集 |')
L.append('| `/showcols/?tb=N` | GET | 页面显示列配置 | 未设置时 `data=null` |')
L.append('| `/savecols/` | POST | 保存显示列配置 | 参数 `{tb, showcols}` |')
L.append('| `/parse/` | POST | 解析查询表达式 | 参数 `{expression, mode}`，mode 默认 `quick` |')
L.append('| `/ai-assist/` | POST | AI 辅助生成查询条件 | |')
L.append('| `/query_dp/?tb=N` | POST | **执行查询（计费接口）** | `multipart/form-data` |')
L.append('| `/api/backtest/` | POST | 收益回测 | 前端超时设置 120s |')
L.append('| `/ai-token-usage/` | GET | AI token 用量 | |')
L.append('| `/strategy/check-login/` | GET | 登录态检查 | |')
L.append('| `/strategy/list/` | GET | 策略条件列表 | |')
L.append('| `/strategy/save/` | POST | 保存策略条件 | |')
L.append('| `/strategy/<id>/` | GET | 读取策略条件 | |')
L.append('| `/strategy/<id>/delete/` | POST | 删除策略条件 | |')
L.append('| `/strategy/set-default/` | POST | 设为默认条件 | 参数 `{condid, type}` |')
L.append('| `/update-info/?key=qupdts` | GET | 数据更新时间 | |')
L.append('')
L.append('其他页面入口（相对 `/arena/`）：`../topquery`（涨停查询）、`../simplequery`（竞价查询）、')
L.append('`../stockmodel`、`../stockalert`、`../dptoday`（今收复盘）、`../historydata`、`../apidoc`。')
L.append('')

L.append('## 3. 计费说明（站点公示）')
L.append('')
L.append('| 项目 | 价格 | 规则 |')
L.append('|---|---|---|')
L.append('| 竞价查询 | 每日 20 次内 0.25 元/次；超出后 0.01 元/次 | 后端查询成功后自动扣除 |')
L.append('| 涨停查询 | 0.01 元/次 | 后端成功即扣 |')
L.append('| 高级查询 | 0.01 元/次 | 后端成功即扣 |')
L.append('| 收益回测 | 0 元 | 图片生成后扣 |')
L.append('')
L.append('相同条件重复查询，在最新一批数据更新完成之前不重复扣费。')
L.append('')

L.append('## 4. 字段体系（condType=1，共 %d 个）' % len(rows))
L.append('')
L.append('每个字段包含 `field` / `title` / `desc`（含计算公式、取值区间、用法示例）/ `min` / `max` / `sort` / `hide`。')
L.append('完整原始定义见同目录 `fields_condType1.json`。')
L.append('')

cats = [
    ('竞价盘口特征', ['dt', 'quopct', 'Ovolpct', 'Ovolpct2', 'Oamt', 'qplinear', 'qcount1', 'qcount2',
                  'qpct', 'qavgpct', 'qhigh', 'qlow', 'vol_times', 'bstimes', 'p2450', 'pct2450',
                  'qhstop', 'qlstop', 'qd1', 'qd1pct', 'Oturn', 'qhigh2', 'lastqamt', 'lastqamtpct',
                  'qamtmax', 'Ovoltimes', 'qf1max', 'buyvsumpct', 'sellvsumpct', 'mpct', 'cpct',
                  'maxqv1pct', 'maxqbotpct', 'jump', 'xy']),
    ('涨停与顶底结构', ['stop', 'istoppre', 'ostop', 'hstop', 'zstop', 'zstop5', 'hstoppre', 'hotblk',
                   'hotblk_pre', '3up', '5up', '10up', '3down', '5down', '10low_rk', '60low_rk',
                   '250low_rk', '250low', '5high', '5hhigh', '10high', '10high_pre', '20high',
                   '60high', '60high_pre', '60high_pre2', '120hhigh', 'highclose', 'closelow',
                   'topavgp', 'topavgup', 'topbreak', 'topturn', 'toptime', 'climedur', 'climeturn',
                   'climeavgup', 'lowdif', 'highdif', 'daytop']),
    ('涨跌幅与趋势', ['cp', 'cp_rk', 'cy', 'cy_rk', 'p_2', 'p_2_rk', 'p_3', 'p_3_rk', 'p_5', 'p_5_rk',
                  'p_10', 'p_10_rk', 'p_20', 'p_20_rk', 'p_60', 'p_60_rk', 'linear5', 'linear10',
                  'linear20', 'linear60', 'vlinear5', 'vlinear10', 'p1next', 'p1next2', 'p2next',
                  'p2next2', 'risetimes', 'longhighpct1', 'dpop']),
    ('量能与换手', ['swing', 'swingMA_3', 'swingMA_10', 'volpct', 'volpct_pre', 'amount', 'amount_rk',
                 'amt_ma2_rk', 'amt_ma3', 'amt_ma3_rk', 'amt_ma5_rk', 'turn', 'turn_pre', 'turnMA_3',
                 'unlock_vol', 'avg_m']),
    ('技术指标与资金', ['dea', 'dif', 'hist', 'histpre', 'ddx', 'ddx_pre', 'ddxdays', 'bbd', 'bbd_pre',
                   'bbd_3', 'bbd_5', 'rzrq', 'freecapm', 'freecapshare', 'holdernum', 'change_pct',
                   'pftop1', 'pftop10']),
    ('均线与其他', ['MA_5', 'MA_10', 'MA_20', 'MA_60', 'avgp', 'closeopen', 'closeopen_pre',
                 'closeopen_pre2', 'shadowup', 'shadowdown', 'shadowup_pre', 'shadowdown_pre',
                 'st', 'listing_days', 'stockname', 'stock', 'close']),
]

for i, (cname, fl) in enumerate(cats, start=1):
    got = [f for f in fl if f in fmap]
    L.append('### 4.%d %s（%d）' % (i, cname, len(got)))
    L.append('')
    L.append('| field | 中文名 | 说明摘要 |')
    L.append('|---|---|---|')
    for f in got:
        r = fmap[f]
        d = (r.get('desc') or '').split('\n')[0]
        for sep in ('。', '；'):
            if sep in d:
                d = d.split(sep)[0]
                break
        d = d[:110].replace('|', '/')
        L.append('| `%s` | %s | %s |' % (f, r.get('title', ''), d))
    L.append('')

L.append('## 5. 查询表达式机制')
L.append('')
L.append('查询为**表达式驱动**：用户条件（或 AI 辅助生成）先 POST 到 `/parse/` 解析成结构化条件，')
L.append('再 POST 到 `/query_dp/?tb=1` 执行。')
L.append('')
L.append('`/query_dp/` 返回体包含 `count` 及聚合统计字段：`p1next_avg`、`p1next2_avg`、')
L.append('`p2next_avg`、`p2next2_avg`（即 T1/T2 的开盘收益与收盘收益均值）。')
L.append('')
L.append('### 关键字段语义示例')
L.append('')
for f in ['op', 'quopct', 'qplinear', 'vol_times', 'bstimes']:
    r = fmap.get(f)
    if r:
        L.append('- **%s**（`%s`）：%s' % (r.get('title'), f, r.get('desc', '')))
L.append('')

L.append('## 6. 官方 API（独立体系，非本页接口）')
L.append('')
L.append('站点另提供策略信号 API，位于 `/wechat/api/`，使用 **32 位 API key**（非 cookie）鉴权，')
L.append('key 从「我的信息」页面获取：')
L.append('')
L.append('| 端点 | 功能 |')
L.append('|---|---|')
L.append('| `/wechat/api/strategy_signals/` | 查询订阅策略的当日信号 |')
L.append('| `/wechat/api/user_info/` | 用户信息与余额 |')
L.append('| `/wechat/api/subscription_list/` | 订阅策略列表 |')
L.append('| `/wechat/api/qxzs/` | 竞价情绪指数（活跃股 / 高位股） |')
L.append('')
L.append('限频建议每分钟不超过 20 次；策略信号于交易日 9:25:50 后更新。')
L.append('返回码：`0` 成功、`1` 无订阅策略、`2` 余额不足、`-1` 参数错误、`-2` 服务端异常、`-3` 数据未就绪。')
L.append('')
L.append('注意：该 API **不提供**高级查询（自定义条件筛选历史竞价数据）能力。')
L.append('')

L.append('## 7. 未完成事项')
L.append('')
L.append('- `/query_dp/` 的实际请求参数结构尚未实测（构造表达式会产生扣费）')
L.append('- `/parse/` 的表达式语法尚未逆向')
L.append('- `condType` 其他取值对应的字段集未勘察')
L.append('- 高级查询结果的数据结构与出图流程未验证')
L.append('- `/api/backtest/` 请求与响应结构未勘察')
L.append('')

out = os.path.join(BASE, 'API_勘察记录.md')
io.open(out, 'w', encoding='utf-8').write('\n'.join(L))
print('written:', out)
print('lines:', len(L))
