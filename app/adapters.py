"""Pluggable public market-data adapters (Wallex, Nobitex, Bitunix).

Only documented public endpoints are used. Each adapter declares its documented primary
endpoint and, where official docs describe one, a fallback. Parsers raise
``ValidationError`` with a stable reason code so the diagnostics page can explain exactly
which rule failed.

Units: every normalized price is TOMAN for toman-quoted markets and USDT for USDT-quoted
markets. Nobitex's IRT order books are published in RIAL and are divided by ten here
(USDT-quoted Nobitex books are never divided).
"""
import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .net import Endpoint, ValidationError
from .symbols import normalize

TOMAN_QUOTES = {'TMN', 'IRT', 'RLS', 'TOMAN'}
USDT_QUOTES = {'USDT'}


@dataclass
class Market:
    exchange: str
    coin: str
    quote: str            # 'toman' | 'USDT'
    symbol: str
    meta: dict = field(default_factory=dict)

    @property
    def key(self):
        return (self.exchange, self.coin, self.quote)


@dataclass
class Ticker:
    exchange: str
    coin: str
    quote: str
    ask: Optional[float]
    bid: Optional[float]
    timestamp: float
    timestamp_reliable: bool
    source: str
    last: Optional[float] = None

    @property
    def has_two_sided(self):
        return self.ask is not None and self.bid is not None

    def public(self):
        return {'exchange': self.exchange, 'coin': self.coin, 'quote': self.quote,
                'ask': self.ask, 'bid': self.bid, 'last': self.last,
                'timestamp': self.timestamp, 'timestamp_reliable': self.timestamp_reliable,
                'source': self.source}


@dataclass
class DepthBook:
    exchange: str
    coin: str
    quote: str
    asks: list
    bids: list
    timestamp: float
    timestamp_reliable: bool
    source: str
    quality: str = 'depth'     # 'depth' | 'best_only'

    @property
    def best_ask(self):
        return self.asks[0][0] if self.asks else None

    @property
    def best_bid(self):
        return self.bids[0][0] if self.bids else None

    @property
    def is_depth(self):
        return self.quality == 'depth'


def _float(value, name, code='missing_field'):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError(code, f'invalid number for {name}: {value!r}')
    if not math.isfinite(number):
        raise ValidationError(code, f'non-finite {name}: {value!r}')
    return number


def _levels(rows, name, divisor=1.0):
    """Parse [[price, quantity], ...] or [{'price':..,'quantity'|'volume':..}, ...]."""
    if rows is None:
        raise ValidationError('missing_field', f'missing {name}')
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        raise ValidationError('shape', f'{name} is not a list')
    result = []
    for row in rows:
        if isinstance(row, dict):
            price = row.get('price')
            quantity = row.get('quantity', row.get('volume', row.get('qty', row.get('amount'))))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            price, quantity = row[0], row[1]
        else:
            raise ValidationError('shape', f'unexpected {name} row: {row!r}')
        price = _float(price, name + '.price') / divisor
        quantity = _float(quantity, name + '.quantity')
        if price <= 0 or quantity <= 0:
            raise ValidationError('unexpected_unit', f'non-positive level in {name}: {row!r}')
        if price > 1e15:
            raise ValidationError('unexpected_unit', f'implausible price in {name}: {price}')
        result.append((price, quantity))
    if not result:
        raise ValidationError('empty_book', f'{name} is empty')
    return result


def _sorted_book(asks, bids):
    asks = sorted(asks)
    bids = sorted(bids, reverse=True)
    if bids[0][0] > asks[0][0]:
        raise ValidationError('crossed_book', f'best bid {bids[0][0]} > best ask {asks[0][0]}')
    return asks, bids


def _epoch_seconds(raw, reference=None):
    """Accept epoch seconds/milliseconds; use ``reference`` to disambiguate tiny values."""
    stamp = float(raw)
    if stamp > 1e11:
        return stamp / 1000.0
    if reference is not None and abs(stamp - reference) > 1e6:
        if abs(stamp / 1000 - reference) < abs(stamp - reference):
            return stamp / 1000.0
    return stamp


def _status_ok(data):
    if not isinstance(data, dict):
        raise ValidationError('shape', 'response root is not an object')


