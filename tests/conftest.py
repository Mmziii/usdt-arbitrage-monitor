"""Shared test setup: the process-wide request budgets are isolated per test."""
import pytest

from app.net import budget, reset_budgets


@pytest.fixture(autouse=True)
def fast_budgets(monkeypatch):
    reset_budgets()
    for name in ('nobitex', 'wallex', 'bitunix', 'nobitex:stats', 'wallex:stats'):
        item = budget(name)
        item.base_backoff = .01
        item.max_backoff = .05
    yield
    reset_budgets()
