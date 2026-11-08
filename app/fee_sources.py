"""Where withdrawal-fee / network data can come from, per exchange.

Only public endpoints and public pages are used; nothing here logs in, reads a balance or
places an order. The contents of each endpoint could not be inspected in the build sandbox
(outbound exchange hosts are blocked), so every source records how sure we are about it and
the UI falls back to the Fee Assistant whenever a source is missing or unconfirmed.
"""
import time

from .net import Endpoint, ValidationError

# Official fee pages the assistant opens in the user's browser. They are editable in the
# settings page because exchanges move their help pages around.
DEFAULT_FEE_PAGES = {
    'nobitex': 'https://nobitex.ir/fees/',
    'wallex': 'https://wallex.ir/fee/',
    'bitunix': 'https://www.bitunix.com/fee-schedule',
}

# ``status`` is deliberately honest:
#   confirmed  -> documented public endpoint, parsed by a tolerant reader here
#   unconfirmed-> no documented public endpoint found; use the Fee Assistant
SOURCES = {
    'nobitex': {
        'status': 'unconfirmed',
        'endpoint': 'https://apiv2.nobitex.ir/v2/options',
        'endpoint_name': '/v2/options',
        'doc': 'Nobitex documents a public options endpoint listing coins and networks. '
               'Field names (withdrawal fee / minimum / enabled flags) are read tolerantly '
               'and were NOT verified against a live response in this build.',
        'note': 'اگر خواندن خودکار نتواند این پاسخ را بفهمد، کارمزد را با «دستیار کارمزد» وارد کنید.',
    },
    'wallex': {
        'status': 'unconfirmed',
        'endpoint': '',
        'endpoint_name': '',
        'doc': 'No documented public currencies/networks/fees endpoint was found for Wallex. '
               'Automatic import stays off until such an endpoint is confirmed.',
        'note': 'برای والکس کارمزد برداشت را باید از صفحه رسمی کارمزد (همین صفحه در دستیار کارمزد) وارد کنید.',
    },
    'bitunix': {
        'status': 'unconfirmed',
        'endpoint': '',
        'endpoint_name': '',
        'doc': 'The documented Bitunix spot endpoints used here (coin pair list, last price, '
               'depth) carry no withdrawal fee, minimum or network status.',
        'note': 'بیت‌یونیکس در نقاط انتهایی عمومی مستندشده کارمزد برداشت نمی‌دهد؛ از دستیار کارمزد استفاده کنید.',
    },
}

COIN_KEYS = ('coin', 'currency', 'symbol', 'asset', 'coinSymbol')
NETWORK_KEYS = ('network', 'networkName', 'network_name', 'chain', 'protocol', 'networkCode')
FEE_KEYS = ('withdrawalFee', 'withdrawal_fee', 'withdrawFee', 'fee', 'fixedFee', 'withdraw_fee')
MIN_KEYS = ('minWithdrawal', 'withdrawalMin', 'min_withdrawal', 'minWithdraw', 'minimum',
            'withdrawMin', 'minWithdrawAmount')
WITHDRAW_KEYS = ('isWithdrawalEnabled', 'withdrawEnabled', 'withdrawalEnabled', 'withdraw',
                 'withdrawalIsActive', 'canWithdraw')
DEPOSIT_KEYS = ('isDepositEnabled', 'depositEnabled', 'depositIsActive', 'canDeposit')


def _pick(entry, keys):
    for key in keys:
        if key in entry and entry[key] not in (None, ''):
            return entry[key]
    return None


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(',', '').replace('٫', '.').replace(' ', '')
        if text in ('', '-', '—', 'null', 'None'):
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    if not (number == number) or number in (float('inf'), float('-inf')) or number < 0:
        return None
    return number


