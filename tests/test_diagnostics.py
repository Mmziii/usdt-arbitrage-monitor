"""Diagnostics: reason mapping, clock skew, gateway retries/backoff and raw previews."""
import asyncio
import json
import time
import httpx
import pytest

from app.diagnostics import REASONS, build, clock_check, describe
from app.net import (Budget, BudgetExhausted, Endpoint, Gateway, Monitor, ValidationError,
                     preview_of, reset_budgets)


def test_every_reason_has_persian_message_and_action():
    for code in REASONS:
        described = describe(code)
        assert described['code'] == code
        assert described['message'] and described['action'] is not None
        assert len(described['message']) > 3
    assert describe('something-new')['code'] == 'unknown'
    assert 'VPN' in describe('network')['action']


def test_clock_check_threshold_and_persian_warning():
    ok = clock_check(3)
    assert ok['level'] == 'ok' and ok['skew_seconds'] == 3
    warn = clock_check(95)
    assert warn['level'] == 'warn'
    assert 'ساعت ویندوز' in warn['action']
    assert 'همگام' in warn['action']
    assert clock_check(None)['level'] == 'unknown'
    assert clock_check(-300)['level'] == 'warn'


def test_preview_is_first_500_characters():
    body = ('x' * 600).encode()
    assert len(preview_of(body)) == 500
    assert preview_of(b'\xff\xfe<html>blocked</html>').startswith('\ufffd\ufffd')


def make_gateway(handler, monitor=None):
    return Gateway(monitor=monitor or Monitor(), user_agent='TraderBot/Test-1.0',
                   max_wait=0.01)


def fetch_with_transport(handler, gateway=None, exchange='nobitex', endpoint=None,
                         parser=None):
    gateway = gateway or make_gateway(handler)
    endpoint = endpoint or Endpoint('orderbook_v3', 'https://example.test/v3/orderbook/BTCIRT')
    async def main():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     headers=gateway.headers) as client:
            return await gateway.fetch(client, exchange, endpoint, parser)
    return asyncio.run(main())


def test_gateway_retries_5xx_then_succeeds_and_logs_both_attempts():
    calls = {'n': 0}
    def handler(request):
        calls['n'] += 1
        if calls['n'] == 1:
            return httpx.Response(503, text='busy')
        return httpx.Response(200, json={'status': 'ok'}, headers={'date': 'Wed, 01 Jan 2025 00:00:00 GMT'})
    gateway = make_gateway(handler)
    result = fetch_with_transport(handler, gateway)
    assert result.ok and result.attempts == 2
    log = gateway.monitor.log('nobitex')
    assert [entry['reason'] for entry in log] == ['ok', 'http_5xx']
    assert log[1]['status'] == 503


def test_gateway_reports_not_json_with_raw_preview():
    def handler(request):
        return httpx.Response(200, text='<html>Access denied</html>',
                              headers={'content-type': 'text/html'})
    gateway = make_gateway(handler)
    result = fetch_with_transport(handler, gateway)
    assert not result.ok and result.reason == 'not_json'
    assert 'Access denied' in result.preview
    assert gateway.monitor.log('nobitex')[0]['json_ok'] is False


def test_gateway_records_validation_reason_without_retry():
    def handler(request):
        return httpx.Response(200, json={'status': 'ok', 'asks': [], 'bids': []})
    def parser(data):
        raise ValidationError('empty_book', 'asks/bids empty')
    result = fetch_with_transport(handler, make_gateway(handler), parser=parser)
    assert not result.ok and result.reason == 'empty_book' and result.attempts == 1


def test_gateway_detects_clock_skew_from_date_header():
    server = time.time() + 300
    date = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(server))
    def handler(request):
        return httpx.Response(200, json={'status': 'ok'}, headers={'date': date})
    gateway = make_gateway(handler)
    fetch_with_transport(handler, gateway)
    state = gateway.monitor.clock_state['nobitex']
    assert state['skew_seconds'] == pytest.approx(300, abs=2)


def test_build_diagnostics_payload_exposes_budget_clock_and_reason():
    gateway = make_gateway(lambda request: httpx.Response(200, json={}))
    fetch_with_transport(lambda request: httpx.Response(200, json={}), gateway)
    payload = build(gateway.monitor, exchange_labels={'nobitex': 'نوبیتکس'},
                    statuses={'nobitex': 'ok'})
    entry = payload['exchanges']['nobitex']
    assert entry['label'] == 'نوبیتکس' and entry['status'] == 'ok'
    assert entry['last_request']['url'].startswith('https://example.test')
    assert entry['last_request']['json_ok'] is True
    assert entry['clock']['level'] in ('ok', 'unknown', 'warn')
    assert 'reason_catalog' in payload


def test_budget_blocks_after_limit_and_backs_off_without_sleeping():
    """Deterministic budget/backoff check with an injected clock and sleep."""
    state = {'now': 0.0}
    def clock():
        return state['now']
    async def sleep(seconds):
        state['now'] += seconds
    b = Budget('wallex', limit=2, window=60, concurrency=1, base_backoff=2, clock=clock, sleep=sleep)
    async def three():
        for _ in range(2):
            async with b.slot(max_wait=5):
                pass
        with pytest.raises(BudgetExhausted):
            async with b.slot(max_wait=5):
                pass
        assert b.stats()['used'] == 2
        b.failure()
        assert b.stats()['backing_off']
        state['now'] += 60      # window rolls over, but backoff still holds the request
        async with b.slot(max_wait=10):
            pass
        assert b.stats()['used'] == 1   # previous window expired, new request recorded
        assert b.success() is None and b.stats()['consecutive_failures'] == 0
    asyncio.run(three())


def test_budget_window_slides_and_counts_used():
    state = {'now': 0.0}
    async def sleep(seconds):
        state['now'] += seconds
    b = Budget('x', limit=2, window=10, concurrency=1, clock=lambda: state['now'], sleep=sleep)
    async def scenario():
        for _ in range(2):
            async with b.slot(max_wait=1):
                pass
        state['now'] = 10.5
        assert b.stats()['used'] == 0
        async with b.slot(max_wait=1):
            pass
        assert b.stats()['used'] == 1 and b.stats()['total'] == 3
    asyncio.run(scenario())


def test_exchange_error_carries_reason():
    from app.net import ExchangeError, HttpResult
    error = ExchangeError(HttpResult(ok=False, reason='http_429', detail='HTTP 429'))
    assert '429' in str(error)


def test_reset_budgets_helper():
    from app.net import budget, budgets
    reset_budgets()
    budget('wallex')
    assert 'wallex' in budgets()
    reset_budgets()
    assert budgets() == {}
