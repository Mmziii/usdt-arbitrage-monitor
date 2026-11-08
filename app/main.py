import asyncio
import contextlib
import csv
import io
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pydantic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from .fetchers import Book, fetch_book
from .storage import Storage
from .scanner import Scanner
from .symbols import normalize
from .fees import parse_pasted_fees, resolve
from .tiers import Tier, active_fees, parse_tiers, export_tiers
from .opportunities import OpportunityTracker, statistics
from .trading import transfer_time, evaluate
from .adapters import ADAPTERS, EXCHANGE_LABELS, public_depth
from .amounts import AmountError, parse_amount
from .diagnostics import build as diagnostics_build, describe
from .hub import Hub
from . import decision as decision_engine
from . import fee_confidence, fee_sources, fee_text, gauge, receipt as receipt_builder
from . import setup as setup_model
from .journal import JournalError, export_csv as journal_csv, validate as validate_journal
from .fee_sources import DEFAULT_FEE_PAGES
from .net import DEFAULT_AGENT, Gateway, Monitor, budget, budgets
from .plans import build_plan, venue_for
from .simulation import SimulationError, create as create_simulation_record
from .simulation import public as public_simulation
from .simulation import settle as settle_simulation
from .simulation import snapshot_prices, summary as simulation_summary
from typing import Any, Optional, Literal

load_dotenv()
store = Storage(os.getenv('DATABASE_PATH', 'history.sqlite3'))


class TradingFees(BaseModel):
    maker: float = Field(ge=0, lt=100, allow_inf_nan=False)
    taker: float = Field(ge=0, lt=100, allow_inf_nan=False)


class Fees(TradingFees):
    withdrawal: float = Field(ge=0, allow_inf_nan=False)


class OptionalTradingFees(BaseModel):
    """Bitunix rates are shipped as *unknown*; the user must enter their real tier."""
    maker: Optional[float] = Field(default=None, ge=0, lt=100, allow_inf_nan=False)
    taker: Optional[float] = Field(default=None, ge=0, lt=100, allow_inf_nan=False)


class AppSettings(BaseModel):
    refresh_seconds: int = Field(default=10, ge=5, le=3600)
    threshold: float = Field(default=.5, ge=0, le=100, allow_inf_nan=False)
    wallex: Fees = Fees(maker=.25, taker=.3, withdrawal=.8)
    nobitex: Fees = Fees(maker=.25, taker=.25, withdrawal=.7)
    wallex_usdt: TradingFees = TradingFees(maker=.25, taker=.3)
    nobitex_usdt: TradingFees = TradingFees(maker=.25, taker=.25)
    bitunix: OptionalTradingFees = OptionalTradingFees()
    bitunix_usdt: OptionalTradingFees = OptionalTradingFees()
    proxy_url: Optional[str] = None
    user_agent: str = Field(default=DEFAULT_AGENT, min_length=3, max_length=200)
    # Nobitex documents a bot style User-Agent and its CDN rejects some library defaults,
    # so this one is separately configurable. Empty means "use the general one".
    nobitex_user_agent: Optional[str] = Field(default=None, max_length=200)
    max_timestamp_age_seconds: int = Field(default=120, ge=10, le=3600)
    clock_skew_warning_seconds: int = Field(default=60, ge=10, le=3600)
    # A fee typed by hand is not wrong forever: after this many days the UI asks the user
    # to check it again. Nothing is ever refreshed silently.
    fee_stale_days: int = Field(default=14, ge=1, le=365)
    # Best-known official fee pages; the user can edit them. The Fee Assistant opens these.
    fee_pages: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_FEE_PAGES))

    fee_tiers: list[Tier] = []
    current_tiers: dict[str, str] = {}

    @field_validator('proxy_url')
    @classmethod
    def valid_proxy(cls, value):
        if value in (None, ''):
            return None
        value = value.strip()
        if not re.match(r'^(https?|socks5h?|socks4)://[^\s]+$', value):
            raise ValueError('آدرس پروکسی باید با http:// یا https:// یا socks5:// شروع شود')
        return value

    @field_validator('user_agent')
    @classmethod
    def valid_agent(cls, value):
        value = value.strip()
        if not value or '\n' in value or '\r' in value:
            raise ValueError('User-Agent نامعتبر است')
        return value

    @field_validator('nobitex_user_agent')
    @classmethod
    def valid_nobitex_agent(cls, value):
        if value in (None, ''):
            return None
        value = value.strip()
        if '\n' in value or '\r' in value:
            raise ValueError('User-Agent نوبیتکس نامعتبر است')
        return value

    @field_validator('fee_pages')
    @classmethod
    def valid_fee_pages(cls, value):
        clean = {}
        for name, url in (value or {}).items():
            if name not in ('wallex', 'nobitex', 'bitunix'):
                continue
            url = str(url or '').strip()
            if not url:
                continue
            if not re.match(r'^https?://[^\s]+$', url):
                raise ValueError('آدرس صفحه کارمزد باید با http:// یا https:// شروع شود')
            clean[name] = url[:300]
        return clean

    @model_validator(mode='after')
    def unique_tiers(self):
        keys = [(t.exchange, t.quote, t.name) for t in self.fee_tiers]
        if len(keys) != len(set(keys)):
            raise ValueError('سطح تکراری')
        return self


    def trading_fees(self, exchange, quote):
        return {k: v for k, v in active_fees(self, exchange, quote).items() if k in ('maker', 'taker')}


Settings = AppSettings

_ENV_DEFAULTS = {
    'refresh_seconds': int(os.getenv('REFRESH_SECONDS', '10')),
    'proxy_url': os.getenv('PROXY_URL') or None,
    'user_agent': os.getenv('USER_AGENT') or DEFAULT_AGENT,
    'nobitex_user_agent': os.getenv('NOBITEX_USER_AGENT') or None,
    'max_timestamp_age_seconds': int(os.getenv('MAX_TIMESTAMP_AGE', '120')),
    'clock_skew_warning_seconds': int(os.getenv('CLOCK_SKEW_WARNING', '60')),
}
settings = Settings(**{**_ENV_DEFAULTS, **(store.settings() or {})})
books, errors, manual = {}, {}, {}
wake = asyncio.Event()
monitor = Monitor()
gateway = Gateway(monitor=monitor, user_agent=settings.user_agent, proxy=settings.proxy_url,
                  exchange_agents={'nobitex': settings.nobitex_user_agent})

scanner = Scanner(store, gateway)
tracker = OpportunityTracker(store)
store.init_ui()
hub = Hub(store, gateway, lambda: settings, classic_rows=lambda: scanner.rows(settings))


async def poll():
    while True:
        async with gateway.make_client() as client:
            async def update(name):
                try:
                    books[name] = await fetch_book(client, name, gateway,
                                                   settings.max_timestamp_age_seconds)
                    errors.pop(name, None)
                except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
                    books.pop(name, None)
                    reason = getattr(getattr(exc, 'result', None), 'reason', None)
                    if reason:
                        described = describe(reason)
                        errors[name] = described['message'] + ' ' + described['action']
                    else:
                        errors[name] = ('دریافت قیمت یا ساختار داده نامعتبر است؛ '
                                        'قیمت خرید و فروش را دستی وارد کنید.')
            await asyncio.gather(*(update(n) for n in ('wallex', 'nobitex')))
            if len(books) == 2:
                store.record(time.time(), books['wallex'], books['nobitex'])
        try:
            await asyncio.wait_for(wake.wait(), timeout=settings.refresh_seconds)
        except asyncio.TimeoutError:
            pass
        wake.clear()


async def scan_loop():
    while True:
        try:
            async with gateway.make_client() as client:
                scanner.tracked_markets = tracker.active_markets()
                await scanner.scan(client)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            pass
        cfg = scanner.config()
        tracker.cycle(scanner.rows(settings), time.time(), cfg['close_confirmations'], known=scanner.error is None)
        tracker.prune(time.time()-cfg['retention_days']*86400)
        scanner.store.prune(cfg['retention_days'])
        hub.invalidate()
        await asyncio.sleep(scanner.config()['interval'])


_best_recorded_at = 0.0


def remember_best():
    """Store this scan's best net % so the gauge has a history to compare against.

    At most one sample per minute: the gauge compares positions in time, not request counts.
    """
    global _best_recorded_at
    now = time.time()
    if now - _best_recorded_at < 60:
        return
    try:
        cfg = hub.config()
        rows = hub.rows(settings, cfg)
        store.record_best(now, [row for row in rows if row.get('net_pct') is not None])
        _best_recorded_at = now
    except (ValueError, KeyError, TypeError):
        pass


async def hub_loop():
    """Bulk overview scan every `interval` seconds; hot-row depth every `depth_interval`."""
    while True:
        try:
            async with gateway.make_client() as client:
                await hub.scan(client)
            remember_best()
            await refresh_automatic_fees()
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            hub.last_error = str(exc) or 'داده بازار نامعتبر بود'
        await asyncio.sleep(max(1, int(hub.config().get('depth_interval', 5))))