class Adapter:
    name = ''
    label = ''
    supports_bulk_tickers = True
    ticker_budget = None
    depth_budget = None

    def market_endpoints(self) -> list:
        raise NotImplementedError

    def bulk_ticker_endpoints(self) -> list:
        return []

    def ticker_endpoints(self, market: Market) -> list:
        return []

    def depth_endpoints(self, market: Market) -> list:
        raise NotImplementedError

    def parse_markets(self, data) -> dict:
        raise NotImplementedError

    def parse_bulk_tickers(self, data, markets) -> dict:
        return {}

    def parse_ticker(self, data, market: Market) -> Ticker:
        raise NotImplementedError

    def parse_depth(self, data, market: Market, received_at: float, max_age: float = 120.0,
                    clock_skew: Optional[float] = None) -> DepthBook:
        raise NotImplementedError

    # -- shared helpers -------------------------------------------------
    @staticmethod
    def _stale(timestamp, reliable, received_at, max_age, clock_skew):
        """Reject stale data only when the exchange's own timestamp is trustworthy.

        A wrong laptop clock is detected separately (HTTP Date header). If the local clock
        is skewed we never reject based on the exchange timestamp, because that is exactly
        how a correct book gets thrown away on a laptop with a drifted clock.
        """
        if not reliable or timestamp is None:
            return False
        if clock_skew is not None and abs(clock_skew) > 60:
            return False
        age = received_at - timestamp
        return age > max_age


class Wallex(Adapter):
    name = 'wallex'
    label = 'والکس'
    BASE = 'https://api.wallex.ir'
    ticker_budget = 'wallex:stats'
    depth_budget = 'wallex'

    def market_endpoints(self):
        # Documented bulk markets + stats payload; no separate documented stats endpoint.
        return [Endpoint('markets', self.BASE + '/v1/markets', kind='markets')]

    def bulk_ticker_endpoints(self):
        return [Endpoint('markets', self.BASE + '/v1/markets', kind='tickers')]

    def depth_endpoints(self, market):
        return [Endpoint('depth', f'{self.BASE}/v1/depth?symbol={market.symbol}', kind='depth')]

    def parse_markets(self, data):
        _status_ok(data)
        if data.get('success') is not True:
            raise ValidationError('unsuccessful_status', str(data.get('message') or data.get('error') or ''))
        symbols = data.get('result', {}).get('symbols')
        if not isinstance(symbols, dict):
            raise ValidationError('missing_field', 'result.symbols missing')
        markets = {}
        for key, info in symbols.items():
            try:
                base = normalize(info.get('baseAsset'))
                quote = normalize(info.get('quoteAsset'))
            except (AttributeError, ValueError, TypeError):
                continue
            if quote in TOMAN_QUOTES:
                quote_code = 'toman'
            elif quote in USDT_QUOTES:
                quote_code = 'USDT'
            else:
                continue
            symbol = str(info.get('symbol') or key).upper()
            markets[(base, quote_code)] = Market(
                self.name, base, quote_code, symbol,
                {'stats': info.get('stats') or {}, 'raw_quote': quote})
        if not markets:
            raise ValidationError('missing_field', 'no TMN/USDT markets in payload')
        return markets

    def parse_bulk_tickers(self, data, markets):
        _status_ok(data)
        if data.get('success') is not True:
            raise ValidationError('unsuccessful_status', str(data.get('message') or ''))
        symbols = data.get('result', {}).get('symbols')
        if not isinstance(symbols, dict):
            raise ValidationError('missing_field', 'result.symbols missing')
        now = float(data.get('__received_at__') or 0) or None
        result = {}
        for key, market in markets.items():
            info = symbols.get(market.symbol) or {}
            stats = info.get('stats') if isinstance(info, dict) else None
            if not isinstance(stats, dict):
                result[key] = ValidationError('missing_field', f'stats missing for {market.symbol}')
                continue
            try:
                ask = _float(stats.get('askPrice'), 'askPrice')
                bid = _float(stats.get('bidPrice'), 'bidPrice')
                if ask <= 0 or bid <= 0 or bid > ask:
                    raise ValidationError('unexpected_unit', f'invalid top of book {bid}/{ask}')
            except ValidationError as exc:
                result[key] = exc
                continue
            result[key] = Ticker(self.name, market.coin, market.quote, ask, bid,
                                 timestamp=now or 0.0, timestamp_reliable=False,
                                 source='markets', last=None)
        return result

    def parse_depth(self, data, market, received_at, max_age=120.0, clock_skew=None):
        _status_ok(data)
        if data.get('success') is not True:
            raise ValidationError('unsuccessful_status', str(data.get('message') or ''))
        body = data.get('result')
        if not isinstance(body, dict):
            raise ValidationError('missing_field', 'result missing')
        asks = _levels(body.get('ask'), 'ask')
        bids = _levels(body.get('bid'), 'bid')
        asks, bids = _sorted_book(asks, bids)
        # Wallex's documented depth payload carries no exchange timestamp: receipt time only.
        return DepthBook(self.name, market.coin, market.quote, asks, bids, received_at,
                         timestamp_reliable=False, source='depth')


