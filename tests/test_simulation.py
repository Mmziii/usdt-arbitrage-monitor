"""Paper-trade simulations: stored expectation, settled reality, honest failure states."""
import json
import time

import pytest

from app.simulation import SimulationError, create, public, settle, summary
from app.storage import Storage

NOW = 1_700_000_000.0


def row(**overrides):
    base = {
        'key': 'A:BTC:wallex', 'kind': 'cycle', 'coin': 'BTC', 'route': 'A',
        'route_label': 'خرید در بیت‌یونیکس، فروش در ایران', 'trading_mode': 'transfer',
        'capital': 100.0, 'capital_unit': 'USDT',
        'detail': {'taker': {'ok': True, 'capital': 100.0, 'final': 104.0,
                             'profit': 4.0, 'profit_pct': 4.0}},
    }
    base.update(overrides)
    return base


@pytest.fixture()
def store(tmp_path):
    item = Storage(str(tmp_path / 'sim.db'))
    item.init_ui()
    return item


def test_create_stores_the_expectation_and_a_due_time(store):
    simulation_id = create(store, row(), {'bitunix:BTC/USDT': {'ask': 100.0}},
                           now=NOW, transfer_minutes=5)
    record = store.simulation(simulation_id)
    assert record['status'] == 'pending'
    assert record['expected_profit'] == pytest.approx(4.0)
    assert record['capital'] == pytest.approx(100.0)
    assert record['due'] == pytest.approx(NOW + 300)
    assert record['transfer_minutes'] == pytest.approx(5)
    assert json.loads(record['prices']) == {'bitunix:BTC/USDT': {'ask': 100.0}}


def test_explicit_delay_overrides_transfer_time(store):
    simulation_id = create(store, row(), {}, now=NOW, transfer_minutes=30, delay_seconds=45)
    record = store.simulation(simulation_id)
    assert record['due'] == pytest.approx(NOW + 45)
    assert record['transfer_minutes'] is None


def test_short_delay_is_clamped_to_ten_seconds(store):
    record = store.simulation(create(store, row(), {}, now=NOW, delay_seconds=1))
    assert record['due'] == pytest.approx(NOW + 10)


def test_create_refuses_rows_without_a_full_calculation(store):
    with pytest.raises(SimulationError) as error:
        create(store, row(detail={'taker': {'ok': False}}), {}, now=NOW)
    assert 'محاسبه' in str(error.value)
    with pytest.raises(SimulationError):
        create(store, row(kind='classic'), {}, now=NOW)
    assert store.simulations() == []


def test_settle_compares_expectation_with_the_real_row(store):
    simulation_id = create(store, row(), {}, now=NOW, delay_seconds=30)
    settled = settle(store, store.simulation(simulation_id),
                     row(detail={'taker': {'ok': True, 'final': 102.0, 'profit': 2.0,
                                           'profit_pct': 2.0}}), now=NOW + 40)
    assert settled['status'] == 'done'
    assert settled['actual_profit'] == pytest.approx(2.0)
    assert settled['actual_final'] == pytest.approx(102.0)
    assert settled['difference'] == pytest.approx(-2.0)
    assert settled['completed'] == pytest.approx(NOW + 40)


def test_settle_marks_unavailable_instead_of_inventing_a_result(store):
    simulation_id = create(store, row(), {}, now=NOW, delay_seconds=30)
    settled = settle(store, store.simulation(simulation_id),
                     row(detail={'taker': {'ok': False, 'error': 'عمق بازار کافی نیست'}}), now=NOW + 60)
    assert settled['status'] == 'unavailable'
    assert settled['note'] == 'عمق بازار کافی نیست'
    assert settled['actual_profit'] is None


def test_summary_averages_only_settled_rows(store):
    first = create(store, row(), {}, now=NOW, delay_seconds=30)
    second = create(store, row(key='A:ETH:wallex', coin='ETH'), {}, now=NOW, delay_seconds=30)
    create(store, row(key='A:SOL:wallex', coin='SOL'), {}, now=NOW, delay_seconds=30)
    settle(store, store.simulation(first), row(detail={'taker': {
        'ok': True, 'final': 103.0, 'profit': 3.0, 'profit_pct': 3.0}}), now=NOW + 40)
    settle(store, store.simulation(second), row(detail={'taker': {
        'ok': True, 'final': 99.0, 'profit': -1.0, 'profit_pct': -1.0}}), now=NOW + 40)
    rows = [public(item) for item in store.simulations()]
    stats = summary(rows)
    assert stats['count'] == 3 and stats['pending'] == 1 and stats['done'] == 2
    assert stats['average_difference'] == pytest.approx(-3.0)
    assert stats['profitable_share'] == pytest.approx(50.0)
    assert stats['best_difference'] == pytest.approx(-1.0)
    assert stats['worst_difference'] == pytest.approx(-5.0)


def test_public_decodes_prices_and_translates_status(store):
    simulation_id = create(store, row(), {'wallex:BTC/toman': {'bid': 1}}, now=NOW,
                           delay_seconds=30)
    published = public(store.simulation(simulation_id))
    assert published['prices'] == {'wallex:BTC/toman': {'bid': 1}}
    assert published['status_label'] == 'در انتظار'
    broken = store.simulation(simulation_id)
    broken['prices'] = 'not json'
    assert public(broken)['prices'] == {}


def test_rows_are_ordered_newest_first(store):
    create(store, row(), {}, now=NOW, delay_seconds=30)
    create(store, row(key='A:ETH:wallex', coin='ETH'), {}, now=NOW + 1, delay_seconds=30)
    coins = [item['coin'] for item in store.simulations()]
    assert coins[0] == 'ETH'