def _flag(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ('true', '1', 'yes', 'active', 'enabled', 'on'):
        return True
    if text in ('false', '0', 'no', 'inactive', 'disabled', 'off'):
        return False
    return None


def _entries(payload):
    """Flatten the plausible shapes of a public coin/network listing into a list of dicts."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ('options', 'data', 'result', 'networks', 'coins', 'list'):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            flat = []
            for name, item in value.items():
                if isinstance(item, dict):
                    flat.append({'coin': name, **item})
                elif isinstance(item, list):
                    flat.extend({'coin': name, **sub} for sub in item if isinstance(sub, dict))
            if flat:
                return flat
    return []


def parse_options(payload, exchange):
    """Tolerant reader for a public coin/network listing.

    Returns ``(rows, notes)``. Anything that cannot be read with certainty is skipped and
    reported as a note; a fee is never guessed and never defaulted to zero.
    """
    rows, notes = [], []
    for entry in _entries(payload):
        networks = entry.get('networks')
        variants = ([item for item in networks if isinstance(item, dict)]
                    if isinstance(networks, list) and networks else [entry])
        for variant in variants:
            merged = {**entry, **variant}
            coin = _pick(merged, COIN_KEYS)
            network = _pick(merged, NETWORK_KEYS)
            if coin is None or network is None:
                notes.append('ردیفی بدون نام ارز یا شبکه نادیده گرفته شد.')
                continue
            fee = _number(_pick(merged, FEE_KEYS))
            minimum = _number(_pick(merged, MIN_KEYS))
            withdraw = _flag(_pick(merged, WITHDRAW_KEYS))
            deposit = _flag(_pick(merged, DEPOSIT_KEYS))
            supported = None
            if withdraw is not None or deposit is not None:
                supported = bool(withdraw if withdraw is not None else True) and \
                    bool(deposit if deposit is not None else True)
            rows.append({
                'exchange': exchange,
                'coin': str(coin).strip().upper()[:20],
                'network': str(network).strip().upper()[:40],
                'withdrawal': fee,
                'minimum': minimum,
                'supported': True if supported is None else supported,
                'note': '' if supported is not None else 'وضعیت فعال/غیرفعال در پاسخ نبود؛ پشتیبانی‌شده فرض شد.',
                'confidence': 'auto',
                'source': exchange + ':' + (SOURCES[exchange].get('endpoint_name') or 'public'),
                'fetched_at': time.time(),
            })
    if not rows:
        raise ValidationError('shape', 'no coin/network rows in the payload')
    return rows, notes


async def fetch_fees(gateway, exchange, describe):
    """Fetch one exchange's public fee list. Never raises; returns a explained result."""
    source = SOURCES.get(exchange) or {}
    started = time.time()
    result = {'exchange': exchange, 'ok': False, 'rows': [], 'attempted': bool(source.get('endpoint')),
              'status': None, 'reason': 'unavailable', 'fetched_at': started,
              'endpoint': source.get('endpoint') or '',
              'message': source.get('note') or 'منبع خودکار برای این صرافی نداریم.'}
    if not source.get('endpoint'):
        return result
    endpoint = Endpoint('fees', source['endpoint'], kind='fees')
    try:
        async with gateway.make_client() as client:
            fetched = await gateway.fetch(
                client, exchange, endpoint,
                parser=lambda data: parse_options(data, exchange))
    except Exception as exc:                       # noqa: BLE001 - keep the page alive
        result['reason'] = 'unknown'
        result['message'] = 'خواندن کارمزدها ناموفق بود؛ از دستیار کارمزد استفاده کنید.'
        result['detail'] = str(exc)[:200]
        return result
    result['status'] = fetched.status
    result['url'] = fetched.url
    if not fetched.ok:
        described = describe(fetched.reason, fetched.detail)
        result['reason'] = fetched.reason
        result['message'] = (described['message'] + ' ' + described['action']).strip()
        return result
    rows, notes = fetched.data
    result.update(ok=True, rows=rows, reason='ok', notes=notes[:5],
                  message='کارمزد برداشت از پاسخ عمومی صرافی خوانده شد.')
    return result