async def settle_one(simulation_id):
    record = store.simulation(simulation_id)
    if record is None or record.get('status') != 'pending':
        return None
    try:
        row = await hub.evaluate_now(record['key'], capital=record.get('capital'),
                                     trading_mode=record.get('mode'), envelope=False)
    except (ValueError, KeyError, TypeError):
        row = None
    if row is None:
        store.update_simulation(simulation_id, {
            'status': 'unavailable', 'completed': time.time(),
            'note': 'مسیر این معامله آزمایشی دیگر در فهرست بازارها نیست.'})
        return store.simulation(simulation_id)
    return settle_simulation(store, record, row)


async def simulation_loop():
    while True:
        await asyncio.sleep(10)
        try:
            pending = store.pending_simulations()
        except (ValueError, TypeError):
            continue
        for record in pending:
            if record.get('due') and record['due'] <= time.time():
                try:
                    await settle_one(record['id'])
                except (ValueError, KeyError, TypeError):
                    pass
        await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app):
    tasks = [asyncio.create_task(poll()), asyncio.create_task(scan_loop()),
             asyncio.create_task(hub_loop()), asyncio.create_task(simulation_loop())]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title='USDT monitor — read only', lifespan=lifespan)
static = Path(__file__).parent / 'static'
app.mount('/static', StaticFiles(directory=static), name='static')


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    '''Malformed input is answered in Persian: the UI shows `detail` verbatim.'''
    fields = []
    for error in exc.errors():
        location = [str(part) for part in error.get('loc', ())
                    if part not in ('body', 'query', 'path')]
        fields.append('.'.join(location) or 'ورودی')
    names = '، '.join(dict.fromkeys(fields))
    message = ('مقدار ورودی نامعتبر است' + (f' (فیلد {names})' if names else '')
               + '؛ عددها و متن‌ها را دوباره بررسی کنید.')
    return JSONResponse(status_code=422, content={'detail': message,
                                                 'errors': jsonable_encoder(exc.errors())})


@app.get('/')
def index():
    """The one question that matters: is now a good moment?"""
    return FileResponse(static / 'home.html')


@app.get('/dashboard')
def dashboard_page():
    """The full table, kept as an advanced tool behind the home screen."""
    return FileResponse(static / 'dashboard.html')


@app.get('/fees')
def fees_page():
    return FileResponse(static / 'fees.html')


@app.get('/classic')
def classic_page():
    return FileResponse(static / 'index.html')


@app.get('/guide')
def guide_page():
    return FileResponse(static / 'guide.html')


@app.get('/settings')
def settings_page():
    return FileResponse(static / 'overview.html')


@app.get('/api/settings')
def get_settings():
    return settings


@app.put('/api/settings')
def put_settings(value: Settings):
    global settings
    settings = value
    store.save_settings(value.model_dump())
    gateway.configure(user_agent=value.user_agent, proxy=value.proxy_url,
                      exchange_agents={'nobitex': value.nobitex_user_agent})
    hub.invalidate()
    wake.set()
    return settings


class ManualPrice(BaseModel):
    ask: float = Field(gt=0, allow_inf_nan=False)
    bid: float = Field(gt=0, allow_inf_nan=False)


@app.put('/api/manual/{name}')
def set_manual(name: str, value: ManualPrice):
    if name not in ('wallex', 'nobitex') or value.bid > value.ask:
        raise HTTPException(400, 'نام صرافی یا قیمت خرید و فروش نامعتبر است')
    manual[name] = Book([(value.ask, 1e15)], [(value.bid, 1e15)], time.time(), 'manual')
    active = {n: books.get(n) or manual.get(n) for n in ('wallex', 'nobitex')}
    if all(active.values()):
        store.record(time.time(), active['wallex'], active['nobitex'])
    return {'ok': True}


@app.get('/api/snapshot')
def snapshot(capital: float = 10000000):
    if not 0 < capital <= 1e15:
        raise HTTPException(400, 'سرمایه باید مثبت و حداکثر ۱۰ به توان ۱۵ باشد')
    active = {n: books.get(n) or manual.get(n) for n in ('wallex', 'nobitex')}
    rows = []
    if all(active.values()):
        for src, dst in [('wallex', 'nobitex'), ('nobitex', 'wallex')]:
            for mode in ('maker', 'taker'):
                row = {'source': src, 'destination': dst, 'mode': mode}
                try:
                    cfg = scanner.config()
                    trading_mode = cfg['row_modes'].get(':'.join(('USDT', 'toman', src, dst)), cfg['trading_mode'])
                    coin_reset = resolve(scanner.store.fees(), 'USDT', dst, cfg['networks'].get('USDT'))
                    quote_reset = resolve(scanner.store.fees(), 'TOMAN', src, cfg['networks'].get('TOMAN'))
                    row.update(evaluate(capital, active[src], active[dst],
                        {**settings.trading_fees(src, 'toman'), 'withdrawal': getattr(settings, src).withdrawal}, settings.trading_fees(dst, 'toman'), mode,
                        trading_mode, cfg['coin_margins'].get('USDT', cfg['safety_margin']), cfg['balances'].get(src, {}).get('toman'),
                        cfg['balances'].get(dst, {}).get('USDT'), cfg['rebalance_trades'],
                        coin_reset.get('withdrawal') if coin_reset['status'] == 'ok' else None,
                        quote_reset.get('withdrawal') if quote_reset['status'] == 'ok' else None))
                    row['fee_sources'] = {n: active_fees(settings, n, 'toman')['fee_source'] for n in (src,dst)}
                except ValueError as exc:
                    row['error'] = str(exc)
                rows.append(row)
    return {'books': {n: {'bid': b.bids[0][0], 'ask': b.asks[0][0], 'timestamp': b.timestamp, 'source': b.source, 'levels': [len(b.asks), len(b.bids)]} if b else None for n, b in active.items()}, 'errors': errors, 'rows': rows, 'settings': settings.model_dump()}


@app.get('/api/history')
def history():
    return store.history()


