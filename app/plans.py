"""Persian step-by-step trade plan and pre-trade checklist, built from live estimates."""
from .adapters import EXCHANGE_LABELS

STAGE_TEXT = {
    'buy_coin': 'خرید {amount} {coin} در {venue}',
    'withdraw_coin': 'برداشت ارز در شبکه {network}',
    'sell_coin': 'فروش ارز در {venue}',
    'convert': 'تبدیل به تتر',
    'withdraw_usdt': 'برداشت تتر در شبکه {network}',
}

UNITS = {'coin': '', 'USDT': 'USDT', 'toman': 'تومان'}


def _venue(route_kind, stage_name):
    """Which exchange performs a stage (kept explicit so the plan is readable)."""
    if route_kind == 'A':
        return {'buy_coin': 'bitunix', 'withdraw_coin': 'bitunix', 'sell_coin': 'iran',
                'convert': 'iran', 'withdraw_usdt': 'iran'}.get(stage_name)
    if route_kind == 'B':
        return {'withdraw_usdt': 'bitunix', 'convert': 'iran', 'buy_coin': 'iran',
                'withdraw_coin': 'iran', 'sell_coin': 'bitunix'}.get(stage_name)
    if route_kind == 'direct_iran_to_bitunix':
        return {'buy_coin': 'iran', 'withdraw_coin': 'iran', 'sell_coin': 'bitunix'}.get(stage_name)
    return {'buy_coin': 'bitunix', 'withdraw_coin': 'bitunix', 'sell_coin': 'iran'}.get(stage_name)


def _fmt(value, digits=6):
    if value is None or isinstance(value, bool):
        return '—'
    try:
        return f'{value:,.{digits}f}'.rstrip('0').rstrip('.')
    except (TypeError, ValueError):
        return str(value)


def venue_for(route, stage):
    """Public alias: which exchange performs a stage of a route."""
    return _venue(route, stage)


def build_plan(row, network=None, capital=None):
    """Turn a calculated row into numbered Persian steps and a checklist.

    Every number is an estimate from the order books captured at ``row['updated_at']``.
    """
    detail = row.get('detail') or {}
    taker = detail.get('taker') or row.get('taker') or {}
    route = row.get('route')
    coin = row.get('coin')
    iran = row.get('iran') or (row.get('venue_pair') or [None, None])[0]
    network = network or row.get('network') or row.get('network_coin') or 'نامعلوم'
    plan = {'coin': coin, 'route': route, 'route_label': row.get('route_label'),
            'capital': capital if capital is not None else row.get('capital'),
            'unit': row.get('capital_unit') or 'USDT', 'network': network,
            'estimates': True, 'ok': bool(taker.get('ok')), 'steps': [], 'checklist': [],
            'warnings': []}
    iran_label = EXCHANGE_LABELS.get(iran, iran or 'صرافی ایرانی')
    bitunix_label = EXCHANGE_LABELS.get('bitunix', 'بیتیونیکس')
    if not taker.get('ok'):
        plan['warnings'].append(taker.get('error') or 'برای این مسیر محاسبه کامل ممکن نیست.')
        return plan
    steps = taker.get('steps') or []
    for index, step in enumerate(steps, 1):
        name = step.get('name')
        venue_key = _venue(route, name)
        venue = bitunix_label if venue_key == 'bitunix' else iran_label
        amount = step.get('value')
        unit = UNITS.get(step.get('unit'), step.get('unit') or '')
        title = STAGE_TEXT.get(name, step.get('label') or name).format(
            amount=_fmt(amount, 6 if unit == '' else 2), coin=coin, venue=venue,
            network=network)
        plan['steps'].append({'n': index, 'stage': name, 'title': title,
                              'venue': venue_key, 'amount': amount, 'unit': step.get('unit'),
                              'note': step.get('label')})
    final = taker.get('final')
    profit = taker.get('profit')
    plan['expected'] = {'final': final, 'profit': profit,
                        'profit_pct': taker.get('profit_pct'),
                        'profit_toman': detail.get('profit_toman') or row.get('net_toman'),
                        'capital': plan['capital']}
    plan['warnings'].extend([
        'همه اعداد تخمینی از دفتر سفارش فعلی هستند؛ قیمت تا رسیدن ارز تغییر می‌کند.',
        'زمان انتقال شبکه تضمینی نیست و ممکن است سود از بین برود.',
    ])
    if row.get('limited_by_visible_depth') or taker.get('limited_by_visible_depth'):
        plan['warnings'].append('سرمایه بیشتر از عمق قابل مشاهده است؛ سود واقعی کمتر خواهد بود.')
    plan['checklist'] = [
        {'id': 'deposit', 'text': f'واریز و برداشت {coin} در هر دو صرافی باز است.'},
        {'id': 'network', 'text': f'شبکه انتخابی ({network}) در هر دو طرف یکی است و memo/tag در صورت نیاز دارد.'},
        {'id': 'minimum', 'text': 'حداقل برداشت و سقف روزانه را با مبلغ هر مرحله مقایسه کنید.'},
        {'id': 'balance', 'text': 'موجودی کافی برای کارمزد معامله و کارمزد برداشت دارید.'},
        {'id': 'test', 'text': 'اول با مبلغ کم آزمایش کنید؛ یک بار کل چرخه را کوچک اجرا کنید.'},
        {'id': 'kyc', 'text': 'دسترسی و احراز هویت صرافی خارجی برای شما فعال است و محدودیت منطقه‌ای وجود ندارد.'},
        {'id': 'memo', 'text': 'آدرس مبدأ و مقصد را دوباره چک کنید؛ آدرس اشتباه بازگشت‌پذیر نیست.'},
    ]
    return plan