class Nobitex(Adapter):
    name = 'nobitex'
    label = 'نوبیتکس'
    BASE = 'https://apiv2.nobitex.ir'
    ticker_budget = 'nobitex:stats'
    depth_budget = 'nobitex'

    def market_endpoints(self):
        # market/stats is the documented bulk endpoint (20 req/min).
        return [Endpoint('market_stats', self.BASE + '/market/stats', kind='markets')]

    def bulk_ticker_endpoints(self):
        return [Endpoint('market_stats', self.BASE + '/market/stats', kind='tickers')]

    def depth_endpoints(self, market):
        return [Endpoint('orderbook_v3', f'{self.BASE}/v3/orderbook/{market.symbol}', kind='depth'),
                Endpoint('market_stats_best', self._stats_url(market), kind='depth',
                         quality='best_only')]

    def _stats_url(self, market):
        dst = 'rls' if market.quote == 'toman' else 'usdt'
        return f'{self.BASE}/market/stats?srcCurrency={market.coin.lower()}&dstCurrency={dst}'

    @staticmethod
    def stats_key(market):
        return market.coin.lower() + ('-rls' if market.quote == 'toman' else '-usdt')

    def parse_markets(self, data):
        _status_ok(data)
        if data.get('status') != 'ok':
            raise ValidationError('unsuccessful_status', str(data.get('message') or data.get('code') or ''))
        stats = data.get('stats')
        if not isinstance(stats, dict):
            raise ValidationError('missing_field', 'stats missing')
        markets = {}
        for pair, info in stats.items():
            if not isinstance(info, dict):
                continue
            if info.get('isClosed', False):
                continue
            try:
                base, quote = str(pair).split('-')
                base = normalize(base)
                quote = normalize(quote)
            except (ValueError, TypeError):
                continue
            if quote in ('RLS', 'IRT') or quote in TOMAN_QUOTES:
                quote_code, symbol = 'toman', base + 'IRT'
            elif quote in USDT_QUOTES:
                quote_code, symbol = 'USDT', base + 'USDT'
            else:
                continue
            markets[(base, quote_code)] = Market(self.name, base, quote_code, symbol,
                                                 {'raw_pair': pair, 'stats': info})
        if not markets:
            raise ValidationError('missing_field', 'no RLS/USDT markets in payload')
        return markets

    def parse_bulk_tickers(self, data, markets):
        _status_ok(data)
        if data.get('status') != 'ok':
            raise ValidationError('unsuccessful_status', str(data.get('message') or ''))
        stats = data.get('stats')
        if not isinstance(stats, dict):
            raise ValidationError('missing_field', 'stats missing')
        result = {}
        for key, market in markets.items():
            info = stats.get(self.stats_key(market))
            if not isinstance(info, dict) or info.get('isClosed', False):
                result[key] = ValidationError('symbol_missing', f'no open stats for {market.symbol}')
                continue
            divisor = 10.0 if market.quote == 'toman' else 1.0
            try:
                # bestSell is the best ask (what a buyer pays), bestBuy is the best bid.
                ask = _float(info.get('bestSell'), 'bestSell') / divisor
                bid = _float(info.get('bestBuy'), 'bestBuy') / divisor
                if ask <= 0 or bid <= 0 or bid > ask:
                    raise ValidationError('unexpected_unit', f'invalid top of book {bid}/{ask}')
            except ValidationError as exc:
                result[key] = exc
                continue
            result[key] = Ticker(self.name, market.coin, market.quote, ask, bid,
                                 timestamp=0.0, timestamp_reliable=False, source='market_stats')
        return result

    def parse_ticker(self, data, market):
        _status_ok(data)
        if data.get('status') != 'ok':
            raise ValidationError('unsuccessful_status', str(data.get('message') or ''))
        stats = data.get('stats')
        info = stats.get(self.stats_key(market)) if isinstance(stats, dict) else None
        if not isinstance(info, dict):
            raise ValidationError('symbol_missing', f'no stats for {market.symbol}')
        divisor = 10.0 if market.quote == 'toman' else 1.0
        ask = _float(info.get('bestSell'), 'bestSell') / divisor
        bid = _float(info.get('bestBuy'), 'bestBuy') / divisor
        if ask <= 0 or bid <= 0 or bid > ask:
            raise ValidationError('unexpected_unit', f'invalid top of book {bid}/{ask}')
        return Ticker(self.name, market.coin, market.quote, ask, bid, 0.0, False, 'market_stats')

    def parse_depth(self, data, market, received_at, max_age=120.0, clock_skew=None):
        _status_ok(data)
        if 'asks' not in data and data.get('status') == 'ok' and 'stats' in data:
            # Fallback shape: market/stats -> top of book only (documented bestSell/bestBuy).
            ticker = self.parse_ticker(data, market)
            return DepthBook(self.name, market.coin, market.quote,
                             [(ticker.ask, 1e-9)], [(ticker.bid, 1e-9)], received_at,
                             timestamp_reliable=False, source='market_stats_best',
                             quality='best_only')
        if data.get('status') != 'ok':
            raise ValidationError('unsuccessful_status', str(data.get('message') or ''))
        divisor = 10.0 if market.quote == 'toman' else 1.0
        asks = _levels(data.get('asks'), 'asks', divisor)
        bids = _levels(data.get('bids'), 'bids', divisor)
        asks, bids = _sorted_book(asks, bids)
        raw_update = data.get('lastUpdate')
        reliable = raw_update is not None
        timestamp = received_at
        if reliable:
            try:
                stamp = float(raw_update)
            except (TypeError, ValueError):
                reliable, stamp = False, received_at
            if reliable:
                stamp = _epoch_seconds(stamp, received_at)
                if not math.isfinite(stamp) or stamp <= 0:
                    reliable, timestamp = False, received_at
                else:
                    timestamp = stamp
        # Unit sanity check: a 10x mismatch between the last trade and the book mid is the
        # signature of the rial/toman mistake, not of a volatile market.
        last_trade = data.get('lastTradePrice')
        if last_trade is not None:
            try:
                last = float(last_trade) / divisor
            except (TypeError, ValueError):
                last = 0.0
            mid = (asks[0][0] + bids[0][0]) / 2
            if last > 0 and mid > 0:
                ratio = mid / last
                if 7 <= ratio <= 13 or 1 / 13 <= ratio <= 1 / 7:
                    raise ValidationError('unexpected_unit',
                                          f'book mid {mid} is ~10x last trade {last}')
        if self._stale(timestamp, reliable, received_at, max_age, clock_skew):
            raise ValidationError('stale_timestamp',
                                  f'lastUpdate age {received_at - timestamp:.0f}s > {max_age:.0f}s')
        return DepthBook(self.name, market.coin, market.quote, asks, bids, timestamp,
                         timestamp_reliable=reliable, source='orderbook_v3')


