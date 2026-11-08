"""A fully local home-screen fixture: fake gateway, synthetic books, known fees.

No exchange is contacted. The same builder feeds the pytest suite and the jsdom smoke
tests, so the browser test sees exactly the JSON the real API produces.
"""
import pathlib
import time
from types import SimpleNamespace

from app import main
from app.adapters import DepthBook, Market, Ticker
from app.hub import Hub
from app.net import HttpResult, Monitor
from app.opportunities import OpportunityTracker
from app.scanner import Scanner
from app.storage import Storage

NOW = time.time()

MINUTE = 60


class FakeGateway:
    """Stands in for the network: every request fails with a clear, local reason."""

    def __init__(self):
        self.monitor = Monitor()
        self.calls = []

    def configure(self, **kwargs):
        pass

    async def fetch(self, *args, **kwargs):
        return HttpResult(ok=False, reason='network', detail='sandbox has no exchange access')

    def make_client(self, *args, **kwargs):
        class Client:
            async def __aenter__(self_inner):
                return object()

            async def __aexit__(self_inner, *exc):
                return False

        return Client()


def fee_rows(fresh=True, coin_fee=0.0002):
    stamp = NOW - (3600 if fresh else 40 * 86400)
    return [
        {'exchange': 'bitunix', 'coin': 'BTC', 'network': 'BTC', 'withdrawal': 0.0005,
         'minimum': 0.001, 'supported': True, 'confidence': 'manual',
         'source': 'assistant', 'fetched_at': stamp, 'note': ''},
        {'exchange': 'wallex', 'coin': 'BTC', 'network': 'BTC', 'withdrawal': coin_fee,
         'minimum': 0.001, 'supported': True, 'confidence': 'manual',
         'source': 'assistant', 'fetched_at': stamp, 'note': ''},
        {'exchange': 'bitunix', 'coin': 'USDT', 'network': 'TRC20', 'withdrawal': 1.0,
         'minimum': 10, 'supported': True, 'confidence': 'auto',
         'source': 'bitunix:public', 'fetched_at': stamp, 'note': ''},
        {'exchange': 'wallex', 'coin': 'USDT', 'network': 'TRC20', 'withdrawal': 1.0,
         'minimum': 10, 'supported': True, 'confidence': 'auto',
         'source': 'wallex:public', 'fetched_at': stamp, 'note': ''},
    ]


def make(tmp_path, fresh=True, with_fees=True, capital=100.0, settings=None):
    """Build a hub with one profitable BTC route (A:BTC:wallex) and its fees."""
    store = Storage(str(pathlib.Path(tmp_path) / 'home.db'))
    store.init_scanner()
    settings = settings or main.AppSettings(
        bitunix={'maker': .05, 'taker': .06}, bitunix_usdt={'maker': .05, 'taker': .06},
        wallex={'maker': .3, 'taker': .35, 'withdrawal': .8},
        nobitex={'maker': .3, 'taker': .35, 'withdrawal': .7},
        wallex_usdt={'maker': .3, 'taker': .35},
        nobitex_usdt={'maker': .3, 'taker': .35})
    if with_fees:
        store.upsert_fees(fee_rows(fresh=fresh))
    gateway = FakeGateway()
    hub = Hub(store, gateway, lambda: settings)
    hub.bitunix[('BTC', 'USDT')] = Market('bitunix', 'BTC', 'USDT', 'BTCUSDT')
    hub.iran['wallex'][('BTC', 'toman')] = Market('wallex', 'BTC', 'toman', 'BTCIRT')
    hub.iran['wallex'][('USDT', 'toman')] = Market('wallex', 'USDT', 'toman', 'USDTIRT')
    hub.rebuild_routes()
    hub.tickers[('bitunix', 'BTC', 'USDT')] = Ticker(
        'bitunix', 'BTC', 'USDT', 100.1, 100.0, NOW, True, 'bulk', last=100.0)
    hub.tickers[('wallex', 'BTC', 'toman')] = Ticker(
        'wallex', 'BTC', 'toman', 6_600_100, 6_600_000, NOW, True, 'bulk')
    hub.tickers[('wallex', 'USDT', 'toman')] = Ticker(
        'wallex', 'USDT', 'toman', 60_000, 59_900, NOW, True, 'bulk')
    hub.books[('bitunix', 'BTC', 'USDT')] = DepthBook(
        'bitunix', 'BTC', 'USDT', [(100, 100)], [(99.9, 100)], NOW, True, 'fixture')
    hub.books[('wallex', 'BTC', 'toman')] = DepthBook(
        'wallex', 'BTC', 'toman', [(6_600_000, 100)], [(6_600_000, 100)], NOW, True, 'fixture')
    hub.books[('wallex', 'USDT', 'toman')] = DepthBook(
        'wallex', 'USDT', 'toman', [(60_000, 1e9)], [(59_900, 1e9)], NOW, True, 'fixture')
    cfg = hub.config()
    cfg['networks'] = {'BTC': 'BTC', 'USDT': 'TRC20'}
    cfg['capital_usdt'] = capital
    store.save_scanner_settings(cfg)
    hub.invalidate()
    return SimpleNamespace(store=store, settings=settings, hub=hub, gateway=gateway,
                           cfg=cfg, tracker=OpportunityTracker(store),
                           scanner=Scanner(store))


def install(env, monkeypatch=None):
    """Point the FastAPI module at the fixture and return a TestClient."""
    from fastapi.testclient import TestClient

    values = {'store': env.store, 'settings': env.settings, 'gateway': env.gateway,
              'hub': env.hub, 'tracker': env.tracker, 'scanner': env.scanner,
              'monitor': env.gateway.monitor}
    for name, value in values.items():
        if monkeypatch is not None:
            monkeypatch.setattr(main, name, value)
        else:
            setattr(main, name, value)
    return TestClient(main.app)


def payload():
    """The exact JSON the browser tests need (home + receipt + fees + setup)."""
    import tempfile

    from fastapi.testclient import TestClient

    env = make(tempfile.mkdtemp())
    for name, value in {'store': env.store, 'settings': env.settings,
                        'gateway': env.gateway, 'hub': env.hub,
                        'tracker': env.tracker, 'scanner': env.scanner}.items():
        setattr(main, name, value)
    client = TestClient(main.app)
    home = client.get('/api/home').json()
    key = (home.get('best') or {}).get('key') or 'A:BTC:wallex'
    return {'home': home,
            'receipt': client.get('/api/receipt', params={'key': key}).json(),
            'fees': client.get('/api/fees').json(),
            'wizard': client.get('/api/setup').json(),
            'key': key}
