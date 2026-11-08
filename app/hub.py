"""Multi-exchange public-data hub behind the new overview.

Owns market discovery across Wallex/Nobitex/Bitunix, bulk tickers, bounded depth requests
for hot rows, and the Iran <-> Bitunix route rows. Read-only: no keys, no orders.
"""
import asyncio
import time

from .adapters import ADAPTERS, EXCHANGE_LABELS, ValidationError
from .cycle import Books, evaluate_cycle
from .discovery import IRAN_EXCHANGES, discover
from .fees import resolve_between
from .refresh import age_of, is_stale, select_hot, depth_targets
from .tiers import active_fees
from .trading import transfer_time

VERDICTS = {'profitable': 'worth', 'below safety margin': 'borderline', 'unprofitable': 'no'}


class Hub:
    def __init__(self, store, gateway, get_settings, classic_rows=None):
        self.store = store
        self.gateway = gateway
        self.monitor = gateway.monitor
        self.get_settings = get_settings
        self.classic_rows = classic_rows
        self.iran = {name: {} for name in IRAN_EXCHANGES}
        self.bitunix = {}
        self.tickers = {}
        self.ticker_errors = {}
        self.books = {}
        self.book_errors = {}
        self.routes = []
        self.excluded = []
        self.markets_time = 0.0
        self.last_tickers = 0.0
        self.last_scan = 0.0
        self.last_error = None
        self.paused = False
        self.visible = []
        self.hot = []
        self.bitunix_cursor = 0
        self.rows_cache = []
        self.scan_count = 0
        self.lock = asyncio.Lock()

    # ------------------------------------------------------------------ state
    def config(self):
        cfg = self.store.scanner_settings()
        return {**self._defaults(), **cfg}

    @staticmethod
    def _defaults():
        return {'interval': 10, 'depth_interval': 5, 'hot_rows': 20, 'stale_seconds': 120,
                'paused': False, 'capital_usdt': 100, 'capital_toman': 10_000_000,
                'ticker_batch': 12, 'depth_batch': 6, 'safety_margin': .3, 'coin_margins': {},
                'row_modes': {}, 'trading_mode': 'transfer',
                # Rough, editable starting points; the UI labels every one as "تقریبی".
                'transfer_minutes': {'default': 60, 'TRC20': 5, 'BEP20': 5, 'ERC20': 10,
                                     'BTC': 60, 'TON': 5},
                'networks': {}, 'rebalancing_trades': 10, 'rebalance_trades': 10,
                'conversion_source': 'auto', 'close_confirmations': 2, 'retention_days': 30,
                'balances': {}, 'setup': {}, 'other_costs_toman': 0, 'other_costs_note': '',
                'fee_candidate_limit': 10, 'gauge_days': 7}

    def postpone(self):
        self.last_scan = 0.0

    # ------------------------------------------------------------ fetching
    async def _fetch(self, client, exchange, endpoints, parser=None, budget_name=None):
        last = None
        for endpoint in endpoints:
            result = await self.gateway.fetch(client, exchange, endpoint, parser,
                                              budget_name=budget_name)
            if result.ok:
                return result
            last = result
            if result.reason == 'budget':
                break
        return last

    def _clock_skew(self, exchange):
        state = self.monitor.clock_state.get(exchange) or {}
        return state.get('skew_seconds')

    async def refresh_markets(self, client, exchange):
        adapter = ADAPTERS[exchange]
        budget_name = adapter.ticker_budget
        result = await self._fetch(client, exchange, adapter.market_endpoints(),
                                   adapter.parse_markets, budget_name)
        if not result or not result.ok:
            return False
        if exchange == 'bitunix':
            self.bitunix = result.data
        else:
            self.iran[exchange] = result.data
        return True

    async def refresh_markets_all(self, client):
        await asyncio.gather(*(self.refresh_markets(client, name) for name in ADAPTERS),
                             return_exceptions=True)
        self.markets_time = time.time()
        self.rebuild_routes()

    def rebuild_routes(self):
        self.routes, self.excluded = discover(self.iran, self.bitunix)

    async def refresh_tickers(self, client, cfg):
        now = time.time()
        reload_markets = now - self.markets_time > 21600 or not self.routes
        results = await asyncio.gather(
            *(self._bulk_tickers(client, name, reload_markets, now) for name in IRAN_EXCHANGES),
            return_exceptions=True)
        if reload_markets:
            await self.refresh_markets(client, 'bitunix')
        elif not self.bitunix:
            await self.refresh_markets(client, 'bitunix')
        await self.refresh_bitunix_tickers(client, cfg, now)
        if reload_markets:
            self.markets_time = now
            self.rebuild_routes()
        self.last_tickers = now

    async def _bulk_tickers(self, client, exchange, reload_markets, now):
        adapter = ADAPTERS[exchange]
        cached = dict(self.iran.get(exchange) or {})

        def parser(data):
            markets = None
            market_error = None
            if reload_markets or not cached:
                try:
                    markets = adapter.parse_markets(data)
                except ValidationError as exc:
                    market_error = exc
            tickers = adapter.parse_bulk_tickers(data, markets or cached)
            if not tickers and market_error is not None:
                raise market_error
            return markets, tickers

        result = await self._fetch(client, exchange, adapter.bulk_ticker_endpoints(), parser,
                                   adapter.ticker_budget)
        if not result or not result.ok:
            self.ticker_errors[exchange] = result.reason if result else 'unknown'
            return False
        markets, tickers = result.data
        if markets:
            self.iran[exchange] = markets
        for (coin, quote), value in tickers.items():
            key = (exchange, coin, quote)
            if isinstance(value, ValidationError):
                self.ticker_errors[key] = value
                self.tickers.pop(key, None)
            else:
                value.timestamp = now
                self.tickers[key] = value
                self.ticker_errors.pop(key, None)
        self.ticker_errors.pop(exchange, None)
        return True

    def bitunix_candidates(self, cfg):
        """Symbols to poll for a last price: visible, pinned, promising, then round-robin."""
        limit = max(1, int(cfg.get('ticker_batch', 12)))
        coins = []
        seen = set()

        def add(coin):
            if coin in seen or (coin, 'USDT') not in self.bitunix:
                return
            seen.add(coin)
            coins.append(coin)

        for key in self.visible:
            for route in self.routes:
                if route.key == key:
                    add(route.coin)
        for coin in self.store.pinned_coins() if hasattr(self.store, 'pinned_coins') else []:
            add(coin)
        scored = []
        for route in self.routes:
            value = self.reference_pct(route)
            if value is not None:
                scored.append((value, route.coin))
        scored.sort(reverse=True)
        for _, coin in scored:
            add(coin)
        symbols = list(self.bitunix)
        if symbols:
            start = self.bitunix_cursor % len(symbols)
            for coin, _ in symbols[start:] + symbols[:start]:
                add(coin)
        self.bitunix_cursor += limit
        return coins[:limit]

    async def refresh_bitunix_tickers(self, client, cfg, now=None):
        now = now or time.time()
        adapter = ADAPTERS['bitunix']
        coins = self.bitunix_candidates(cfg)
        if not coins:
            return
        async def one(coin):
            market = self.bitunix.get((coin, 'USDT'))
            if market is None:
                return
            result = await self._fetch(client, 'bitunix', adapter.ticker_endpoints(market),
                                       lambda data: adapter.parse_ticker(data, market),
                                       adapter.ticker_budget)
            key = ('bitunix', coin, 'USDT')
            if result and result.ok:
                ticker = result.data
                ticker.timestamp = now
                self.tickers[key] = ticker
                self.ticker_errors.pop(key, None)
            else:
                self.ticker_errors[key] = result.reason if result else 'unknown'
                self.tickers.pop(key, None)
        await asyncio.gather(*(one(coin) for coin in coins), return_exceptions=True)

    async def fetch_depth(self, client, book_key, cfg=None):
        cfg = cfg or self.config()
        exchange, coin, quote = book_key
        market = self.market(exchange, coin, quote)
        if market is None:
            raise ValueError('بازار یافت نشد')
        adapter = ADAPTERS[exchange]
        received = time.time()
        skew = self._clock_skew(exchange)
        stale_seconds = int(cfg.get('stale_seconds', 120))

        def parser(data):
            return adapter.parse_depth(data, market, received, stale_seconds, skew)

        result = await self._fetch(client, exchange, adapter.depth_endpoints(market), parser,
                                   adapter.depth_budget)
        if result and result.ok:
            self.books[book_key] = result.data
            self.book_errors.pop(book_key, None)
            return result.data
        self.books.pop(book_key, None)
        if result:
            self.book_errors[book_key] = {'reason': result.reason, 'detail': result.detail,
                                          'url': result.url, 'at': received}
        else:
            self.book_errors[book_key] = {'reason': 'unknown', 'detail': '', 'url': '', 'at': received}
        return None

    async def refresh_depths(self, client, cfg):
        rows = self.rows_cache or self.build_rows(cfg)
        hot = select_hot(rows, cfg.get('hot_rows', 20), self.visible, self._pinned())
        self.hot = hot
        needed = {}
        for row in rows:
            if row.get('kind') == 'classic':
                continue
            route = self.route_by_key(row.get('key'))
            if route is None:
                continue
            needed[row['key']] = route.books()
        stale_seconds = int(cfg.get('stale_seconds', 120))

        def fresh(book_key):
            book = self.books.get(book_key)
            return book is not None and not is_stale(book.timestamp, stale_seconds)

        targets = depth_targets(rows, hot, needed, fresh, cfg.get('depth_batch', 6))
        if targets:
            await asyncio.gather(*(self.fetch_depth(client, key, cfg) for key in targets),
                                 return_exceptions=True)
        return targets

    async def scan(self, client):
        async with self.lock:
            cfg = self.config()
            self.paused = bool(cfg.get('paused'))
            if self.paused:
                return
            try:
                if not self.routes or time.time() - self.markets_time > 21600:
                    await self.refresh_markets_all(client)
                if time.time() - self.last_tickers >= max(3, cfg.get('interval', 10)) or not self.tickers:
                    await self.refresh_tickers(client, cfg)
                await self.refresh_depths(client, cfg)
                rows = self.refresh_rows(cfg)
                self.rows_cache = rows
                self.last_error = None
                self.scan_count += 1
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                self.last_error = str(exc) or 'داده بازار نامعتبر بود'
            finally:
                self.last_scan = time.time()

    def refresh_rows(self, cfg):
        """Lighten first, then compute the full size envelope only for hot/visible rows."""
        light = self.build_rows(cfg)
        self.hot = select_hot(light, cfg.get('hot_rows', 20), self.visible, self._pinned())
        envelope_keys = set(self.hot) | set(self.visible) | set(self._pinned_routes())
        rows = self.build_rows(cfg, envelope_keys=envelope_keys)
        return self.merge_classic(rows, self.get_settings(), cfg)

    def _pinned_routes(self):
        pins = set(self._pinned())
        if not pins:
            return []
        return [route.key for route in self.routes if route.coin in pins]

    # ------------------------------------------------------------- discovery
    def market(self, exchange, coin, quote):
        if exchange == 'bitunix':
            return self.bitunix.get((coin, quote))
        return (self.iran.get(exchange) or {}).get((coin, quote))

    def route_by_key(self, key):
        for route in self.routes:
            if route.key == key:
                return route
        return None

    def _pinned(self):
        try:
            return self.store.pinned_coins()
        except AttributeError:
            return []

    def books_for(self, route):
        return self._book_set(route)

    def _book_set(self, route):
        books = Books()
        for exchange, coin, quote in route.books():
            book = self.books.get((exchange, coin, quote))
            if exchange == 'bitunix':
                books.bitunix = book
            elif (coin, quote) == ('USDT', 'toman'):
                books.conversion = book
            else:
                books.iran = book
        return books

    # ------------------------------------------------------------- reference
    def reference_pct(self, route):
        """Rough spread from tickers/last prices only; never displayed as profit."""
        bitunix = self.tickers.get(('bitunix', route.coin, 'USDT'))
        iran = self.tickers.get((route.iran, route.coin, route.quote))
        conversion = self.tickers.get((route.iran, 'USDT', 'toman'))
        if bitunix is None or getattr(bitunix, 'last', None) in (None, 0):
            return None
        if route.quote == 'USDT':
            if iran is None or not iran.has_two_sided:
                return None
            if route.kind == 'direct_iran_to_bitunix':
                return (bitunix.last / iran.ask - 1) * 100
            return (iran.bid / bitunix.last - 1) * 100
        if iran is None or not iran.has_two_sided or conversion is None:
            return None
        if route.kind == 'A':
            price = iran.bid / conversion.ask
            return (price / bitunix.last - 1) * 100
        price = iran.ask / conversion.bid
        return (bitunix.last / price - 1) * 100 if price else None

    # ---------------------------------------------------------------- rows
    def _fees_for(self, route, settings):
        if route.needs_conversion:
            return {'bitunix': settings.trading_fees('bitunix', 'USDT'),
                    'iran': settings.trading_fees(route.iran, 'toman'),
                    'conversion': settings.trading_fees(route.iran, 'toman')}
        return {'bitunix': settings.trading_fees('bitunix', 'USDT'),
                'iran': settings.trading_fees(route.iran, 'USDT'),
                'conversion': {'maker': 0, 'taker': 0}}

    def _withdrawals_for(self, route, cfg, fees_rows):
        selected = cfg.get('networks', {}).get(route.coin)
        usdt_selected = cfg.get('networks', {}).get('USDT')
        if route.kind == 'A':
            coin = resolve_between(fees_rows, route.coin, 'bitunix', route.iran, selected)
            usdt = resolve_between(fees_rows, 'USDT', route.iran, 'bitunix', usdt_selected)
        elif route.kind == 'B':
            coin = resolve_between(fees_rows, route.coin, route.iran, 'bitunix', selected)
            usdt = resolve_between(fees_rows, 'USDT', 'bitunix', route.iran, usdt_selected)
        elif route.kind == 'direct_iran_to_bitunix':
            coin = resolve_between(fees_rows, route.coin, route.iran, 'bitunix', selected)
            usdt = {'status': 'ok', 'withdrawal': 0, 'minimum': 0, 'networks': []}
        else:
            coin = resolve_between(fees_rows, route.coin, 'bitunix', route.iran, selected)
            usdt = {'status': 'ok', 'withdrawal': 0, 'minimum': 0, 'networks': []}
        withdrawals = {
            'bitunix_coin': coin.get('withdrawal') if coin['status'] == 'ok' else None,
            'iran_coin': coin.get('withdrawal') if coin['status'] == 'ok' else None,
            'bitunix_usdt': usdt.get('withdrawal') if usdt['status'] == 'ok' else None,
            'iran_usdt': usdt.get('withdrawal') if usdt['status'] == 'ok' else None,
        }
        return coin, usdt, withdrawals

    def _route_row(self, route, cfg, settings, fees_rows, envelope=False):
        now = time.time()
        stale_seconds = int(cfg.get('stale_seconds', 120))
        books = self._book_set(route)
        quote = route.quote
        capital = float(cfg.get('capital_usdt', 100))
        trading_mode = cfg.get('row_modes', {}).get(route.key, cfg.get('trading_mode', 'transfer'))
        margin = cfg.get('coin_margins', {}).get(route.coin, cfg.get('safety_margin', .3))
        coin_net, usdt_net, withdrawals = self._withdrawals_for(route, cfg, fees_rows)
        row = {'key': route.key, 'kind': 'cycle' if route.needs_conversion else 'direct',
               'coin': route.coin, 'quote': quote, 'route': route.kind,
               'route_label': route.label, 'venue_pair': [route.buy, route.sell],
               'buy_venue': route.buy, 'sell_venue': route.sell, 'iran': route.iran,
               'trading_mode': trading_mode, 'capital': capital, 'capital_unit': 'USDT',
               'network_coin': coin_net.get('network'), 'network_usdt': usdt_net.get('network'),
               'networks': coin_net.get('networks', []),
               'transfer_time': transfer_time(cfg, coin_net.get('network')),
               'reference_pct': self.reference_pct(route), 'status': 'ok',
               'flags': {'gross_only': False, 'stale': False, 'prefunded': trading_mode == 'prefunded',
                         'depth': bool(books.iran and books.bitunix and
                                       (books.conversion or not route.needs_conversion))}}
        missing_reason = None
        for exchange, coin, q in route.books():
            book = self.books.get((exchange, coin, q))
            error = self.book_errors.get((exchange, coin, q))
            if book is None:
                missing_reason = 'depth needed'
                row['error'] = (error or {}).get('detail') or 'عمق بازار هنوز دریافت نشده است'
                break
            if not book.is_depth:
                missing_reason = 'depth needed'
                row['error'] = 'فقط بهترین قیمت در دسترس است؛ برای سود، دفتر سفارش کامل لازم است.'
                break
            if is_stale(book.timestamp, stale_seconds, now):
                missing_reason = 'stale'
                break
        if missing_reason is None:
            for exchange, coin, q in route.books():
                ticker = self.tickers.get((exchange, coin, q))
                if ticker is None:
                    missing_reason = 'error'
                    row['error'] = 'قیمت لحظه‌ای این بازار در دسترس نیست'
                    break
        row['updated_at'] = self._updated_at(route)
        row['age'] = age_of(row['updated_at'], now)
        if missing_reason in ('stale', 'depth needed', 'error'):
            row['status'] = missing_reason
            row['flags']['stale'] = missing_reason == 'stale'
            row['flags']['gross_only'] = missing_reason != 'ok'
            row['depth_timestamp'] = None
            return row
        row['depth_timestamp'] = min(self.books[(exchange, coin, q)].timestamp
                                     for exchange, coin, q in route.books())
        result = evaluate_cycle(route.kind, books, self._fees_for(route, settings), withdrawals,
                                capital, margin=margin, trading_mode=trading_mode,
                                rebalance_trades=cfg.get('rebalance_trades', 10),
                                limit=self._balance_limit(route, cfg, trading_mode), now=now,
                                envelope=envelope)
        row['detail'] = result
        row['fee_sources'] = {'bitunix': active_fees(settings, 'bitunix', 'USDT')['fee_source'],
                              route.iran: active_fees(settings, route.iran, quote)['fee_source']}
        if route.needs_conversion:
            row['fee_sources'][route.iran + ':conversion'] = active_fees(
                settings, route.iran, 'toman')['fee_source']
        row['gross_pct'] = result.get('gross_pct')
        taker, maker = result.get('taker') or {}, result.get('maker') or {}
        row['taker'], row['maker'] = taker, maker
        row['local_rate'] = (result.get('conversion') or {}).get('rate')
        row['conversion'] = result.get('conversion')
        row['effective_rate'] = result.get('effective_rate')
        net_pct = taker.get('profit_pct') if taker.get('ok') else None
        row['net_pct'] = net_pct
        row['net_quote'] = taker.get('profit') if taker.get('ok') else None
        row['net_usdt'] = row['net_quote']
        row['net_toman'] = result.get('profit_toman')
        row['max_profitable_capital'] = taker.get('max_profitable_capital')
        row['profit_maximizing_capital'] = taker.get('profit_maximizing_capital')
        row['breakeven_capital'] = taker.get('breakeven_capital')
        row['limited_by_visible_depth'] = taker.get('limited_by_visible_depth')
        row['safety_status'] = taker.get('safety_status')
        row['verdict'] = VERDICTS.get(row['safety_status'], 'unknown')
        row['network'] = coin_net.get('network')
        network_problem = trading_mode == 'transfer' and (
            coin_net['status'] != 'ok' or usdt_net['status'] != 'ok')
        if network_problem:
            failed = coin_net if coin_net['status'] != 'ok' else usdt_net
            row['status'] = failed['status']
            row['flags']['gross_only'] = True
            row['net_pct'] = None
            row['net_quote'] = None
            row['net_usdt'] = None
            row['net_toman'] = None
            row['verdict'] = 'unknown'
            row['error'] = ('شبکه مشترک یا کارمزد برداشت برای این مسیر ثبت نشده است؛ '
                            'فقط اختلاف خام محاسبه شد.')
        elif not taker.get('ok'):
            reason = taker.get('reason') or 'error'
            row['status'] = reason if reason in ('fee unknown', 'insufficient depth') else 'error'
            row['flags']['gross_only'] = True
            row['error'] = taker.get('error') or 'محاسبه ممکن نشد'
            row['verdict'] = 'unknown'
        else:
            row['status'] = 'ok'
        return row

    def stage_prices(self, route):
        """Best ask/bid of the book each receipt stage trades against."""
        def best(key, side):
            book = self.books.get(key)
            if book is None:
                return None
            return book.best_ask if side == 'ask' else book.best_bid

        bitunix = ('bitunix', route.coin, 'USDT')
        iran = (route.iran, route.coin, route.quote)
        conversion = (route.iran, 'USDT', 'toman')
        if route.kind == 'A':
            return {'buy_coin': {'ask': best(bitunix, 'ask')},
                    'sell_coin': {'bid': best(iran, 'bid')},
                    'convert': {'ask': best(conversion, 'ask')}}
        if route.kind == 'B':
            return {'buy_coin': {'ask': best(iran, 'ask')},
                    'sell_coin': {'bid': best(bitunix, 'bid')},
                    'convert': {'bid': best(conversion, 'bid')}}
        if route.kind == 'direct_iran_to_bitunix':
            return {'buy_coin': {'ask': best(iran, 'ask')},
                    'sell_coin': {'bid': best(bitunix, 'bid')}}
        return {'buy_coin': {'ask': best(bitunix, 'ask')},
                'sell_coin': {'bid': best(iran, 'bid')}}

    def _balance_limit(self, route, cfg, trading_mode):
        if trading_mode != 'prefunded':
            return None
        balances = cfg.get('balances', {}) or {}
        value = (balances.get(route.buy) or {}).get('USDT')
        return None if value is None else float(value)

    def _updated_at(self, route):
        stamps = []
        for exchange, coin, quote in route.books():
            book = self.books.get((exchange, coin, quote))
            if book is not None:
                stamps.append(book.timestamp)
                continue
            ticker = self.tickers.get((exchange, coin, quote))
            if ticker is not None:
                stamps.append(ticker.timestamp)
        return min(stamps) if stamps else None

    def build_rows(self, cfg, envelope_keys=None):
        settings = self.get_settings()
        fees_rows = self.store.fees()
        envelope_keys = envelope_keys or set()
        rows = []
        for route in self.routes:
            try:
                rows.append(self._route_row(route, cfg, settings, fees_rows,
                                            route.key in envelope_keys))
            except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
                rows.append({'key': route.key, 'kind': 'cycle', 'coin': route.coin,
                             'quote': route.quote, 'route': route.kind,
                             'route_label': route.label, 'status': 'error',
                             'error': str(exc), 'net_pct': None, 'verdict': 'unknown',
                             'flags': {'gross_only': True, 'depth': False}})
        return rows

    def merge_classic(self, rows, settings, cfg):
        if not self.classic_rows:
            return rows
        try:
            classic = self.classic_rows()
        except (ValueError, KeyError, TypeError):
            return rows
        stale_seconds = int(cfg.get('stale_seconds', 120))
        merged = rows + [self.summarize_classic(row, stale_seconds) for row in classic]
        return merged

    def summarize_classic(self, row, stale_seconds=120):
        """Unify the classic Wallex<->Nobitex row shape for the new overview."""
        key = 'classic:' + row.get('row_key', '')
        taker = row.get('taker') or {}
        maker = row.get('maker') or {}
        quote = row.get('quote')
        net = taker.get('profit') if taker else None
        rate = row.get('rate')
        net_toman = net if quote == 'toman' else (None if net is None or not rate else net * rate)
        net_usdt = net if quote == 'USDT' else (None if net is None or not rate else net / rate)
        status = row.get('status', 'ok')
        summary = {**row, 'key': key, 'kind': 'classic', 'route': 'classic',
                   'route_label': 'بین والکس و نوبیتکس', 'venue_pair': [row.get('source'),
                                                                   row.get('destination')],
                   'status': status, 'taker': taker, 'maker': maker,
                   'net_pct': taker.get('profit_pct') if taker else None,
                   'net_quote': net, 'net_toman': net_toman, 'net_usdt': net_usdt,
                   'capital': taker.get('capital') if taker else None,
                   'capital_unit': 'تومان' if quote == 'toman' else 'USDT',
                   'max_profitable_capital': taker.get('max_profitable_capital'),
                   'profit_maximizing_capital': taker.get('profit_maximizing_capital'),
                   'breakeven_capital': taker.get('breakeven_capital'),
                   'safety_status': taker.get('safety_status'),
                   'verdict': VERDICTS.get(taker.get('safety_status'), 'unknown') if taker else 'unknown',
                   'gross_pct': row.get('gross_spread'), 'local_rate': rate,
                   'conversion': None, 'effective_rate': rate,
                   'updated_at': row.get('timestamp'),
                   'age': age_of(row.get('timestamp')),
                   'trading_mode': row.get('trading_mode'),
                   'reference_pct': row.get('gross_spread'),
                   'flags': {'gross_only': not bool(taker),
                             'stale': status == 'stale',
                             'prefunded': row.get('trading_mode') == 'prefunded',
                             'depth': bool(taker)}}
        summary['flags']['stale'] = summary['flags']['stale'] or is_stale(row.get('timestamp'), stale_seconds)
        if summary['flags']['gross_only']:
            summary['verdict'] = 'unknown'
        return summary

    async def evaluate_now(self, key, capital=None, trading_mode=None, envelope=True):
        """Fetch fresh depth for one route and calculate it (used by detail/simulations)."""
        route = self.route_by_key(key)
        if route is None:
            return None
        cfg = dict(self.config())
        if capital is not None:
            cfg['capital_usdt'] = float(capital)
        if trading_mode is not None:
            modes = dict(cfg.get('row_modes') or {})
            modes[key] = trading_mode
            cfg['row_modes'] = modes
        async with self.gateway.make_client() as client:
            await asyncio.gather(*(self.fetch_depth(client, book_key, cfg)
                                   for book_key in route.books()), return_exceptions=True)
        return self._route_row(route, cfg, self.get_settings(), self.store.fees(),
                               envelope=envelope)

    def rows(self, settings=None, cfg=None):
        cfg = cfg or self.config()
        if self.rows_cache:
            return self.rows_cache
        self.rows_cache = self.refresh_rows(cfg)
        return self.rows_cache

    def invalidate(self):
        """Settings or fees changed: recompute on the next request/scan."""
        self.rows_cache = []
        self.last_tickers = 0.0

    def pinned(self):
        try:
            return list(self.store.ui_state().get('pins', []))
        except AttributeError:
            return []

    # ------------------------------------------------------------ summaries
    def conversion_rate(self, cfg):
        """Reference USDT/toman rate for display, with its source and side."""
        source = cfg.get('conversion_source', 'auto')
        options = []
        for exchange in IRAN_EXCHANGES:
            ticker = self.tickers.get((exchange, 'USDT', 'toman'))
            if ticker is None or not ticker.has_two_sided:
                continue
            options.append({'exchange': exchange, 'bid': ticker.bid, 'ask': ticker.ask,
                            'timestamp': ticker.timestamp, 'age': age_of(ticker.timestamp)})
        if not options:
            return None
        chosen = next((item for item in options if item['exchange'] == source), None)
        if chosen is None:
            chosen = min(options, key=lambda item: item['age'] or 0)
        return {**chosen, 'requested_source': source, 'side': 'bid/ask',
                'label': 'نرخ تتر/تومان از ' + EXCHANGE_LABELS.get(chosen['exchange'], chosen['exchange'])}

    def exchange_status(self, cfg):
        now = time.time()
        stale_seconds = int(cfg.get('stale_seconds', 120))
        status = {}
        for name in ADAPTERS:
            last = self.monitor.last_failure.get(name)
            success = self.monitor.last_success.get(name)
            samples = [ticker for key, ticker in self.tickers.items() if key[0] == name]
            fresh = [ticker for ticker in samples
                     if not is_stale(ticker.timestamp, stale_seconds, now)] if samples else []
            if last is not None and (success is None or last.at > success):
                state = 'error'
            elif samples and not fresh:
                state = 'stale'
            elif success is not None:
                state = 'ok'
            else:
                state = 'unknown'
            status[name] = {'state': state, 'label': EXCHANGE_LABELS.get(name, name),
                            'last_success': success, 'last_error': last.reason if last else None,
                            'markets': len(self.bitunix) if name == 'bitunix' else len(self.iran.get(name) or {}),
                            'fresh_tickers': len(fresh), 'tickers': len(samples)}
        return status

    def summary(self, rows, cfg):
        usable = [row for row in rows if row.get('net_pct') is not None
                  and row.get('status') == 'ok' and not row.get('flags', {}).get('stale')]
        profitable = [row for row in usable if (row.get('net_quote') or 0) > 0]
        best = max(profitable, key=lambda row: row['net_pct'], default=None)
        rate = self.conversion_rate(cfg)
        next_refresh = None
        if self.last_scan and not cfg.get('paused'):
            next_refresh = max(0.0, self.last_scan + max(1, int(cfg.get('interval', 10)))
                               - time.time())
        return {'profitable_count': len(profitable), 'usable_count': len(usable),
                'total_rows': len(rows),
                'best': None if best is None else {
                    'key': best['key'], 'coin': best['coin'], 'net_pct': best['net_pct'],
                    'net_toman': best.get('net_toman'), 'route_label': best.get('route_label')},
                'conversion': rate, 'exchanges': self.exchange_status(cfg),
                'next_refresh': next_refresh, 'paused': bool(cfg.get('paused')),
                'last_scan': self.last_scan, 'last_error': self.last_error,
                'hot_keys': self.hot[:int(cfg.get('hot_rows', 20))],
                'market_routes': len(self.routes), 'scan_count': self.scan_count}
