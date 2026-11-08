"""Every request identifies itself politely, with a per-exchange User-Agent.

Nobitex documents a bot style agent, so it is configurable separately; nothing here is
allowed to be an anonymous library default.
"""
import asyncio

import httpx

from app.main import AppSettings
from app.net import DEFAULT_AGENT, Endpoint, Gateway


def request_headers(gateway, exchange):
    seen = {}

    def handler(request):
        seen['user-agent'] = request.headers.get('user-agent')
        seen['from'] = request.headers.get('from')
        seen['accept'] = request.headers.get('accept')
        return httpx.Response(200, json={'status': 'ok'}, headers={'date': 'Wed, 21 Oct 2015 07:28:00 GMT'})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await gateway.fetch(client, exchange,
                                       Endpoint('options', 'https://api.test/v2/options'),
                                       max_attempts=1)

    result = asyncio.run(run())
    assert result.ok is True
    return seen


def test_the_default_agent_names_the_tool_and_is_read_only():
    assert DEFAULT_AGENT.startswith('TraderBot/')
    assert 'read-only' in DEFAULT_AGENT
    assert len(DEFAULT_AGENT) < 200


def test_default_requests_send_the_polite_agent_and_a_from_header():
    headers = request_headers(Gateway(), 'wallex')
    assert headers['user-agent'] == DEFAULT_AGENT
    assert headers['from'] == 'local-read-only-monitor'
    assert headers['accept'] == 'application/json'


def test_nobitex_can_have_its_own_user_agent():
    gateway = Gateway(exchange_agents={'nobitex': 'TraderBot/nobitex-check-1.0'})
    assert request_headers(gateway, 'nobitex')['user-agent'] == 'TraderBot/nobitex-check-1.0'
    assert request_headers(gateway, 'wallex')['user-agent'] == DEFAULT_AGENT


def test_an_empty_override_falls_back_to_the_general_agent():
    gateway = Gateway(exchange_agents={'nobitex': ''})
    assert gateway.agent_for('nobitex') == DEFAULT_AGENT


def test_configure_replaces_the_overrides():
    gateway = Gateway()
    gateway.configure(exchange_agents={'nobitex': 'TraderBot/custom-2.0'})
    assert gateway.agent_for('nobitex') == 'TraderBot/custom-2.0'
    gateway.configure(exchange_agents={})
    assert gateway.agent_for('nobitex') == DEFAULT_AGENT


def test_the_settings_default_is_the_polite_agent_and_empty_means_inherit():
    settings = AppSettings()
    assert settings.user_agent == DEFAULT_AGENT
    assert settings.nobitex_user_agent is None


def test_a_newline_in_the_agent_is_refused():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AppSettings(user_agent='bad\nagent')
