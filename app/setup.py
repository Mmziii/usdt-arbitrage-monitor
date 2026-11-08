"""What the user actually has: which exchanges and where the money is.

The home screen asks two plain questions and this module turns the answers into
(a) which routes are usable at all and (b) the trading mode (transfer vs pre-funded).
Pure functions only.
"""
from .adapters import EXCHANGE_LABELS

EXCHANGES = ('wallex', 'nobitex', 'bitunix')
MONEY = {
    'toman_iran': 'تومان در ایران',
    'usdt': 'تتر',
    'coins_both': 'موجودی در هر دو صرافی',
}
DEFAULT = {
    'exchanges': ['wallex', 'nobitex', 'bitunix'],
    'money': 'toman_iran',
    'capital_toman': 10_000_000,
    'capital_usdt': 100,
    'notify': False,
}


def normalize(setup):
    """Fill gaps and drop unknown values; never crash on a hand-edited settings file."""
    setup = setup or {}
    exchanges = [name for name in (setup.get('exchanges') or [])
                 if name in EXCHANGES]
    if not exchanges:
        exchanges = list(DEFAULT['exchanges'])
    money = setup.get('money')
    if money not in MONEY:
        money = DEFAULT['money']
    result = {**DEFAULT, **setup, 'exchanges': exchanges, 'money': money,
              'notify': bool(setup.get('notify', DEFAULT['notify']))}
    for key in ('capital_toman', 'capital_usdt'):
        try:
            value = float(result.get(key) or DEFAULT[key])
        except (TypeError, ValueError):
            value = float(DEFAULT[key])
        result[key] = value if value > 0 else float(DEFAULT[key])
    return result


def trading_mode(setup):
    """Money already on both sides -> pre-funded; otherwise a real transfer is needed."""
    return 'prefunded' if normalize(setup)['money'] == 'coins_both' else 'transfer'


def route_venues(row):
    pair = row.get('venue_pair') or []
    venues = [venue for venue in pair if venue]
    if not venues:
        for key in ('buy_venue', 'sell_venue', 'iran'):
            if row.get(key):
                venues.append(row[key])
    return list(dict.fromkeys(venues))


def route_allowed(row, setup):
    """Return ``(allowed, reason)`` for one candidate row."""
    setup = normalize(setup)
    venues = route_venues(row)
    missing = [venue for venue in venues if venue not in setup['exchanges']]
    if missing:
        names = '، '.join(EXCHANGE_LABELS.get(name, name) for name in missing)
        return False, f'حساب {names} را ندارید.'
    if not venues:
        return False, 'صرافی‌های این مسیر مشخص نیست.'
    return True, ''


def filter_rows(rows, setup):
    allowed, excluded = [], []
    for row in rows or []:
        ok, reason = route_allowed(row, setup)
        if ok:
            allowed.append(row)
        else:
            excluded.append({'key': row.get('key'), 'coin': row.get('coin'),
                             'label': row.get('route_label') or row.get('route'),
                             'reason': reason})
    return {'rows': allowed, 'excluded': excluded}


def summary(setup):
    setup = normalize(setup)
    return {
        'exchanges': setup['exchanges'],
        'exchange_labels': [EXCHANGE_LABELS.get(name, name) for name in setup['exchanges']],
        'money': setup['money'],
        'money_label': MONEY[setup['money']],
        'mode': trading_mode(setup),
        'mode_label': 'بدون انتقال (موجودی از پیش)' if trading_mode(setup) == 'prefunded'
                      else 'با انتقال بین صرافی‌ها',
        'capital_toman': setup['capital_toman'],
        'capital_usdt': setup['capital_usdt'],
        'notify': setup['notify'],
        'money_options': [{'value': key, 'label': value} for key, value in MONEY.items()],
    }
