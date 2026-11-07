"""Every HTTP route: valid, empty and malformed input must answer without a 500.

The fixture keeps everything local (temp SQLite, fake gateway) so no exchange is contacted.
"""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.hub import Hub
from app.net import HttpResult, Monitor
from app.scanner import Scanner
from app.storage import Storage
from app.opportunities import OpportunityTracker


def persian(text):
    return any('\u0600' <= char <= '\u06ff' for char in text)


def detail_text(response):
    body = response.json()
    detail = body.get('detail', body)
    return detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)


class FakeGateway:
    def __init__(self):
        self.monitor = Monitor()

    def configure(self, **kwargs):
        pass

    async def fetch(self, *args, **kwargs):
        return HttpResult(ok=False, reason='network', detail='sandbox has no exchange access')

    def make_client(self, *args, **kwargs):
        class Client:
            async def __aenter__(self_inner):
                return object()

            async def __aexit__(self_inner, *exc):
                return False
        return Client()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = Storage(str(tmp_path / 'sweep.db'))
    store.init_scanner()
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'scanner', Scanner(store))
    monkeypatch.setattr(main, 'tracker', OpportunityTracker(store))
    monkeypatch.setattr(main, 'settings', main.Settings())
    gateway = FakeGateway()
    monkeypatch.setattr(main, 'gateway', gateway)
    monkeypatch.setattr(main, 'hub', Hub(store, gateway, lambda: main.settings))
    monkeypatch.setattr(main, 'monitor', gateway.monitor)

    async def failing_scan(*args, **kwargs):
        raise ValueError('sandbox has no exchange access')

    monkeypatch.setattr(main.scanner, 'scan', failing_scan)

    async def failing_depth(*args, **kwargs):
        raise ValueError('sandbox has no exchange access')

    monkeypatch.setattr(main.scanner, 'fetch_depth', failing_depth)
    # No lifespan: the background loops are not started.
    return TestClient(main.app)


GET_ROUTES = ['/', '/classic', '/guide', '/settings', '/overview',
              '/api/settings', '/api/snapshot', '/api/history', '/api/history.csv',
              '/api/scanner/settings', '/api/scanner/fees', '/api/scanner',
              '/api/scanner/history', '/api/scanner/history.csv',
              '/api/tiers/export', '/api/opportunities', '/api/opportunities.csv',
              '/api/overview', '/api/diagnostics', '/api/ui', '/api/backup',
              '/api/simulations', '/api/journal', '/api/journal.csv', '/api/wizard']


@pytest.mark.parametrize('path', GET_ROUTES)
def test_get_routes_never_return_500(client, path):
    response = client.get(path)
    assert response.status_code < 500, (path, response.status_code, response.text[:300])


@pytest.mark.parametrize('path', ['/api/plan?key=A:BTC:wallex',
                                  '/api/overview/detail?key=A:BTC:wallex',
                                  '/api/simulations/999/settle'])
def test_async_routes_without_market_data_answer_cleanly(client, path):
    response = client.post(path) if 'settle' in path else client.get(path)
    assert response.status_code < 500, (path, response.text[:300])


def test_missing_and_invalid_query_parameters(client):
    assert client.get('/api/amount').status_code == 422
    assert client.get('/api/plan').status_code == 422
    assert client.get('/api/overview/detail').status_code == 422
    assert client.get('/api/snapshot', params={'capital': 'abc'}).status_code == 422
    assert client.get('/api/snapshot', params={'capital': -5}).status_code == 400
    assert client.get('/api/tiers/export', params={'format': 'xml'}).status_code == 422
    assert client.get('/api/opportunities', params={'mode': 'bad'}).status_code == 422
    assert client.get('/api/scanner/detail/BTC/EUR').status_code == 422


def test_amount_endpoint_parses_and_explains(client):
    ok = client.get('/api/amount', params={'text': '۵۰ میلیون تومان'}).json()
    assert ok['ok'] and ok['value'] == 50_000_000 and ok['currency'] == 'toman'
    bad = client.get('/api/amount', params={'text': 'خیلی زیاد'}).json()
    assert bad['ok'] is False and persian(bad['error'])
    empty = client.get('/api/amount', params={'text': ''}).json()
    assert empty['ok'] is False and persian(empty['error'])


