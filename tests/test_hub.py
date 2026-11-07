"""Hub wiring: route rows, unknown-fee blocking and the read-only summary counters."""
import time

import pytest

from app.adapters import DepthBook, Market, Ticker
from app.hub import Hub
from app.main import AppSettings
from app.net import Monitor
from app.storage import Storage

NOW = time.time()


class FakeGateway:
    def __init__(self):
        self.monitor = Monitor()

    def fetch(self, *args, **kwargs):      # pragma: no cover - network is never used here
        raise AssertionError('hub tests must not touch the network')


def make_hub(tmp_path, settings=None):
    store = Storage(str(tmp_path / 'hub.db'))
    store.init_scanner()
    settings = settings or AppSettings(bitunix={'maker': .1, 'taker': .1},
                                       bitunix_usdt={'maker': .1, 'taker': .1})
    hub = Hub(store, FakeGateway(), lambda: settings)
    hub.bitunix[('BTC', 'USDT')] = Market('bitunix', 'BTC', 'USDT', 'BTCUSDT')
    hub.iran['wallex'][('BTC', 'toman')] = Market('wallex', 'BTC', 'toman', 'BTCIRT')
    hub.iran['wallex'][('USDT', 'toman')] = Market('wallex', 'USDT', 'toman', 'USDTIRT')
    hub.rebuild_routes()
    hub.tickers[('bitunix', 'BTC', 'USDT')] = Ticker('bitunix', 'BTC', 'USDT', 100.1, 100.0,
                                                     NOW, True, 'bulk', last=100.0)
    hub.tickers[('wallex', 'BTC', 'toman')] = Ticker('wallex', 'BTC', 'toman', 6_600_100, 6_600_000,
                                                     NOW, True, 'bulk')
    hub.tickers[('wallex', 'USDT', 'toman')] = Ticker('wallex', 'USDT', 'toman', 60_000, 59_900,
                                                      NOW, True, 'bulk')
    hub.books[('bitunix', 'BTC', 'USDT')] = DepthBook('bitunix', 'BTC', 'USDT',
                                                      [(100, 100)], [(99.9, 100)], NOW, True, 'fixture')
    hub.books[('wallex', 'BTC', 'toman')] = DepthBook('wallex', 'BTC', 'toman',
                                                      [(6_600_000, 100)], [(6_600_000, 100)], NOW, True, 'fixture')
    hub.books[('wallex', 'USDT', 'toman')] = DepthBook('wallex', 'USDT', 'toman',
                                                       [(60_000, 1e9)], [(59_900, 1e9)], NOW, True, 'fixture')
    return hub


def test_discovery_creates_one_cycle_route_and_no_direct_route(tmp_path):
    hub = make_hub(tmp_path)
    kinds = sorted(route.kind for route in hub.routes)
    assert kinds == ['A', 'B']                     # toman market only -> full cycle routes
    assert hub.route_by_key('A:BTC:wallex').iran == 'wallex'
    assert hub.market('bitunix', 'BTC', 'USDT').symbol == 'BTCUSDT'
    assert hub.market('nobitex', 'BTC', 'toman') is None


def test_config_merges_defaults_with_saved_values(tmp_path):
    hub = make_hub(tmp_path)
    assert hub.config()['interval'] == 10
    hub.store.save_scanner_settings({'interval': 15, 'hot_rows': 5})
    cfg = hub.config()
    assert cfg['interval'] == 15 and cfg['hot_rows'] == 5
    assert cfg['depth_interval'] == 5              # untouched defaults survive


def test_missing_network_fee_keeps_gross_and_blanks_net(tmp_path):
    hub = make_hub(tmp_path)
    cfg = hub.config()
    rows = hub.build_rows(cfg)
    assert len(rows) == 2
    row = next(item for item in rows if item['key'] == 'A:BTC:wallex')
    assert row['status'] in ('network unknown', 'no common network')
    assert row['flags']['gross_only'] is True
    assert row.get('net_pct') is None and row['verdict'] == 'unknown'
    assert row['gross_pct'] is not None            # the raw spread is still shown
    assert 'شبکه' in row['error']                  # Persian explanation, never a crash


