"""Recalculation edge cases: zero/tiny capital, capital beyond the visible depth, a
withdrawal fee larger than the amount, missing fee data and empty order books.

Every case must answer with a Persian explanation instead of raising, returning NaN/inf
or showing a profit that the visible orders cannot support.
"""
import math
import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.adapters import DepthBook, Market, Ticker
from app.cycle import Books, evaluate_cycle
from app.hub import Hub
from app.main import AppSettings
from app.net import Monitor
from app.storage import Storage

NOW = 1_700_000_000.0


def book(exchange, coin, quote, asks, bids, timestamp=NOW):
    return DepthBook(exchange, coin, quote, list(asks), list(bids), timestamp, True,
                     'fixture', 'depth')


def main_books(bitunix_asks=((100, 100),), bitunix_bids=((99.9, 100),),
               iran_bids=((6_600_000, 100),), conversion_asks=((60_000, 1e9),)):
    return Books(iran=book('wallex', 'BTC', 'toman', [(6_600_000, 100)], iran_bids),
                 conversion=book('wallex', 'USDT', 'toman', conversion_asks, [(59_900, 1e9)]),
                 bitunix=book('bitunix', 'BTC', 'USDT', bitunix_asks, bitunix_bids))


FEES = {'bitunix': {'maker': .1, 'taker': .1}, 'iran': {'maker': .1, 'taker': .2},
        'conversion': {'maker': .1, 'taker': .2}}
WITHDRAWALS = {'bitunix_coin': .01, 'iran_coin': .001, 'bitunix_usdt': 1, 'iran_usdt': 1}


def persian(text):
    return any('\u0600' <= char <= '\u06ff' for char in (text or ''))


def finite_or_none(value):
    return value is None or (isinstance(value, (int, float)) and math.isfinite(value))


def test_the_reference_case_still_matches_the_hand_calculation():
    """Guard rail: the edge cases below are compared against this known-good number."""
    taker = evaluate_cycle('A', main_books(), FEES, WITHDRAWALS, 1000, now=NOW)['taker']
    assert taker['ok'] and taker['profit_pct'] == pytest.approx(9.24131912)


def test_zero_capital_is_explained_instead_of_dividing_by_zero():
    taker = evaluate_cycle('A', main_books(), FEES, WITHDRAWALS, 0, now=NOW)['taker']
    assert taker['ok'] is False and taker['reason'] == 'error'
    assert persian(taker['error']) and 'سرمایه' in taker['error']
    for key in ('profit', 'profit_pct', 'final', 'breakeven_capital', 'max_profitable_capital'):
        assert finite_or_none(taker.get(key)), (key, taker.get(key))


@pytest.mark.parametrize('capital', [float('nan'), float('inf'), -1000, -1e-9])
def test_hostile_capital_values_never_leak_nan(capital):
    taker = evaluate_cycle('A', main_books(), FEES, WITHDRAWALS, capital, now=NOW)['taker']
    assert taker['ok'] is False
    assert persian(taker['error'])
    assert finite_or_none(taker.get('profit_pct'))


def test_tiny_capital_reports_the_withdrawal_fee_it_cannot_pay():
    # 1 micro-USDT buys 0.00000000999 BTC, which cannot pay the 0.01 BTC withdrawal.
    taker = evaluate_cycle('A', main_books(), FEES, WITHDRAWALS, 1e-6, now=NOW)['taker']
    assert taker['ok'] is False
    assert 'برداشت' in taker['error'] and persian(taker['error'])
    assert taker.get('profit_pct') is None


def test_small_but_workable_capital_is_computed_with_a_real_loss():
    # 2 USDT -> 0.01998 BTC -> 0.00998 BTC after the fee; the Iranian USDT fee dominates.
    taker = evaluate_cycle('A', main_books(), FEES, WITHDRAWALS, 2, now=NOW)['taker']
    assert taker['ok'] is True
    assert taker['profit'] < 0
    assert taker['profit_pct'] == pytest.approx(-95.32934044)
    assert math.isfinite(taker['profit_pct'])


