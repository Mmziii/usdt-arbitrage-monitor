"""Trading-mode policy layered over the existing depth calculator."""
from .calculation import calculate
from .capital import capital_limits, cost_for_quantity


def evaluate(capital, source, destination, source_fees, destination_fees, liquidity,
             trading_mode='transfer', margin=.3, quote_balance=None, coin_balance=None,
             rebalance_trades=10, rebalance_coin_fee=None, rebalance_quote_fee=None):
    prefunded = trading_mode == 'prefunded'
    sf = {**source_fees}
    if prefunded:
        sf.update(withdrawal=0, minimum=0)
        if quote_balance is not None:
            capital = min(capital, quote_balance)
        if coin_balance is not None:
            cost = cost_for_quantity(coin_balance / (1-sf[liquidity]/100), source.asks)
            if cost is not None:
                capital = min(capital, cost)
    if capital <= 0:
        raise ValueError('موجودی برای معامله کافی نیست')
    result = calculate(capital, source, destination, sf, destination_fees, liquidity)
    result.update(capital=capital, trading_mode=trading_mode, safety_margin=0 if prefunded else margin,
                  safety_status='profitable' if result['profit_pct'] > (0 if prefunded else margin) else 'below safety margin' if result['profit'] > 0 else 'unprofitable',
                  balances_unlimited=quote_balance is None and coin_balance is None)
    result.update(capital_limits(source.asks, destination.bids, sf[liquidity]/100,
                                destination_fees[liquidity]/100, sf['withdrawal'], sf.get('minimum', 0),
                                0 if prefunded else margin, quote_balance if prefunded else None, coin_balance if prefunded else None))
    if result['breakeven_capital'] is not None and result['breakeven_capital'] > result.get('visible_capital', 0):
        result['breakeven_capital'] = None
    if prefunded:
        # Reset direction is destination -> source for coin, source -> destination for quote.
        coin_cost = None if rebalance_coin_fee is None else rebalance_coin_fee * destination.bids[0][0]
        total = None if coin_cost is None or rebalance_quote_fee is None else coin_cost + rebalance_quote_fee
        result['rebalancing'] = dict(trades=rebalance_trades, coin_cost_quote=coin_cost,
                                    quote_cost=rebalance_quote_fee, total=total,
                                    per_trade=None if total is None else total/rebalance_trades,
                                    profit_before=result['profit'],
                                    profit_after=None if total is None else result['profit']-total/rebalance_trades,
                                    incomplete=total is None)
    return result


def transfer_time(config, network):
    table = config.get('transfer_minutes', {})
    value = table.get(network)
    return {'minutes': value if value is not None else table.get('default'), 'estimated': True,
            'uses_default': value is None}
