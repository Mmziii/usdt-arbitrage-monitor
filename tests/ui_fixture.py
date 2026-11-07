"""Build a deterministic JSON payload for the jsdom dashboard smoke test.

Everything comes from the real Python modules (hub, cycle, plans) using synthetic order
books; no exchange is contacted and no network access is needed.

Usage: .venv/bin/python tests/ui_fixture.py > /tmp/dashboard.json
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DATABASE_PATH', os.path.join(tempfile.mkdtemp(), 'smoke.db'))

from app.adapters import DepthBook, Market, Ticker          # noqa: E402
from app.adapters import public_depth                        # noqa: E402
from app.main import AppSettings, UI_DEFAULTS, public_row    # noqa: E402
from app.hub import Hub                                      # noqa: E402
from app.net import Monitor                                  # noqa: E402
from app.plans import build_plan                             # noqa: E402
from app.storage import Storage                              # noqa: E402

NOW = time.time()


class FakeGateway:
    def __init__(self):
        self.monitor = Monitor()


def build():
    store = Storage(os.environ['DATABASE_PATH'])
    store.init_scanner()
    settings = AppSettings(bitunix={'maker': .1, 'taker': .1},
                           bitunix_usdt={'maker': .1, 'taker': .1})
    fees = []
    for exchange in ('wallex', 'bitunix'):
        fees.append(dict(exchange=exchange, coin='BTC', network='TRC20', withdrawal=.01,
                         minimum=0, supported=True))
        fees.append(dict(exchange=exchange, coin='USDT', network='TRC20', withdrawal=1,
                         minimum=0, supported=True))
    store.replace_fees(fees)
    store.save_scanner_settings({'networks': {'BTC': 'TRC20', 'USDT': 'TRC20'},
                                 'capital_usdt': 100, 'capital_toman': 6_000_000,
                                 'safety_margin': .1, 'interval': 10, 'depth_interval': 5,
                                 'hot_rows': 20, 'threshold': .5, 'watchlist': ['BTC']})
    hub = Hub(store, FakeGateway(), lambda: settings)
    hub.bitunix[('BTC', 'USDT')] = Market('bitunix', 'BTC', 'USDT', 'BTCUSDT')
    hub.iran['wallex'][('BTC', 'toman')] = Market('wallex', 'BTC', 'toman', 'BTCIRT')
    hub.iran['wallex'][('USDT', 'toman')] = Market('wallex', 'USDT', 'toman', 'USDTIRT')
    hub.iran['nobitex'][('BTC', 'toman')] = Market('nobitex', 'BTC', 'toman', 'btc-rls')
    hub.rebuild_routes()
    hub.tickers[('bitunix', 'BTC', 'USDT')] = Ticker('bitunix', 'BTC', 'USDT', 100.1, 100.0,
                                                     NOW, True, 'bulk', last=100.0)
    hub.tickers[('wallex', 'BTC', 'toman')] = Ticker('wallex', 'BTC', 'toman', 6_700_000,
                                                     6_699_000, NOW, True, 'bulk')
    hub.tickers[('nobitex', 'BTC', 'toman')] = Ticker('nobitex', 'BTC', 'toman', 6_600_000,
                                                      6_599_000, NOW, True, 'bulk')
    hub.tickers[('wallex', 'USDT', 'toman')] = Ticker('wallex', 'USDT', 'toman', 60_000,
                                                      59_900, NOW, True, 'bulk')
    hub.books[('bitunix', 'BTC', 'USDT')] = DepthBook('bitunix', 'BTC', 'USDT',
                                                      [(100, 50)], [(99.9, 50)], NOW, True, 'fixture')
    hub.books[('wallex', 'BTC', 'toman')] = DepthBook('wallex', 'BTC', 'toman',
                                                      [(6_700_000, 20)], [(6_699_000, 20)],
                                                      NOW, True, 'fixture')
    hub.books[('nobitex', 'BTC', 'toman')] = DepthBook('nobitex', 'BTC', 'toman',
                                                       [(6_600_000, 20)], [(6_599_000, 20)],
                                                       NOW, True, 'fixture')
    hub.books[('wallex', 'USDT', 'toman')] = DepthBook('wallex', 'USDT', 'toman',
                                                       [(60_000, 1e9)], [(59_900, 1e9)],
                                                       NOW, True, 'fixture')
    hub.last_scan = NOW
    cfg = hub.config()
    raw_rows = hub.build_rows(cfg, envelope_keys={route.key for route in hub.routes})
    rows = [public_row(row) for row in raw_rows]
    detail_row = max(raw_rows, key=lambda row: row.get('net_pct') or -1e9)
    route = hub.route_by_key(detail_row['key'])
    books = {f'{exchange}:{coin}/{quote}': public_depth(hub.books[(exchange, coin, quote)])
             for exchange, coin, quote in route.books()}
    history = [
        {'timestamp': NOW - 300 + index * 60,
         'spread_a': 9.6 + index * .05, 'spread_b': 9.1 + index * .04,
         'wallex_bid': 6_690_000 + index * 1000, 'nobitex_bid': 6_590_000 + index * 1000}
        for index in range(6)
    ]
    return {
        'overview': {
            'rows': rows,
            'summary': hub.summary(raw_rows, cfg),
            'excluded': hub.excluded,
            'scanner': cfg,
            'ui': {**UI_DEFAULTS, 'pins': ['BTC']},
            'settings': settings.model_dump(exclude={'proxy_url'}),
            'errors': None,
            'now': NOW,
            'exchange_labels': {'wallex': 'والکس', 'nobitex': 'نوبیتکس', 'bitunix': 'بیت‌یونیکس'},
            'route_labels': ['والکس', 'نوبیتکس', 'بیت‌یونیکس'],
            'budgets': {},
        },
        'detail': {
            'row': {**detail_row, 'taker': detail_row.get('taker'),
                    'maker': detail_row.get('maker')},
            'plan': build_plan(detail_row, network='TRC20'),
            'books': books,
            'history': history,
            'conversion': hub.conversion_rate(cfg),
            'classic': False,
        },
        'wizard': {'complete': False, 'missing': ['کارمزد برداشت ارز در بیت‌یونیکس'],
                   'wizard_done': False, 'network_ready': False},
        'settings': settings.model_dump(),
        'fees': fees,
        'ui': {**UI_DEFAULTS, 'pins': ['BTC']},
        'diagnostics': {
            'generated_at': NOW, 'paused': False,
            'exchanges': {
                'wallex': {'label': 'والکس', 'status': 'ok', 'last_success': NOW,
                           'last_success_age': 1.5, 'endpoints_in_use': {'ticker': 'bulk'},
                           'clock': {'level': 'ok', 'skew_seconds': 1.0, 'message': 'اختلاف ساعت حدود ۱ ثانیه است.',
                                     'action': '', 'checked_at': NOW, 'samples': 3},
                           'last_request': {'exchange': 'wallex', 'endpoint': 'bulk',
                                            'url': 'https://api.wallex.ir/v1/markets',
                                            'at': NOW, 'status': 200, 'elapsed_ms': 120.5,
                                            'json_ok': True, 'reason': 'ok', 'detail': '',
                                            'preview': '{"success":true}', 'skew_seconds': 1.0,
                                            'attempt': 1, 'quality': 'depth'},
                           'log': [], 'budget': {'limit': 60, 'used': 4, 'window_seconds': 60,
                                                 'in_flight': 0, 'total': 4, 'failed': 0,
                                                 'consecutive_failures': 0, 'backoff_seconds': 0,
                                                 'backing_off': False, 'remaining': 56}},
                'bitunix': {'label': 'بیت‌یونیکس', 'status': 'error', 'last_success': None,
                            'last_success_age': None, 'endpoints_in_use': {},
                            'clock': {'level': 'unknown', 'skew_seconds': None,
                                      'message': 'اختلاف ساعت هنوز اندازه‌گیری نشده است.',
                                      'action': '', 'checked_at': None, 'samples': 0},
                            'last_request': {'exchange': 'bitunix', 'endpoint': 'depth',
                                             'url': 'https://openapi.bitunix.com/api/spot/v1/market/depth',
                                             'at': NOW, 'status': 451, 'elapsed_ms': 90.0,
                                             'json_ok': False, 'reason': 'blocked',
                                             'detail': 'restricted region',
                                             'preview': '<html>blocked</html>',
                                             'skew_seconds': None, 'attempt': 1,
                                             'quality': 'depth'},
                            'error': {'code': 'blocked', 'message': 'صرافی دسترسی را بست (۴۰۱/۴۰۳/۴۵۱).',
                                      'action': 'VPN یا پروکسی را خاموش کنید.', 'detail': 'restricted region'},
                            'log': [], 'budget': None},
            },
            'budgets': {'wallex': {'limit': 60, 'used': 4, 'remaining': 56, 'window_seconds': 60,
                                   'total': 4, 'failed': 0, 'backing_off': False,
                                   'backoff_seconds': 0, 'in_flight': 0,
                                   'consecutive_failures': 0, 'name': 'wallex'}},
            'extra': {'proxy': None, 'user_agent': 'TraderBot/USDTMonitor-2.0 (+read-only)',
                      'max_timestamp_age_seconds': 120, 'clock_skew_warning_seconds': 60,
                      'markets': {'wallex': 1, 'nobitex': 1, 'bitunix': 1}, 'routes': 4,
                      'last_scan': NOW, 'scan_count': 3, 'stale_seconds': 120,
                      'depth_interval': 5, 'interval': 10, 'hot_rows': 2},
            'reason_catalog': {'ok': {'code': 'ok', 'message': 'درخواست موفق بود.',
                                      'action': '', 'detail': ''},
                               'blocked': {'code': 'blocked', 'message': 'صرافی دسترسی را بست (۴۰۱/۴۰۳/۴۵۱).',
                                           'action': 'VPN را خاموش کنید.', 'detail': ''}},
        },
        'simulations': {
            'rows': [
                {'id': 1, 'created': NOW - 600, 'coin': 'BTC', 'route': 'A',
                 'route_label': 'خرید در بیت‌یونیکس، فروش در ایران', 'mode': 'transfer',
                 'capital': 100, 'unit': 'USDT', 'expected_profit': 9.2, 'expected_pct': 9.2,
                 'actual_profit': 8.1, 'actual_pct': 8.1, 'difference': -1.1,
                 'status': 'done', 'status_label': 'انجام شد', 'note': ''},
                {'id': 2, 'created': NOW - 60, 'coin': 'BTC', 'route': 'B',
                 'route_label': 'خرید در ایران، فروش در بیت‌یونیکس', 'mode': 'prefunded',
                 'capital': 100, 'unit': 'USDT', 'expected_profit': -2.0, 'expected_pct': -2.0,
                 'actual_profit': None, 'actual_pct': None, 'difference': None,
                 'status': 'pending', 'status_label': 'در انتظار', 'note': ''},
            ],
            'summary': {'count': 2, 'pending': 1, 'done': 1, 'unavailable': 0,
                        'average_difference': -1.1, 'profitable_share': 100.0,
                        'worst_difference': -1.1, 'best_difference': -1.1},
        },
        'journal': {'rows': [
            {'id': 1, 'date': '2025-03-01', 'coin': 'BTC', 'route': 'A', 'mode': 'transfer',
             'capital': 100, 'final_amount': 104, 'profit': 4.0, 'fees': '1 USDT',
             'note': 'آزمایش'},
        ]},
    }


if __name__ == '__main__':
    json.dump(build(), sys.stdout, ensure_ascii=False)
