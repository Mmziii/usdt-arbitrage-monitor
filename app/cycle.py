"""Full-cycle Iran <-> Bitunix calculations, starting and ending in USDT.

Route A (buy abroad, sell in Iran) — modelled order:
    1. spend USDT on Bitunix ask depth (taker/maker fee)
    2. withdraw the coin from Bitunix (fixed coin withdrawal fee, chosen network)
    3. sell the coin into the Iranian exchange bid depth (fee)
    4. buy USDT with the toman proceeds on that exchange's USDT/toman ask depth (fee)
    5. withdraw USDT back to Bitunix (Iranian exchange USDT withdrawal fee)
So both transfers in the description exist, and the result is directly comparable with the
starting USDT.

Route B (buy in Iran, sell abroad) — the reverse, kept symmetric so two transfers are
modelled as well:
    1. withdraw USDT from Bitunix to the Iranian exchange (Bitunix USDT withdrawal fee)
    2. sell that USDT for toman on the Iranian exchange bid depth (fee)
    3. buy the coin with toman on the Iranian exchange ask depth (fee)
    4. withdraw the coin to Bitunix (Iranian exchange coin withdrawal fee)
    5. sell the coin into the Bitunix bid depth (fee)
This is the variant where the toman needed to buy the coin comes from a USDT sale, with
all trading and USDT withdrawal fees included.

The direct variant compares an Iranian USDT-quoted coin market with Bitunix: buy, withdraw
the coin, sell. No toman conversion is involved.

Unknown fees are never assumed to be zero: they block the net result (gross-only label).
"""
import math
from dataclasses import dataclass

from .chain import (Chain, ChainError, analyse, buy_stage, fixed_stage, sell_stage)
from .calculation import InsufficientDepth

ROUTES = {
    'A': 'خرید در بیتیونیکس، فروش در ایران',
    'B': 'خرید در ایران، فروش در بیتیونیکس',
    'direct_iran_to_bitunix': 'خرید در ایران، فروش در بیتیونیکس (بازار USDT)',
    'direct_bitunix_to_iran': 'خرید در بیتیونیکس، فروش در ایران (بازار USDT)',
}


class UnknownFee(ValueError):
    """A required fee has not been entered by the user; net profit is not claimed."""


@dataclass
class Books:
    iran: object = None
    conversion: object = None
    bitunix: object = None


def _fee(fees, venue, mode, label):
    value = (fees.get(venue) or {}).get(mode)
    if value is None:
        raise UnknownFee(f'کارمزد {label} وارد نشده است')
    value = float(value)
    if not math.isfinite(value) or value < 0 or value >= 100:
        raise UnknownFee(f'کارمزد {label} نامعتبر است')
    return value


def _withdrawal(withdrawals, key, label):
    value = withdrawals.get(key)
    if value is None:
        raise UnknownFee(f'کارمزد برداشت {label} وارد نشده است')
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise UnknownFee(f'کارمزد برداشت {label} نامعتبر است')
    return value


