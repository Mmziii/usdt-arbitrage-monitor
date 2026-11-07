"""Manual trade journal: strict validation, automatic profit, storage and CSV export."""
import pytest

from app.journal import JournalError, export_csv, validate
from app.storage import Storage

NOW = 1_700_000_000.0
BASE = {'date': '2025-03-01', 'coin': 'btc', 'route': 'A', 'mode': 'transfer',
        'capital': 100, 'final_amount': 104}


def test_valid_entry_normalizes_symbol_and_computes_profit():
    entry = validate(BASE, now=NOW)
    assert entry['coin'] == 'BTC'
    assert entry['profit'] == pytest.approx(4.0)
    assert entry['created'] == NOW
    assert entry['fees'] == '' and entry['note'] == ''


def test_explicit_profit_wins_over_derived_value():
    entry = validate({**BASE, 'profit': 3.5, 'fees': '1 USDT', 'note': 'ok'}, now=NOW)
    assert entry['profit'] == pytest.approx(3.5)
    assert entry['fees'] == '1 USDT'
    assert entry['note'] == 'ok'


def test_long_text_is_truncated_not_rejected():
    entry = validate({**BASE, 'note': 'x' * 900, 'fees': 'y' * 400}, now=NOW)
    assert len(entry['note']) == 500
    assert len(entry['fees']) == 200


@pytest.mark.parametrize('change,message_part', [
    ({'date': '2025/03/01'}, 'تاریخ'),
    ({'date': '2025-13-01'}, 'تاریخ'),
    ({'coin': '?'}, 'نماد'),
    ({'route': 'Z'}, 'مسیر'),
    ({'mode': 'instant'}, 'حالت'),
    ({'capital': 0}, 'سرمایه'),
    ({'capital': 'abc'}, 'سرمایه'),
    ({'final_amount': float('inf')}, 'مبلغ نهایی'),
])
def test_invalid_entries_are_rejected_in_persian(change, message_part):
    with pytest.raises(JournalError) as error:
        validate({**BASE, **change}, now=NOW)
    assert message_part in str(error.value)


def test_missing_route_or_mode_defaults_instead_of_guessing_numbers():
    entry = validate({'date': '2025-03-01', 'coin': 'ETH'}, now=NOW)
    assert entry['route'] == 'other'
    assert entry['mode'] == 'transfer'
    assert entry['capital'] is None and entry['profit'] is None


def test_storage_round_trip_and_delete(tmp_path):
    store = Storage(str(tmp_path / 'journal.db'))
    store.init_ui()
    first = store.add_journal(validate(BASE, now=NOW))
    store.add_journal(validate({**BASE, 'date': '2025-03-02', 'coin': 'ETH',
                                'final_amount': 99}, now=NOW))
    rows = store.journal()
    assert [row['coin'] for row in rows] == ['ETH', 'BTC']      # newest date first
    store.delete_journal(first)
    assert [row['coin'] for row in store.journal()] == ['ETH']


def test_csv_export_has_bom_header_and_quoted_text(tmp_path):
    store = Storage(str(tmp_path / 'journal.db'))
    store.init_ui()
    store.add_journal(validate({**BASE, 'note': 'خرید, فروش'}, now=NOW))
    text = export_csv(store.journal())
    assert text.startswith('\ufeff')
    lines = text.splitlines()
    assert lines[0].lstrip('\ufeff').startswith('id,date,coin,route,mode,capital')
    assert 'BTC' in lines[1]
    assert '"خرید, فروش"' in lines[1]
