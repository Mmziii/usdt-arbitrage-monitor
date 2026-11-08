"""Bulk public market scan, bounded depth requests and conservative estimates."""
import asyncio
import math
import time
from collections import deque
import httpx
from .markets import wallex_markets, nobitex_markets, intersection
from .fetchers import parse_book
from .fees import resolve
from .calculation import InsufficientDepth
from .trading import evaluate, transfer_time, analyze_capital
from .tiers import active_fees

URLS = {'wallex': 'https://api.wallex.ir/v1/markets', 'nobitex': 'https://apiv2.nobitex.ir/market/stats'}


def quotes(w, n, markets, now):
    result = {}
    for market in markets:
        coin, quote = market['coin'], market['quote']
        try:
            ws = w['result']['symbols'][market['wallex']]['stats']
            ns = n['stats'][coin.lower() + ('-rls' if quote == 'toman' else '-usdt')]
            div = 10 if quote == 'toman' else 1
            values = [float(ws['askPrice']), float(ws['bidPrice']), float(ns['bestSell'])/div, float(ns['bestBuy'])/div]
            if not all(math.isfinite(x) and x > 0 for x in values) or values[1] > values[0] or values[3] > values[2]:
                raise ValueError('invalid ticker')
            result[(coin, quote)] = {'wallex_ask': values[0], 'wallex_bid': values[1], 'nobitex_ask': values[2], 'nobitex_bid': values[3], 'timestamp': now}
        except (ValueError, KeyError, TypeError, OverflowError):
            result[(coin, quote)] = {'error': 'قیمت بازار نامعتبر یا در دسترس نیست', 'timestamp': now}
    return result