def test_capital_far_beyond_the_visible_depth_is_refused():
    taker = evaluate_cycle('A', main_books(), FEES, WITHDRAWALS, 1e9, now=NOW)['taker']
    assert taker['ok'] is False and taker['reason'] == 'insufficient depth'
    assert persian(taker['error'])
    assert taker.get('profit_pct') is None


def test_capital_at_the_visible_depth_edge_reports_depth_limitation():
    taker = evaluate_cycle('A', main_books(), FEES, WITHDRAWALS, 10_000, now=NOW)['taker']
    assert taker['ok'] is True
    assert taker['limited_by_visible_depth'] is True
    # 100 BTC of asks at 100 USDT is the whole visible capacity.
    assert taker['visible_capital'] == pytest.approx(10_000)
    # The fixed 0.01 BTC / 1 USDT withdrawal fees weigh less on a bigger ticket, so the
    # percentage rises until the books run out — capacity, not a free lunch.
    assert taker['profit_pct'] > 9.24131912
    assert taker['profit'] == pytest.approx(10_000 * taker['profit_pct'] / 100)


def test_withdrawal_fee_larger_than_the_bought_amount():
    withdrawals = {**WITHDRAWALS, 'bitunix_coin': 20}     # 20 BTC fee on ~9.99 BTC
    result = evaluate_cycle('A', main_books(), FEES, withdrawals, 1000, now=NOW)
    taker = result['taker']
    assert taker['ok'] is False
    assert 'کافی نیست' in taker['error'] and 'برداشت' in taker['error']
    assert taker.get('profit') is None
    # The gross reference has no transfer and keeps working; it must not inherit the failure.
    assert result['gross_pct'] == pytest.approx(10.0, abs=1e-6)


def test_missing_fee_data_blocks_net_and_keeps_gross():
    fees = {**FEES, 'iran': {'maker': .1, 'taker': None}}
    result = evaluate_cycle('A', main_books(), fees, WITHDRAWALS, 1000, now=NOW)
    assert result['taker']['ok'] is False and result['taker']['reason'] == 'fee unknown'
    assert persian(result['taker']['error'])
    assert result['gross_pct'] == pytest.approx(10.0, abs=1e-6)


def test_missing_withdrawal_row_names_the_step():
    result = evaluate_cycle('A', main_books(), FEES, {}, 1000, now=NOW)
    assert result['taker']['ok'] is False and result['taker']['reason'] == 'fee unknown'
    assert 'برداشت' in result['taker']['error']


@pytest.mark.parametrize('books, step', [
    (main_books(bitunix_asks=()), 'فروش'),
    (main_books(iran_bids=()), 'خرید'),
    (main_books(conversion_asks=()), 'فروش'),
])
def test_empty_order_books_are_refused_without_an_exception(books, step):
    result = evaluate_cycle('A', books, FEES, WITHDRAWALS, 1000, now=NOW)
    taker = result['taker']
    assert taker['ok'] is False and taker['reason'] == 'insufficient depth'
    assert step in taker['error'] and 'خالی' in taker['error']


def test_zero_price_book_is_not_a_division_by_zero():
    result = evaluate_cycle('A', main_books(bitunix_asks=((0, 100),)), FEES, WITHDRAWALS,
                            1000, now=NOW)
    assert result['taker']['ok'] is False
    assert finite_or_none(result['taker'].get('profit_pct'))


# ------------------------------------------------------------------ hub and HTTP layer
class SilentGateway:
    def __init__(self):
        self.monitor = Monitor()

    def configure(self, **kwargs):
        pass

    async def fetch(self, *args, **kwargs):     # pragma: no cover - never used here
        raise AssertionError('edge-case tests must not touch the network')

    def make_client(self, *args, **kwargs):
        class Client:
            async def __aenter__(self_inner):
                return object()

            async def __aexit__(self_inner, *exc):
                return False
        return Client()


