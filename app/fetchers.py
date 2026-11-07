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


def parse_book(name, data, max_age=120, clock_skew=None):
    """Legacy USDT/IRT parser for the classic dashboard.

    ``max_age`` is configurable and the age rule is skipped when the local clock is known
    to be skewed (the exchange timestamp cannot be judged from a wrong laptop clock).
    """
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
        raw = data.get('lastUpdate')
        if raw is None:
            updated = time.time()
        else:
            updated = float(raw) / 1000
            reliable = math.isfinite(updated)
            skewed = clock_skew is not None and abs(clock_skew) > 60
            if reliable and not skewed and time.time() - updated > max_age:
                raise ValueError('Stale exchange order book')
    asks.sort()
    bids.sort(reverse=True)
    if bids[0][0] > asks[0][0]:
        raise ValueError('Crossed order book')
    return Book(asks, bids, updated)


async def fetch_book(client, name, gateway=None, max_age=120):
    if name == 'wallex':
        url = 'https://api.wallex.ir/v1/depth?symbol=USDTTMN'
    else:
        url = 'https://apiv2.nobitex.ir/v3/orderbook/USDTIRT'
    if gateway is not None:
        from .net import Endpoint
        skew = (gateway.monitor.clock_state.get(name) or {}).get('skew_seconds')
        result = await gateway.fetch(client, name, Endpoint('depth', url),
                                     lambda data: parse_book(name, data, max_age, skew),
                                     budget_name=name)
        if not result.ok:
            from .net import ExchangeError
            raise ExchangeError(result)
        return result.data
    response = await client.get(url)
    response.raise_for_status()
    return parse_book(name, response.json(), max_age)
