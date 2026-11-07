import asyncio
import contextlib
import csv
import io
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .fetchers import Book, fetch_book
from .calculation import calculate
from .storage import Storage
from .scanner import Scanner
from .symbols import normalize
from .fees import parse_pasted_fees
from .tiers import Tier, active_fees, parse_tiers, export_tiers
from typing import Optional, Literal

load_dotenv()
store = Storage(os.getenv('DATABASE_PATH', 'history.sqlite3'))


class TradingFees(BaseModel):
    maker: float = Field(ge=0, lt=100, allow_inf_nan=False)
    taker: float = Field(ge=0, lt=100, allow_inf_nan=False)


class Fees(TradingFees):
    withdrawal: float = Field(ge=0, allow_inf_nan=False)


class Settings(BaseModel):
    refresh_seconds: int = Field(default=10, ge=5, le=3600)
    threshold: float = Field(default=.5, ge=0, le=100, allow_inf_nan=False)
    wallex: Fees = Fees(maker=.25, taker=.3, withdrawal=.8)
    nobitex: Fees = Fees(maker=.25, taker=.25, withdrawal=.7)
    wallex_usdt: TradingFees = TradingFees(maker=.25, taker=.3)
    nobitex_usdt: TradingFees = TradingFees(maker=.25, taker=.25)

    fee_tiers: list[Tier] = []
    current_tiers: dict[str, str] = {}

    def trading_fees(self, exchange, quote):
        return {k: v for k, v in active_fees(self, exchange, quote).items() if k in ('maker', 'taker')}


settings = Settings(**store.settings({'refresh_seconds': int(os.getenv('REFRESH_SECONDS', '10'))}))
books, errors, manual = {}, {}, {}
wake = asyncio.Event()
scanner = Scanner(store)


async def poll():
    async with httpx.AsyncClient(timeout=8, headers={'User-Agent': 'TraderBot/USDTMonitor-1.0'}) as client:
        while True:
            async def update(name):
                try:
                    books[name] = await fetch_book(client, name)
                    errors.pop(name, None)
                except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
                    books.pop(name, None)
                    errors[name] = 'دریافت قیمت یا ساختار داده نامعتبر است؛ قیمت خرید و فروش را دستی وارد کنید.'
            await asyncio.gather(*(update(n) for n in ('wallex', 'nobitex')))
            if len(books) == 2:
                store.record(time.time(), books['wallex'], books['nobitex'])
            try:
                await asyncio.wait_for(wake.wait(), timeout=settings.refresh_seconds)
            except asyncio.TimeoutError:
                pass
            wake.clear()


async def scan_loop():
    async with httpx.AsyncClient(timeout=8, headers={'User-Agent': 'TraderBot/USDTMonitor-1.0'}) as client:
        while True:
            try:
                await scanner.scan(client)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                pass
            scanner.store.prune(scanner.config()['retention_days'])
            await asyncio.sleep(scanner.config()['interval'])


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(poll())
    scan_task = asyncio.create_task(scan_loop())
    yield
    scan_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await scan_task
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title='USDT monitor — read only', lifespan=lifespan)
static = Path(__file__).parent / 'static'
app.mount('/static', StaticFiles(directory=static), name='static')


@app.get('/')
def index():
    return FileResponse(static / 'index.html')


@app.get('/api/settings')
def get_settings():
    return settings


@app.put('/api/settings')
def put_settings(value: Settings):
    global settings
    settings = value
    store.save_settings(value.model_dump())
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
                    row.update(calculate(capital, active[src], active[dst], getattr(settings, src).model_dump(), getattr(settings, dst).model_dump(), mode))
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
    exchange: Literal['wallex', 'nobitex']
    coin: str = Field(min_length=2, max_length=20)
    network: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
    withdrawal: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    minimum: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    supported: bool


class ScannerSettings(BaseModel):
    interval: int = Field(default=30, ge=10, le=3600)
    retention_days: int = Field(default=30, ge=1, le=3650)
    capital_toman: float = Field(default=10000000, gt=0, le=1e15, allow_inf_nan=False)
    capital_usdt: float = Field(default=100, gt=0, le=1e15, allow_inf_nan=False)
    threshold: float = Field(default=.5, ge=0, le=100, allow_inf_nan=False)
    watchlist: list[str] = []
    networks: dict[str, str] = {}


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
        raise HTTPException(503, str(e))
    return {'ok': True}


@app.get('/api/scanner/detail/{coin}/{quote}')
async def scanner_detail(coin: str, quote: Literal['toman', 'USDT']):
    try:
        coin = normalize(coin)
        async with httpx.AsyncClient(timeout=8) as client:
            books = await scanner.fetch_depth(client, coin, quote)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as e:
        raise HTTPException(503, str(e))
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
