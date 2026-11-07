"""UI preference storage: dismissal flags survive refreshes and a restart, bad input is 400."""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.storage import Storage


@pytest.fixture()
def store(tmp_path, monkeypatch):
    item = Storage(str(tmp_path / 'ui.db'))
    monkeypatch.setattr(main, 'store', item)
    return item


@pytest.fixture()
def client(store):
    # No lifespan: no background loops and no outbound requests.
    return TestClient(main.app)


def test_setup_banner_dismissal_defaults_to_empty(client):
    payload = client.get('/api/ui').json()
    assert payload['setup_banner_dismissed'] == ''
    assert 'wizard_done' in payload


def test_setup_banner_dismissal_round_trip(client, store):
    signature = 'کارمزد بیت‌یونیکس در بازار USDT|کارمزد برداشت ارز در بیت‌یونیکس'
    response = client.put('/api/ui', json={'values': {'setup_banner_dismissed': signature}})
    assert response.status_code == 200
    assert response.json()['setup_banner_dismissed'] == signature
    assert client.get('/api/ui').json()['setup_banner_dismissed'] == signature
    # Persisted in SQLite, not just in memory: a restart (new Storage on the same file)
    # must still remember that the notice was closed.
    reopened = Storage(store.path)
    assert reopened.ui_state()['setup_banner_dismissed'] == signature


def test_malformed_dismissal_is_rejected_in_persian(client, store):
    for bad in ({'a': 1}, 5, ['a'], True):
        response = client.put('/api/ui', json={'values': {'setup_banner_dismissed': bad}})
        assert response.status_code == 400
        assert 'پیام راه‌اندازی' in response.json()['detail']
    assert client.get('/api/ui').json()['setup_banner_dismissed'] == ''


def test_long_signature_is_truncated_not_rejected(client):
    response = client.put('/api/ui', json={'values': {'setup_banner_dismissed': 'x' * 900}})
    assert response.status_code == 200
    assert len(response.json()['setup_banner_dismissed']) == 500


def test_unknown_keys_are_ignored(client):
    response = client.put('/api/ui', json={'values': {'nope': 1, 'theme': 'dark'}})
    assert response.status_code == 200
    body = response.json()
    assert body['theme'] == 'dark'
    assert 'nope' not in body


def test_invalid_lists_still_fail_with_persian_messages(client):
    pins = client.put('/api/ui', json={'values': {'pins': 'BTC'}})
    assert pins.status_code == 400 and 'پین' in pins.json()['detail']
    presets = client.put('/api/ui', json={'values': {'presets': {}}})
    assert presets.status_code == 400 and 'فیلتر' in presets.json()['detail']