@app.get('/api/history.csv')
def export():
    rows = store.history(1000000)
    stream = io.StringIO()
    columns = ['timestamp', 'wallex_bid', 'wallex_ask', 'nobitex_bid', 'nobitex_ask', 'spread_a', 'spread_b', 'source']
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return Response('\ufeff' + stream.getvalue(), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename=usdt-history.csv'})


class NetworkFee(BaseModel):
    exchange: Literal['wallex', 'nobitex', 'bitunix']
    coin: str = Field(min_length=2, max_length=20)
    network: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
    withdrawal: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    minimum: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    supported: bool = Field(strict=True)


class ScannerSettings(BaseModel):
    interval: int = Field(default=10, ge=5, le=60)
    depth_interval: int = Field(default=5, ge=3, le=120)
    hot_rows: int = Field(default=20, ge=0, le=200)
    sort_hysteresis_pct: float = Field(default=.05, ge=0, le=5, allow_inf_nan=False)
    stale_seconds: int = Field(default=120, ge=30, le=3600)
    paused: bool = Field(default=False, strict=True)
    conversion_source: Literal['auto', 'wallex', 'nobitex'] = 'auto'
    show_gross_only: bool = Field(default=True, strict=True)
    retention_days: int = Field(default=30, ge=1, le=3650)
    capital_toman: float = Field(default=10000000, gt=0, le=1e15, allow_inf_nan=False)
    capital_usdt: float = Field(default=100, gt=0, le=1e15, allow_inf_nan=False)
    threshold: float = Field(default=.5, ge=0, le=100, allow_inf_nan=False)
    watchlist: list[str] = []
    networks: dict[str, str] = {}
    trading_mode: Literal['transfer', 'prefunded'] = 'transfer'
    row_modes: dict[str, Literal['transfer', 'prefunded']] = {}
    safety_margin: float = Field(default=.3, ge=0, le=100, allow_inf_nan=False)
    coin_margins: dict[str, float] = {}
    # Rough, clearly-labelled starting points. They are editable and the UI always says
    # "تقریبی"; nothing here is measured.
    transfer_minutes: dict[str, Optional[float]] = {'default': 60, 'TRC20': 5, 'BEP20': 5,
                                                    'ERC20': 10, 'BTC': 60, 'TON': 5}
    setup: dict = {}
    other_costs_toman: float = Field(default=0, ge=0, le=1e12, allow_inf_nan=False)
    other_costs_note: str = Field(default='', max_length=200)
    fee_candidate_limit: int = Field(default=10, ge=1, le=50)
    gauge_days: int = Field(default=7, ge=1, le=30)
    balances: dict[str, dict[str, Optional[float]]] = {}
    rebalance_trades: int = Field(default=10, ge=1, le=1000000)
    close_confirmations: int = Field(default=2, ge=1, le=100)

    @model_validator(mode='after')
    def validate_options(self):
        import math
        values = list(self.coin_margins.values()) + list(self.transfer_minutes.values())
        values += [v for balances in self.balances.values() for v in balances.values()]
        if any(v is not None and (not math.isfinite(v) or v < 0) for v in values):
            raise ValueError('مقادیر باید نامنفی و متناهی باشند')
        return self




@app.get('/overview')
def overview_page():
    return FileResponse(static / 'overview.html')


@app.get('/api/scanner/settings')
def scanner_settings():
    return scanner.config()


@app.put('/api/scanner/settings')
def save_scanner_settings(value: ScannerSettings):
    scanner.store.save_scanner_settings(value.model_dump())
    return scanner.config()


class FeePaste(BaseModel):
    text: str = Field(max_length=200000)


@app.post('/api/scanner/fees/preview')
def preview_fees(value: FeePaste):
    return parse_pasted_fees(value.text)


@app.get('/api/scanner/fees')
def scanner_fees():
    return scanner.store.fees()


@app.put('/api/scanner/fees')
def save_scanner_fees(values: list[NetworkFee]):
    rows = []
    seen = set()
    for value in values:
        row = value.model_dump()
        try:
            row['coin'] = normalize(row['coin'])
        except ValueError:
            raise HTTPException(400, 'نماد نامعتبر')
        row['network'] = row['network'].upper()
        key = (row['exchange'], row['coin'], row['network'])
        if key in seen:
            raise HTTPException(400, 'ردیف تکراری')
        seen.add(key); rows.append(row)
    scanner.store.replace_fees(rows)
    return rows


@app.get('/api/scanner')
def scanner_snapshot():
    return {'rows': scanner.rows(settings), 'excluded': scanner.excluded, 'market_time': scanner.market_time, 'error': scanner.error, 'settings': scanner.config()}


@app.post('/api/scanner/refresh')
async def scanner_refresh():
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await scanner.scan(client, refresh=True)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        raise HTTPException(503, describe('network')['message'] + ' '
                            + 'دوباره تلاش کنید؛ اگر تکرار شد تب «عیب‌یابی» را ببینید.')
    return {'ok': True}


@app.get('/api/scanner/detail/{coin}/{quote}')
async def scanner_detail(coin: str, quote: Literal['toman', 'USDT']):
    try:
        coin = normalize(coin)
        async with httpx.AsyncClient(timeout=8) as client:
            books = await scanner.fetch_depth(client, coin, quote)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        raise HTTPException(503, 'دفتر سفارش این بازار دریافت نشد؛ کمی بعد دوباره تلاش کنید '
                                 'یا تب «عیب‌یابی» را ببینید.')
    return {'books': {n: {'asks': books[n].asks[:10], 'bids': books[n].bids[:10]} for n in ('wallex', 'nobitex')}, 'rows': [r for r in scanner.rows(settings) if r['coin'] == coin and r['quote'] == quote], 'history': scanner.store.scan_history(coin, quote)}


@app.get('/api/scanner/history')
def scanner_history(coin: Optional[str] = None, quote: Optional[str] = None):
    return scanner.store.scan_history(coin, quote)


@app.get('/api/scanner/history.csv')
def scanner_history_csv(coin: Optional[str] = None, quote: Optional[str] = None):
    stream = io.StringIO()
    columns = ['timestamp','coin','quote','wallex_bid','wallex_ask','nobitex_bid','nobitex_ask','spread_a','spread_b']
    writer = csv.DictWriter(stream, fieldnames=columns); writer.writeheader()
    writer.writerows(scanner.store.scan_history(coin, quote, 1000000))
    return Response('\ufeff' + stream.getvalue(), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename=market-history.csv'})


@app.get('/api/tiers/export')
def tiers_export(format: Literal['json', 'csv'] = 'json'):
    return Response(export_tiers(settings.fee_tiers, format), media_type='application/json' if format == 'json' else 'text/csv', headers={'Content-Disposition': f'attachment; filename=fee-tiers.{format}'})


class TierImport(BaseModel):
    text: str = Field(max_length=200000)
    format: Literal['json', 'csv'] = 'json'


@app.post('/api/tiers/import')
def tiers_import(value: TierImport):
    try:
        tiers = parse_tiers(value.text, value.format)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(400, str(exc))
    updated = settings.model_copy(update={'fee_tiers': tiers})
    put_settings(updated)
    return settings


@app.get('/api/opportunities')
def opportunity_stats(coin: Optional[str] = None, mode: Optional[Literal['transfer', 'prefunded']] = None, network: Optional[str] = None):
    mode = mode or scanner.config()['trading_mode']
    rows = tracker.rows(coin, mode)
    minutes = transfer_time(scanner.config(), network)['minutes'] if mode == 'transfer' else None
    return {'overall': statistics(rows, minutes), 'coins': {c: statistics([r for r in rows if r['coin'] == c], minutes) for c in sorted({r['coin'] for r in rows})}, 'transfer_minutes': minutes}


@app.get('/api/opportunities.csv')
def opportunity_export(coin: Optional[str] = None, mode: Optional[str] = None):
    rows = tracker.rows(coin, mode)
    stream = io.StringIO()
    columns = ['id','key','coin','quote','source','destination','mode','network','start','end','duration','peak_pct','capital_at_peak','unknown_gaps']
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader(); writer.writerows(rows)
    return Response('\ufeff'+stream.getvalue(), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename=opportunities.csv'})


# ===================================================================== new overview API
UI_DEFAULTS = {
    'theme': 'system', 'font_scale': 'medium', 'digits': 'fa', 'view': 'simple',
    'columns': ['net', 'gross', 'safety', 'capacity', 'liquidity', 'conversion',
                'updated', 'verdict'],
    'pins': [], 'presets': [], 'freeze_sort': False, 'sound': False, 'desktop': False,
    'last_filter': {}, 'wizard_done': False, 'welcome_seen': False,
    'bitunix_batch_note': True,
    # Signature of the "setup is incomplete" banner the user closed, so a dismissed
    # notice stays closed until the list of missing items actually changes.
    'setup_banner_dismissed': '', 'fees_auto_at': 0,
}


def ui_payload():
    saved = store.ui_state()
    return {**UI_DEFAULTS, **saved}


def public_row(row):
    keys = ('key', 'kind', 'coin', 'quote', 'route', 'route_label', 'venue_pair',
            'buy_venue', 'sell_venue', 'iran', 'trading_mode', 'capital', 'capital_unit',
            'status', 'flags', 'net_pct', 'net_quote', 'net_toman', 'net_usdt', 'gross_pct',
            'reference_pct', 'local_rate', 'effective_rate', 'conversion',
            'max_profitable_capital', 'profit_maximizing_capital', 'breakeven_capital',
            'limited_by_visible_depth', 'safety_status', 'verdict', 'updated_at', 'age',
            'network', 'networks', 'error', 'transfer_time', 'fee_sources', 'source',
            'destination', 'row_key', 'gross_spread', 'rate', 'liquidity', 'timestamp')
    out = {key: row.get(key) for key in keys}
    taker = row.get('taker') or {}
    maker = row.get('maker') or {}
    out['taker_pct'] = taker.get('profit_pct') if taker.get('ok') else None
    out['maker_pct'] = maker.get('profit_pct') if maker.get('ok') else None
    out['taker_profit'] = taker.get('profit') if taker.get('ok') else None
    out['maker_profit'] = maker.get('profit') if maker.get('ok') else None
    out['envelope'] = taker.get('ok') and taker.get('max_profitable_capital') is not None
    return out


def mask_proxy(url):
    if not url:
        return None
    try:
        from urllib.parse import urlsplit, urlunsplit
        parts = urlsplit(url)
        host = parts.hostname or ''
        if parts.port:
            host += ':' + str(parts.port)
        if parts.username:
            host = '***@' + host
        return urlunsplit((parts.scheme, host, parts.path, '', ''))
    except ValueError:
        return '***'


@app.get('/api/overview')
def api_overview():
    cfg = hub.config()
    rows = hub.rows(settings, cfg)
    summary = hub.summary(rows, cfg)
    safe_settings = settings.model_dump(exclude={'proxy_url'})
    safe_settings['has_proxy'] = bool(settings.proxy_url)
    return {'rows': [public_row(row) for row in rows], 'summary': summary,
            'excluded': hub.excluded, 'scanner': cfg, 'ui': ui_payload(),
            'settings': safe_settings, 'errors': hub.last_error, 'now': time.time(),
            'exchange_labels': EXCHANGE_LABELS, 'route_labels': list(EXCHANGE_LABELS.values()),
            'budgets': {name: item.stats() for name, item in budgets().items()}}


@app.post('/api/overview/refresh')
async def api_overview_refresh():
    hub.invalidate()
    try:
        async with gateway.make_client() as client:
            await hub.scan(client)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, describe('network')['message'])
    return {'ok': True}


class PauseRequest(BaseModel):
    paused: bool = Field(strict=True)


@app.post('/api/overview/pause')
def api_overview_pause(value: PauseRequest):
    cfg = hub.config()
    cfg['paused'] = value.paused
    store.save_scanner_settings(cfg)
    hub.paused = value.paused
    hub.invalidate()
    return {'paused': value.paused}


class VisibleRequest(BaseModel):
    keys: list[str] = Field(default_factory=list, max_length=200)


@app.post('/api/overview/visible')
def api_overview_visible(value: VisibleRequest):
    hub.visible = [key[:120] for key in value.keys][:120]
    return {'visible': len(hub.visible)}


@app.get('/api/overview/detail')
async def api_overview_detail(key: str):
    cfg = hub.config()
    row = await hub.evaluate_now(key)
    if row is None and key.startswith('classic:'):
        classic = [hub.summarize_classic(item) for item in scanner.rows(settings)]
        row = next((item for item in classic if item['key'] == key), None)
        if row is not None:
            return {'row': row, 'plan': build_plan(row), 'books': {}, 'history': [],
                    'conversion': hub.conversion_rate(cfg), 'classic': True}
    if row is None:
        raise HTTPException(404, 'این ردیف پیدا نشد؛ بازارها را به‌روزرسانی کنید.')
    route = hub.route_by_key(key)
    books = {}
    if route is not None:
        for exchange, coin, quote in route.books():
            book = hub.books.get((exchange, coin, quote))
            if book is not None:
                books[f'{exchange}:{coin}/{quote}'] = public_depth(book)
    history = store.scan_history(row.get('coin'), row.get('quote'))
    network = cfg.get('networks', {}).get(row.get('coin'))
    return {'row': row, 'plan': build_plan(row, network=network), 'books': books,
            'history': history, 'conversion': hub.conversion_rate(cfg),
            'route_books': route.books() if route else [], 'classic': False}


@app.get('/api/plan')
async def api_plan(key: str, network: Optional[str] = None):
    row = await hub.evaluate_now(key, envelope=False)
    if row is None:
        raise HTTPException(404, 'این ردیف پیدا نشد؛ بازارها را به‌روزرسانی کنید.')
    return build_plan(row, network=network)


# --------------------------------------------------------------------- diagnostics
@app.get('/api/diagnostics')
def api_diagnostics():
    cfg = hub.config()
    statuses = {name: info['state'] for name, info in hub.exchange_status(cfg).items()}
    payload = diagnostics_build(monitor, settings.clock_skew_warning_seconds,
                                EXCHANGE_LABELS, statuses, paused=bool(cfg.get('paused')),
                                extra={
                                    'proxy': mask_proxy(settings.proxy_url),
                                    'user_agent': settings.user_agent,
                                    # Which agent each exchange actually sees; Nobitex
                                    # rejects anonymous library defaults.
                                    'agents': {name: gateway.agent_for(name)
                                               for name in ADAPTERS}
                                    if hasattr(gateway, 'agent_for') else {},
                                    'max_timestamp_age_seconds': settings.max_timestamp_age_seconds,
                                    'clock_skew_warning_seconds': settings.clock_skew_warning_seconds,
                                    'markets': {name: (len(hub.bitunix) if name == 'bitunix'
                                                       else len(hub.iran.get(name) or {}))
                                                for name in ADAPTERS},
                                    'routes': len(hub.routes),
                                    'last_scan': hub.last_scan,
                                    'scan_count': hub.scan_count,
                                    'stale_seconds': cfg.get('stale_seconds'),
                                    'depth_interval': cfg.get('depth_interval'),
                                    'interval': cfg.get('interval'),
                                    'hot_rows': len(hub.hot),
                                })
    return payload


def _step(name, result):
    described = describe(result.reason, result.detail) if result else describe('unknown')
    return {'step': name, 'ok': bool(result and result.ok), 'reason': result.reason if result else 'unknown',
            'endpoint': result.endpoint if result else '', 'url': result.url if result else '',
            'status': result.status if result else None,
            'elapsed_ms': round(result.elapsed_ms, 1) if result else None,
            'preview': result.preview if result else '',
            'message': described['message'], 'action': described['action'],
            'detail': described['detail']}


async def test_exchange(name):
    adapter = ADAPTERS[name]
    cfg = hub.config()
    stale_seconds = int(cfg.get('stale_seconds', 120))
    steps = []
    async with gateway.make_client() as client:
        markets_result = await hub._fetch(client, name, adapter.market_endpoints(),
                                          adapter.parse_markets, adapter.ticker_budget)
        steps.append(_step('فهرست بازارها', markets_result))
        markets = markets_result.data if markets_result and markets_result.ok else {}
        if markets:
            sample = next(iter(sorted(markets.values(), key=lambda market: market.coin)))
            if adapter.supports_bulk_tickers:
                ticker_result = await hub._fetch(
                    client, name, adapter.bulk_ticker_endpoints(),
                    lambda data: adapter.parse_bulk_tickers(data, markets), adapter.ticker_budget)
            else:
                ticker_result = await hub._fetch(
                    client, name, adapter.ticker_endpoints(sample),
                    lambda data: adapter.parse_ticker(data, sample), adapter.ticker_budget)
            steps.append(_step(f'قیمت لحظه‌ای {sample.coin}', ticker_result))
            skew = hub._clock_skew(name)
            depth_result = await hub._fetch(
                client, name, adapter.depth_endpoints(sample),
                lambda data: adapter.parse_depth(data, sample, time.time(), stale_seconds, skew),
                adapter.depth_budget)
            steps.append(_step(f'دفتر سفارش {sample.coin}', depth_result))
    clock = monitor.clock_state.get(name, {})
    from .diagnostics import clock_check
    return {'exchange': name, 'label': EXCHANGE_LABELS.get(name, name),
            'ok': all(step['ok'] for step in steps),
            'steps': steps, 'clock': clock_check(clock.get('skew_seconds'),
                                                 settings.clock_skew_warning_seconds),
            'markets': len(markets)}


@app.post('/api/diagnostics/test')
async def api_diagnostics_test(exchange: Literal['wallex', 'nobitex', 'bitunix', 'all'] = 'all'):
    names = list(ADAPTERS) if exchange == 'all' else [exchange]
    results = [await test_exchange(name) for name in names]
    return {'results': results, 'ok': all(item['ok'] for item in results)}


class ConnectionSettings(BaseModel):
    proxy_url: Optional[str] = None
    user_agent: Optional[str] = None
    max_timestamp_age_seconds: Optional[int] = Field(default=None, ge=10, le=3600)
    clock_skew_warning_seconds: Optional[int] = Field(default=None, ge=10, le=3600)


@app.put('/api/connection')
def api_connection(value: ConnectionSettings):
    global settings
    update = settings.model_dump()
    for key, item in value.model_dump(exclude_none=True).items():
        update[key] = item
    try:
        candidate = Settings(**update)
    except pydantic.ValidationError as exc:
        raise HTTPException(422, 'تنظیمات اتصال نامعتبر است: ' + str(exc.errors()[0].get('msg')))
    settings = candidate
    store.save_settings(settings.model_dump())
    gateway.configure(user_agent=settings.user_agent, proxy=settings.proxy_url,
                      exchange_agents={'nobitex': settings.nobitex_user_agent})
    hub.invalidate()
    return {'proxy_url': mask_proxy(settings.proxy_url), 'user_agent': settings.user_agent,
            'max_timestamp_age_seconds': settings.max_timestamp_age_seconds,
            'clock_skew_warning_seconds': settings.clock_skew_warning_seconds}


# ------------------------------------------------------------------------- amounts
@app.get('/api/amount')
def api_amount(text: str):
    try:
        return {'ok': True, **parse_amount(text)}
    except AmountError as exc:
        return {'ok': False, 'error': str(exc)}


# ------------------------------------------------------------------------ ui state
class UiUpdate(BaseModel):
    values: dict[str, Any]


@app.get('/api/ui')
def api_ui():
    return ui_payload()


@app.put('/api/ui')
def api_ui_put(value: UiUpdate):
    allowed = set(UI_DEFAULTS)
    clean = {key: item for key, item in value.values.items() if key in allowed}
    if 'pins' in clean and not isinstance(clean['pins'], list):
        raise HTTPException(400, 'فهرست ارزهای پین‌شده نامعتبر است')
    if 'presets' in clean and not isinstance(clean['presets'], list):
        raise HTTPException(400, 'فیلترهای ذخیره‌شده نامعتبر است')
    if 'setup_banner_dismissed' in clean:
        value = clean['setup_banner_dismissed']
        if not isinstance(value, str):
            raise HTTPException(400, 'وضعیت بستن پیام راه‌اندازی نامعتبر است')
        clean['setup_banner_dismissed'] = value[:500]
    store.save_ui_state(clean)
    hub.invalidate()
    return ui_payload()


# -------------------------------------------------------------------------- backup
@app.get('/api/backup')
def api_backup():
    payload = {
        'app': 'usdt-arbitrage-monitor', 'version': 2, 'exported_at': time.time(),
        'settings': settings.model_dump(), 'scanner': hub.config(),
        'fees': store.fees(), 'ui': store.ui_state(),
    }
    return Response(__import__('json').dumps(payload, ensure_ascii=False, indent=2),
                    media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename=usdt-monitor-backup.json'})


@app.post('/api/backup/restore')
def api_backup_restore(value: dict):
    global settings
    if not isinstance(value, dict) or value.get('app') != 'usdt-arbitrage-monitor':
        raise HTTPException(400, 'این فایل پشتیبان این برنامه نیست.')
    try:
        candidate = Settings.model_validate(value.get('settings') or {})
        scan_candidate = ScannerSettings.model_validate(value.get('scanner') or {})
        fees = [NetworkFee.model_validate(row) for row in (value.get('fees') or [])]
        ui = value.get('ui') or {}
        if not isinstance(ui, dict):
            raise ValueError('ui')
    except (pydantic.ValidationError, ValueError, TypeError) as exc:
        raise HTTPException(422, 'فایل پشتیبان معتبر نیست؛ هیچ تنظیمی تغییر نکرد.')
    rows, seen = [], set()
    for fee in fees:
        row = fee.model_dump()
        try:
            row['coin'] = normalize(row['coin'])
            row['network'] = row['network'].upper()
        except (ValueError, AttributeError):
            raise HTTPException(422, 'فایل پشتیبان کارمزد نامعتبر دارد؛ تغییری اعمال نشد.')
        if (row['exchange'], row['coin'], row['network']) in seen:
            raise HTTPException(422, 'فایل پشتیبان ردیف کارمزد تکراری دارد؛ تغییری اعمال نشد.')
        seen.add((row['exchange'], row['coin'], row['network']))
        rows.append(row)
    settings = candidate
    store.save_settings(settings.model_dump())
    store.save_scanner_settings(scan_candidate.model_dump())
    store.replace_fees(rows)
    store.save_ui_state({key: item for key, item in ui.items() if key in UI_DEFAULTS})
    gateway.configure(user_agent=settings.user_agent, proxy=settings.proxy_url)
    hub.invalidate()
    return {'ok': True, 'fees': len(rows)}


# --------------------------------------------------------------------- simulations
class SimulationRequest(BaseModel):
    key: str = Field(min_length=3, max_length=200)
    delay_seconds: Optional[int] = Field(default=None, ge=10, le=86400)


@app.post('/api/simulations')
async def api_simulation_create(value: SimulationRequest):
    route = hub.route_by_key(value.key)
    if route is None:
        raise HTTPException(404, 'فقط برای مسیرهای بیت‌یونیکس می‌توان معامله آزمایشی ثبت کرد.')
    cfg = hub.config()
    row = await hub.evaluate_now(value.key, envelope=False)
    if row is None or not (row.get('taker') or {}).get('ok'):
        raise HTTPException(400, 'برای این ردیف محاسبه کامل ممکن نیست؛ معامله آزمایشی ثبت نشد.')
    prices = snapshot_prices({f'{exchange}:{coin}/{quote}': hub.books.get((exchange, coin, quote))
                              for exchange, coin, quote in route.books()})
    minutes = transfer_time(cfg, row.get('network_coin') or row.get('network'))['minutes']
    try:
        simulation_id = create_simulation_record(store, row, prices, transfer_minutes=minutes,
                                                 delay_seconds=value.delay_seconds)
    except SimulationError as exc:
        raise HTTPException(400, str(exc))
    return public_simulation(store.simulation(simulation_id))


@app.get('/api/simulations')
def api_simulations():
    rows = [public_simulation(row) for row in store.simulations()]
    return {'rows': rows, 'summary': simulation_summary(rows)}


@app.post('/api/simulations/{simulation_id}/settle')
async def api_simulation_settle(simulation_id: int):
    record = store.simulation(simulation_id)
    if record is None:
        raise HTTPException(404, 'معامله آزمایشی پیدا نشد.')
    if record.get('status') == 'done':
        return public_simulation(record)
    settled = await settle_one(simulation_id)
    if settled is None:
        raise HTTPException(400, 'این معامله آزمایشی در وضعیت انتظار نیست.')
    return public_simulation(settled)


@app.delete('/api/simulations/{simulation_id}')
def api_simulation_delete(simulation_id: int):
    store.delete_simulation(simulation_id)
    return {'ok': True}


# ------------------------------------------------------------------------ journal
class JournalEntry(BaseModel):
    date: str = Field(min_length=8, max_length=10)
    coin: str = Field(min_length=2, max_length=20)
    route: str = 'other'
    mode: str = 'transfer'
    capital: Optional[float] = None
    final_amount: Optional[float] = None
    profit: Optional[float] = None
    fees: Optional[str] = Field(default=None, max_length=200)
    note: Optional[str] = Field(default=None, max_length=500)


@app.get('/api/journal')
def api_journal():
    return {'rows': store.journal()}


@app.post('/api/journal')
def api_journal_add(value: JournalEntry):
    try:
        clean = validate_journal(value.model_dump())
    except JournalError as exc:
        raise HTTPException(400, str(exc))
    entry_id = store.add_journal(clean)
    return {'id': entry_id, 'rows': store.journal()}


@app.delete('/api/journal/{entry_id}')
def api_journal_delete(entry_id: int):
    store.delete_journal(entry_id)
    return {'ok': True}


@app.get('/api/journal.csv')
def api_journal_csv():
    return Response(journal_csv(store.journal()), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=trade-journal.csv'})


# ------------------------------------------------------- home, decision and receipt
STATUS_FA = {
    'ok': '',
    'stale': 'قیمت‌های این مسیر کهنه شده‌اند؛ تا به‌روزرسانی بعدی صبر کنید.',
    'depth needed': 'عمق دفتر سفارش این مسیر هنوز کامل دریافت نشده است.',
    'error': 'قیمت یکی از بازارهای این مسیر در دسترس نیست.',
}
TRADING_STAGES = {'buy_coin': 'کارمزد خرید', 'sell_coin': 'کارمزد فروش',
                  'convert': 'کارمزد تبدیل'}
WITHDRAW_STAGES = {'withdraw_coin': 'کارمزد برداشت ارز', 'withdraw_usdt': 'کارمزد برداشت تتر'}


def exchange_label(name):
    return EXCHANGE_LABELS.get(name, name or '—')


def margin_for(row, cfg):
    margins = cfg.get('coin_margins') or {}
    coin = row.get('coin')
    if coin in margins and margins[coin] is not None:
        return float(margins[coin])
    return float(cfg.get('safety_margin', .3) or 0)


def lifetime_minutes(row):
    """Typical (median) lifetime of recorded profitable moments for this coin, in minutes."""
    try:
        history = tracker.rows(row.get('coin'), row.get('trading_mode') or 'transfer')
    except Exception:                      # noqa: BLE001 - history is a nice-to-have
        return None
    durations = sorted(float(item['duration']) for item in history
                       if item.get('duration') and not item.get('unknown_gaps'))
    if len(durations) < 3:
        return None
    return durations[len(durations) // 2] / 60.0


def reference_rate(cfg):
    """One number for the USDT/toman rate (mid of bid and ask), or None."""
    rate = hub.conversion_rate(cfg) or {}
    values = [float(value) for value in (rate.get('bid'), rate.get('ask')) if value]
    return (sum(values) / len(values)) if values else None


def route_stages(row):
    """The stages this route actually performs, independent of whether it can be priced.

    Used for the fee checklist: a required fee is still required when a *different* fee is
    missing and the engine refuses to build the chain.
    """
    kind = row.get('route')
    transfer = (row.get('trading_mode') or 'transfer') != 'prefunded'
    if kind == 'A':
        stages = ['buy_coin'] + (['withdraw_coin'] if transfer else []) + ['sell_coin', 'convert']
        return stages + (['withdraw_usdt'] if transfer else [])
    if kind == 'B':
        stages = (['withdraw_usdt'] if transfer else []) + ['convert', 'buy_coin']
        return stages + (['withdraw_coin'] if transfer else []) + ['sell_coin']
    stages = ['buy_coin'] + (['withdraw_coin'] if transfer else []) + ['sell_coin']
    return stages


def stage_exchange(row, stage):
    venue = venue_for(row.get('route'), stage)
    return row.get('iran') if venue == 'iran' else (venue or row.get('iran'))


def trading_quote(row, exchange):
    return 'toman' if row.get('quote') == 'toman' else 'USDT'


def fee_entry(fee_row, name, kind):
    """One fee a route needs, with the confidence metadata the UI shows."""
    if fee_row is None:
        return {'name': name, 'kind': kind, 'confidence': 'unknown', 'label': 'نامعلوم',
                'status': 'نامعلوم', 'source': '', 'fetched_at': None, 'age_days': None,
                'stale': False, 'needs_review': True, 'note': '', 'known': False}
    return {'name': name, 'kind': kind, 'known': True, **fee_row.get('meta', {})}


def find_fee(fees_rows, exchange, coin, network=None):
    if not exchange or not coin:
        return None
    coin = str(coin).upper()
    network = (network or '').upper()
    fallback = None
    for row in fees_rows or []:
        if row.get('exchange') != exchange or str(row.get('coin', '')).upper() != coin:
            continue
        if network and str(row.get('network', '')).upper() == network:
            return row
        if not network:
            fallback = fallback or row
    return fallback


def route_fee_entries(row, fees_rows=None, now=None):
    """Every fee the net number of this row actually uses, with its confidence."""
    fees_rows = fees_rows if fees_rows is not None else []
    now = time.time() if now is None else now
    priced = [step.get('name') for step in
              (((row.get('detail') or {}).get('taker') or {}).get('steps') or [])]
    entries = []
    for stage in (priced or route_stages(row)):
        if stage in TRADING_STAGES:
            exchange = stage_exchange(row, stage)
            quote = trading_quote(row, exchange)
            entries.append({**fee_confidence.trading_fee_tag(
                settings, exchange, quote,
                TRADING_STAGES[stage] + ' ' + exchange_label(exchange),
                now=now, stale_days=settings.fee_stale_days), 'stage': stage, 'kind': 'trading'})
        elif stage in WITHDRAW_STAGES:
            exchange = stage_exchange(row, stage)
            usdt = stage == 'withdraw_usdt'
            coin = 'USDT' if usdt else row.get('coin')
            network = row.get('network_usdt') if usdt else (
                row.get('network_coin') or (row.get('networks') or [None])[0])
            name = WITHDRAW_STAGES[stage] + ' ' + exchange_label(exchange)
            entries.append({**fee_entry(find_fee(fees_rows, exchange, coin, network), name,
                                        'withdrawal'),
                            'stage': stage, 'kind': 'withdrawal'})
    return entries


def other_costs_pct(cfg, row):
    other = float(cfg.get('other_costs_toman') or 0)
    effective = row.get('effective_rate')
    rate = effective if isinstance(effective, (int, float)) else None
    rate = rate or reference_rate(cfg)
    capital = float(row.get('capital') or 0)
    if not other or not rate or capital <= 0:
        return 0.0, 0.0
    return other, other / (capital * float(rate)) * 100.0


def decision_context(row, fees_rows, cfg, now=None):
    taker = (row.get('detail') or {}).get('taker') or {}
    entries = route_fee_entries(row, fees_rows, now)
    other_toman, other_pct = other_costs_pct(cfg, row)
    return {
        'status': row.get('status'),
        'status_text': STATUS_FA.get(row.get('status'), ''),
        'net_pct': row.get('net_pct'),
        'gross_pct': row.get('gross_pct'),
        'margin': margin_for(row, cfg),
        'depth_ok': bool((row.get('flags') or {}).get('depth')),
        'capital_ok': None,
        'fees': entries,
        'transfer_minutes': (row.get('transfer_time') or {}).get('minutes'),
        'lifetime_minutes': lifetime_minutes(row),
        'data_age': row.get('age'),
        'stale_seconds': float(cfg.get('stale_seconds', 120)),
        'other_costs_pct': other_pct,
        'error': taker.get('error') or row.get('error'),
    }


def annotated_fees(now=None):
    return fee_confidence.annotate(store.fees() or [], now or time.time(),
                                   settings.fee_stale_days)


def stage_prices_for(key):
    route = hub.route_by_key(key)
    if route is None:
        return {}
    try:
        return hub.stage_prices(route)
    except (ValueError, KeyError, TypeError):
        return {}


def build_receipt(row, fees_rows, cfg, now=None):
    other = float(cfg.get('other_costs_toman') or 0)
    return receipt_builder.build(
        row, prices=stage_prices_for(row.get('key')),
        fee_tags={entry['stage']: entry for entry in route_fee_entries(row, fees_rows, now)},
        other_costs_toman=other, stale_days=settings.fee_stale_days,
        conversion_rate=row.get('effective_rate'), now=now)


def candidate_rows(rows, setup_state):
    """Rows the user can actually act on, best net first."""
    filtered = setup_model.filter_rows(rows, setup_state)
    usable = [row for row in filtered['rows']
              if not str(row.get('key') or '').startswith('classic:')]
    def key(row):
        value = row.get('net_pct')
        if value is None:
            value = (row.get('gross_pct') if row.get('gross_pct') is not None else -1e9) - 1e6
        return float(value)
    usable.sort(key=key, reverse=True)
    return usable, filtered['excluded']


def fee_needs(rows, fees_rows, cfg, now=None):
    """Which fees the best few routes still need — the lazy fee loading list."""
    limit = int(cfg.get('fee_candidate_limit', 10) or 10)
    top = sorted([row for row in rows if row.get('gross_pct') is not None],
                 key=lambda row: float(row['gross_pct']), reverse=True)[:limit]
    coins, missing, stale, estimated, routes = [], [], [], [], []
    for row in top:
        for entry in route_fee_entries(row, fees_rows, now):
            coin = row.get('coin')
            if entry['confidence'] == 'unknown':
                if coin not in missing:
                    missing.append(coin)
                if row.get('key') not in routes:
                    routes.append(row.get('key'))
            elif entry.get('stale'):
                if coin not in stale:
                    stale.append(coin)
            elif entry['confidence'] == 'estimated':
                if coin not in estimated:
                    estimated.append(coin)
        if row.get('coin') not in coins:
            coins.append(row.get('coin'))
    result = {'coins': coins[:limit], 'count': len(coins[:limit]),
              'missing_coins': missing, 'stale_coins': stale,
              'estimated_coins': estimated, 'routes': routes[:limit],
              'limit': limit}
    if missing:
        result['text'] = ('برای این ' + str(len(missing)) + ' ارز کارمزد برداشت لازم است.')
        result['action'] = 'کارمزدها را وارد کنید'
    elif stale:
        result['text'] = ('کارمزد ' + str(len(stale)) + ' ارز قدیمی شده؛ یک بار بررسی کنید.')
        result['action'] = 'بررسی دوباره کارمزدها'
    elif estimated:
        result['text'] = ('کارمزد ' + str(len(estimated)) + ' ارز تخمینی است؛ برای عدد قطعی تأییدش کنید.')
        result['action'] = 'تأیید کارمزدها'
    else:
        result['text'] = ''
        result['action'] = ''
    return result


def _net_after(card):
    numbers = card.get('numbers') or {}
    value = numbers.get('net_after_other')
    if value is None:
        value = numbers.get('net_pct')
    return float(value) if value is not None else -1e9


def home_card(row, fees_rows, cfg, now):
    context = decision_context(row, fees_rows, cfg, now)
    result = decision_engine.decide(context)
    confidence = fee_confidence.route_confidence(context['fees'])
    receipt = build_receipt(row, fees_rows, cfg, now)
    totals = receipt.get('totals') or {}
    numbers = {'net_pct': totals.get('profit_pct'),
               'net_after_other': totals.get('pct_after_other'),
               'profit_usdt': totals.get('profit'),
               'profit_toman': totals.get('profit_toman'),
               'final_usdt': totals.get('final'),
               'gross_pct': totals.get('gross_pct'),
               'costs_pct': totals.get('costs_pct'),
               'transfer_minutes': totals.get('transfer_minutes'),
               'minimum_capital': totals.get('minimum_capital'),
               'breakeven_capital': totals.get('breakeven_capital')}
    # A route that cannot be priced yet still shows its raw spread so the user can see why
    # the fee question matters; the net number stays empty.
    if numbers['gross_pct'] is None:
        numbers['gross_pct'] = row.get('gross_pct')
    if numbers['net_pct'] is None:
        numbers['net_pct'] = row.get('net_pct')
    if numbers['net_after_other'] is None and row.get('net_pct') is not None:
        numbers['net_after_other'] = row.get('net_pct') - context['other_costs_pct']
    if numbers['transfer_minutes'] is None:
        numbers['transfer_minutes'] = (row.get('transfer_time') or {}).get('minutes')
    return {'key': row.get('key'), 'coin': row.get('coin'), 'quote': row.get('quote'),
            'route': row.get('route'), 'route_label': row.get('route_label'),
            'venue_pair': row.get('venue_pair'),
            'venues': [exchange_label(name) for name in (row.get('venue_pair') or [])],
            'title': f"{row.get('coin')} — "
                     f"{exchange_label((row.get('venue_pair') or [None])[0])} ← "
                     f"{exchange_label((row.get('venue_pair') or [None, None])[1])}",
            'row': public_row(row), 'decision': result,
            'summary_text': decision_engine.summary_text(result, row.get('coin'),
                                                         row.get('venue_pair')),
            'confidence': confidence,
            'receipt': receipt,
            'numbers': numbers}


def gauge_payload(cfg, current=None):
    days = int(cfg.get('gauge_days', 7) or 7)
    rows = store.best_history(days * 86400)
    data = gauge.from_history(rows, current=current, window_hours=days * 24)
    data['days'] = days
    return data


def empty_state(cfg, rows):
    """A friendly, honest answer for the days nothing is profitable."""
    days = int(cfg.get('gauge_days', 7) or 7)
    cutoff = time.time() - days * 86400
    margin = float(cfg.get('safety_margin', .3) or 0)
    last = None
    for sample in reversed(store.best_history(days * 86400)):
        if sample.get('net_pct') is not None and float(sample['net_pct']) > margin:
            last = sample['timestamp']
            break
    nets = [float(row['net_pct']) for row in rows if row.get('net_pct') is not None]
    return {'message': 'فعلاً فرصت سودده‌ای نیست. همان‌طور که بازار حرکت کند، بهترین '
                       'فرصت‌ها همین‌جا نشان داده می‌شوند.',
            'last_profitable_at': last,
            'window_days': days, 'since': cutoff,
            'best_now': max(nets) if nets else None,
            'notify': bool((cfg.get('setup') or {}).get('notify'))}


@app.get('/api/home')
def api_home():
    now = time.time()
    cfg = hub.config()
    fees_rows = annotated_fees(now)
    setup_state = setup_model.normalize(cfg.get('setup') or {})
    rows = hub.rows(settings, cfg)
    candidates, excluded = candidate_rows(rows, setup_state)
    cards = [home_card(row, fees_rows, cfg, now) for row in candidates[:6]]
    # Only a route whose spread could actually be read can be the headline; when nothing is
    # priced (books missing, market closed) the page shows the friendly empty state instead.
    priced = [card for card in cards
              if card['numbers'].get('gross_pct') is not None
              or card['numbers'].get('net_pct') is not None]
    best = priced[0] if priced else None
    positive = [card for card in cards if _net_after(card) > 0]
    state = ui_payload()
    rate = hub.conversion_rate(cfg)
    mid = reference_rate(cfg)
    capital_usdt = float(cfg.get('capital_usdt') or 0)
    return {
        'now': now,
        'paused': bool(cfg.get('paused')),
        'interval': cfg.get('interval'),
        'age': None if not hub.last_scan else round(now - hub.last_scan, 1),
        'next_refresh': hub.summary(rows, cfg).get('next_refresh'),
        'error': hub.last_error,
        'setup': setup_model.summary(setup_state),
        'wizard_done': bool(state.get('wizard_done')),
        'capital': {'usdt': capital_usdt,
                    'toman': capital_usdt * mid if mid else None,
                    'rate': mid, 'rate_source': rate},
        'best': best,
        'count': len(cards),
        'positive_count': len(positive),
        'others': [{'key': card['key'], 'coin': card['coin'],
                    'route_label': card['route_label'], 'venues': card['venues'],
                    'verdict': card['decision']['verdict'],
                    'label': card['decision']['label'],
                    'icon': card['decision']['icon'],
                    'tone': card['decision']['tone'],
                    'net_pct': card['numbers'].get('net_pct'),
                    'net_after_other': card['numbers'].get('net_after_other')}
                   for card in cards[1:6]],
        'empty': None if best and _net_after(best) > 0 else empty_state(cfg, rows),
        'fees': fee_needs(candidates, fees_rows, cfg, now),
        'gauge': gauge_payload(cfg, current=(best or {}).get('numbers', {}).get(
            'net_after_other')),
        'excluded': excluded[:20],
        'rows_count': len(candidates),
        'banner': banner_payload(state, candidates, fees_rows, cfg, now),
        'disclaimer': receipt_builder.DISCLAIMER,
        'fee_pages': settings.fee_pages,
    }


@app.get('/api/decide')
def api_decide(key: str):
    now = time.time()
    cfg = hub.config()
    row = next((item for item in hub.rows(settings, cfg) if item.get('key') == key), None)
    if row is None:
        raise HTTPException(404, 'این مسیر پیدا نشد؛ بازارها را به‌روزرسانی کنید.')
    fees_rows = annotated_fees(now)
    result = decision_engine.decide(decision_context(row, fees_rows, cfg, now))
    return {'key': key, 'decision': result,
            'summary_text': decision_engine.summary_text(result, row.get('coin'),
                                                         row.get('venue_pair')),
            'confidence': fee_confidence.route_confidence(
                route_fee_entries(row, fees_rows, now))}


@app.get('/api/receipt')
def api_receipt(key: str):
    now = time.time()
    cfg = hub.config()
    row = next((item for item in hub.rows(settings, cfg) if item.get('key') == key), None)
    if row is None:
        raise HTTPException(404, 'این مسیر پیدا نشد؛ بازارها را به‌روزرسانی کنید.')
    fees_rows = annotated_fees(now)
    receipt = build_receipt(row, fees_rows, cfg, now)
    return {'key': key, 'receipt': receipt, 'text': receipt_builder.to_text(receipt),
            'plan': build_plan(row, network=row.get('network_coin')),
            'decision': decision_engine.decide(decision_context(row, fees_rows, cfg, now)),
            'fees': route_fee_entries(row, fees_rows, now)}


@app.get('/api/receipt.csv')
def api_receipt_csv(key: str):
    now = time.time()
    cfg = hub.config()
    row = next((item for item in hub.rows(settings, cfg) if item.get('key') == key), None)
    if row is None:
        raise HTTPException(404, 'این مسیر پیدا نشد؛ بازارها را به‌روزرسانی کنید.')
    receipt = build_receipt(row, annotated_fees(now), cfg, now)
    return Response(receipt_builder.to_csv(receipt.get('steps')),
                    media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=receipt.csv'})


@app.get('/api/gauge')
def api_gauge():
    cfg = hub.config()
    return gauge_payload(cfg)


# ------------------------------------------------------------------- setup / wizard
def banner_payload(state, candidates, fees_rows, cfg, now):
    """What is still needed — a small, dismissible list, never a modal."""
    items = []
    setup_state = setup_model.normalize(cfg.get('setup') or {})
    if not setup_state.get('exchanges'):
        items.append({'id': 'exchanges', 'text': 'صرافی‌هایی که در آن‌ها حساب دارید را انتخاب کنید.',
                      'page': 'setup'})
    needs = fee_needs(candidates, fees_rows, cfg, now)
    if needs.get('missing_coins'):
        items.append({'id': 'fees', 'text': needs['text'], 'page': 'fees',
                      'coins': needs['missing_coins']})
    if not cfg.get('capital_usdt'):
        items.append({'id': 'capital', 'text': 'سرمایه‌ای که می‌خواهید جابه‌جا کنید را وارد کنید.',
                      'page': 'setup'})
    if not state.get('wizard_done'):
        items.append({'id': 'wizard', 'text': 'راه‌اندازی سه‌مرحله‌ای را کامل کنید.',
                      'page': 'setup'})
    signature = '|'.join(item['id'] for item in items)
    return {'items': items, 'signature': signature,
            'dismissed': str(state.get('setup_banner_dismissed') or '') == signature,
            'visible': bool(items) and str(state.get('setup_banner_dismissed') or '') != signature}


class SetupRequest(BaseModel):
    exchanges: list[Literal['wallex', 'nobitex', 'bitunix']] = Field(default_factory=list,
                                                                     max_length=3)
    money: Literal['toman_iran', 'usdt', 'coins_both'] = 'toman_iran'
    capital: Optional[float] = Field(default=None, gt=0, le=1e12, allow_inf_nan=False)
    capital_unit: Literal['toman', 'USDT'] = 'toman'
    notify: bool = False
    interval: Optional[int] = Field(default=None, ge=5, le=3600)
    accept_default_fees: bool = True
    complete: bool = False


@app.get('/api/setup')
def api_setup():
    cfg = hub.config()
    setup_state = setup_model.normalize(cfg.get('setup') or {})
    state = ui_payload()
    fees_rows = annotated_fees()
    rows = hub.rows(settings, cfg)
    candidates, _ = candidate_rows(rows, setup_state)
    return {'setup': setup_model.summary(setup_state), 'wizard_done': bool(state.get('wizard_done')),
            'exchanges': [{'value': name, 'label': exchange_label(name)}
                          for name in setup_model.EXCHANGES],
            'money_options': [{'value': key, 'label': value}
                              for key, value in setup_model.MONEY.items()],
            'fees': fee_needs(candidates, fees_rows, cfg),
            'capital': {'usdt': cfg.get('capital_usdt'), 'toman': cfg.get('capital_toman'),
                        'interval': cfg.get('interval')},
            'fee_pages': settings.fee_pages}


@app.put('/api/setup')
def save_setup(value: SetupRequest):
    cfg = hub.config()
    exchanges = [name for name in value.exchanges if name in setup_model.EXCHANGES] or \
        list(setup_model.DEFAULT['exchanges'])
    rate = reference_rate(cfg) or 0
    capital_usdt = float(cfg.get('capital_usdt') or 100)
    capital_toman = float(cfg.get('capital_toman') or 10_000_000)
    if value.capital is not None:
        if value.capital_unit == 'toman':
            capital_toman = float(value.capital)
            if rate:
                capital_usdt = capital_toman / float(rate)
        else:
            capital_usdt = float(value.capital)
            if rate:
                capital_toman = capital_usdt * float(rate)
    setup_state = setup_model.normalize({'exchanges': exchanges, 'money': value.money,
                                         'capital_toman': capital_toman,
                                         'capital_usdt': capital_usdt,
                                         'notify': value.notify})
    cfg['setup'] = setup_state
    cfg['capital_usdt'] = round(capital_usdt, 6)
    cfg['capital_toman'] = round(capital_toman, 2)
    cfg['trading_mode'] = setup_model.trading_mode(setup_state)
    if value.interval:
        cfg['interval'] = int(value.interval)
    store.save_scanner_settings(cfg)
    state = {'wizard_done': bool(value.complete) or bool(ui_payload().get('wizard_done'))}
    store.save_ui_state(state)
    hub.invalidate()
    return {'setup': setup_model.summary(setup_state), 'fees': fee_needs(
        candidate_rows(hub.rows(settings, cfg), setup_state)[0], annotated_fees(), cfg),
        'wizard_done': bool(state['wizard_done'])}


# ------------------------------------------------------------------------- fees
class FeesParseRequest(BaseModel):
    text: str = Field(max_length=200000)
    exchange: Literal['wallex', 'nobitex', 'bitunix'] = 'nobitex'
    kind: Literal['auto', 'csv', 'page'] = 'auto'


class FeeRowIn(BaseModel):
    exchange: Literal['wallex', 'nobitex', 'bitunix']
    coin: str = Field(min_length=1, max_length=20)
    network: str = Field(min_length=1, max_length=40)
    withdrawal: Optional[float] = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)
    minimum: Optional[float] = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)
    supported: bool = True
    note: str = Field(default='', max_length=200)


class FeesSaveRequest(BaseModel):
    rows: list[FeeRowIn] = Field(default_factory=list, max_length=500)
    fetch_now: bool = False


def normalise_fee_row(value):
    try:
        coin = normalize(value.coin)
    except ValueError:
        raise HTTPException(400, 'نماد ارز «' + value.coin + '» شناخته نشد.')
    network = re.sub(r'[^A-Za-z0-9_-]', '', value.network).upper()
    if not network:
        raise HTTPException(400, 'نام شبکه خالی است.')
    return {'exchange': value.exchange, 'coin': coin, 'network': network,
            'withdrawal': value.withdrawal, 'minimum': value.minimum,
            'supported': bool(value.supported),
            'confidence': 'manual' if value.withdrawal is not None else 'unknown',
            'source': 'assistant', 'fetched_at': time.time(),
            'note': value.note[:200]}


@app.get('/api/fees')
def api_fees():
    now = time.time()
    rows = annotated_fees(now)
    counts = {level: 0 for level in fee_confidence.CONFIDENCE}
    stale = 0
    for row in rows:
        counts[row['meta']['confidence']] = counts.get(row['meta']['confidence'], 0) + 1
        stale += 1 if row['meta']['stale'] else 0
    cfg = hub.config()
    setup_state = setup_model.normalize(cfg.get('setup') or {})
    candidates, _ = candidate_rows(hub.rows(settings, cfg), setup_state)
    trading = []
    for exchange, quote, market in (('wallex', 'toman', 'تومان'), ('nobitex', 'toman', 'تومان'),
                                    ('wallex', 'USDT', 'USDT'), ('nobitex', 'USDT', 'USDT'),
                                    ('bitunix', 'USDT', 'USDT')):
        tag = fee_confidence.trading_fee_tag(
            settings, exchange, quote,
            exchange_label(exchange) + ' / ' + market, now=now,
            stale_days=settings.fee_stale_days)
        values = tag.get('values') or {}
        trading.append({'exchange': exchange_label(exchange), 'market': market,
                        'maker': values.get('maker'), 'taker': values.get('taker'),
                        'confidence': tag['confidence'], 'label': tag['label'],
                        'source': tag['source']})
    return {'rows': rows, 'counts': counts, 'stale': stale,
            'stale_days': settings.fee_stale_days,
            'sources': fee_sources.SOURCES, 'pages': settings.fee_pages,
            'trading': trading,
            'needs': fee_needs(candidates, rows, cfg, now),
            'last_auto': ui_payload().get('fees_auto_at') or 0}


@app.post('/api/fees/parse')
def api_fees_parse(value: FeesParseRequest):
    result = fee_text.parse_any(value.text, value.exchange,
                               'csv' if value.kind == 'csv' else 'auto')
    for row in result['rows']:
        row['fetched_at'] = time.time()
        row['source'] = 'assistant'
    return result


@app.post('/api/fees/save')
def api_fees_save(value: FeesSaveRequest):
    if not value.rows:
        raise HTTPException(400, 'هیچ ردیفی برای ذخیره نبود.')
    rows = []
    seen = set()
    for item in value.rows:
        row = normalise_fee_row(item)
        key = (row['exchange'], row['coin'], row['network'])
        if key in seen:
            raise HTTPException(400, 'ردیف تکراری: ' + row['coin'] + ' ' + row['network'])
        seen.add(key)
        rows.append(row)
    store.upsert_fees(rows)
    hub.invalidate()
    return {'saved': len(rows), 'rows': annotated_fees()}


def merge_auto_fees(incoming):
    """Automatic rows never overwrite a newer hand-entered fee."""
    existing = {(row['exchange'], row['coin'], row['network']): row for row in store.fees()}
    keep, skipped = [], 0
    for row in incoming:
        key = (row['exchange'], row['coin'], row['network'])
        before = existing.get(key)
        if before is not None and fee_confidence.normalize(before.get('confidence')) == 'manual':
            old = before.get('fetched_at')
            new = row.get('fetched_at')
            if old is not None and (new is None or float(old) >= float(new)):
                skipped += 1
                continue
        keep.append(row)
    return keep, skipped


async def refresh_automatic_fees(force=False):
    """Once a day, ask each documented public endpoint for its fee list."""
    state = ui_payload()
    last = float(state.get('fees_auto_at') or 0)
    if not force and time.time() - last < 86400:
        return {'skipped': True, 'last': last}
    results = []
    saved = 0
    for exchange in ('nobitex', 'wallex', 'bitunix'):
        try:
            result = await fee_sources.fetch_fees(gateway, exchange, describe)
        except Exception as exc:                    # noqa: BLE001 - never break the scan
            result = {'exchange': exchange, 'ok': False, 'rows': [], 'attempted': True,
                      'reason': 'unknown', 'detail': str(exc)[:200],
                      'message': 'خواندن خودکار کارمزد ناموفق بود.'}
        summary = {key: result.get(key) for key in
                   ('exchange', 'ok', 'attempted', 'reason', 'message', 'status', 'url')}
        summary['count'] = len(result.get('rows') or [])
        if result.get('rows'):
            keep, skipped = merge_auto_fees(result['rows'])
            if keep:
                store.upsert_fees(keep)
                saved += len(keep)
            summary['skipped_manual'] = skipped
        results.append(summary)
    if any(item.get('ok') for item in results):
        store.save_ui_state({'fees_auto_at': time.time()})
        hub.invalidate()
    return {'skipped': False, 'results': results, 'saved': saved,
            'at': time.time()}


@app.post('/api/fees/refresh')
async def api_fees_refresh():
    return await refresh_automatic_fees(force=True)


@app.get('/api/fees/needed')
def api_fees_needed():
    now = time.time()
    cfg = hub.config()
    fees_rows = annotated_fees(now)
    setup_state = setup_model.normalize(cfg.get('setup') or {})
    candidates, _ = candidate_rows(hub.rows(settings, cfg), setup_state)
    return fee_needs(candidates, fees_rows, cfg, now)



# ------------------------------------------------------------------------ wizard
@app.get('/api/wizard')
def api_wizard():
    fees_rows = store.fees()
    missing = []
    labels = [('wallex', 'toman', 'کارمزد والکس در بازار تومان'),
              ('nobitex', 'toman', 'کارمزد نوبیتکس در بازار تومان'),
              ('wallex', 'USDT', 'کارمزد والکس در بازار USDT'),
              ('nobitex', 'USDT', 'کارمزد نوبیتکس در بازار USDT'),
              ('bitunix', 'USDT', 'کارمزد بیت‌یونیکس در بازار USDT')]
    for exchange, quote, label in labels:
        fees = settings.trading_fees(exchange, quote)
        if fees.get('taker') is None or fees.get('maker') is None:
            missing.append(label)
    if not any(row['exchange'] == 'bitunix' and row['withdrawal'] is not None for row in fees_rows):
        missing.append('کارمزد برداشت ارز در بیت‌یونیکس')
    if not any(row['exchange'] in ('wallex', 'nobitex') and row['withdrawal'] is not None
               for row in fees_rows):
        missing.append('کارمزد برداشت ارز در صرافی ایرانی')
    cfg = hub.config()
    if not cfg.get('capital_usdt'):
        missing.append('سرمایه USDT')
    state = ui_payload()
    return {'complete': not missing, 'missing': missing,
            'wizard_done': bool(state.get('wizard_done')), 'network_ready': not missing}
