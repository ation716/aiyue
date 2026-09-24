"""Demo 唯一入口：真实只读数据、隔离结果、断言及静态报告。"""
import argparse
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding='utf-8')


def configuration(experiment='E02'):
    if not re.fullmatch(r'E\d{2,}', experiment):
        raise ValueError('实验编号格式无效')
    text = (ROOT / 'traces/demo.md').read_text(encoding='utf-8')
    sections = re.findall(r'^## (E\d+)\b[^\n]*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    selected = [body for number, body in sections if number == experiment]
    if len(selected) != 1:
        raise ValueError('档案必须有且仅有一个对应实验节')
    snapshots = re.findall(r'```json\s*(.*?)\s*```', selected[0], re.S)
    if len(snapshots) != 1:
        raise ValueError('实验节必须有且仅有一个配置快照')
    cfg = json.loads(snapshots[0])
    if cfg.get('experiment') != experiment or cfg.get('strat') != 'demo':
        raise ValueError('配置与实验编号不一致')
    return cfg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--validate-only', type=Path)
    parser.add_argument('--experiment', default='E02')
    args = parser.parse_args()
    import numpy as np
    import pandas as pd
    from data.connectors.db_connector import DBConnector
    from scoring.demo import demo_candidates
    from backtest.demo import run_demo, validate_results
    from backtest.demo_report import report_html

    if args.validate_only:
        directory = args.validate_only.resolve()
        values = [json.loads((directory / f'{name}.json').read_text(encoding='utf-8'))
                  for name in ('trades', 'equity', 'positions', 'config')]
        print(json.dumps(validate_results(*values), ensure_ascii=True))
        return
    cfg = configuration(args.experiment)
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    directory = ROOT / 'results/demo' / args.experiment / run_id
    directory.mkdir(parents=True, exist_ok=False)
    dump(directory / 'config.json', cfg)
    metadata = {'run_id': run_id, 'created_at': datetime.now().isoformat(),
                'python': sys.executable, 'python_version': platform.python_version(),
                'pandas_version': pd.__version__, 'numpy_version': np.__version__,
                'source': cfg['daily_table'], 'config_sha256': hashlib.sha256(
                    json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                'assumption': '零费用零滑点演示；不是净真实可实现回报',
                'limitations': ['日线价格为前复权，不能还原真实限制价格',
                                '名称映射是当前状态而非历史ST状态，不能保证全部排除历史ST/*ST',
                                '名称缺失对象排除，当前映射存在幸存者偏差与时点偏差',
                                '日期并集不是独立官方日历，整日缺失可能无法识别',
                                '仅日K，不知道盘中先后、排队、真实成交容量；vol/amount仅事后有效性校验',
                                '缺日不能成交，缺日持仓按最后已知close估值；期末不强制清仓']}
    stage = 'static_validation'
    try:
        source_files = ['scoring/demo.py', 'portfolio/demo.py', 'backtest/demo.py',
                        'backtest/demo_report.py', 'scripts/run_demo.py']
        hashes = {}
        for name in source_files:
            content = (ROOT / name).read_text(encoding='utf-8')
            ast.parse(content, filename=name)
            hashes[name] = hashlib.sha256(content.encode()).hexdigest()
        metadata['code_sha256'] = hashes
        connector = DBConnector()
        connector.options['read_timeout'] = cfg['query_timeout_seconds']
        stage = 'connect'
        with connector as db:
            stage = 'names'
            members = db.get_concept_members()
            known = set(members.loc[members.stock_name.notna() & members.stock_name.str.strip().ne(''), 'ts_code'])
            banned = set(members.loc[members.stock_name.fillna('').str.contains('ST', case=False, regex=False), 'ts_code'])
            frames = []
            all_dates, unknown_names = set(), set()
            raw_rows = 0
            raw_hash = hashlib.sha256()
            metadata['monthly_reads'] = []
            periods = pd.period_range(cfg['start'], cfg['end'], freq='M')
            for number, period in enumerate(periods, 1):
                start = max(pd.Timestamp(cfg['start']), period.start_time).date()
                end = min(pd.Timestamp(cfg['end']), period.end_time).date()
                stage = 'daily_' + str(period)
                frame = db.get_daily(start_date=start, end_date=end)
                metadata['monthly_reads'].append({'month': str(period), 'rows': len(frame),
                    'start': str(frame.trade_date.min().date()) if len(frame) else None,
                    'end': str(frame.trade_date.max().date()) if len(frame) else None})
                if frame.empty:
                    raise ValueError('请求月份完全无真实日线，停止而不补造')
                if frame.duplicated(['ts_code', 'trade_date']).any():
                    raise ValueError('日线存在重复主键')
                raw_rows += len(frame)
                all_dates.update(frame.trade_date.unique())
                raw_hash.update(pd.util.hash_pandas_object(frame, index=False).values.tobytes())
                board = frame.ts_code.str.match(r'^(?:000|001|002|003)\d{3}\.SZ$|^(?:600|601|603|605)\d{3}\.SH$')
                unknown_names.update(frame.loc[board & ~frame.ts_code.isin(known), 'ts_code'])
                frames.append(frame.loc[board & frame.ts_code.isin(known - banned)].copy())
                print(f'fetch {number}/{len(periods)} rows={len(frame)}', flush=True)
                del frame
        stage = 'data_validation'
        calendar = pd.DatetimeIndex(sorted(all_dates))
        metadata.update({'raw_rows': raw_rows, 'actual_start': str(calendar[0].date()),
                         'actual_end': str(calendar[-1].date()), 'calendar_days': len(calendar)})
        if len(calendar) <= cfg['warmup_days'] or calendar[-1] != pd.Timestamp(cfg['end']):
            raise ValueError('真实数据未覆盖指定截止日或预热不足')
        daily = pd.concat(frames, ignore_index=True)
        frames.clear()
        if daily.empty:
            raise ValueError('名称过滤后没有真实数据')
        numeric = ['open', 'high', 'low', 'close', 'vol', 'amount', 'turnover_rate', 'float_mv', 'outstanding_share']
        for column in numeric:
            daily[column] = pd.to_numeric(daily[column], errors='coerce')
        valid_ohlc = daily[['open', 'high', 'low', 'close']].notna().all(axis=1)
        inconsistent = valid_ohlc & ((daily.high < daily[['open', 'close', 'low']].max(axis=1))
                                    | (daily.low > daily[['open', 'close', 'high']].min(axis=1)))
        if inconsistent.any():
            raise ValueError('真实OHLC存在不一致记录，需要检查原数据')
        unit_sample = daily.loc[(daily.close > 0) & (daily.outstanding_share > 0) & (daily.float_mv > 0)]
        ratio = unit_sample.float_mv / (unit_sample.close * unit_sample.outstanding_share)
        metadata.update({'requested_start': cfg['start'], 'requested_end': cfg['end'],
                         'actual_start': str(calendar[0].date()), 'actual_end': str(calendar[-1].date()),
                         'calendar_days': len(calendar), 'warmup_end': str(calendar[cfg['warmup_days']-1].date()),
                         'first_execution_day': str(calendar[cfg['warmup_days']].date()),
                         'raw_rows': raw_rows, 'eligible_rows': len(daily), 'eligible_symbols': daily.ts_code.nunique(),
                         'known_name_symbols': len(known), 'excluded_current_st_symbols': len(banned),
                         'unknown_name_mainboard_symbols': len(unknown_names),
                         'size_semantics': '仅float_mv，元，流通市值估算；日线没有提供总市值',
                         'units_source': 'data/database.md第4.2节；标准接口字段与实际数值比率核对，未查询字段元数据',
                         'float_mv_to_close_times_shares_median': float(ratio.median()) if len(ratio) else None,
                         'turnover_rate_quantiles': {str(k): float(v) for k, v in daily.turnover_rate.quantile([.01,.5,.99]).items()},
                         'missing_numeric_values': {k: int(v) for k,v in daily[numeric].isna().sum().items()},
                         'data_sha256': raw_hash.hexdigest(),
                         'data_hash_order': '按月顺序，每月ts_code/trade_date排序，原始行哈希流'})
        dump(directory / 'metadata.json', metadata)
        stage = 'candidate_generation'
        signals = demo_candidates(daily, calendar, cfg)
        # 真实数据截断重算：验证未来尾部不改变过去的候选。
        cutoff = calendar[len(calendar)//2]
        truncated = demo_candidates(daily.loc[daily.trade_date <= cutoff], calendar[calendar <= cutoff], cfg)
        pd.testing.assert_frame_equal(signals.loc[signals.trade_date <= cutoff].reset_index(drop=True), truncated.reset_index(drop=True))
        stage = 'backtest'
        trades, equity, positions, checks = run_demo(daily, calendar, signals, cfg)
        validation = validate_results(trades, equity, positions, cfg)
        validation.update({'runtime_checks': checks, 'prefix_invariance': 'passed', 'ast_files': len(hashes),
                           'generated_signal_rows': len(signals), 'real_data_only': True})
        # 独立核对每笔买入必须来自紧邻前日真实候选。
        signal_keys = {(str(r.trade_date.date()), r.ts_code) for r in signals.itertuples()}
        date_index = {str(d.date()): i for i,d in enumerate(calendar)}
        for row in trades:
            if row['side'] == 'buy':
                assert (row['signal_date'], row['ts_code']) in signal_keys
                assert date_index[row['date']] - date_index[row['signal_date']] == 1
        for name, value in [('signals', signals.to_dict('records')), ('trades', trades), ('equity', equity),
                            ('positions', positions), ('validation', validation)]:
            dump(directory / f'{name}.json', value)
        html = report_html(equity, trades, metadata, cfg, validation)
        assert '<script' not in html and html.count('<svg ') == 2
        (directory / 'report.html').write_text(html, encoding='utf-8')
        delivery = ROOT / 'outputs' / run_id
        delivery.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(directory / 'report.html', delivery / 'demo.html')
        print(json.dumps({'status': 'passed', 'run_id': run_id, 'trades': len(trades),
                          'signals': len(signals), 'final_total': equity[-1]['total'],
                          'return': equity[-1]['return']}, ensure_ascii=True))
    except Exception as error:
        # 不输出连接参数或原始异常消息，避免任何凭据进入日志。
        dump(directory / 'metadata.json', metadata)
        error_code = error.args[0] if error.args and isinstance(error.args[0], int) else None
        dump(directory / 'error.json', {'status': 'blocked', 'stage': stage, 'error_type': type(error).__name__,
                                       'error_code': error_code,
                                       'message': '真实读取或验证失败；未生成成功报告，无自动重试、无替代数据。'})
        print(json.dumps({'status': 'blocked', 'run_id': run_id, 'stage': stage,
                          'error_type': type(error).__name__, 'error_code': error_code}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
