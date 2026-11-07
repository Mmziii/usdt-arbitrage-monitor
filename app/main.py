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
from .journal import JournalError, export_csv as journal_csv, validate as validate_journal
from .net import Gateway, Monitor, budget, budgets
from .plans import build_plan
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
    user_agent: str = Field(default='TraderBot/USDTMonitor-2.0 (+read-only)', min_length=3, max_length=200)
    max_timestamp_age_seconds: int = Field(default=120, ge=10, le=3600)
    clock_skew_warning_seconds: int = Field(default=60, ge=10, le=3600)

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
    'user_agent': os.getenv('USER_AGENT') or 'TraderBot/USDTMonitor-2.0 (+read-only)',
    'max_timestamp_age_seconds': int(os.getenv('MAX_TIMESTAMP_AGE', '120')),
    'clock_skew_warning_seconds': int(os.getenv('CLOCK_SKEW_WARNING', '60')),
}
settings = Settings(**{**_ENV_DEFAULTS, **(store.settings() or {})})
books, errors, manual = {}, {}, {}
wake = asyncio.Event()
monitor = Monitor()
gateway = Gateway(monitor=monitor, user_agent=settings.user_agent, proxy=settings.proxy_url)
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


async def hub_loop():
    """Bulk overview scan every `interval` seconds; hot-row depth every `depth_interval`."""
    while True:
        try:
            async with gateway.make_client() as client:
                await hub.scan(client)
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
    return FileResponse(static / 'dashboard.html')


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
    gateway.configure(user_agent=value.user_agent, proxy=value.proxy_url)
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
    transfer_minutes: dict[str, Optional[float]] = {'default': None, 'TRC20': None, 'BEP20': None, 'ERC20': None}
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
    'setup_banner_dismissed': '',
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
    gateway.configure(user_agent=settings.user_agent, proxy=settings.proxy_url)
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