class Bitunix(Adapter):
    """Bitunix spot (documented public endpoints only).

    Note: the official spot documentation lists per-symbol price/depth endpoints and a coin
    pair list, but **no bulk ticker endpoint** (unlike the futures API). The scanner
    therefore uses a budgeted, rotating set of per-symbol last-price calls and fetches full
    depth only for hot/visible rows. No undocumented endpoint is invented here.
    """
    name = 'bitunix'
    label = 'بیت‌یونیکس'
    BASE = 'https://openapi.bitunix.com'
    supports_bulk_tickers = False
    ticker_budget = 'bitunix'
    depth_budget = 'bitunix'

    def market_endpoints(self):
        return [Endpoint('coin_pair_list', self.BASE + '/api/spot/v1/common/coin_pair/list',
                         kind='markets')]

    def bulk_ticker_endpoints(self):
        return []

    def ticker_endpoints(self, market):
        return [Endpoint('last_price',
                         f'{self.BASE}/api/spot/v1/market/last_price?symbol={market.symbol}',
                         kind='tickers', quality='last_price')]

    def depth_endpoints(self, market):
        precision = (market.meta or {}).get('depth_precision')
        query = f'symbol={market.symbol}'
        if precision not in (None, ''):
            query += f'&precision={precision}'
        return [Endpoint('depth', f'{self.BASE}/api/spot/v1/market/depth?{query}', kind='depth')]

    @staticmethod
    def _check(data):
        _status_ok(data)
        code = data.get('code')
        if str(code) not in ('0', 'None') and data.get('success') is not True:
            raise ValidationError('unsuccessful_status', f'code={code} msg={data.get("msg")!r}')

    def parse_markets(self, data):
        self._check(data)
        rows = data.get('data')
        if not isinstance(rows, list):
            raise ValidationError('missing_field', 'data list missing')
        markets = {}
        for item in rows:
            if not isinstance(item, dict):
                continue
            try:
                base = normalize(item.get('base'))
                quote = normalize(item.get('quote'))
            except (ValueError, TypeError):
                continue
            if quote not in USDT_QUOTES:
                continue           # Bitunix spot: USDT-quoted markets only
            if str(item.get('isOpen', '1')) in ('0', 'False', 'false'):
                continue
            candidate = str(item.get('symbol') or item.get('id') or '').upper()
            if not candidate.endswith('USDT') or base not in candidate:
                candidate = base + 'USDT'
            precisions = item.get('precisions')
            precision = None
            if isinstance(precisions, list) and precisions:
                precision = precisions[0]
            elif precisions not in (None, ''):
                precision = precisions
            if precision is None:
                precision = item.get('basePrecision')
            markets[(base, 'USDT')] = Market(self.name, base, 'USDT', candidate,
                                             {'depth_precision': precision, 'raw': item})
        if not markets:
            raise ValidationError('missing_field', 'no open USDT spot pairs in payload')
        return markets

    def parse_ticker(self, data, market):
        self._check(data)
        price = _float(data.get('data'), 'last price')
        if price <= 0 or price > 1e15:
            raise ValidationError('unexpected_unit', f'implausible last price {price}')
        # last_price has no bid/ask and no exchange timestamp: reference only, never a spread.
        return Ticker(self.name, market.coin, market.quote, None, None,
                      timestamp=float(data.get('__received_at__') or 0.0),
                      timestamp_reliable=False, source='last_price', last=price)

    def parse_depth(self, data, market, received_at, max_age=120.0, clock_skew=None):
        self._check(data)
        body = data.get('data')
        if not isinstance(body, dict):
            raise ValidationError('missing_field', 'data missing')
        asks = _levels(body.get('asks'), 'asks')
        bids = _levels(body.get('bids'), 'bids')
        asks, bids = _sorted_book(asks, bids)
        timestamp, reliable = received_at, False
        raw = body.get('ts', data.get('ts'))
        if raw not in (None, ''):
            stamp = _parse_timestamp(raw, received_at)
            if stamp is not None:
                timestamp, reliable = stamp, True
        if self._stale(timestamp, reliable, received_at, max_age, clock_skew):
            raise ValidationError('stale_timestamp',
                                  f'ts age {received_at - timestamp:.0f}s > {max_age:.0f}s')
        return DepthBook(self.name, market.coin, market.quote, asks, bids, timestamp,
                         timestamp_reliable=reliable, source='depth')


