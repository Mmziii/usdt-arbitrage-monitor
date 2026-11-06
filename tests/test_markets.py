import pytest
from app.markets import wallex_markets, nobitex_markets, intersection
from app.calculation import outcome


def test_intersection_and_symbol_review():
    w = wallex_markets({'success': True, 'result': {'symbols': {
        'BTCTMN': {'baseAsset': 'btc', 'quoteAsset': 'tmn'},
        'BTCUSDT': {'baseAsset': 'BTC', 'quoteAsset': 'USDT'},
        '1000SHIBTMN': {'baseAsset': '1000SHIB', 'quoteAsset': 'TMN'},
        'LUNATMN': {'baseAsset': 'LUNA', 'quoteAsset': 'TMN'}}}})
    n = nobitex_markets({'status': 'ok', 'stats': {'btc-rls': {}, 'btc-usdt': {}, '1000shib-rls': {}, 'luna-rls': {}, 'eth-rls': {}}})
    rows, excluded = intersection(w, n)
    assert {(x['coin'], x['quote']) for x in rows} == {('BTC', 'toman'), ('BTC', 'USDT')}
    assert {x['coin'] for x in excluded} == {'1000SHIB', 'LUNA'}
    assert rows[0]['nobitex'] in ('BTCIRT', 'BTCUSDT')


def test_different_coin_network_examples():
    # BTC via a hypothetical network: 1 BTC bought, .01 trading fee, .1 withdrawal, 110 sale, 2% sell.
    btc = outcome(100, [(100, 5)], [(110, 5)], .01, .02, .1, .5)
    assert btc['coin_after_withdrawal'] == pytest.approx(.89)
    assert btc['profit'] == pytest.approx(-4.058)
    # ETH on another network: 10 ETH bought, 0.1 fee, 0.2 withdrawal, 12 per coin.
    eth = outcome(100, [(10, 20)], [(12, 20)], .01, 0, .2, 1)
    assert eth['profit'] == pytest.approx(16.4)
    with pytest.raises(ValueError, match='حداقل'):
        outcome(100, [(100, 5)], [(110, 5)], 0, 0, .1, 2)


def test_fee_unknown_and_network_selection():
    from app.fees import resolve
    assert resolve([], 'BTC', 'wallex')['status'] == 'fee unknown'
    rows = [dict(exchange='wallex',coin='BTC',network='BTC',supported=True,withdrawal=None,minimum=None), dict(exchange='nobitex',coin='BTC',network='BTC',supported=True,withdrawal=.1,minimum=.2)]
    assert resolve(rows, 'BTC', 'wallex')['status'] == 'fee unknown'
    assert resolve(rows, 'BTC', 'nobitex')['status'] == 'ok'
    rows[1]['supported'] = False
    assert resolve(rows, 'BTC', 'wallex')['status'] == 'no common network'


def test_ticker_parsing_and_per_coin_failure():
    from app.scanner import quotes
    markets = [{'coin':'BTC','quote':'toman','wallex':'BTCTMN'}, {'coin':'ETH','quote':'USDT','wallex':'ETHUSDT'}]
    w = {'result': {'symbols': {'BTCTMN': {'stats': {'askPrice':'101', 'bidPrice':'100'}}, 'ETHUSDT': {'stats': {}}}}}
    n = {'stats': {'btc-rls': {'bestSell':'1010', 'bestBuy':'1000'}}}
    result = quotes(w, n, markets, 123)
    assert result['BTC','toman']['nobitex_bid'] == 100
    assert 'error' in result['ETH','USDT']
