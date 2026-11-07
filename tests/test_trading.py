import pytest
from app.fetchers import Book
from app.trading import evaluate, transfer_time
from app.capital import capital_limits


def book(asks, bids):
    return Book(asks, bids, 100, 'fixture')


def test_prefunded_toman_hand_calculated():
    a = book([(100, 10), (110, 10)], [(99, 20)])
    b = book([(125, 20)], [(120, 20)])
    fees = dict(taker=1, maker=0, withdrawal=5, minimum=100)
    r = evaluate(1000, a, b, fees, fees, 'taker', 'prefunded')
    assert r['coin_after_buy'] == pytest.approx(9.9)
    assert r['coin_after_withdrawal'] == pytest.approx(9.9)
    assert r['final_quote'] == pytest.approx(1176.12)
    assert r['profit'] == pytest.approx(176.12)
    assert r['balances_unlimited']
    assert r['rebalancing']['incomplete']


def test_prefunded_usdt_amortization_and_balances():
    a = book([(2, 100)], [(1.9, 100)])
    b = book([(2.3, 100)], [(2.2, 100)])
    fees = dict(taker=0, maker=0, withdrawal=9)
    r = evaluate(100, a, b, fees, fees, 'taker', 'prefunded', quote_balance=80,
                 coin_balance=30, rebalance_trades=10, rebalance_coin_fee=1, rebalance_quote_fee=.8)
    assert r['capital'] == 60
    assert r['profit'] == 6
    assert r['rebalancing']['total'] == 3
    assert r['rebalancing']['per_trade'] == .3
    assert r['rebalancing']['profit_after'] == 5.7
    assert not r['balances_unlimited']


def test_transfer_below_margin():
    a = book([(100, 100)], [(99, 100)])
    b = book([(101, 100)], [(100.2, 100)])
    f = dict(taker=0, maker=0, withdrawal=0)
    r = evaluate(1000, a, b, f, f, 'taker')
    assert r['profit'] == pytest.approx(2)
    assert r['safety_status'] == 'below safety margin'
    assert transfer_time({}, 'UNKNOWN') == dict(minutes=None, estimated=True, uses_default=True)


def test_multilevel_exact_capital_limits():
    # First 10 cost 100 and return 120. Thereafter each costs 20 and returns 12:
    # peak at 100; zero profit at 150 (12.5 coins).
    r = capital_limits([(10, 10), (20, 20)], [(12, 30)], 0, 0)
    assert r['max_profitable_capital'] == pytest.approx(150)
    assert r['profit_maximizing_capital'] == 100
    assert not r['limited_by_visible_depth']
    r = capital_limits([(10, 10)], [(12, 10)], 0, 0)
    assert r['limited_by_visible_depth']
    assert r['max_profitable_capital'] is None
