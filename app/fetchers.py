"""Read-only public order books. All normalized prices are TOMAN, quantities USDT."""
import math
import time
from dataclasses import dataclass
import httpx


@dataclass
class Book:
    asks: list[tuple[float, float]]
    bids: list[tuple[float, float]]
    timestamp: float
    source: str = 'live'


def levels(rows, divisor=1, objects=False):
    result = []
    for row in rows:
        p, q = (row['price'], row['quantity']) if objects else row
        p, q = float(p) / divisor, float(q)
        if not all(math.isfinite(v) and v > 0 for v in (p, q)):
            raise ValueError('Invalid price/quantity')
        result.append((p, q))
    if not result:
        raise ValueError('Empty order book')
    return result


def parse_book(name, data):
    if name == 'wallex':
        if data.get('success') is not True:
            raise ValueError('Wallex unsuccessful response')
        body = data['result']
        asks, bids = levels(body['ask'], objects=True), levels(body['bid'], objects=True)
        updated = time.time()
    else:
        if data.get('status') != 'ok':
            raise ValueError('Nobitex unsuccessful response')
        # IRT market in Nobitex public API is denominated in RIAL, not toman.
        asks, bids = levels(data['asks'], 10), levels(data['bids'], 10)
        updated = float(data['lastUpdate']) / 1000
        if not math.isfinite(updated) or abs(time.time() - updated) > 120:
            raise ValueError('Stale exchange order book')
    asks.sort()
    bids.sort(reverse=True)
    if bids[0][0] > asks[0][0]:
        raise ValueError('Crossed order book')
    return Book(asks, bids, updated)


async def fetch_book(client, name):
    if name == 'wallex':
        url = 'https://api.wallex.ir/v1/depth?symbol=USDTTMN'
    else:
        url = 'https://apiv2.nobitex.ir/v3/orderbook/USDTIRT'
    response = await client.get(url)
    response.raise_for_status()
    return parse_book(name, response.json())
