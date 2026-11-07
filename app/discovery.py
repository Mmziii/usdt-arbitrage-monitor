"""Conservative three-exchange market discovery.

Tickers are matched only by exact normalized base symbol. Bitunix spot lists USDT-quoted
markets only, so each Iranian market becomes either a direct USDT-market route (iran
USDT quote) or a full toman <-> USDT cycle route (iran toman quote). Nothing is inferred
about multipliers or renamed tokens: suspicious tickers are listed for manual review.
"""
from dataclasses import dataclass

from .symbols import review_reason

IRAN_EXCHANGES = ('wallex', 'nobitex')

LABELS = {
    'A': 'خرید در بیت‌یونیکس، فروش در ایران',
    'B': 'خرید در ایران، فروش در بیت‌یونیکس',
    'direct_iran_to_bitunix': 'بازار تتر: خرید در ایران، فروش در بیت‌یونیکس',
    'direct_bitunix_to_iran': 'بازار تتر: خرید در بیت‌یونیکس، فروش در ایران',
}


@dataclass(frozen=True)
class Route:
    kind: str          # 'A' | 'B' | 'direct_iran_to_bitunix' | 'direct_bitunix_to_iran'
    coin: str
    quote: str         # Iranian market quote: 'toman' | 'USDT'
    iran: str          # Iranian exchange used for the coin market
    buy: str           # exchange where the coin is bought
    sell: str          # exchange where the coin is sold
    key: str
    label: str

    @property
    def needs_conversion(self):
        return self.kind in ('A', 'B')

    def books(self):
        """(exchange, coin, quote) depth books this route needs."""
        needed = []
        if self.needs_conversion:
            # The coin is priced in USDT on Bitunix and in toman on the Iranian exchange.
            needed = [('bitunix', self.coin, 'USDT'), (self.iran, self.coin, 'toman'),
                      (self.iran, 'USDT', 'toman')]
        else:
            needed = [(self.buy, self.coin, self.quote), (self.sell, self.coin, self.quote)]
        # De-duplicate while keeping the order stable.
        return list(dict.fromkeys(needed))


def _route(kind, coin, quote, iran, buy, sell):
    prefix = {'A': 'A', 'B': 'B', 'direct_iran_to_bitunix': 'D',
              'direct_bitunix_to_iran': 'D'}[kind]
    if kind in ('A', 'B'):
        key = f'{prefix}:{coin}:{iran}'
    else:
        key = f'{prefix}:{coin}:{buy}:{sell}'
    return Route(kind, coin, quote, iran, buy, sell, key, LABELS[kind])


def discover(iran_markets, bitunix_markets):
    """Build every evaluable Iran <-> Bitunix route.

    ``iran_markets`` is ``{exchange: {(coin, quote): Market}}`` and ``bitunix_markets`` is
    ``{(coin, 'USDT'): Market}``. Returns ``(routes, excluded)``.
    """
    bitunix_coins = {coin for coin, quote in bitunix_markets if quote == 'USDT'}
    routes, excluded = [], {}
    seen_pairs = set()
    for exchange in IRAN_EXCHANGES:
        markets = iran_markets.get(exchange) or {}
        for (coin, quote) in sorted(markets):
            if coin not in bitunix_coins:
                continue
            seen_pairs.add((coin, quote))
            reason = review_reason(coin)
            if reason:
                excluded[(coin, quote)] = reason
                continue
            if quote == 'USDT':
                routes.append(_route('direct_iran_to_bitunix', coin, quote, exchange,
                                     exchange, 'bitunix'))
                routes.append(_route('direct_bitunix_to_iran', coin, quote, exchange,
                                     'bitunix', exchange))
            elif quote == 'toman':
                if ('USDT', 'toman') not in markets:
                    excluded[(coin, quote)] = 'بازار تتر/تومان این صرافی برای تبدیل در دسترس نیست'
                    continue
                routes.append(_route('A', coin, quote, exchange, 'bitunix', exchange))
                routes.append(_route('B', coin, quote, exchange, exchange, 'bitunix'))
    # Ambiguous tickers that *look* matched are still reported for manual review.
    for exchange in IRAN_EXCHANGES:
        for (coin, quote) in (iran_markets.get(exchange) or {}):
            if coin in bitunix_coins and review_reason(coin) and (coin, quote) not in seen_pairs:
                excluded[(coin, quote)] = review_reason(coin)
    for coin in bitunix_coins:
        if review_reason(coin):
            excluded.setdefault((coin, 'USDT'), review_reason(coin))
    excluded_rows = [{'coin': coin, 'quote': quote, 'reason': reason,
                      'exchanges': ['bitunix'] + [e for e in IRAN_EXCHANGES
                                                  if (coin, quote) in (iran_markets.get(e) or {})]}
                     for (coin, quote), reason in sorted(excluded.items())]
    routes.sort(key=lambda route: (route.coin, route.iran, route.kind))
    return routes, excluded_rows


def conversion_market_for(iran_markets, exchange):
    """The Iranian USDT/toman book used for the toman<->USDT leg, if listed."""
    return (iran_markets.get(exchange) or {}).get(('USDT', 'toman'))
