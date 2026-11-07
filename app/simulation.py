"""Simulated trades: save the current prices and outcome, then re-read the books later.

Only real fetched data is used. If the books cannot be fetched again the simulation is
marked ``unavailable`` instead of inventing a result.
"""
import json
import math
import time

STATUS_LABELS = {'pending': 'در انتظار', 'done': 'انجام‌شده', 'unavailable': 'داده کافی نبود'}


class SimulationError(ValueError):
    pass


def snapshot_prices(books):
    """Minimal, JSON-safe price snapshot for later comparison."""
    result = {}
    for key, book in (books or {}).items():
        if book is None:
            continue
        result[key] = {'best_ask': book.best_ask, 'best_bid': book.best_bid,
                       'timestamp': book.timestamp, 'source': book.source,
                       'quality': book.quality}
    return result


def create(store, row, prices, now=None, transfer_minutes=None, delay_seconds=None):
    now = time.time() if now is None else now
    taker = (row.get('detail') or {}).get('taker') or row.get('taker') or {}
    if not taker.get('ok'):
        raise SimulationError('برای این ردیف محاسبه کامل ممکن نیست؛ معامله آزمایشی ثبت نشد.')
    if row.get('kind') == 'classic':
        raise SimulationError('معامله آزمایشی برای مسیرهای بیت‌یونیکس فعال است؛ '
                              'برای این ردیف امکان بازخوانی خودکار دفتر سفارش وجود ندارد.')
    if delay_seconds is not None:
        wait = max(10, min(86400, float(delay_seconds)))
    else:
        wait = float(transfer_minutes) * 60 if transfer_minutes else 0.0
        wait = max(10.0, wait or 60.0)
    record = {
        'created': now, 'key': row.get('key'), 'coin': row.get('coin'),
        'route': row.get('route'), 'route_label': row.get('route_label'),
        'mode': row.get('trading_mode') or 'transfer',
        'capital': taker.get('capital') or row.get('capital'),
        'unit': row.get('capital_unit') or 'USDT',
        'expected_final': taker.get('final'), 'expected_profit': taker.get('profit'),
        'expected_pct': taker.get('profit_pct'),
        'prices': json.dumps(prices or {}, ensure_ascii=False),
        'transfer_minutes': None if delay_seconds is not None else wait / 60,
        'due': now + wait, 'status': 'pending', 'note': '',
    }
    return store.add_simulation(record)


def settle(store, simulation, actual_row, now=None):
    """Compare the stored expectation with a freshly calculated result."""
    now = time.time() if now is None else now
    taker = (actual_row.get('detail') or {}).get('taker') or actual_row.get('taker') or {}
    if not taker.get('ok'):
        store.update_simulation(simulation['id'], {
            'status': 'unavailable', 'completed': now,
            'note': (taker.get('error') or 'دفتر سفارش جدید در دسترس نبود')[:300]})
        return store.simulation(simulation['id'])
    actual_profit = taker.get('profit')
    expected_profit = simulation.get('expected_profit')
    difference = None
    if actual_profit is not None and expected_profit is not None:
        difference = actual_profit - expected_profit
    store.update_simulation(simulation['id'], {
        'status': 'done', 'completed': now, 'actual_final': taker.get('final'),
        'actual_profit': actual_profit, 'actual_pct': taker.get('profit_pct'),
        'difference': difference, 'note': ''})
    return store.simulation(simulation['id'])


def summary(rows):
    done = [row for row in rows if row.get('status') == 'done']
    differences = [row['difference'] for row in done if row.get('difference') is not None]
    profitable = [row for row in done if (row.get('actual_profit') or 0) > 0]
    return {
        'count': len(rows),
        'pending': sum(1 for row in rows if row.get('status') == 'pending'),
        'done': len(done),
        'unavailable': sum(1 for row in rows if row.get('status') == 'unavailable'),
        'average_difference': sum(differences) / len(differences) if differences else None,
        'profitable_share': (len(profitable) / len(done) * 100) if done else None,
        'worst_difference': min(differences) if differences else None,
        'best_difference': max(differences) if differences else None,
    }


def public(row):
    item = dict(row)
    try:
        item['prices'] = json.loads(item.get('prices') or '{}')
    except (TypeError, ValueError):
        item['prices'] = {}
    item['status_label'] = STATUS_LABELS.get(item.get('status'), item.get('status'))
    return item


def valid_number(value, name='مقدار'):
    if value is None:
        return None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SimulationError(f'{name} نامعتبر است')
    return float(value)
