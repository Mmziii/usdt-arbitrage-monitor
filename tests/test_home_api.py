"""Home, decision, receipt, gauge, fees and setup endpoints — all local."""
import time

import pytest

from app import main

from home_fixture import fee_rows, install, make

NOW = time.time()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    env = make(tmp_path)
    return install(env, monkeypatch)


def test_home_answers_the_one_question(client):
    data = client.get('/api/home').json()
    assert data['best'] is not None
    assert data['best']['key'] == 'A:BTC:wallex'
    assert data['best']['decision']['label'] in ('برو', 'صبر کن', 'نه', 'نامطمئن')
    assert data['best']['decision']['checks']
    assert data['best']['numbers']['net_pct'] is not None
    assert data['best']['receipt']['totals']['reconciled'] is True
    assert data['disclaimer'] and 'تضمین' in data['disclaimer']
    assert data['rows_count'] >= 1
    assert isinstance(data['fees']['coins'], list)


def test_home_never_opens_a_dialog_itself(client):
    """The server sends no 'open this on load' instruction; the page decides."""
    data = client.get('/api/home').json()
    assert 'open_dialog' not in data
    assert data['banner']['visible'] in (True, False)


def test_home_reports_a_negative_opportunity_without_pretending(tmp_path, monkeypatch):
    env = make(tmp_path)
    cfg = env.hub.config()
    cfg['other_costs_toman'] = 9_000_000        # a real cost that eats the whole spread
    env.store.save_scanner_settings(cfg)
    env.hub.invalidate()
    client = install(env, monkeypatch)
    data = client.get('/api/home').json()
    assert data['best']['decision']['verdict'] == 'no'
    assert data['empty'] is not None
    assert 'فرصت' in data['empty']['message']
    checks = {item['title']: item for item in data['best']['decision']['checks']}
    assert checks['هزینه‌های دیگر']['status'] == 'warn'


def test_a_route_without_fees_is_unsure_not_profitable(tmp_path, monkeypatch):
    env = make(tmp_path, with_fees=False)
    client = install(env, monkeypatch)
    data = client.get('/api/home').json()
    best = data['best']
    assert best['decision']['verdict'] == 'unsure'
    assert best['numbers']['net_pct'] is None
    assert data['fees']['missing_coins']


def test_stale_fees_are_asked_about_again(tmp_path, monkeypatch):
    env = make(tmp_path, fresh=False)
    client = install(env, monkeypatch)
    data = client.get('/api/home').json()
    assert data['fees']['stale_coins']
    assert 'بررسی' in data['fees']['text'] or 'قدیمی' in data['fees']['text']
    checks = {item['title']: item for item in data['best']['decision']['checks']}
    assert checks['کارمزدها']['status'] == 'warn'


def test_gauge_is_honest_until_twenty_four_hours_of_history(client, monkeypatch, tmp_path):
    env = main.hub
    assert client.get('/api/gauge').json()['ready'] is False
    rows = [{'key': 'A:BTC:wallex', 'net_pct': 1 + index / 10, 'coin': 'BTC', 'route': 'A'}
            for index in range(10)]
    for index in range(0, 30):
        env.store.record_best(time.time() - (29 - index) * 3600, rows)
    data = client.get('/api/gauge').json()
    assert data['ready'] is True
    assert data['percentile'] is not None
    assert data['days'] == 7


def test_decide_and_receipt_share_the_same_engine(client):
    key = 'A:BTC:wallex'
    decision = client.get('/api/decide', params={'key': key}).json()
    payload = client.get('/api/receipt', params={'key': key}).json()
    assert decision['decision']['verdict'] == payload['decision']['verdict']
    assert payload['receipt']['totals']['reconciled'] is True
    assert payload['text'].startswith('رسید سفر')
    assert payload['fees']


def test_receipt_csv_download(client):
    response = client.get('/api/receipt.csv', params={'key': 'A:BTC:wallex'})
    assert response.status_code == 200
    assert 'text/csv' in response.headers['content-type']
    assert 'attachment' in response.headers['content-disposition']


def test_unknown_key_is_a_persian_404(client):
    response = client.get('/api/receipt', params={'key': 'A:NOPE:wallex'})
    assert response.status_code == 404
    assert 'پیدا نشد' in response.json()['detail']


def test_setup_saves_exchanges_money_and_capital(client):
    response = client.put('/api/setup', json={
        'exchanges': ['wallex', 'bitunix'], 'money': 'coins_both',
        'capital': 50, 'capital_unit': 'USDT', 'notify': True, 'interval': 20,
        'complete': True})
    assert response.status_code == 200
    body = response.json()
    assert body['setup']['mode'] == 'prefunded'
    assert body['setup']['capital_usdt'] == 50
    assert body['wizard_done'] is True
    home = client.get('/api/home').json()
    assert home['best']['row']['trading_mode'] == 'prefunded'
    assert home['wizard_done'] is True