def test_settings_validation_is_persian(client):
    payload = client.get('/api/settings').json()
    broken = {**payload, 'wallex': {**payload['wallex'], 'taker': -1}}
    response = client.put('/api/settings', json=broken)
    assert response.status_code == 422
    assert persian(detail_text(response))
    proxy = client.put('/api/settings', json={**payload, 'proxy_url': 'not-a-url'})
    assert proxy.status_code == 422 and persian(detail_text(proxy))
    assert client.put('/api/settings', json=payload).status_code == 200


def test_manual_price_endpoint(client):
    assert client.put('/api/manual/tether', json={'ask': 2, 'bid': 1}).status_code == 400
    bad = client.put('/api/manual/wallex', json={'ask': 1, 'bid': 2})
    assert bad.status_code == 400 and persian(detail_text(bad))
    assert client.put('/api/manual/wallex', json={'ask': 2, 'bid': 1}).status_code == 200
    zero = client.put('/api/manual/wallex', json={'ask': 0, 'bid': 0})
    assert zero.status_code == 422


def test_scanner_settings_and_fees_validation(client):
    cfg = client.get('/api/scanner/settings').json()
    assert client.put('/api/scanner/settings', json={**cfg, 'interval': 1}).status_code == 422
    assert client.put('/api/scanner/settings', json={**cfg, 'safety_margin': -1}).status_code == 422
    assert client.put('/api/scanner/settings', json={**cfg, 'hot_rows': 9999}).status_code == 422
    assert client.put('/api/scanner/settings', json=cfg).status_code == 200

    row = {'exchange': 'wallex', 'coin': 'btc', 'network': 'trc20', 'withdrawal': 1,
           'minimum': 2, 'supported': True}
    saved = client.put('/api/scanner/fees', json=[row])
    assert saved.status_code == 200
    assert saved.json()[0]['coin'] == 'BTC' and saved.json()[0]['network'] == 'TRC20'
    duplicate = client.put('/api/scanner/fees', json=[row, row])
    assert duplicate.status_code == 400 and persian(detail_text(duplicate))
    bad_coin = client.put('/api/scanner/fees', json=[{**row, 'coin': '?'}])
    assert bad_coin.status_code == 422 and persian(detail_text(bad_coin))
    loose_bool = client.put('/api/scanner/fees', json=[{**row, 'supported': 'yes'}])
    assert loose_bool.status_code == 422 and persian(detail_text(loose_bool))
    bad_network = client.put('/api/scanner/fees', json=[{**row, 'network': 'TRC 20'}])
    assert bad_network.status_code == 422
    preview = client.post('/api/scanner/fees/preview', json={'text': 'TRX, TRC20, wallex, 1'})
    assert preview.status_code == 200
    assert client.post('/api/scanner/fees/preview', json={}).status_code == 422


def test_scan_endpoints_report_persian_errors(client):
    refresh = client.post('/api/scanner/refresh')
    assert refresh.status_code == 503 and persian(detail_text(refresh))
    detail = client.get('/api/scanner/detail/BTC/USDT')
    assert detail.status_code == 503 and persian(detail_text(detail))
    overview_refresh = client.post('/api/overview/refresh')
    assert overview_refresh.status_code in (200, 503)


def test_diagnostics_payload_and_test_route(client):
    payload = client.get('/api/diagnostics').json()
    assert payload['exchanges'] and payload['reason_catalog']
    assert payload['extra']['user_agent']
    result = client.post('/api/diagnostics/test').json()
    assert set(result) == {'results', 'ok'}
    assert result['ok'] is False
    for item in result['results']:
        assert item['steps'] and persian(item['steps'][0]['message'])
    assert client.post('/api/diagnostics/test', params={'exchange': 'nope'}).status_code == 422


def test_connection_settings(client):
    assert client.put('/api/connection', json={'user_agent': 'x'}).status_code == 422
    good = client.put('/api/connection', json={'user_agent': 'TraderBot/Test',
                                               'proxy_url': None,
                                               'clock_skew_warning_seconds': 30})
    assert good.status_code == 200
    assert good.json()['user_agent'] == 'TraderBot/Test'
    assert client.put('/api/connection',
                      json={'proxy_url': 'ftp://nope'}).status_code == 422


def test_overview_controls(client):
    assert client.post('/api/overview/pause', json={'paused': True}).status_code == 200
    loose = client.post('/api/overview/pause', json={'paused': 'yes'})
    assert loose.status_code == 422 and persian(detail_text(loose))
    assert client.post('/api/overview/pause', json={'paused': 'true'}).status_code == 422
    assert client.post('/api/overview/visible', json={'keys': ['a']}).status_code == 200
    too_many = client.post('/api/overview/visible', json={'keys': ['k'] * 201})
    assert too_many.status_code == 422
    assert client.post('/api/overview/visible', json={'keys': [1, 2]}).status_code == 422
    assert client.get('/api/overview/detail', params={'key': 'nope'}).status_code == 404


