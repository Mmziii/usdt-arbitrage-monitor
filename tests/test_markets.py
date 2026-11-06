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


def test_minimum_breakeven_is_feasible():
    from app.calculation import breakeven
    assert breakeven([(10, 100)], [(12, 100)], 0, 0, 1, minimum=20) == pytest.approx(200)


def test_scanner_profit_requires_known_fee(tmp_path):
    from app.scanner import Scanner
    from app.storage import Storage
    from app.fetchers import Book
    from app.main import Settings
    s = Scanner(Storage(str(tmp_path/'scanner.db')))
    s.markets = [{'coin':'BTC','quote':'USDT','wallex':'BTCUSDT','nobitex':'BTCUSDT'}]
    import time
    now = time.time()
    s.tickers = {('BTC','USDT'): dict(wallex_ask=100,wallex_bid=99,nobitex_ask=111,nobitex_bid=110,timestamp=now)}
    s.depth = {('BTC','USDT'): {'wallex':Book([(100,10)],[(99,10)],now), 'nobitex':Book([(111,10)],[(110,10)],now), 'timestamp':now}}
    rows = s.rows(Settings())
    assert all(r['status'] == 'fee unknown' and 'taker' not in r for r in rows)
    s.store.replace_fees([dict(exchange=e,coin='BTC',network='BTC',withdrawal=.01,minimum=.1,supported=True) for e in ('wallex','nobitex')])
    assert all(r['status'] == 'ok' and 'taker' in r for r in s.rows(Settings()))


def test_bulk_scan_and_depth_fixtures(tmp_path):
    import httpx, time
    from app.scanner import Scanner
    from app.storage import Storage
    now = time.time()
    w = {'success':True,'result':{'symbols':{'BTCUSDT':{'baseAsset':'BTC','quoteAsset':'USDT','stats':{'askPrice':'100','bidPrice':'99'}}}}}
    n = {'status':'ok','stats':{'btc-usdt':{'bestSell':'111','bestBuy':'110'}}}
    def respond(request):
        if request.url.path == '/v1/markets': return httpx.Response(200,json=w)
        if request.url.path == '/market/stats': return httpx.Response(200,json=n)
        if request.url.path == '/v1/depth': return httpx.Response(200,json={'success':True,'result':{'ask':[{'price':'100','quantity':'10'}],'bid':[{'price':'99','quantity':'10'}]}})
        return httpx.Response(200,json={'status':'ok','lastUpdate':now*1000,'asks':[['111','10']],'bids':[['110','10']]})
    scanner = Scanner(Storage(str(tmp_path/'test.db')))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await scanner.scan(client)
    import asyncio
    asyncio.run(run())
    assert len(scanner.markets) == 1
    assert scanner.depth['BTC','USDT']['nobitex'].bids == [(110,10)]
    assert scanner.store.scan_history('BTC', 'USDT')[0]['spread_a'] == pytest.approx(10)


def test_stale_depth_never_returns_profit(tmp_path):
    import time
    from app.scanner import Scanner
    from app.storage import Storage
    from app.fetchers import Book
    from app.main import Settings
    now = time.time(); s = Scanner(Storage(str(tmp_path/'stale.db')))
    s.markets = [{'coin':'BTC','quote':'USDT','wallex':'BTCUSDT','nobitex':'BTCUSDT'}]
    s.tickers = {('BTC','USDT'): dict(wallex_ask=100,wallex_bid=99,nobitex_ask=111,nobitex_bid=110,timestamp=now)}
    b = Book([(100,10)],[(99,10)],now-121)
    s.depth = {('BTC','USDT'): {'wallex':b,'nobitex':b,'timestamp':now-121}}
    s.store.replace_fees([dict(exchange=e,coin='BTC',network='BTC',withdrawal=.01,minimum=0,supported=True) for e in ('wallex','nobitex')])
    assert all(r['status']=='stale' and 'taker' not in r for r in s.rows(Settings()))


def test_prune_history_without_successful_scan(tmp_path):
    import time
    from app.storage import Storage
    store = Storage(str(tmp_path/'prune.db')); store.init_scanner()
    old = time.time() - 2*86400
    with store.connect() as db:
        db.execute('INSERT INTO scan_history VALUES (?,?,?,?,?,?,?,?,?)', (old,'BTC','USDT',1,1,1,1,0,0))
        db.execute('INSERT INTO history VALUES (?,?,?,?,?,?,?,?)', (old,1,1,1,1,0,0,'live'))
    store.prune(1)
    assert store.scan_history() == []
    assert store.history() == []
