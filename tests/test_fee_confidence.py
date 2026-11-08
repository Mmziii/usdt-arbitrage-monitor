"""Fee confidence: every fee knows where it came from and how old it is."""
import time

from app import fee_confidence
from app.main import AppSettings
from app.tiers import Tier

NOW = time.time()


def row(**overrides):
    base = {'exchange': 'wallex', 'coin': 'BTC', 'network': 'BTC', 'withdrawal': 0.0002,
            'minimum': 0.001, 'supported': True, 'confidence': 'manual',
            'source': 'assistant', 'fetched_at': NOW - 86400, 'note': ''}
    base.update(overrides)
    return base


def test_labels_are_the_persian_words_the_ui_shows():
    assert fee_confidence.label('auto') == 'تأیید خودکار'
    assert fee_confidence.label('manual') == 'تأیید دستی'
    assert fee_confidence.label('estimated') == 'تخمینی'
    assert fee_confidence.label('unknown') == 'نامعلوم'


def test_fresh_manual_fee_is_not_flagged():
    meta = fee_confidence.describe(row(), now=NOW, stale_days=14)
    assert meta['confidence'] == 'manual'
    assert meta['status'] == 'تأیید دستی'
    assert meta['stale'] is False and meta['needs_review'] is False
    assert round(meta['age_days'], 2) == 1.0


def test_old_fee_asks_for_a_second_look():
    meta = fee_confidence.describe(row(fetched_at=NOW - 40 * 86400), now=NOW, stale_days=14)
    assert meta['stale'] is True
    assert meta['status'] == fee_confidence.REVIEW_TEXT
    assert meta['needs_review'] is True


def test_fee_without_a_value_is_unknown_and_never_guessed():
    meta = fee_confidence.describe(row(withdrawal=None, confidence='auto'), now=NOW)
    assert meta['confidence'] == 'unknown'
    assert meta['status'] == 'نامعلوم'
    assert meta['needs_review'] is True


def test_fee_without_a_date_is_reported_as_such():
    meta = fee_confidence.describe(row(fetched_at=None), now=NOW)
    assert meta['age_days'] is None
    assert meta['status'] == 'بدون تاریخ ثبت'
    assert meta['needs_review'] is True


def test_shipped_trading_fee_defaults_are_only_estimates():
    settings = AppSettings()
    tag = fee_confidence.trading_fee_tag(settings, 'wallex', 'toman', now=NOW)
    assert tag['confidence'] == 'estimated'
    assert tag['status'] == 'تخمینی'
    assert tag['values'] == {'maker': .25, 'taker': .3}


def test_a_confirmed_trading_fee_counts_as_manual():
    settings = AppSettings(wallex={'maker': .1, 'taker': .12, 'withdrawal': .8})
    tag = fee_confidence.trading_fee_tag(settings, 'wallex', 'toman')
    assert tag['confidence'] == 'manual'


def test_missing_bitunix_fee_is_unknown():
    tag = fee_confidence.trading_fee_tag(AppSettings(), 'bitunix', 'USDT')
    assert tag['confidence'] == 'unknown'
    assert tag['values']['taker'] is None


def test_a_selected_tier_is_manual_confidence():
    settings = AppSettings()
    settings.fee_tiers = [Tier(exchange='wallex', quote='toman', name='VIP',
                               threshold=0, maker=.1, taker=.1)]
    settings.current_tiers = {'wallex:toman': 'VIP'}
    tag = fee_confidence.trading_fee_tag(settings, 'wallex', 'toman')
    assert tag['confidence'] == 'manual'
    assert tag['source'] == 'tier:VIP'


def test_route_confidence_reports_why_it_is_low():
    entries = [{'name': 'کارمزد برداشت BTC', 'confidence': 'unknown', 'stale': False}]
    result = fee_confidence.route_confidence(entries)
    assert result['level'] == 'low' and result['label'] == 'پایین'
    assert 'نامعلوم' in result['reasons'][0]


def test_route_confidence_is_high_when_every_fee_is_confirmed():
    entries = [{'name': 'الف', 'confidence': 'auto', 'stale': False},
               {'name': 'ب', 'confidence': 'manual', 'stale': False}]
    assert fee_confidence.route_confidence(entries)['level'] == 'high'


def test_merging_never_drops_rows_the_new_list_omits():
    existing = [row(exchange='wallex'), row(exchange='nobitex')]
    merged = fee_confidence.merge_rows(existing, [dict(row(exchange='wallex'), withdrawal=.9)])
    assert len(merged) == 2
    assert next(item for item in merged if item['exchange'] == 'wallex')['withdrawal'] == .9
