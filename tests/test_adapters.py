"""Fixture-backed adapter tests. No outbound exchange access is performed."""
import time
import pytest

from app.adapters import ADAPTERS, Bitunix, DepthBook, Nobitex, Wallex, adapter
from app.discovery import discover
from app.net import ValidationError


WALLEX_DEPTH = {'success': True, 'result': {
    'ask': [{'price': '101.5', 'quantity': '2'}, {'price': '102', 'quantity': '3'}],
    'bid': [{'price': '101', 'quantity': '4'}]}}
NOBITEX_DEPTH = {'status': 'ok', 'lastUpdate': 1657620166710,
                 'lastTradePrice': '6423000000',
                 'asks': [['1010000000', '2']], 'bids': [['1000000000', '3']]}
BITUNIX_PAIRS = {'code': '0', 'msg': 'Success', 'success': True, 'data': [
    {'id': 'BTCUSDT', 'base': 'BTC', 'quote': 'USDT', 'basePrecision': '6',
     'quotePrecision': '2', 'precisions': ['2', '4'], 'isOpen': '1'},
    {'id': 'ethusdt', 'base': 'ETH', 'quote': 'USDT', 'precisions': ['2'],
     'isOpen': '1'},
    {'id': 'BTCUSDC', 'base': 'BTC', 'quote': 'USDC', 'isOpen': '1'},
    {'id': 'OLDUSDT', 'base': 'OLD', 'quote': 'USDT', 'isOpen': '0'}]}
BITUNIX_DEPTH = {'code': '0', 'msg': 'Success', 'success': True, 'data': {
    'asks': [{'price': '57001', 'volume': '.5'}, {'price': '57002', 'volume': '1'}],
    'bids': [{'price': '57000', 'volume': '2'}], 'ts': '1732178884994'}}


def test_nobitex_irt_prices_are_rial_and_usdt_is_not_divided():
    iran = ADAPTERS['nobitex'].parse_markets({'status': 'ok', 'stats': {
        'btc-rls': {'bestSell': '600000', 'bestBuy': '599000'},
        'btc-usdt': {'bestSell': '57001', 'bestBuy': '57000'}}})
    toman_book = ADAPTERS['nobitex'].parse_depth(
        NOBITEX_DEPTH, iran[('BTC', 'toman')], 1657620166.8)
    assert toman_book.bids[0][0] == 100000000.0   # 1,000,000,000 rial -> 100,000,000 toman
    usdt_book = ADAPTERS['nobitex'].parse_depth(
        {'status': 'ok', 'asks': [['57001', '1']], 'bids': [['57000', '2']],
         'lastUpdate': int(time.time() * 1000)},
        iran[('BTC', 'USDT')], time.time())
    assert usdt_book.asks[0][0] == 57001.0        # USDT-quoted books are never divided
    assert usdt_book.timestamp_reliable


def test_nobitex_nullable_timestamp_and_stale_rule():
    nobitex = ADAPTERS['nobitex']
    market = nobitex.parse_markets({'status': 'ok', 'stats': {'btc-rls': {}}})[('BTC', 'toman')]
    now = 10_000.0
    # A null lastUpdate is documented as nullable: use receipt time and mark it unreliable.
    book = nobitex.parse_depth({'status': 'ok', 'lastUpdate': None,
                                'asks': [['1000', '1']], 'bids': [['900', '1']]}, market, now)
    assert book.timestamp == now and book.timestamp_reliable is False
    # A reliable but old exchange timestamp is rejected...
    with pytest.raises(ValidationError) as error:
        nobitex.parse_depth({'status': 'ok', 'lastUpdate': int((now - 500) * 1000),
                             'asks': [['1000', '1']], 'bids': [['900', '1']]}, market, now)
    assert error.value.code == 'stale_timestamp'
    # ...unless the laptop clock is known to be skewed: then staleness is not judged locally.
    skewed = nobitex.parse_depth({'status': 'ok', 'lastUpdate': int((now - 500) * 1000),
                                  'asks': [['1000', '1']], 'bids': [['900', '1']]},
                                 market, now, 120, clock_skew=300)
    assert skewed.timestamp == now - 500 and skewed.timestamp_reliable