class Scanner:
    def __init__(self, store, gateway=None):
        self.store = store
        self.gateway = gateway
        self.store.init_scanner()
        self.markets, self.excluded, self.tickers, self.depth = [], [], {}, {}
        self.market_time = 0
        self.depth_errors = {}
        self.tracked_markets = set()
        self.error = None
        self.depth_cursor = 0
        self.lock = asyncio.Lock()
        self.semaphores = {n: asyncio.Semaphore(2) for n in URLS}
        self.budgets = {n: deque() for n in URLS}
        self.budget_locks = {n: asyncio.Lock() for n in URLS}

    def config(self):
        saved = self.store.scanner_settings()
        saved.pop('trading_overrides', None)  # Ignore legacy per-coin fees.
        return {'interval': 10, 'retention_days': 30, 'capital_toman': 10000000, 'capital_usdt': 100, 'threshold': .5, 'watchlist': [], 'networks': {}, 'trading_mode': 'transfer', 'row_modes': {}, 'safety_margin': .3, 'coin_margins': {}, 'transfer_minutes': {'default': 60, 'TRC20': 5, 'BEP20': 5, 'ERC20': 10, 'BTC': 60}, 'balances': {}, 'rebalance_trades': 10, 'close_confirmations': 2, 'depth_interval': 5, 'hot_rows': 20, 'sort_hysteresis_pct': .05, 'stale_seconds': 120, 'paused': False, 'conversion_source': 'auto', 'show_gross_only': True, **saved}

    async def request(self, client, name, url, endpoint_id='classic', budget_name=None):
        if self.gateway is not None:
            from .net import Endpoint, ExchangeError
            result = await self.gateway.fetch(client, name, Endpoint(endpoint_id, url),
                                              budget_name=budget_name or name)
            if not result.ok:
                raise ExchangeError(result)
            return result.data
        async with self.semaphores[name]:
            for attempt in range(3):
                async with self.budget_locks[name]:
                    q = self.budgets[name]
                    while q and q[0] <= time.monotonic() - 60:
                        q.popleft()
                    if len(q) >= 18:
                        await asyncio.sleep(max(0, 60 - (time.monotonic() - q[0])))
                        while q and q[0] <= time.monotonic() - 60:
                            q.popleft()
                    q.append(time.monotonic())
                try:
                    response = await client.get(url, timeout=8)
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 429 and exc.response.status_code < 500:
                        raise
                    if attempt == 2:
                        raise
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == 2:
                        raise
                await asyncio.sleep(2 ** attempt)

    async def scan(self, client, refresh=False):
        async with self.lock:
            try:
                budgets = {'wallex': 'wallex:stats', 'nobitex': 'nobitex:stats'}
                w, n = await asyncio.gather(*(self.request(client, name, url, 'stats', budgets[name])
                                              for name, url in URLS.items()))
                if refresh or not self.markets or time.time() - self.market_time >= 21600:
                    markets, excluded = intersection(wallex_markets(w), nobitex_markets(n))
                    self.markets, self.excluded, self.market_time = markets, excluded, time.time()
                now = time.time()
                self.tickers = quotes(w, n, self.markets, now)
                self.error = None
                samples = []
                for (coin, quote), q in self.tickers.items():
                    if 'error' not in q:
                        samples.append((now, coin, quote, q['wallex_bid'], q['wallex_ask'], q['nobitex_bid'], q['nobitex_ask'], (q['nobitex_bid']/q['wallex_ask']-1)*100, (q['wallex_bid']/q['nobitex_ask']-1)*100))
                self.store.scan_record(samples, self.config()['retention_days'])
                # Cap work to two markets; revisit previously observed depth even after raw spread turns negative.
                candidates = [(max(q['nobitex_bid']/q['wallex_ask'], q['wallex_bid']/q['nobitex_ask']), key) for key, q in self.tickers.items() if 'error' not in q]
                candidates = sorted((item for item in candidates if item[0] > 1 or item[1] in self.depth or item[1] in self.depth_errors or item[1] in self.tracked_markets), reverse=True)
                if candidates:
                    start = self.depth_cursor % len(candidates)
                    selected = (candidates[start:] + candidates[:start])[:2]
                    self.depth_cursor += len(selected)
                    for _, key in selected:
                        try:
                            await self.fetch_depth(client, *key)
                        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
                            pass  # fetch_depth records a per-market error
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                self.error = str(exc) or 'دریافت داده بازار ناموفق بود'
                raise

    async def fetch_depth(self, client, coin, quote):
        market = next((m for m in self.markets if m['coin'] == coin and m['quote'] == quote), None)
        if not market:
            raise ValueError('بازار مشترک یافت نشد')
        urls = {'wallex': 'https://api.wallex.ir/v1/depth?symbol=' + market['wallex'], 'nobitex': 'https://apiv2.nobitex.ir/v3/orderbook/' + market['nobitex']}
        key = (coin, quote)
        try:
            data = await asyncio.gather(*(self.request(client, name, url, 'depth', name)
                                          for name, url in urls.items()))
            # Existing parser divides Nobitex prices by ten; compensate on USDT books.
            w = parse_book('wallex', data[0]); n = parse_book('nobitex', data[1])
            if quote == 'USDT':
                n.asks = [(p*10, q) for p, q in n.asks]; n.bids = [(p*10, q) for p, q in n.bids]
            self.depth[key] = {'wallex': w, 'nobitex': n, 'timestamp': min(w.timestamp, n.timestamp)}
            self.depth_errors.pop(key, None)
            return self.depth[key]
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            self.depth.pop(key, None)
            self.depth_errors[key] = str(exc) or 'دریافت عمق ناموفق بود'
            raise

    def rows(self, settings):
        cfg = self.config(); fees = self.store.fees(); now = time.time(); rows = []
        conversion = self.tickers.get(('USDT', 'toman'), {})
        rate = (conversion.get('wallex_bid', 0) + conversion.get('nobitex_bid', 0))/2 if now - conversion.get('timestamp', 0) <= 120 else 0
        for market in self.markets:
            coin, quote = market['coin'], market['quote']; q = self.tickers.get((coin, quote), {})
            for src, dst in [('wallex','nobitex'), ('nobitex','wallex')]:
                row = {'coin': coin, 'quote': quote, 'source': src, 'destination': dst, **q, 'rate': rate or None}
                key = ':'.join((coin, quote, src, dst))
                trading_mode = cfg['row_modes'].get(key, cfg['trading_mode'])
                fee = resolve(fees, coin, src, cfg['networks'].get(coin)); row.update(fee)
                row.update(row_key=key, trading_mode=trading_mode, transfer_time=transfer_time(cfg, fee.get('network')))
                if trading_mode == 'prefunded':
                    row['status'] = 'ok'  # No network support is needed for simultaneous trades.
                row['fee_sources'] = {n: active_fees(settings, n, quote)['fee_source'] for n in (src, dst)}
                book = self.depth.get((coin, quote))
                if not q or 'error' in q:
                    row['status'] = 'error'
                elif now - q['timestamp'] > 120:
                    row['status'] = 'stale'
                else:
                    row['gross_spread'] = (q[dst+'_bid']/q[src+'_ask']-1)*100
                    if row['status'] == 'ok':
                        if not book:
                            row['status'] = 'error' if (coin, quote) in self.depth_errors else 'depth needed'
                            if (coin, quote) in self.depth_errors:
                                row['error'] = self.depth_errors[(coin, quote)]
                        elif now - book['timestamp'] > 120:
                            row['status'] = 'stale'
                        else:
                            row['liquidity'] = min(sum(p*v for p,v in book[src].asks), sum(p*v for p,v in book[dst].bids))
                            row['capital_analysis'] = {}
                            for mode in ('taker','maker'):
                                source_fees = {**settings.trading_fees(src, quote), 'withdrawal': fee.get('withdrawal') or 0, 'minimum': fee.get('minimum') or 0}
                                dest_fees = settings.trading_fees(dst, quote)
                                row['capital_analysis'][mode] = analyze_capital(book[src], book[dst], source_fees, dest_fees, mode,
                                    trading_mode, cfg['coin_margins'].get(coin, cfg['safety_margin']),
                                    cfg['balances'].get(src, {}).get(quote), cfg['balances'].get(dst, {}).get(coin))
                                try:
                                    coin_reset = resolve(fees, coin, dst, cfg['networks'].get(coin))
                                    quote_reset = resolve(fees, 'USDT' if quote == 'USDT' else 'TOMAN', src, cfg['networks'].get('USDT' if quote == 'USDT' else 'TOMAN'))
                                    row[mode] = evaluate(cfg['capital_toman' if quote == 'toman' else 'capital_usdt'], book[src], book[dst], source_fees, dest_fees, mode,
                                        trading_mode, cfg['coin_margins'].get(coin, cfg['safety_margin']),
                                        cfg['balances'].get(src, {}).get(quote), cfg['balances'].get(dst, {}).get(coin),
                                        cfg['rebalance_trades'], coin_reset.get('withdrawal') if coin_reset['status'] == 'ok' else None,
                                        quote_reset.get('withdrawal') if quote_reset['status'] == 'ok' else None)
                                except (ValueError, ZeroDivisionError) as e:
                                    row['status'] = 'insufficient depth' if isinstance(e, InsufficientDepth) else 'error'
                                    row['error'] = str(e)
                    if row['status'] != 'ok':
                        row.pop('maker', None); row.pop('taker', None)
                    row['depth_timestamp'] = book['timestamp'] if book else None
                rows.append(row)
        return rows
