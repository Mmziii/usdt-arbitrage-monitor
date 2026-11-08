"""The journey receipt must reuse the engine's numbers and reconcile exactly."""
import time

from app import main, receipt as receipt_builder

from home_fixture import make

NOW = time.time()


def test_the_receipt_has_one_numbered_step_per_engine_stage(tmp_path, monkeypatch):
    env = make(tmp_path)
    monkeypatch.setattr(main, 'store', env.store)
    monkeypatch.setattr(main, 'settings', env.settings)
    monkeypatch.setattr(main, 'hub', env.hub)
    monkeypatch.setattr(main, 'tracker', env.tracker)
    row = next(item for item in env.hub.rows(env.settings, env.hub.config())
               if item['key'] == 'A:BTC:wallex')
    engine_steps = row['detail']['taker']['steps']
    result = main.build_receipt(row, main.annotated_fees(NOW), env.hub.config(), NOW)
    assert [step['stage'] for step in result['steps']] == [step['name'] for step in engine_steps]
    assert [step['n'] for step in result['steps']] == list(range(1, len(engine_steps) + 1))


def test_the_running_balance_is_continuous(tmp_path, monkeypatch):
    env = make(tmp_path)
    monkeypatch.setattr(main, 'store', env.store)
    monkeypatch.setattr(main, 'settings', env.settings)
    monkeypatch.setattr(main, 'hub', env.hub)
    monkeypatch.setattr(main, 'tracker', env.tracker)
    row = next(item for item in env.hub.rows(env.settings, env.hub.config())
               if item['key'] == 'A:BTC:wallex')
    result = main.build_receipt(row, main.annotated_fees(NOW), env.hub.config(), NOW)
    steps = result['steps']
    assert abs(steps[0]['amount_in'] - result['totals']['capital']) < 1e-9
    for previous, current in zip(steps, steps[1:]):
        assert abs(current['amount_in'] - previous['amount_out']) < 1e-9
    assert abs(result['steps_balance']['end'] - steps[-1]['amount_out']) < 1e-9


def test_totals_reconcile_with_the_engine(tmp_path, monkeypatch):
    env = make(tmp_path)
    monkeypatch.setattr(main, 'store', env.store)
    monkeypatch.setattr(main, 'settings', env.settings)
    monkeypatch.setattr(main, 'hub', env.hub)
    monkeypatch.setattr(main, 'tracker', env.tracker)
    row = next(item for item in env.hub.rows(env.settings, env.hub.config())
               if item['key'] == 'A:BTC:wallex')
    result = main.build_receipt(row, main.annotated_fees(NOW), env.hub.config(), NOW)
    taker = row['detail']['taker']
    totals = result['totals']
    assert totals['reconciled'] is True
    assert abs(totals['final'] - taker['final']) < 1e-9
    assert abs(totals['profit'] - taker['profit']) < 1e-9
    assert abs(totals['capital'] + totals['profit'] - totals['final']) < 1e-9
    assert abs(totals['profit_pct'] - taker['profit_pct']) < 1e-9
    assert abs(totals['costs_pct'] - (totals['gross_pct'] - totals['profit_pct'])) < 1e-6


def test_every_step_carries_a_fee_confidence_tag(tmp_path, monkeypatch):
    env = make(tmp_path)
    monkeypatch.setattr(main, 'store', env.store)
    monkeypatch.setattr(main, 'settings', env.settings)
    monkeypatch.setattr(main, 'hub', env.hub)
    monkeypatch.setattr(main, 'tracker', env.tracker)
    row = next(item for item in env.hub.rows(env.settings, env.hub.config())
               if item['key'] == 'A:BTC:wallex')
    result = main.build_receipt(row, main.annotated_fees(NOW), env.hub.config(), NOW)
    for step in result['steps']:
        assert step['confidence'] in ('auto', 'manual', 'estimated', 'unknown')
        assert step['confidence_label']
    withdrawal = next(step for step in result['steps'] if step['stage'] == 'withdraw_coin')
    assert withdrawal['confidence'] in ('manual', 'auto')


def test_other_costs_are_a_separate_line_and_reduce_the_profit(tmp_path, monkeypatch):
    env = make(tmp_path)
    monkeypatch.setattr(main, 'store', env.store)
    monkeypatch.setattr(main, 'settings', env.settings)
    monkeypatch.setattr(main, 'hub', env.hub)
    monkeypatch.setattr(main, 'tracker', env.tracker)
    cfg = env.hub.config()
    cfg['other_costs_toman'] = 500_000
    env.store.save_scanner_settings(cfg)
    env.hub.invalidate()
    row = next(item for item in env.hub.rows(env.settings, env.hub.config())
               if item['key'] == 'A:BTC:wallex')
    result = main.build_receipt(row, main.annotated_fees(NOW), env.hub.config(), NOW)
    totals = result['totals']
    assert totals['other_costs_toman'] == 500_000
    assert totals['other_costs_pct'] > 0
    assert totals['profit_after_other'] < totals['profit']
    assert abs(totals['pct_after_other'] - (totals['profit_pct'] - totals['other_costs_pct'])) < 1e-9


def test_text_and_csv_exports_are_readable(tmp_path, monkeypatch):
    env = make(tmp_path)
    monkeypatch.setattr(main, 'store', env.store)
    monkeypatch.setattr(main, 'settings', env.settings)
    monkeypatch.setattr(main, 'hub', env.hub)
    monkeypatch.setattr(main, 'tracker', env.tracker)
    row = next(item for item in env.hub.rows(env.settings, env.hub.config())
               if item['key'] == 'A:BTC:wallex')
    result = main.build_receipt(row, main.annotated_fees(NOW), env.hub.config(), NOW)
    text = receipt_builder.to_text(result)
    assert 'رسید' in text and 'چک‌لیست' in text
    assert 'تضمینی نیستند' in text or 'تضمین' in text
    csv_text = receipt_builder.to_csv(result['steps'])
    assert csv_text.startswith('\ufeff')
    assert csv_text.lstrip('\ufeff').splitlines()[0].startswith('n,stage,venue')


def test_a_blocked_route_has_no_numbers(tmp_path, monkeypatch):
    env = make(tmp_path, with_fees=False)
    monkeypatch.setattr(main, 'store', env.store)
    monkeypatch.setattr(main, 'settings', env.settings)
    monkeypatch.setattr(main, 'hub', env.hub)
    monkeypatch.setattr(main, 'tracker', env.tracker)
    rows = env.hub.rows(env.settings, env.hub.config())
    row = next(item for item in rows if item['key'] == 'A:BTC:wallex')
    result = main.build_receipt(row, main.annotated_fees(NOW), env.hub.config(), NOW)
    assert result['ok'] is False
    assert result['steps'] == []
    assert result['totals'] == {}