def test_nobitex_ten_x_unit_mismatch_is_detected():
    nobitex = ADAPTERS['nobitex']
    market = nobitex.parse_markets({'status': 'ok', 'stats': {'btc-rls': {}}})[('BTC', 'toman')]
    with pytest.raises(ValidationError) as error:
        nobitex.parse_depth({'status': 'ok', 'lastUpdate': None,
                             'lastTradePrice': '642300000',
                             'asks': [['6423000000', '1']], 'bids': [['6422000000', '1']]},
                            market, time.time())
    assert error.value.code == 'unexpected_unit'


def test_nobitex_documented_best_only_fallback():
    nobitex = ADAPTERS['nobitex']
    market = nobitex.parse_markets({'status': 'ok', 'stats': {'btc-rls': {}}})[('BTC', 'toman')]
    book = nobitex.parse_depth({'status': 'ok', 'stats': {'btc-rls': {
        'bestSell': '1100', 'bestBuy': '1000'}}}, market, 50.0)
    assert book.quality == 'best_only' and book.best_ask == 110.0 and book.best_bid == 100.0
    assert book.source == 'market_stats_best'
    endpoints = [endpoint.id for endpoint in nobitex.depth_endpoints(market)]
    assert endpoints[0] == 'orderbook_v3' and 'market_stats_best' in endpoints


def test_wallex_depth_and_markets_fixture():
    wallex = ADAPTERS['wallex']
    markets = wallex.parse_markets({'success': True, 'result': {'symbols': {
        'BTCTMN': {'baseAsset': 'btc', 'quoteAsset': 'TMN', 'symbol': 'BTCTMN'},
        'BTCUSDT': {'baseAsset': 'BTC', 'quoteAsset': 'USDT'},
        'EURTMN': {'baseAsset': 'EUR', 'quoteAsset': 'TMN'}}}})
    assert set(markets) == {('BTC', 'toman'), ('BTC', 'USDT'), ('EUR', 'toman')}
    book = wallex.parse_depth(WALLEX_DEPTH, markets[('BTC', 'toman')], 99.0)
    assert book.asks == [(101.5, 2), (102, 3)] and book.bids == [(101, 4)]
    assert book.timestamp_reliable is False    # documented payload has no exchange timestamp
    with pytest.raises(ValidationError) as error:
        wallex.parse_depth({'success': True, 'result': {'ask': [{'price': '1', 'quantity': '1'}],
                                                        'bid': [{'price': '2', 'quantity': '1'}]}},
                           markets[('BTC', 'toman')], 99.0)
    assert error.value.code == 'crossed_book'


def test_bitunix_markets_tickers_and_depth_fixtures():
    bitunix = adapter('bitunix')
    markets = bitunix.parse_markets(BITUNIX_PAIRS)
    assert set(markets) == {('BTC', 'USDT'), ('ETH', 'USDT')}   # USDC and closed pairs dropped
    assert markets[('BTC', 'USDT')].symbol == 'BTCUSDT'
    assert markets[('ETH', 'USDT')].symbol == 'ETHUSDT'   # normalized for requests
    ticker = bitunix.parse_ticker({'code': '0', 'msg': 'Success', 'data': '57000.5'},
                                  markets[('BTC', 'USDT')])
    assert ticker.last == 57000.5 and ticker.ask is None and ticker.bid is None
    assert ticker.source == 'last_price'
    book = bitunix.parse_depth(BITUNIX_DEPTH, markets[('BTC', 'USDT')], 1732178885.0)
    assert book.asks[0] == (57001.0, .5) and book.bids[0] == (57000.0, 2)
    assert book.timestamp_reliable and book.timestamp == pytest.approx(1732178884.994)


def test_bitunix_has_no_bulk_ticker_endpoint_so_it_never_fakes_one():
    bitunix = adapter('bitunix')
    assert bitunix.supports_bulk_tickers is False
    assert bitunix.bulk_ticker_endpoints() == []
    markets = bitunix.parse_markets(BITUNIX_PAIRS)
    endpoints = bitunix.ticker_endpoints(markets[('BTC', 'USDT')])
    assert [endpoint.id for endpoint in endpoints] == ['last_price']
    assert 'BTCUSDT' in endpoints[0].url


