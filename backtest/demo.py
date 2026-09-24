"""仅日K三阶段演示执行；不声称日线能证明真实成交。"""
from decimal import Decimal, ROUND_HALF_UP
import math

from portfolio.demo import ultimate_distribute


def dec(value):
    return Decimal(str(value))


def price(value):
    return dec(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def match(bar, previous, side, limit, phase, stop=False):
    o, h, l, c = (price(bar[k]) for k in ('open', 'high', 'low', 'close'))
    up, down = price(dec(previous) * Decimal('1.10')), price(dec(previous) * Decimal('0.90'))
    if phase in ('open', 'close'):
        p = o if phase == 'open' else c
        if side == 'buy':
            return p if p < up and p <= limit else None
        triggered = p <= limit if stop else p >= limit
        return p if p > down and triggered else None
    if not l < limit < h:
        return None
    if side == 'buy':
        return limit if limit < up and (h != c or l < o) else None
    return limit if limit > down and (l != c or h > o) else None


def run_demo(daily, calendar, signals, config):
    dates = list(calendar)
    bars = {day: g.set_index('ts_code').to_dict('index') for day, g in daily.groupby('trade_date')}
    candidates = {day: g.to_dict('records') for day, g in signals.groupby('trade_date')}
    cash = dec(config['initial_cash'])
    positions, trades, equity, snapshots = {}, [], [], []
    fee_rate, min_fee, slip = (dec(config[k]) for k in ('fee_rate', 'min_fee', 'slippage'))
    if slip != 0:
        raise ValueError('本版仅支持已登记的零滑点，不隐式更改成交模型')
    checks = {'cash_checks': 0, 'accounting_checks': 0, 'position_checks': 0,
              't1_checks': 0, 'signal_checks': 0, 'missing_day_blocks': 0}

    def fee(value):
        return price(max(min_fee, value * fee_rate))

    def execute(side, code, px, qty, day, phase, reason, signal_day, entry_day):
        nonlocal cash
        value = px * qty
        cost = fee(value)
        cash += value - cost if side == 'sell' else -value - cost
        assert cash >= 0
        assert qty > 0 and qty % config['lot_size'] == 0
        checks['cash_checks'] += 1
        trades.append({'date': str(day.date()), 'phase': phase, 'side': side, 'ts_code': code,
                       'price': str(px), 'quantity': qty, 'value': str(value), 'fee': str(cost),
                       'cash_after': str(cash), 'reason': reason,
                       'signal_date': str(signal_day.date()), 'entry_date': str(entry_day.date())})

    for index, day in enumerate(dates):
        current = bars.get(day, {})
        prior_day = dates[index - 1] if index else None
        prior = bars.get(prior_day, {})
        sold_today, bought_today = set(), set()

        def usable(code):
            b, p = current.get(code), prior.get(code)
            if b is None or p is None:
                checks['missing_day_blocks'] += 1
                return False
            values = [b.get(k) for k in ('open', 'high', 'low', 'close', 'vol', 'amount')] + [p.get('close')]
            return all(v is not None and math.isfinite(float(v)) and v > 0 for v in values)

        pending = candidates.get(prior_day, []) if index >= config['warmup_days'] else []
        for phase in ('open', 'intraday', 'close'):
            before_sell_cash = cash
            for code, pos in list(positions.items()):
                if pos['entry_index'] == index or not usable(code):
                    continue
                b, previous = current[code], prior[code]['close']
                sl = price(pos['entry_price'] * (1 - dec(config['stop_loss'])))
                tp = price(pos['entry_price'] * (1 + dec(config['take_profit'])))
                px = match(b, previous, 'sell', sl, phase, stop=True)
                reason = 'sl'
                if px is None:
                    px = match(b, previous, 'sell', tp, phase)
                    reason = 'tp'
                if px is None and phase == 'close' and index - pos['entry_index'] + 1 >= config['hold_days']:
                    px = match(b, previous, 'sell', Decimal('0'), phase)
                    reason = 'hold_days'
                if px is not None:
                    assert index > pos['entry_index']
                    checks['t1_checks'] += 1
                    execute('sell', code, px, pos['quantity'], day, phase, reason,
                            pos['signal_day'], pos['entry_day'])
                    del positions[code]
                    sold_today.add(code)
            # 盘中先后不可知，本阶段不得使用该阶段卖出才产生的现金。
            available = min(cash, before_sell_cash) if phase == 'intraday' else cash
            symbol_list = [r['ts_code'] for r in pending
                           if r['ts_code'] not in sold_today and r['ts_code'] not in bought_today]
            allocation = ultimate_distribute(symbol_list, positions=positions,
                                             available_cash=available, max_positions=config['max_positions'])
            for code, budget in allocation.items():
                if not usable(code):
                    continue
                previous = prior[code]['close']
                limit = price(dec(previous) * dec(config['buy_ratio']))
                px = match(current[code], previous, 'buy', limit, phase)
                if px is None:
                    continue
                lot = config['lot_size']
                budget = min(budget, cash)
                quantity = max(0, int((budget - min_fee) / (px * (1 + fee_rate))) // lot * lot)
                while quantity > 0 and px * quantity + fee(px * quantity) > budget:
                    quantity -= lot
                if not quantity:
                    continue
                assert prior_day < day and prior_day == dates[index - 1]
                assert index >= config['warmup_days']
                checks['signal_checks'] += 1
                execute('buy', code, px, quantity, day, phase, 'previous_day_signal', prior_day, day)
                positions[code] = {'quantity': quantity, 'entry_price': px, 'entry_index': index,
                                   'entry_day': day, 'signal_day': prior_day, 'last_price': px,
                                   'valuation_day': day}
                bought_today.add(code)
            assert len(positions) <= config['max_positions']
            checks['position_checks'] += 1
        market_value, stale = Decimal('0'), 0
        for code, pos in positions.items():
            bar = current.get(code)
            if bar and bar['close'] is not None and math.isfinite(float(bar['close'])) and bar['close'] > 0:
                pos['last_price'] = price(bar['close'])
                pos['valuation_day'] = day
            if pos['valuation_day'] != day:
                stale += 1
            value = pos['last_price'] * pos['quantity']
            market_value += value
            snapshots.append({'date': str(day.date()), 'ts_code': code, 'quantity': pos['quantity'],
                              'entry_date': str(pos['entry_day'].date()), 'entry_price': str(pos['entry_price']),
                              'valuation_price': str(pos['last_price']),
                              'valuation_date': str(pos['valuation_day'].date()), 'value': str(value)})
        total = cash + market_value
        assert total == cash + sum((p['quantity'] * p['last_price'] for p in positions.values()), Decimal('0'))
        assert cash >= 0
        checks['accounting_checks'] += 1
        equity.append({'date': str(day.date()), 'cash': str(cash), 'market_value': str(market_value),
                       'total': str(total), 'return': str(total / dec(config['initial_cash']) - 1),
                       'position_count': len(positions), 'stale_positions': stale,
                       'warmup': index < config['warmup_days']})
    return trades, equity, snapshots, checks


def validate_results(trades, equity, positions, config):
    cash = dec(config['initial_cash'])
    held = {}
    day_rows = {}
    phase_order = {'open': 0, 'intraday': 1, 'close': 2}
    last_key = ('', -1)
    for row in trades:
        key = (row['date'], phase_order[row['phase']])
        assert key >= last_key
        last_key = key
        q, px, f = row['quantity'], dec(row['price']), dec(row['fee'])
        assert q > 0 and q % config['lot_size'] == 0 and px == price(px)
        assert dec(row['value']) == px * q
        if row['side'] == 'buy':
            assert row['ts_code'] not in held and row['signal_date'] < row['date']
            held[row['ts_code']] = (q, row['date'])
            cash -= px * q + f
        else:
            assert held[row['ts_code']] == (q, row['entry_date'])
            assert row['date'] > row['entry_date']
            del held[row['ts_code']]
            cash += px * q - f
        assert cash == dec(row['cash_after']) and cash >= 0
        assert len(held) <= config['max_positions']
        day_rows[row['date']] = cash
    values = {}
    for row in positions:
        assert row['valuation_date'] <= row['date']
        assert dec(row['value']) == row['quantity'] * dec(row['valuation_price'])
        values[row['date']] = values.get(row['date'], Decimal('0')) + dec(row['value'])
    running_cash = dec(config['initial_cash'])
    for row in equity:
        running_cash = day_rows.get(row['date'], running_cash)
        assert dec(row['cash']) == running_cash >= 0
        assert dec(row['market_value']) == values.get(row['date'], Decimal('0'))
        assert dec(row['total']) == running_cash + dec(row['market_value'])
        assert row['position_count'] <= config['max_positions']
    return {'status': 'passed', 'trade_rows': len(trades), 'equity_rows': len(equity),
            'position_rows': len(positions), 'checks': '余额、逐笔现金、总值对账、整手、上限、T+1、阶段时序、信号时点'}
