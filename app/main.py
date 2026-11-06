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

load_dotenv()
store = Storage(os.getenv('DATABASE_PATH', 'history.sqlite3'))


class Fees(BaseModel):
    maker: float = Field(ge=0, lt=100, allow_inf_nan=False)
    taker: float = Field(ge=0, lt=100, allow_inf_nan=False)
    withdrawal: float = Field(ge=0, allow_inf_nan=False)


class Settings(BaseModel):
    refresh_seconds: int = Field(default=10, ge=5, le=3600)
    threshold: float = Field(default=.5, ge=0, le=100, allow_inf_nan=False)
    wallex: Fees = Fees(maker=.25, taker=.3, withdrawal=.8)
    nobitex: Fees = Fees(maker=.25, taker=.25, withdrawal=.7)


settings = Settings(**store.settings({'refresh_seconds': int(os.getenv('REFRESH_SECONDS', '10'))}))
books, errors, manual = {}, {}, {}
wake = asyncio.Event()


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


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(poll())
    yield
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