def test_capital_can_be_written_in_toman(client):
    client.put('/api/setup', json={'exchanges': ['wallex', 'bitunix'], 'money': 'toman_iran',
                                   'capital': 50_000_000, 'capital_unit': 'toman'})
    home = client.get('/api/home').json()
    assert 700 < home['capital']['usdt'] < 900        # ~50 m toman at ~60 000
    assert home['capital']['toman'] == pytest.approx(50_000_000, rel=.02)


def test_setup_rejects_an_unknown_exchange(client):
    response = client.put('/api/setup', json={'exchanges': ['kraken'], 'money': 'usdt',
                                              'capital': 10, 'capital_unit': 'USDT'})
    assert response.status_code == 422
    assert isinstance(response.json()['detail'], str)


def test_fee_parse_preview_and_save_roundtrip(client):
    preview = client.post('/api/fees/parse', json={
        'text': 'USDT  TRC20  1  10\n12 34 56', 'exchange': 'nobitex'}).json()
    assert len(preview['rows']) == 1
    assert preview['errors']
    saved = client.post('/api/fees/save', json={'rows': [{
        'exchange': 'nobitex', 'coin': 'USDT', 'network': 'TRC20',
        'withdrawal': 1.0, 'minimum': 10}]})
    assert saved.status_code == 200
    assert saved.json()['saved'] == 1
    row = next(item for item in saved.json()['rows']
               if item['exchange'] == 'nobitex' and item['coin'] == 'USDT')
    assert row['meta']['confidence'] == 'manual'
    assert row['meta']['age_days'] is not None
    assert row['meta']['stale'] is False


def test_saving_an_unknown_coin_is_refused(client):
    response = client.post('/api/fees/save', json={'rows': [{
        'exchange': 'nobitex', 'coin': '!!!', 'network': 'TRC20', 'withdrawal': 1}]})
    assert response.status_code in (400, 422)


def test_saving_duplicate_rows_is_refused(client):
    response = client.post('/api/fees/save', json={'rows': [
        {'exchange': 'nobitex', 'coin': 'USDT', 'network': 'TRC20', 'withdrawal': 1},
        {'exchange': 'nobitex', 'coin': 'USDT', 'network': 'TRC20', 'withdrawal': 2}]})
    assert response.status_code == 400
    assert 'تکراری' in response.json()['detail']


def test_automatic_fee_refresh_never_breaks_and_explains_itself(client):
    data = client.post('/api/fees/refresh').json()
    assert data['skipped'] is False
    assert {item['exchange'] for item in data['results']} == {'nobitex', 'wallex', 'bitunix'}
    assert all(item['ok'] is False for item in data['results'])
    assert all(item['message'] for item in data['results'])


def test_fee_sources_are_labelled_as_unconfirmed_where_they_are(client):
    data = client.get('/api/fees').json()
    assert set(data['sources']) == {'nobitex', 'wallex', 'bitunix'}
    for source in data['sources'].values():
        assert source['status'] in ('confirmed', 'unconfirmed')
        assert source['doc']
    assert data['pages']['nobitex']
    assert len(data['trading']) == 5


def test_lazy_fee_loading_only_asks_about_the_top_routes(client, monkeypatch, tmp_path):
    env = make(tmp_path)
    # Ten routes with a gross spread, eleven without: only the top ones should be reported.
    rows = [{'key': f'k{index}', 'coin': f'C{index}', 'gross_pct': 5 - index * .1}
            for index in range(12)]
    rows += [{'key': 'low', 'coin': 'LOW', 'gross_pct': 0.01}]
    needs = main.fee_needs(rows, [], env.hub.config())
    assert needs['limit'] == 10
    assert len(needs['coins']) == 10
    assert 'LOW' not in needs['coins']
    assert needs['missing_coins'] == needs['coins']
    assert 'کارمزد' in needs['text']


def test_banner_lists_what_is_missing_without_a_modal(client):
    data = client.get('/api/home').json()
    banner = data['banner']
    assert isinstance(banner['items'], list)
    if banner['items']:
        assert banner['visible'] is True
        assert banner['signature']


def test_home_survives_an_empty_market(tmp_path, monkeypatch):
    env = make(tmp_path)
    env.hub.books.clear()
    env.hub.tickers.clear()
    env.hub.invalidate()
    client = install(env, monkeypatch)
    response = client.get('/api/home')
    assert response.status_code == 200
    data = response.json()
    assert data['best'] is None
    assert data['empty']['message']
