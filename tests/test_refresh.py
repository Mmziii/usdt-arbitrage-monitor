"""Refresh strategy: staleness rules, hot-row ranking and depth request batching."""
import time

from app.refresh import age_of, depth_targets, is_stale, rank_value, select_hot


def test_age_and_staleness():
    now = 1_700_000_000.0
    assert age_of(None, now) is None
    assert age_of(now - 10, now) == 10
    assert age_of(now + 10, now) == 0           # future timestamps never show negative age
    assert is_stale(now - 5, 120, now) is False
    assert is_stale(now - 500, 120, now) is True
    assert is_stale(None, 120, now) is True      # missing timestamp is treated as unusable


def test_staleness_uses_the_wall_clock_by_default():
    assert is_stale(time.time() - 1, 120) is False
    assert is_stale(time.time() - 600, 120) is True


def test_rank_value_prefers_net_then_reference_then_gross():
    assert rank_value({'net_pct': 1.2, 'reference_pct': 3.0, 'gross_pct': 4.0}) == 1.2
    assert rank_value({'net_pct': None, 'reference_pct': 3.0, 'gross_pct': 4.0}) == 3.0
    assert rank_value({'net_pct': None, 'reference_pct': None, 'gross_pct': 4.0}) == 4.0
    assert rank_value({'net_pct': None, 'reference_pct': None, 'gross_pct': None}) is None
    assert rank_value({'net_pct': float('nan')}) is None


def test_select_hot_keeps_pins_and_visible_rows_and_skips_unknown_rows():
    rows = [
        {'key': 'A:BTC:wallex', 'net_pct': 2.0},
        {'key': 'A:ETH:wallex', 'net_pct': 1.5},
        {'key': 'A:SOL:wallex', 'net_pct': None},
        {'key': 'A:XRP:wallex', 'net_pct': .5},
    ]
    chosen = select_hot(rows, limit=1, visible=['A:XRP:wallex'], pinned=['A:SOL:wallex'])
    assert chosen[:2] == ['A:SOL:wallex', 'A:XRP:wallex']
    assert 'A:BTC:wallex' in chosen                # the best remaining row fills the limit
    assert len(chosen) == 3
    assert 'A:ETH:wallex' not in chosen            # limit reached, unknown row never added
    assert select_hot(rows, limit=0) == []
    assert select_hot(rows, limit=5, pinned=['A:NOPE:wallex']) == ['A:BTC:wallex', 'A:ETH:wallex', 'A:XRP:wallex']


def test_depth_targets_batches_in_priority_order_and_skips_fresh_books():
    rows = {'A:BTC:wallex': ['bitunix:BTC/USDT', 'wallex:BTC/toman'],
            'A:ETH:wallex': ['bitunix:ETH/USDT', 'wallex:ETH/toman']}
    fresh = {'wallex:BTC/toman'}
    assert depth_targets(rows, ['A:BTC:wallex', 'A:ETH:wallex'], rows,
                         lambda key: key in fresh, batch=2) == ['bitunix:BTC/USDT', 'bitunix:ETH/USDT']
    assert depth_targets(rows, ['A:BTC:wallex'], rows, lambda key: False, batch=6) == [
        'bitunix:BTC/USDT', 'wallex:BTC/toman']
    assert depth_targets({'x': []}, ['x'], {'x': []}, lambda key: False) == []