def _parse_timestamp(raw, reference=None):
    """Accept epoch seconds/milliseconds or an ISO-8601 string; else None."""
    if isinstance(raw, (int, float)):
        stamp = float(raw)
    else:
        text = str(raw).strip()
        if re.fullmatch(r'\d+(\.\d+)?', text):
            stamp = float(text)
        else:
            try:
                from datetime import datetime
                stamp = datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()
            except ValueError:
                return None
    if not math.isfinite(stamp) or stamp <= 0:
        return None
    return _epoch_seconds(stamp, reference)


ADAPTERS = {adapter.name: adapter for adapter in (Wallex(), Nobitex(), Bitunix())}
EXCHANGE_LABELS = {name: adapter.label for name, adapter in ADAPTERS.items()}


def adapter(name) -> Adapter:
    try:
        return ADAPTERS[name]
    except KeyError:
        raise ValueError(f'unknown exchange: {name}')


def public_depth(book: DepthBook, levels=10):
    return {'asks': [[round(p, 10), q] for p, q in book.asks[:levels]],
            'bids': [[round(p, 10), q] for p, q in book.bids[:levels]],
            'timestamp': book.timestamp, 'timestamp_reliable': book.timestamp_reliable,
            'source': book.source, 'quality': book.quality,
            'best_ask': book.best_ask, 'best_bid': book.best_bid}
