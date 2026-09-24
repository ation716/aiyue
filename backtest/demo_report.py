"""自含静态SVG报告，无外部资源或JavaScript。"""
from html import escape
import json


def report_html(equity, trades, metadata, config, validation):
    def chart(field, title, multiplier=1):
        vals = [float(r[field]) * multiplier for r in equity]
        low, high = min(vals), max(vals)
        span = high - low or max(abs(high) * .01, 1)
        points = ' '.join(f'{80 + i * 900 / max(1, len(vals)-1):.2f},{260-(v-low)*210/span:.2f}' for i, v in enumerate(vals))
        return (f'<h2>{title}</h2><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1020 310" role="img" aria-label="{title}">'
                f'<path d="M80 35V260H980" fill="none" stroke="#aaa"/>'
                f'<text x="5" y="50">{high:,.2f}</text><text x="5" y="260">{low:,.2f}</text>'
                f'<polyline points="{points}" fill="none" stroke="#2461a8" stroke-width="2"/>'
                f'<text x="80" y="290">{equity[0]["date"]}</text><text x="880" y="290">{equity[-1]["date"]}</text></svg>')
    headers = ['date', 'phase', 'side', 'ts_code', 'price', 'quantity', 'fee', 'cash_after', 'reason', 'signal_date', 'entry_date']
    labels = ['日期', '阶段', '方向', '代码', '价格', '数量', '费用', '可用现金', '原因', '信号日', '买入日']
    table = '<table><thead><tr>' + ''.join(f'<th>{x}</th>' for x in labels) + '</tr></thead><tbody>'
    table += ''.join('<tr>' + ''.join('<td>' + escape(str(r[k])) + '</td>' for k in headers) + '</tr>' for r in trades)
    table += '</tbody></table>'
    disclaimer = '以上内容基于公开数据和量化分析，仅供参考，不构成投资建议。市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标独立判断，必要时咨询持牌专业机构。过往表现不预示未来收益。'
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Demo 真实数据演示</title>'
            '<style>body{font:16px system-ui;color:#172638;background:#f5f7fa;margin:32px auto;max-width:1200px;padding:20px}'
            'section,svg{background:white;border-radius:8px;padding:16px;box-sizing:border-box;width:100%}'
            '.warn{background:#fff0db;padding:18px;border-left:5px solid #bc6f00}table{border-collapse:collapse;font-size:13px;width:100%}'
            'td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}th{background:#e7eef7}pre{white-space:pre-wrap;word-break:break-word}.scroll{overflow:auto}</style>'
            '<h1>Demo · 真实日线数据演示</h1><p class="warn"><strong>零摩擦假设：不是净真实可实现回报。</strong>'
            '未计官方费用、滑点、成交队列和容量；前复权价格及历史ST状态缺失影响可实现性。不得视为已完整排除历史ST/*ST。</p>'
            f'<section>期末总值：{float(equity[-1]["total"]):,.2f} 元 · 区间变化：{float(equity[-1]["return"]):.2%}'
            f' · 交易记录：{len(trades)} 条 · 期末持仓：{equity[-1]["position_count"]}</section>'
            '<p>来源：本机数据库日线长表，经既有只读接口；日期并集为统一日历近似。前60日预热也显示在曲线中。</p>'
            + chart('total', '资金总值（元）') + chart('return', '累计收益（%）', 100)
            + '<h2>覆盖、单位与局限</h2><pre>' + escape(json.dumps(metadata, ensure_ascii=False, indent=2)) + '</pre>'
            + '<h2>真实数据断言</h2><pre>' + escape(json.dumps(validation, ensure_ascii=False, indent=2)) + '</pre>'
            + '<h2>完整配置</h2><pre>' + escape(json.dumps(config, ensure_ascii=False, indent=2)) + '</pre>'
            + '<h2>完整交易记录</h2><div class="scroll">' + table + '</div><p><strong>免责声明：</strong>' + disclaimer + '</p></html>')
