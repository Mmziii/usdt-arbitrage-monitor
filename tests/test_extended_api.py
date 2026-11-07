"""Isolated API round trips, using public-book fixtures only."""
import time
import pytest
from fastapi.testclient import TestClient
from app import main
from app.storage import Storage
from app.scanner import Scanner
from app.opportunities import OpportunityTracker
from app.fetchers import Book


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = Storage(str(tmp_path/'extended.db'))
    scanner = Scanner(store)
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'scanner', scanner)
    monkeypatch.setattr(main, 'tracker', OpportunityTracker(store))
    monkeypatch.setattr(main, 'settings', main.Settings())
    # No lifespan: no outbound calls or background observations.
    return TestClient(main.app)


def seed(scanner):
    now = time.time()
    scanner.markets = [dict(coin='BTC',quote='USDT',wallex='BTCUSDT',nobitex='BTCUSDT')]
    scanner.tickers = {('BTC','USDT'): dict(wallex_ask=10,wallex_bid=9.9,nobitex_ask=11.2,nobitex_bid=11,timestamp=now)}
    scanner.depth = {('BTC','USDT'): dict(wallex=Book([(10,100)],[(9.9,100)],now),nobitex=Book([(11.2,100)],[(11,100)],now),timestamp=now)}


def test_prefunded_no_network_needed_modes_tiers_balances_and_export(client):
    seed(main.scanner)
    cfg = client.get('/api/scanner/settings').json()
    cfg.update(trading_mode='prefunded', balances={'wallex': {'USDT': 50}, 'nobitex': {'BTC': 2}})
    assert client.put('/api/scanner/settings',json=cfg).status_code == 200
    s = client.get('/api/settings').json()
    s['fee_tiers'] = [dict(exchange='wallex',quote='USDT',name='personal',threshold=10,maker=0,taker=0)]
    s['current_tiers'] = {'wallex:USDT': 'personal'}
    assert client.put('/api/settings',json=s).status_code == 200
    a,b = client.get('/api/scanner').json()['rows']
    assert a['status'] == b['status'] == 'ok'
    assert a['taker']['capital'] == 20
    assert a['taker']['coin_after_buy'] == a['taker']['coin_after_withdrawal'] == 2
    assert a['fee_sources']['wallex'] == 'tier:personal'
    assert a['taker']['rebalancing']['incomplete']
    assert a['taker']['breakeven_capital'] == 0
    cfg['row_modes'] = {a['row_key']: 'transfer'}
    assert client.put('/api/scanner/settings',json=cfg).status_code == 200
    a,b = client.get('/api/scanner').json()['rows']
    assert a['status'] == 'network unknown' and 'taker' not in a
    assert b['status'] == 'ok'
    for fmt in ('csv','json'):
        text = client.get('/api/tiers/export',params={'format': fmt}).text
        assert client.post('/api/tiers/import',json={'format':fmt,'text':text}).status_code == 200
    s['fee_tiers'] *= 2
    assert client.put('/api/settings',json=s).status_code == 422
    assert client.get('/overview').status_code == 200
    assert client.get('/static/Vazirmatn-Regular.woff2').status_code == 200


def test_stats_read_only_and_retention(client):
    seed(main.scanner)
    cfg = main.scanner.config(); cfg['trading_mode']='prefunded'
    main.scanner.store.save_scanner_settings(cfg)
    # Merely reading a snapshot must never count as an observation.
    client.get('/api/scanner'); client.get('/api/scanner')
    assert client.get('/api/opportunities?mode=prefunded').json()['overall']['count'] == 0
    main.tracker.cycle(main.scanner.rows(main.settings),time.time())
    assert client.get('/api/opportunities?mode=prefunded').json()['overall']['count'] == 1
    assert 'capital_at_peak' in client.get('/api/opportunities.csv').text
    main.tracker.prune(time.time()+1)
    assert main.tracker.rows() == []


@pytest.mark.parametrize('changes', [dict(safety_margin=-1), dict(coin_margins={'BTC':-1}), dict(transfer_minutes={'default':-1}),dict(balances={'wallex':{'BTC':-1}}),dict(close_confirmations=0),dict(rebalance_trades=0)])
def test_invalid_policy_rejected(client, changes):
    cfg = client.get('/api/scanner/settings').json(); cfg.update(changes)
    assert client.put('/api/scanner/settings',json=cfg).status_code == 422


def test_capital_analysis_survives_insufficient_selected_capital(client):
    seed(main.scanner)
    cfg = main.scanner.config(); cfg.update(trading_mode='prefunded',capital_usdt=100000)
    main.scanner.store.save_scanner_settings(cfg)
    row = client.get('/api/scanner').json()['rows'][0]
    assert row['status'] == 'insufficient depth'
    assert 'taker' not in row
    assert row['capital_analysis']['taker']['profit_maximizing_capital'] is not None


def test_negative_raw_spread_active_market_is_revisited(client, monkeypatch):
    import asyncio
    from app import scanner as scanner_module
    scanner = main.scanner
    seed(scanner)
    scanner.market_time = time.time()
    scanner.tracked_markets = {('BTC','USDT')}
    scanner.depth = {}  # Simulate restart: only the persisted active event is known.
    quotes = {('BTC','USDT'): dict(wallex_ask=10,wallex_bid=9,nobitex_ask=12,nobitex_bid=8,timestamp=time.time())}
    monkeypatch.setattr(scanner_module, 'quotes', lambda *args: quotes)
    async def request(*args):
        return {}
    called=[]
    async def fetch(*args):
        called.append(args[1:])
    monkeypatch.setattr(scanner,'request',request)
    monkeypatch.setattr(scanner,'fetch_depth',fetch)
    asyncio.run(scanner.scan(None))
    assert called == [('BTC','USDT')]
