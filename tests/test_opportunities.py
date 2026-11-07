from app.storage import Storage
from app.opportunities import OpportunityTracker, statistics


def row(profit, stamp):
    return dict(row_key='BTC:USDT:wallex:nobitex', coin='BTC',quote='USDT',source='wallex',destination='nobitex',trading_mode='prefunded',status='ok',depth_timestamp=stamp,taker=dict(profit=profit, profit_pct=profit,capital=100))


def test_start_end_unknown_restart_and_persistence(tmp_path):
    store = Storage(str(tmp_path/'test.db'))
    t = OpportunityTracker(store)
    t.observe(row(-1, 1), 1)
    assert t.rows() == []
    t.observe(row(1, 2), 2)
    t.observe(row(3, 3), 3)
    t.observe(row(-1, 4), 4)
    t.observe(row(-1, 5), 5, known=False)
    t = OpportunityTracker(store)
    t.observe(row(-1, 6), 6)
    assert t.rows()[0]['end'] is None
    t.observe(row(-1, 7), 7)
    r = t.rows()[0]
    assert (r['start'],r['end'],r['duration']) == (2,6,4)
    assert r['peak_pct'] == 3
    assert r['unknown_gaps'] == 1
    t.observe(row(2, 8), 8)
    assert len(t.rows()) == 2
    stats = statistics(t.rows(), 1)
    assert stats['uncertain_count'] == 1
    assert stats['median_seconds'] is None
    t.prune(9)
    assert t.rows() == []


def test_statistics():
    rows = [dict(start=0,duration=d,unknown_gaps=0,peak_pct=2) for d in [10,20,30]]
    s = statistics(rows, .4)
    assert s['median_seconds'] == 20
    assert s['p90_seconds'] == 28
    assert round(s['shorter_than_transfer_pct']) == 67


def test_active_markets_for_restart(tmp_path):
    t = OpportunityTracker(Storage(str(tmp_path/'restart.db')))
    t.observe(row(1,1),1)
    assert t.active_markets() == {('BTC','USDT')}
    t.observe(row(-1,2),2,confirmations=1)
    assert t.active_markets() == set()
