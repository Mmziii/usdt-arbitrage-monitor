"""Hand-calculated full-cycle examples (Route A, Route B, direct) and fee blocking."""
import pytest

from app.adapters import DepthBook
from app.cycle import Books, UnknownFee, evaluate_cycle, build_chain


NOW = 1_700_000_000.0


def book(exchange, coin, quote, asks, bids, timestamp=NOW, quality='depth'):
    return DepthBook(exchange, coin, quote, asks, bids, timestamp, True, 'fixture', quality)


def main_books(bitunix_asks=((100, 100),), bitunix_bids=((99.9, 100),)):
    iran = book('wallex', 'BTC', 'toman', [(6_600_000, 100)], [(6_600_000, 100)])
    conversion = book('wallex', 'USDT', 'toman', [(60_000, 1_000_000_000)],
                      [(59_900, 1_000_000_000)])
    bitunix = book('bitunix', 'BTC', 'USDT', list(bitunix_asks), list(bitunix_bids))
    return Books(iran=iran, conversion=conversion, bitunix=bitunix)


FEES = {'bitunix': {'maker': .1, 'taker': .1}, 'iran': {'maker': .1, 'taker': .2},
        'conversion': {'maker': .1, 'taker': .2}}
WITHDRAWALS = {'bitunix_coin': .01, 'iran_coin': .001, 'bitunix_usdt': 1, 'iran_usdt': 1}


def test_route_a_hand_calculated_profitable_cycle_with_conversion_step():
    result = evaluate_cycle('A', main_books(), FEES, WITHDRAWALS, 1000, now=NOW)
    taker = result['taker']
    # Step by step, exactly as documented:
    coins = 1000 / 100 * (1 - .001)                       # 9.99 BTC bought on Bitunix
    coins -= .01                                          # Bitunix coin withdrawal fee
    toman = coins * 6_600_000 * (1 - .002)                # sold into Iranian bids, fee
    usdt = toman / 60_000 * (1 - .002)                    # USDT bought with toman (ask)
    final = usdt - 1                                      # Iranian USDT withdrawal fee
    assert taker['ok']
    assert taker['steps'][0]['value'] == pytest.approx(9.99)
    assert taker['steps'][1]['value'] == pytest.approx(9.98)
    assert taker['steps'][2]['value'] == pytest.approx(65_736_264)
    assert taker['steps'][3]['value'] == pytest.approx(1093.4131912)
    assert taker['final'] == pytest.approx(final)
    assert taker['final'] == pytest.approx(1092.4131912)
    assert taker['profit'] == pytest.approx(92.4131912)
    assert taker['profit_pct'] == pytest.approx(9.24131912)
    assert taker['safety_status'] == 'profitable'
    # Conversion source and rate are explicit and come from the Iranian USDT/toman book.
    assert result['conversion']['exchange'] == 'wallex'
    assert result['conversion']['side'] == 'ask'
    assert result['conversion']['rate'] == 60_000
    assert result['conversion']['timestamp'] == NOW
    assert result['effective_rate'] == pytest.approx(65_736_264 / 1093.4131912)
    assert result['profit_toman'] == pytest.approx(92.4131912 * result['effective_rate'])
    # Maker is a hypothetical with the same books and maker rates only.
    assert result['maker']['profit'] > taker['profit']


def test_route_a_made_unprofitable_by_a_fixed_coin_withdrawal_fee():
    withdrawals = {**WITHDRAWALS, 'bitunix_coin': 5}
    result = evaluate_cycle('A', main_books(), FEES, withdrawals, 1000, now=NOW)
    taker = result['taker']
    # Same cycle, but 5 BTC of the 9.99 BTC bought is lost as a fixed withdrawal fee.
    coins = 1000 / 100 * (1 - .001) - 5
    toman = coins * 6_600_000 * (1 - .002)
    usdt = toman / 60_000 * (1 - .002)
    final = usdt - 1
    assert taker['final'] == pytest.approx(final)
    assert taker['final'] == pytest.approx(545.7065956)
    assert taker['profit'] == pytest.approx(-454.2934044)
    assert taker['profit_pct'] == pytest.approx(-45.42934044)
    assert taker['safety_status'] == 'unprofitable'
    # The gross reference does not include withdrawal fees, so it stays positive: this is
    # exactly why the app labels gross-only numbers instead of calling them profit.
    assert result['gross_pct'] is not None and result['gross_pct'] > 0
    # Profit envelope: a larger fixed fee makes the smallest viable capital bigger.
    assert taker['minimum_capital'] > 5 * 100


def test_route_b_hand_calculated_reverse_cycle():
    result = evaluate_cycle('B', main_books(), FEES, WITHDRAWALS, 1000, now=NOW)
    usdt = 1000 - 1                                        # Bitunix USDT withdrawal fee
    toman = usdt * 59_900 * (1 - .002)                     # sold for toman (bid side)
    coins = toman / 6_600_000 * (1 - .002)                 # coin bought in Iran
    coins -= .001                                          # Iranian coin withdrawal fee
    final = coins * 99.9 * (1 - .001)                      # sold into Bitunix bids
    assert result['taker']['ok']
    assert result['taker']['final'] == pytest.approx(final)
    assert result['taker']['final'] == pytest.approx(901.14014844, abs=1e-6)
    assert result['taker']['profit'] == pytest.approx(-98.85985156, abs=1e-6)
    assert result['conversion']['side'] == 'bid'
    assert result['conversion']['rate'] == 59_900
    # Stage order: withdraw USDT, convert, buy coin, withdraw coin, sell coin.
    assert [step['name'] for step in result['taker']['steps']] == [
        'withdraw_usdt', 'convert', 'buy_coin', 'withdraw_coin', 'sell_coin']