def build_chain(route, books, fees, withdrawals, mode='taker', trading_mode='transfer',
                prefunded=False, gross=False):
    """Construct the monotone chain for one route, direction and fee mode."""
    if gross:
        zero = {'maker': 0.0, 'taker': 0.0}
        fees = {'bitunix': zero, 'iran': zero, 'conversion': zero}
        withdrawals = {key: 0.0 for key in ('bitunix_coin', 'iran_coin', 'bitunix_usdt', 'iran_usdt')}
        prefunded = True
    bitunix_fee = _fee(fees, 'bitunix', mode, 'بیتیونیکس')
    iran_fee = _fee(fees, 'iran', mode, 'صرافی ایرانی')
    conversion_fee = _fee(fees, 'conversion', mode, 'بازار تتر/تومان')
    transfer = not prefunded
    stages = []
    if route == 'A':
        stages.append(buy_stage('buy_coin', 'خرید ارز در بیتیونیکس', books.bitunix.asks,
                                bitunix_fee, 'USDT', 'coin'))
        if transfer:
            stages.append(fixed_stage('withdraw_coin', 'برداشت ارز از بیتیونیکس',
                                      _withdrawal(withdrawals, 'bitunix_coin', 'ارز در بیتیونیکس'),
                                      'coin'))
        stages.append(sell_stage('sell_coin', 'فروش ارز در ایران', books.iran.bids,
                                 iran_fee, 'coin', 'toman'))
        stages.append(buy_stage('convert', 'خرید تتر با تومان', books.conversion.asks,
                                conversion_fee, 'toman', 'USDT'))
        if transfer:
            stages.append(fixed_stage('withdraw_usdt', 'برداشت تتر از ایران',
                                      _withdrawal(withdrawals, 'iran_usdt', 'تتر در صرافی ایرانی'),
                                      'USDT'))
    elif route == 'B':
        if transfer:
            stages.append(fixed_stage('withdraw_usdt', 'برداشت تتر از بیتیونیکس',
                                      _withdrawal(withdrawals, 'bitunix_usdt', 'تتر در بیتیونیکس'),
                                      'USDT'))
        stages.append(sell_stage('convert', 'فروش تتر برای تومان', books.conversion.bids,
                                 conversion_fee, 'USDT', 'toman'))
        stages.append(buy_stage('buy_coin', 'خرید ارز در ایران', books.iran.asks,
                                iran_fee, 'toman', 'coin'))
        if transfer:
            stages.append(fixed_stage('withdraw_coin', 'برداشت ارز از ایران',
                                      _withdrawal(withdrawals, 'iran_coin', 'ارز در صرافی ایرانی'),
                                      'coin'))
        stages.append(sell_stage('sell_coin', 'فروش ارز در بیتیونیکس', books.bitunix.bids,
                                 bitunix_fee, 'coin', 'USDT'))
    elif route == 'direct_iran_to_bitunix':
        stages.append(buy_stage('buy_coin', 'خرید ارز در ایران', books.iran.asks,
                                iran_fee, 'USDT', 'coin'))
        if transfer:
            stages.append(fixed_stage('withdraw_coin', 'برداشت ارز از ایران',
                                      _withdrawal(withdrawals, 'iran_coin', 'ارز در صرافی ایرانی'),
                                      'coin'))
        stages.append(sell_stage('sell_coin', 'فروش ارز در بیتیونیکس', books.bitunix.bids,
                                 bitunix_fee, 'coin', 'USDT'))
    elif route == 'direct_bitunix_to_iran':
        stages.append(buy_stage('buy_coin', 'خرید ارز در بیتیونیکس', books.bitunix.asks,
                                bitunix_fee, 'USDT', 'coin'))
        if transfer:
            stages.append(fixed_stage('withdraw_coin', 'برداشت ارز از بیتیونیکس',
                                      _withdrawal(withdrawals, 'bitunix_coin', 'ارز در بیتیونیکس'),
                                      'coin'))
        stages.append(sell_stage('sell_coin', 'فروش ارز در ایران', books.iran.bids,
                                 iran_fee, 'coin', 'USDT'))
    else:
        raise ChainError('مسیر ناشناخته')
    return Chain(stages)


def conversion_info(books, route, now=0.0):
    """Which book/side supplied the toman<->USDT conversion, and at what rate."""
    if route == 'A':
        book, side = books.conversion, 'ask'
    elif route == 'B':
        book, side = books.conversion, 'bid'
    else:
        return None
    if book is None:
        return None
    rate = book.best_ask if side == 'ask' else book.best_bid
    return {'rate': rate, 'side': side, 'timestamp': book.timestamp,
            'age': None if not now else max(0.0, now - book.timestamp),
            'source': book.source, 'quality': book.quality,
            'exchange': book.exchange,
            'label': 'خرید تتر با تومان' if side == 'ask' else 'فروش تتر برای تومان'}


def _effective_rate(result, route):
    if not result.get('ok'):
        return None
    wanted = 'convert'
    for record in result.get('steps', []):
        if record['name'] == wanted and record.get('input'):
            return record['input'] / record['value']
    return None