def test_tiers_import_validation(client):
    assert client.post('/api/tiers/import', json={'text': '[', 'format': 'json'}).status_code == 400
    assert client.post('/api/tiers/import', json={'text': [], 'format': 'json'}).status_code == 422
    assert client.post('/api/tiers/import', json={'text': '[]', 'format': 'json'}).status_code == 200
    bad_row = [{'exchange': 'tether', 'quote': 'toman', 'name': 'x', 'threshold': 0,
                'maker': 0, 'taker': 0}]
    response = client.post('/api/tiers/import',
                           json={'text': json.dumps(bad_row), 'format': 'json'})
    assert response.status_code == 400 and persian(detail_text(response))


def test_backup_and_restore(client):
    backup = client.get('/api/backup')
    assert backup.status_code == 200
    payload = backup.json()
    assert payload['app'] == 'usdt-arbitrage-monitor' and payload['version'] == 2
    assert client.post('/api/backup/restore', json={'app': 'tether'}).status_code == 400
    assert client.post('/api/backup/restore', json={}).status_code == 400
    broken = {**payload, 'settings': {'wallex': {'taker': -5}}}
    response = client.post('/api/backup/restore', json=broken)
    assert response.status_code in (400, 422) and persian(detail_text(response))
    duplicate = {**payload, 'fees': [payload['fees'][0]] * 2 if payload['fees'] else []}
    if duplicate['fees']:
        assert client.post('/api/backup/restore', json=duplicate).status_code == 422
    assert client.post('/api/backup/restore', json=payload).status_code == 200


def test_simulation_and_journal_validation(client):
    assert client.post('/api/simulations', json={}).status_code == 422
    bad_key = client.post('/api/simulations', json={'key': 'A:BTC:wallex'})
    assert bad_key.status_code == 404 and persian(detail_text(bad_key))
    short_delay = client.post('/api/simulations',
                              json={'key': 'A:BTC:wallex', 'delay_seconds': 1})
    assert short_delay.status_code == 422
    assert client.post('/api/simulations/abc/settle').status_code == 422
    assert client.post('/api/simulations/999/settle').status_code == 404
    assert client.delete('/api/simulations/999').status_code == 200

    entry = {'date': '2025-03-01', 'coin': 'btc', 'route': 'A', 'mode': 'transfer',
             'capital': 100, 'final_amount': 104}
    created = client.post('/api/journal', json=entry)
    assert created.status_code == 200 and created.json()['rows'][0]['coin'] == 'BTC'
    for change in ({'date': '2025/03/01'}, {'date': '2025-13-01'}, {'coin': '??'},
                   {'route': 'Z'}, {'mode': 'x'}, {'capital': 0}):
        response = client.post('/api/journal', json={**entry, **change})
        assert response.status_code == 400, change
        assert persian(detail_text(response)), change
    short_coin = client.post('/api/journal', json={**entry, 'coin': '?'})
    assert short_coin.status_code == 422 and persian(detail_text(short_coin))
    assert client.delete('/api/journal/999').status_code == 200
    csv = client.get('/api/journal.csv')
    assert csv.status_code == 200 and csv.text.startswith('\ufeff')


def test_unknown_routes_are_404(client):
    assert client.get('/api/nope').status_code == 404
    assert client.post('/api/overview/pause').status_code == 422


def test_concurrent_reads_and_writes_do_not_lock_the_database(tmp_path, monkeypatch):
    store = Storage(str(tmp_path / 'lock.db'))
    monkeypatch.setattr(main, 'store', store)
    client = TestClient(main.app)
    errors = []

    def writer(index):
        try:
            for step in range(20):
                store.save_ui_state({'pins': ['BTC']})
                store.add_journal({'date': '2025-03-01', 'coin': 'BTC', 'route': 'A',
                                   'mode': 'transfer', 'capital': 1.0,
                                   'final_amount': 1.0, 'profit': 0.0, 'fees': '',
                                   'note': str(index) + '-' + str(step), 'created': time.time()})
        except Exception as exc:                      # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for _ in range(40):
        assert client.get('/api/ui').status_code == 200
        assert client.get('/api/journal').status_code == 200
    for thread in threads:
        thread.join()
    assert not errors, errors[:3]
    assert len(client.get('/api/journal').json()['rows']) == 80
