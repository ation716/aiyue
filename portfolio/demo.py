"""Demo 数量和现金分配，保留用户指定接口拼写。"""
from decimal import Decimal


def stock_keep(**kwargs):
    return max(0, kwargs.get('max_positions', 8) - len(set(kwargs.get('positions', {}))))


def position_managent(symbol_list, **kwargs):
    held = set(kwargs.get('positions', {}))
    candidates = list(dict.fromkeys(s for s in symbol_list if s not in held))
    count = kwargs.get('keep_count', stock_keep(**kwargs))
    selected = candidates[:count]
    cash = Decimal(str(kwargs.get('available_cash', 0)))
    if cash < 0:
        raise ValueError('可用现金不能为负')
    return {symbol: cash / len(selected) for symbol in selected} if selected else {}


def ultimate_distribute(symbol_list, **kwargs):
    kwargs['keep_count'] = stock_keep(**kwargs)
    return position_managent(symbol_list, **kwargs)