def evaluate_cycle(route, books, fees, withdrawals, capital, margin=0.0,
                   trading_mode='transfer', rebalance_trades=10, limit=None, now=0.0,
                   envelope=True):
    """Full result for one route: taker + maker hypothetical + gross reference."""
    prefunded = trading_mode == 'prefunded'
    result = {'route': route, 'route_label': ROUTES.get(route, route), 'capital': capital,
              'trading_mode': trading_mode, 'safety_margin': 0 if prefunded else margin,
              'conversion': conversion_info(books, route, now)}
    unknown = []
    for mode in ('taker', 'maker'):
        try:
            chain = build_chain(route, books, fees, withdrawals, mode, trading_mode, prefunded)
            report = analyse(chain, capital, 0 if prefunded else margin, limit,
                            envelope=envelope)
            report['trading_mode'] = trading_mode
            report['fee_mode'] = mode
            report['safety_status'] = _safety(report, margin, prefunded)
            if prefunded:
                report['rebalancing'] = _rebalance(route, withdrawals, books, rebalance_trades,
                                                  report.get('profit'))
            result[mode] = report
        except (UnknownFee, ChainError) as exc:
            unknown.append(str(exc))
            result[mode] = {'ok': False, 'reason': 'fee unknown', 'error': str(exc),
                            'trading_mode': trading_mode, 'fee_mode': mode}
        except InsufficientDepth as exc:
            result[mode] = {'ok': False, 'reason': 'insufficient depth', 'error': str(exc),
                            'trading_mode': trading_mode, 'fee_mode': mode}
    try:
        gross = analyse(build_chain(route, books, fees, withdrawals, 'taker', 'prefunded',
                                    prefunded, gross=True), capital, 0, limit,
                        envelope=False)
        result['gross_pct'] = gross.get('profit_pct') if gross.get('ok') else None
        result['gross_detail'] = gross
    except (UnknownFee, ChainError, InsufficientDepth):
        result['gross_pct'] = None
    taker = result.get('taker') or {}
    if taker.get('ok'):
        rate = _effective_rate(taker, route) or (result['conversion'] or {}).get('rate')
        result['effective_rate'] = rate
        result['profit_toman'] = None if rate is None else taker['profit'] * rate
        result['capital_toman'] = None if rate is None else capital * rate
    else:
        result['effective_rate'] = None
        result['profit_toman'] = None
        result['capital_toman'] = None
    result['unknown_fees'] = sorted(set(unknown))
    return result


def _safety(report, margin, prefunded):
    if not report.get('ok'):
        return None
    if report['profit'] <= 0:
        return 'unprofitable'
    return 'profitable' if report['profit_pct'] > (0 if prefunded else margin) else 'below safety margin'


def _rebalance(route, withdrawals, books, trades, profit):
    """Prefunded mode: transfers are rare, so the network cost is amortised separately."""
    if route == 'A':
        coin_key, quote_key = 'bitunix_coin', 'iran_usdt'
    elif route == 'B':
        coin_key, quote_key = 'iran_coin', 'bitunix_usdt'
    elif route == 'direct_iran_to_bitunix':
        coin_key, quote_key = 'iran_coin', None
    else:
        coin_key, quote_key = 'bitunix_coin', None
    coin_fee = withdrawals.get(coin_key)
    quote_fee = withdrawals.get(quote_key) if quote_key else 0.0
    # Rebalancing cost is expressed in USDT (the cycle's own unit): the coin fee is priced
    # on the Bitunix book, not on the toman book.
    price = books.bitunix.best_bid if books.bitunix is not None else None
    coin_cost = None if coin_fee is None or price is None else coin_fee * price
    total = None if coin_cost is None or quote_fee is None else coin_cost + quote_fee
    return {'trades': trades, 'coin_cost_quote': coin_cost, 'quote_cost': quote_fee,
            'total': total, 'per_trade': None if total is None else total / max(1, trades),
            'profit_before': profit,
            'profit_after': None if total is None or profit is None else profit - total / max(1, trades),
            'incomplete': total is None}
