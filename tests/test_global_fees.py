import time
import pytest
from app.main import Settings
from app.scanner import Scanner
from app.storage import Storage
from app.fetchers import Book
from app.fees import resolve


def test_defaults_and_old_settings_are_preserved(tmp_path):
    db = Storage(str(tmp_path / 'settings.db'))
    legacy = {'wallex': {'maker': 1, 'taker': 2, 'withdrawal': .8}, 'nobitex': {'maker': 3, 'taker': 4, 'withdrawal': .7}}
    db.save_settings(legacy)
    settings = Settings(**db.settings())
    assert settings.trading_fees('wallex', 'toman')['maker'] == 1
    assert settings.trading_fees('nobitex', 'toman')['taker'] == 4
    assert settings.trading_fees('wallex', 'USDT') == {'maker': .25, 'taker': .3}
    assert settings.trading_fees('nobitex', 'USDT') == {'maker': .25, 'taker': .25}
    scanner = Scanner(db)
    db.save_scanner_settings({'trading_overrides': {'wallex': {'BTC': {'taker': 99}}}})
    assert 'trading_overrides' not in scanner.config()


def test_withdrawal_only_fee_unknown_and_minimum_blocks():
    rows = [dict(exchange=e, coin='BTC', network='BTC', supported=True, withdrawal=0, minimum=0) for e in ('wallex', 'nobitex')]
    assert resolve(rows, 'BTC', 'wallex')['status'] == 'ok'
    rows[0]['withdrawal'] = None
    assert resolve(rows, 'BTC', 'wallex')['status'] == 'fee unknown'
    rows[0]['withdrawal'], rows[0]['minimum'] = 0, None
    assert resolve(rows, 'BTC', 'wallex')['status'] == 'minimum unknown'
    rows[1]['supported'] = False
    assert resolve(rows, 'BTC', 'wallex')['status'] == 'no common network'


def test_quote_specific_fees_both_directions_and_modes(tmp_path):
    s = Scanner(Storage(str(tmp_path / 'scan.db'))); now = time.time()
    settings = Settings(wallex={'maker': 1, 'taker': 2, 'withdrawal': .8}, nobitex={'maker': 3, 'taker': 4, 'withdrawal': .7}, wallex_usdt={'maker': 5, 'taker': 6}, nobitex_usdt={'maker': 7, 'taker': 8})
    s.store.replace_fees([dict(exchange=e,coin='BTC',network='BTC',withdrawal=1,minimum=0,supported=True) for e in ('wallex','nobitex')])
    s.store.save_scanner_settings({'capital_toman': 100000, 'capital_usdt': 1000, 'trading_overrides': {'wallex': {'BTC': {'taker': 99}}}})
    s.markets = [dict(coin='BTC',quote=q,wallex='BTC',nobitex='BTC') for q in ('toman','USDT')]
    # 100 units bought in either market; taker toman: (100*.98-1)*1100*.96=102432.
    # USDT: (100*.94-1)*11*.92=941.16.
    for quote, scale in [('toman',1000),('USDT',10)]:
        s.tickers['BTC',quote] = dict(wallex_ask=scale,wallex_bid=scale, nobitex_ask=scale*1.1,nobitex_bid=scale*1.1,timestamp=now)
        s.depth['BTC',quote] = dict(wallex=Book([(scale,1000)],[(scale,1000)],now), nobitex=Book([(scale*1.1,1000)],[(scale*1.1,1000)],now), timestamp=now)
    rows = s.rows(settings)
    assert len(rows) == 4 and all(r['status']=='ok' and 'maker' in r and 'taker' in r for r in rows)
    toman = next(r for r in rows if r['source']=='wallex' and r['quote']=='toman')
    usdt = next(r for r in rows if r['source']=='wallex' and r['quote']=='USDT')
    assert toman['taker']['final_quote'] == pytest.approx(102432)
    assert usdt['taker']['final_quote'] == pytest.approx(941.16)
    assert toman['maker']['final_quote'] == pytest.approx((100*.99-1)*1100*.97)
    assert usdt['maker']['final_quote'] == pytest.approx((100*.95-1)*11*.93)
    reverse = next(r for r in rows if r['source']=='nobitex' and r['quote']=='USDT')
    assert reverse['taker']['final_quote'] == pytest.approx((1000/11*.92-1)*10*.94)


def test_api_saves_global_fees_and_drops_legacy_overrides(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    db = Storage(str(tmp_path/'settings.db'))
    scanner = Scanner(db)
    db.save_scanner_settings({'trading_overrides': {'wallex': {'BTC': {'maker': 90}}}})
    monkeypatch.setattr(main, 'store', db)
    monkeypatch.setattr(main, 'scanner', scanner)
    monkeypatch.setattr(main, 'settings', Settings())
    client = TestClient(main.app)
    cfg = client.get('/api/settings').json()
    cfg['wallex_usdt']['maker'] = 1.2
    cfg['nobitex']['taker'] = 2.3
    assert client.put('/api/settings', json=cfg).status_code == 200
    restored = Settings(**db.settings())
    assert restored.wallex_usdt.maker == 1.2 and restored.nobitex.taker == 2.3
    cfg['wallex_usdt']['maker'] = 100
    assert client.put('/api/settings', json=cfg).status_code == 422
    scan_cfg = client.get('/api/scanner/settings').json()
    assert 'trading_overrides' not in scan_cfg
    assert client.put('/api/scanner/settings', json=scan_cfg).status_code == 200
    assert 'trading_overrides' not in db.scanner_settings()


def test_scanner_gross_only_for_missing_source_withdrawal_and_minimum(tmp_path):
    s = Scanner(Storage(str(tmp_path/'missing.db'))); now = time.time()
    s.markets = [dict(coin='BTC', quote='toman', wallex='BTCTMN', nobitex='BTCIRT')]
    s.tickers = {('BTC','toman'): dict(wallex_ask=1000, wallex_bid=990, nobitex_ask=1110, nobitex_bid=1100, timestamp=now), ('USDT','toman'): dict(wallex_bid=50000, nobitex_bid=52000, timestamp=now)}
    s.depth = {('BTC','toman'): dict(wallex=Book([(1000,20000)],[(990,20000)],now), nobitex=Book([(1110,20000)],[(1100,20000)],now), timestamp=now)}
    fee_rows = [dict(exchange='wallex',coin='BTC',network='BTC',withdrawal=None,minimum=1,supported=True),dict(exchange='nobitex',coin='BTC',network='BTC',withdrawal=1,minimum=1,supported=True)]
    s.store.replace_fees(fee_rows)
    a,b = s.rows(Settings())
    assert a['status'] == 'fee unknown' and a['gross_spread'] == pytest.approx(10)
    assert 'maker' not in a and 'taker' not in a
    assert b['status'] == 'ok' and b['rate'] == 51000
    assert b['taker']['profit'] / b['rate'] == pytest.approx((b['taker']['profit']) / 51000)
    fee_rows[0]['withdrawal'],fee_rows[0]['minimum'] = 1,None
    s.store.replace_fees(fee_rows)
    assert s.rows(Settings())[0]['status'] == 'minimum unknown'
    assert 'taker' not in s.rows(Settings())[0]
