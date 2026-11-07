import pytest
from app.main import Settings
from app.tiers import Tier, parse_tiers, export_tiers, active_fees


def test_tier_override_and_fallback():
    s = Settings()
    assert s.fee_tiers == []
    baseline = s.trading_fees('wallex', 'toman')['taker']
    s.fee_tiers = [Tier(exchange='wallex', quote='toman', name='mine', threshold=100, maker=.1, taker=.15)]
    s.current_tiers = {'wallex:toman': 'mine'}
    assert s.trading_fees('wallex', 'toman')['taker'] == .15
    assert active_fees(s, 'wallex', 'USDT')['fee_source'] == 'global'
    s.current_tiers = {}
    assert s.trading_fees('wallex', 'toman')['taker'] == baseline
    for fmt in ['csv', 'json']:
        assert parse_tiers(export_tiers(s.fee_tiers, fmt), fmt) == s.fee_tiers
    with pytest.raises(ValueError):
        parse_tiers(export_tiers(s.fee_tiers * 2, 'json'), 'json')