def test_route_b_with_deeper_books_walks_depth():
    books = main_books()
    books.conversion.bids = [(59_900, 500), (59_800, 10_000)]
    result = evaluate_cycle('B', books, FEES, WITHDRAWALS, 1000, now=NOW)
    expected_toman = (500 * 59_900 + (999 - 500) * 59_800) * (1 - .002)
    assert result['taker']['steps'][1]['value'] == pytest.approx(expected_toman)


def test_direct_usdt_market_variant_needs_no_toman_conversion():
    iran = book('wallex', 'BTC', 'USDT', [(10, 1000)], [(9.9, 1000)])
    bitunix = book('bitunix', 'BTC', 'USDT', [(10.1, 1000)], [(10.5, 1000)])
    books = Books(iran=iran, conversion=None, bitunix=bitunix)
    result = evaluate_cycle('direct_iran_to_bitunix', books, FEES, WITHDRAWALS, 1000, now=NOW)
    coins = 1000 / 10 * (1 - .002) - .001
    final = coins * 10.5 * (1 - .001)
    assert result['taker']['final'] == pytest.approx(final)
    assert result['conversion'] is None
    reverse = evaluate_cycle('direct_bitunix_to_iran', books, FEES, WITHDRAWALS, 1000, now=NOW)
    coins = 1000 / 10.1 * (1 - .001) - .01
    assert reverse['taker']['final'] == pytest.approx(coins * 9.9 * (1 - .002))


def test_unknown_bitunix_fees_block_net_profit_but_keep_gross():
    fees = {**FEES, 'bitunix': {'maker': None, 'taker': None}}
    result = evaluate_cycle('A', main_books(), fees, WITHDRAWALS, 1000, now=NOW)
    assert result['taker']['reason'] == 'fee unknown'
    assert 'بیتیونیکس' in result['taker']['error']
    assert result['taker'].get('final') is None
    assert result['gross_pct'] == pytest.approx(10.0)


def test_unknown_withdrawal_fee_blocks_transfer_but_not_prefunded():
    withdrawals = {**WITHDRAWALS, 'bitunix_coin': None}
    transfer = evaluate_cycle('A', main_books(), FEES, withdrawals, 1000, now=NOW,
                              trading_mode='transfer')
    assert transfer['taker']['reason'] == 'fee unknown'
    prefunded = evaluate_cycle('A', main_books(), FEES, withdrawals, 1000, now=NOW,
                               trading_mode='prefunded')
    assert prefunded['taker']['ok']
    # Prefunded skips both network withdrawals: 9.99 BTC, no coin/USDT fees.
    assert prefunded['taker']['final'] == pytest.approx(9.99 * 6_600_000 * .998 / 60_000 * .998)
    assert prefunded['taker']['rebalancing']['incomplete'] is True


def test_prefunded_rebalancing_cost_is_amortised_separately():
    result = evaluate_cycle('A', main_books(), FEES, WITHDRAWALS, 1000, now=NOW,
                            trading_mode='prefunded', rebalance_trades=10)
    taker = result['taker']
    cost = .01 * 99.9 + 1
    assert taker['rebalancing']['total'] == pytest.approx(cost)
    assert taker['rebalancing']['per_trade'] == pytest.approx(cost / 10)
    assert taker['rebalancing']['profit_after'] == pytest.approx(taker['profit'] - cost / 10)
    assert result['safety_margin'] == 0


def test_safety_margin_and_capital_envelope():
    below = evaluate_cycle('A', main_books(), FEES, WITHDRAWALS, 1000, margin=12, now=NOW)
    assert below['taker']['profit_pct'] == pytest.approx(9.2413, abs=1e-3)
    assert below['taker']['safety_status'] == 'below safety margin'
    assert below['taker']['max_profitable_capital'] is None    # nothing beats a 12% margin
    result = evaluate_cycle('A', main_books(), FEES, WITHDRAWALS, 1000, margin=5, now=NOW)
    taker = result['taker']
    assert taker['safety_status'] == 'profitable'
    assert taker['breakeven_capital'] is not None and taker['breakeven_capital'] > 0
    assert taker['profit_maximizing_capital'] is not None
    # Profit keeps growing up to the visible depth, so no global maximum is claimed.
    assert taker['limited_by_visible_depth'] is True
    assert taker['max_profitable_capital'] is None


def test_missing_book_is_reported_as_insufficient_depth():
    books = main_books()
    books.bitunix.asks = [(100, .1)]   # only 10 USDT of visible ask liquidity
    result = evaluate_cycle('direct_bitunix_to_iran', books, FEES, WITHDRAWALS, 1000, now=NOW)
    assert result['taker']['ok'] is False
    assert result['taker']['reason'] in ('insufficient depth', 'error')


def test_chain_requires_known_trading_fee():
    books = main_books()
    with pytest.raises(UnknownFee):
        build_chain('A', books, {**FEES, 'iran': {'maker': .1, 'taker': None}},
                    WITHDRAWALS, 'taker')