def test_bitunix_rejects_unsuccessful_and_stale_payloads():
    bitunix = adapter('bitunix')
    markets = bitunix.parse_markets(BITUNIX_PAIRS)
    with pytest.raises(ValidationError) as error:
        bitunix.parse_depth({'code': '10001', 'msg': 'invalid symbol'}, markets[('BTC', 'USDT')],
                            time.time())
    assert error.value.code == 'unsuccessful_status'
    old = {'code': '0', 'data': {'asks': [{'price': '1', 'volume': '1'}],
                                 'bids': [{'price': '0.5', 'volume': '1'}],
                                 'ts': str(int((time.time() - 900) * 1000))}}
    with pytest.raises(ValidationError) as error:
        bitunix.parse_depth(old, markets[('BTC', 'USDT')], time.time())
    assert error.value.code == 'stale_timestamp'


def test_symbol_matching_across_three_exchanges():
    wallex = ADAPTERS['wallex'].parse_markets({'success': True, 'result': {'symbols': {
        'BTCTMN': {'baseAsset': 'BTC', 'quoteAsset': 'TMN'},
        'ETHUSDT': {'baseAsset': 'ETH', 'quoteAsset': 'USDT'},
        '1000SHIBTMN': {'baseAsset': '1000SHIB', 'quoteAsset': 'TMN'},
        'USDTTMN': {'baseAsset': 'USDT', 'quoteAsset': 'TMN'}}}})
    nobitex = ADAPTERS['nobitex'].parse_markets({'status': 'ok', 'stats': {
        'btc-rls': {}, 'eth-usdt': {}, 'usdt-rls': {}, 'luna-rls': {}}})
    bitunix = ADAPTERS['bitunix'].parse_markets({'code': '0', 'data': [
        {'base': 'BTC', 'quote': 'USDT', 'isOpen': '1'},
        {'base': 'ETH', 'quote': 'USDT', 'isOpen': '1'},
        {'base': '1000SHIB', 'quote': 'USDT', 'isOpen': '1'},
        {'base': 'LUNA', 'quote': 'USDT', 'isOpen': '1'},
        {'base': 'USDTTMNONLY', 'quote': 'USDT', 'isOpen': '1'}]})
    iran = {'wallex': wallex, 'nobitex': nobitex}
    routes, excluded = discover(iran, bitunix)
    kinds = {(route.kind, route.coin, route.iran) for route in routes}
    assert ('A', 'BTC', 'wallex') in kinds and ('B', 'BTC', 'wallex') in kinds
    assert ('A', 'BTC', 'nobitex') in kinds and ('B', 'BTC', 'nobitex') in kinds
    assert ('direct_iran_to_bitunix', 'ETH', 'wallex') in kinds
    assert ('direct_bitunix_to_iran', 'ETH', 'nobitex') in kinds
    assert {row['coin'] for row in excluded} >= {'1000SHIB', 'LUNA'}
    assert all('USDTTMNONLY' not in route.coin for route in routes)
    # No route may be duplicated.
    assert len({route.key for route in routes}) == len(routes)
    route = next(r for r in routes if r.kind == 'A' and r.coin == 'BTC' and r.iran == 'wallex')
    assert route.books() == [('bitunix', 'BTC', 'USDT'), ('wallex', 'BTC', 'toman'),
                             ('wallex', 'USDT', 'toman')]


def test_iran_market_without_usdt_toman_book_is_excluded():
    wallex = ADAPTERS['wallex'].parse_markets({'success': True, 'result': {'symbols': {
        'BTCTMN': {'baseAsset': 'BTC', 'quoteAsset': 'TMN'}}}})
    bitunix = ADAPTERS['bitunix'].parse_markets({'code': '0', 'data': [
        {'base': 'BTC', 'quote': 'USDT', 'isOpen': '1'}]})
    routes, excluded = discover({'wallex': wallex}, bitunix)
    assert routes == []
    assert any('تتر/تومان' in row['reason'] for row in excluded)
