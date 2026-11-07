"""Public spot market adapters and conservative intersection."""
from .symbols import normalize, review_reason


def wallex_markets(data):
    if data.get('success') is not True:
        raise ValueError('Wallex markets response unsuccessful')
    symbols = data['result']['symbols']
    result = {}
    for symbol, info in symbols.items():
        try:
            base, quote = normalize(info['baseAsset']), normalize(info['quoteAsset'])
            if quote in ('TMN', 'USDT'):
                result[(base, 'toman' if quote == 'TMN' else 'USDT')] = str(info.get('symbol', symbol)).upper()
        except (KeyError, ValueError, TypeError):
            continue
    return result


def nobitex_markets(data):
    if data.get('status') != 'ok':
        raise ValueError('Nobitex stats response unsuccessful')
    result = {}
    for pair, info in data['stats'].items():
        try:
            base, quote = pair.split('-')
            base, quote = normalize(base), normalize(quote)
            if quote in ('RLS', 'USDT') and not info.get('isClosed', False):
                result[(base, 'toman' if quote == 'RLS' else 'USDT')] = base + ('IRT' if quote == 'RLS' else 'USDT')
        except (ValueError, TypeError, AttributeError):
            continue
    return result


def intersection(wallex, nobitex):
    common, excluded = [], []
    for coin, quote in sorted(wallex.keys() & nobitex.keys()):
        reason = review_reason(coin)
        if reason:
            excluded.append({'coin': coin, 'quote': quote, 'reason': reason})
        else:
            common.append({'coin': coin, 'quote': quote, 'wallex': wallex[(coin, quote)], 'nobitex': nobitex[(coin, quote)]})
    # Report possible multiplier/renamed mismatches without assuming equivalence.
    for coin, quote in sorted(wallex.keys() ^ nobitex.keys()):
        if review_reason(coin):
            excluded.append({'coin': coin, 'quote': quote, 'reason': 'فقط در یک صرافی یا نیازمند بررسی تطبیق نماد'})
    return common, excluded