def make_hub(tmp_path, books=None, settings=None):
    store = Storage(str(tmp_path / 'edges.db'))
    store.init_scanner()
    settings = settings or AppSettings(bitunix={'maker': .1, 'taker': .1},
                                       bitunix_usdt={'maker': .1, 'taker': .1})
    hub = Hub(store, SilentGateway(), lambda: settings)
    hub.bitunix[('BTC', 'USDT')] = Market('bitunix', 'BTC', 'USDT', 'BTCUSDT')
    hub.iran['wallex'][('BTC', 'toman')] = Market('wallex', 'BTC', 'toman', 'BTCIRT')
    hub.iran['wallex'][('USDT', 'toman')] = Market('wallex', 'USDT', 'toman', 'USDTIRT')
    hub.rebuild_routes()
    now = time.time()
    for (exchange, coin, quote), prices in {
            ('bitunix', 'BTC', 'USDT'): (100.1, 100.0),
            ('wallex', 'BTC', 'toman'): (6_600_100, 6_600_000),
            ('wallex', 'USDT', 'toman'): (60_000, 59_900)}.items():
        hub.tickers[(exchange, coin, quote)] = Ticker(exchange, coin, quote, prices[0],
                                                      prices[1], now, True, 'bulk')
    hub.books.update(books or {
        ('bitunix', 'BTC', 'USDT'): book('bitunix', 'BTC', 'USDT', [(100, 100)], [(99.9, 100)], now),
        ('wallex', 'BTC', 'toman'): book('wallex', 'BTC', 'toman', [(6_600_000, 100)],
                                         [(6_600_000, 100)], now),
        ('wallex', 'USDT', 'toman'): book('wallex', 'USDT', 'toman', [(60_000, 1e9)],
                                          [(59_900, 1e9)], now)})
    for exchange in ('wallex', 'bitunix'):
        store.replace_fees([{'exchange': exchange, 'coin': 'BTC', 'network': 'TRC20',
                             'withdrawal': .01, 'minimum': 0, 'supported': True},
                            {'exchange': exchange, 'coin': 'USDT', 'network': 'TRC20',
                             'withdrawal': 1, 'minimum': 0, 'supported': True}])
    store.save_scanner_settings({'networks': {'BTC': 'TRC20', 'USDT': 'TRC20'},
                                 'capital_usdt': 100})
    return hub, store, settings


def test_hub_row_with_an_empty_bitunix_book_keeps_the_page_alive(tmp_path):
    hub, _, _ = make_hub(tmp_path)
    hub.books[('bitunix', 'BTC', 'USDT')] = book('bitunix', 'BTC', 'USDT', [], [(99.9, 100)],
                                                 time.time())
    rows = hub.build_rows(hub.config())
    row = next(item for item in rows if item['key'] == 'A:BTC:wallex')
    assert row['status'] != 'ok'
    assert row['taker']['ok'] is False
    assert 'خالی' in row['taker']['error']
    assert row.get('net_pct') is None
    # Route A needs the Bitunix ask ladder even for the gross reference, so it is blank too.
    assert row['gross_pct'] is None and row['verdict'] == 'unknown'


def test_overview_endpoint_survives_an_empty_book(tmp_path, monkeypatch):
    hub, store, settings = make_hub(tmp_path)
    hub.books[('bitunix', 'BTC', 'USDT')] = book('bitunix', 'BTC', 'USDT', [], [(99.9, 100)],
                                                 time.time())
    monkeypatch.setattr(main, 'hub', hub)
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'settings', settings)
    client = TestClient(main.app)              # no lifespan: the loops never start
    response = client.get('/api/overview')
    assert response.status_code == 200
    body = response.json()
    row = next(item for item in body['rows'] if item['key'] == 'A:BTC:wallex')
    assert row['status'] != 'ok' and row['taker_pct'] is None
    detail = client.get('/api/overview/detail', params={'key': 'A:BTC:wallex'})
    assert detail.status_code == 200
