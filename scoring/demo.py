"""Demo 候选；所有滚动计算只使用当日及以前真实记录。"""
import numpy as np
import pandas as pd


def demo_candidates(daily, calendar, config):
    if daily.duplicated(['ts_code', 'trade_date']).any():
        raise ValueError('日线主键重复')
    frames = []
    dates = pd.DatetimeIndex(calendar)
    for code, group in daily.groupby('ts_code', sort=True):
        g = group.sort_values('trade_date').set_index('trade_date')
        close = g.close.where(np.isfinite(g.close) & g.close.gt(0))
        valid = close.dropna()
        mean = valid.rolling(config['window'], min_periods=config['window']).mean()
        median = valid.rolling(config['window'], min_periods=config['window']).median()
        aligned = close.reindex(dates)
        means = mean.reindex(dates)
        medians = median.reindex(dates)
        change = aligned / aligned.shift(config['change_days']) - 1
        eligible = ((aligned.shift(1) <= means.shift(1)) & (aligned > means)
                    & (medians < means * config['median_ratio'])
                    & (change > config['change_min']))
        g = g.reindex(dates)
        eligible &= (g[config['size_field']] > config['size_min'])
        eligible &= np.isfinite(g.turnover_rate) & g.turnover_rate.ge(0)
        eligible &= np.isfinite(g[config['size_field']])
        selected = g.loc[eligible, ['close', 'turnover_rate', config['size_field']]].copy()
        selected['ts_code'] = code
        selected['mean60'] = means.loc[eligible]
        selected['median60'] = medians.loc[eligible]
        selected['change5'] = change.loc[eligible]
        selected.index.name = 'trade_date'
        frames.append(selected.reset_index())
    columns = ['trade_date', 'close', 'turnover_rate', config['size_field'], 'ts_code', 'mean60', 'median60', 'change5']
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
    return result.sort_values(['trade_date', 'turnover_rate', config['size_field']],
                              ascending=[True, False, True], kind='stable').reset_index(drop=True)