def test_known_fees_produce_a_net_number_and_sources(tmp_path):
    hub = make_hub(tmp_path)
    fees = []
    for exchange in ('wallex', 'bitunix'):
        fees.append({'exchange': exchange, 'coin': 'BTC', 'network': 'TRC20',
                     'withdrawal': .01, 'minimum': 0, 'supported': True})
        fees.append({'exchange': exchange, 'coin': 'USDT', 'network': 'TRC20',
                     'withdrawal': 1, 'minimum': 0, 'supported': True})
    hub.store.replace_fees(fees)
    hub.store.save_scanner_settings({'networks': {'BTC': 'TRC20', 'USDT': 'TRC20'},
                                     'capital_usdt': 100})
    cfg = hub.config()
    row = next(item for item in hub.build_rows(cfg) if item['key'] == 'A:BTC:wallex')
    assert row['status'] == 'ok', row.get('error')
    assert row['flags']['gross_only'] is False
    assert row['net_pct'] is not None
    assert row['network'] == 'TRC20'
    assert row['fee_sources']['bitunix'] == 'global'
    assert row['fee_sources'].get('wallex:conversion') == 'global'
    assert row['detail']['taker']['ok'] is True
    assert row['depth_timestamp'] is not None


def test_missing_depth_is_reported_without_computing_profit(tmp_path):
    hub = make_hub(tmp_path)
    hub.books.pop(('wallex', 'BTC', 'toman'))
    row = next(item for item in hub.build_rows(hub.config()) if item['key'] == 'A:BTC:wallex')
    assert row['status'] == 'depth needed'
    assert row.get('net_pct') is None
    assert 'عمق' in row['error']


def test_stale_book_is_flagged_and_never_used_for_profit(tmp_path):
    hub = make_hub(tmp_path)
    old = NOW - 10_000
    hub.books[('wallex', 'BTC', 'toman')] = DepthBook('wallex', 'BTC', 'toman',
                                                      [(6_600_000, 100)], [(6_600_000, 100)],
                                                      old, True, 'fixture')
    hub.store.save_scanner_settings({'stale_seconds': 120})
    row = next(item for item in hub.build_rows(hub.config()) if item['key'] == 'A:BTC:wallex')
    assert row['status'] == 'stale'
    assert row['flags']['stale'] is True
    assert row.get('net_pct') is None


def test_reference_pct_uses_last_price_and_is_not_profit(tmp_path):
    hub = make_hub(tmp_path)
    route_a = hub.route_by_key('A:BTC:wallex')
    # Iranian bid 6,600,000 toman / 60,000 toman per USDT = 110 USDT vs 100 USDT on Bitunix.
    assert hub.reference_pct(route_a) == pytest.approx(10.0)
    hub.tickers.pop(('wallex', 'USDT', 'toman'))
    assert hub.reference_pct(route_a) is None


def test_summary_counts_profitable_and_unknown_rows(tmp_path):
    hub = make_hub(tmp_path)
    rows = [
        {'key': 'a', 'coin': 'BTC', 'route_label': 'A', 'verdict': 'worth', 'net_pct': 2.0,
         'net_quote': 5.0, 'status': 'ok', 'flags': {}},
        {'key': 'b', 'coin': 'ETH', 'verdict': 'no', 'net_pct': -1.0, 'net_quote': -2.0,
         'status': 'ok', 'flags': {}},
        {'key': 'c', 'coin': 'SOL', 'verdict': 'unknown', 'net_pct': None,
         'status': 'fee unknown', 'flags': {'gross_only': True}},
    ]
    summary = hub.summary(rows, hub.config())
    assert summary['profitable_count'] == 1
    assert summary['usable_count'] == 2
    assert summary['best']['key'] == 'a'


def test_exchange_status_reports_missing_and_fresh_data(tmp_path):
    hub = make_hub(tmp_path)
    status = hub.exchange_status(hub.config())
    assert status['wallex']['state'] == 'unknown'      # data present, no successful fetch yet
    assert status['wallex']['tickers'] == 2
    old = NOW - 10_000
    for key, ticker in list(hub.tickers.items()):
        if key[0] == 'wallex':
            hub.tickers[key] = Ticker(**{**ticker.__dict__, 'timestamp': old})
    stale = hub.exchange_status(hub.config())['wallex']
    assert stale['state'] == 'stale'
    assert stale['fresh_tickers'] == 0
