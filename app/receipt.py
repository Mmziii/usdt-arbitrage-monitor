"""The journey receipt: "از صفر تا صد" for one route and one capital.

Every number comes from the same engine that draws the tables (`cycle.evaluate_cycle`), so
the receipt can never disagree with the rest of the app. The steps are numbered in the order
the user would act, each with in/out amounts, its own cost, and a fee-confidence tag.
"""
import math

from .adapters import EXCHANGE_LABELS
from .plans import build_plan, venue_for

UNITS = {'coin': 'واحد ارز', 'USDT': 'USDT', 'toman': 'تومان'}

DISCLAIMER = ('همه اعداد از دفتر سفارش همین لحظه تخمین زده شده‌اند، تضمینی نیستند و '
              'مشاوره مالی محسوب نمی‌شوند. قیمت تا رسیدن ارز تغییر می‌کند؛ قواعد هر صرافی، '
              'مالیات و وضعیت قانونی خودتان را جداگانه بررسی کنید و اول با مبلغ کم آزمایش کنید.')

RISKS = [
    {'id': 'price', 'text': 'قیمت در زمان انتقال تغییر می‌کند و سود را می‌خورد یا صفر می‌کند.'},
    {'id': 'paused', 'text': 'واریز یا برداشت این ارز/شبکه ممکن است در یکی از صرافی‌ها موقتاً بسته شود.'},
    {'id': 'network', 'text': 'شبکه یا memo اشتباه یعنی از دست رفتن پول؛ آدرس و شبکه را دقیق چک کنید.'},
    {'id': 'limits', 'text': 'حداقل برداشت و سقف روزانه ممکن است از مبلغ شما کمتر باشد.'},
    {'id': 'region', 'text': 'صرافی خارجی ممکن است احراز هویت یا محدودیت منطقه‌ای داشته باشد.'},
    {'id': 'liquidity', 'text': 'عمق بازار کم است؛ با حجم بزرگ، قیمت اجرایی بدتر می‌شود.'},
    {'id': 'timing', 'text': 'فرصت ممکن است کوتاه‌تر از زمان انتقال باشد و تا رسیدن ارز تمام شود.'},
]

CHECKLIST = [
    'واریز و برداشت این ارز در هر دو صرافی باز است.',
    'شبکه انتخابی در هر دو طرف یکی است و در صورت نیاز memo/tag را دارید.',
    'مبلغ هر مرحله از حداقل برداشت و سقف روزانه کمتر است.',
    'موجودی کافی برای کارمزد معامله و کارمزد برداشت دارید.',
    'اول با مبلغ کم یک بار کل مسیر را آزمایش می‌کنید.',
    'دسترسی و احراز هویت صرافی خارجی فعال است و محدودیت منطقه‌ای ندارید.',
    'آدرس مبدأ و مقصد را دوباره چک کرده‌اید؛ آدرس اشتباه برنمی‌گردد.',
]


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value, digits=2):
    number = _number(value)
    if number is None:
        return '—'
    text = f'{number:,.{digits}f}'
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text


def step_cost(step, price):
    """Cost of one stage in its own output unit, against the best price of that book.

    ``price`` is the best ask for a buy stage and the best bid for a sell stage. Returns
    ``(cost, percent, ideal_output)`` or ``(None, None, None)`` when the price is unknown.
    A fixed withdrawal stage costs exactly its fee.
    """
    kind = step.get('kind')
    amount_in = _number(step.get('input'))
    amount_out = _number(step.get('value'))
    if kind == 'fixed':
        fee = _number((step.get('meta') or {}).get('amount'))
        if fee is None:
            return None, None, None
        return fee, None, amount_in
    best = _number(price)
    if amount_in is None or amount_out is None or not best or best <= 0:
        return None, None, None
    if kind == 'sell':
        ideal = amount_in * best
    else:
        ideal = amount_in / best
    cost = ideal - amount_out
    percent = (cost / ideal * 100) if ideal else None
    return cost, percent, ideal


def build(row, prices=None, fee_tags=None, other_costs_toman=0, stale_days=14,
          conversion_rate=None, now=None):
    """Build the receipt for one calculated row. All money numbers are estimates."""
    prices = prices or {}
    fee_tags = fee_tags or {}
    detail = row.get('detail') or {}
    taker = detail.get('taker') or row.get('taker') or {}
    route = row.get('route')
    coin = row.get('coin')
    network = row.get('network') or row.get('network_coin') or 'نامعلوم'
    capital = _number(taker.get('capital')) or _number(row.get('capital'))
    receipt = {'key': row.get('key'), 'coin': coin, 'route': route,
               'route_label': row.get('route_label'), 'network': network,
               'capital': capital, 'capital_unit': row.get('capital_unit') or 'USDT',
               'ok': bool(taker.get('ok')), 'steps': [], 'totals': {}, 'checklist': CHECKLIST,
               'risks': RISKS, 'disclaimer': DISCLAIMER,
               'trading_mode': row.get('trading_mode'),
               'mode_label': 'موجودی از قبل در دو طرف' if row.get('trading_mode') == 'prefunded'
                             else 'با انتقال بین صرافی‌ها',
               'estimate_only': True, 'error': taker.get('error') if not taker.get('ok') else None}
    if not taker.get('ok'):
        return receipt

    plan = build_plan(row, network=network)
    plan_steps = plan.get('steps') or []
    steps = taker.get('steps') or []
    running = capital
    previous_unit = row.get('capital_unit') or 'USDT'
    for index, step in enumerate(steps):
        name = step.get('name')
        venue_key = venue_for(route, name)
        venue = EXCHANGE_LABELS.get(venue_key, venue_key or '—')
        plan_step = plan_steps[index] if index < len(plan_steps) else {}
        amount_in = _number(step.get('input'))
        amount_out = _number(step.get('value'))
        cost, percent, _ideal = step_cost(step, (prices.get(name) or {}).get(
            'bid' if step.get('kind') == 'sell' else 'ask'))
        tag = fee_tags.get(name) or fee_tags.get(step.get('kind')) or {}
        receipt['steps'].append({
            'n': index + 1,
            'stage': name,
            'venue': venue_key,
            'venue_label': venue,
            'title': plan_step.get('title') or step.get('label') or name,
            'action': step.get('label') or name,
            'unit_in': previous_unit,
            'unit_out': step.get('unit'),
            'amount_in': amount_in,
            'amount_out': amount_out,
            'cost': cost,
            'cost_pct': percent,
            'confidence': tag.get('confidence') or 'manual',
            'confidence_label': tag.get('label') or 'تأیید دستی',
            'confidence_stale': bool(tag.get('stale')),
        })
        previous_unit = step.get('unit')
        if amount_out is not None:
            running = amount_out

    final = _number(taker.get('final'))
    profit = _number(taker.get('profit'))
    profit_pct = _number(taker.get('profit_pct'))
    gross_pct = _number(row.get('gross_pct'))
    rate = _number(row.get('effective_rate')) or _number(conversion_rate)
    other = _number(other_costs_toman) or 0.0
    other_pct = 0.0 if (rate and capital) else None
    if other and rate and capital:
        other_pct = other / (capital * rate) * 100.0
    profit_after_other = None if profit is None else profit - (other / rate if rate else 0.0)
    pct_after_other = None if profit_pct is None or other_pct is None else profit_pct - other_pct
    costs_pct = None
    if gross_pct is not None and profit_pct is not None:
        costs_pct = gross_pct - profit_pct
    receipt['steps_balance'] = {'start': capital, 'end': running,
                                'end_unit': previous_unit}
    receipt['totals'] = {
        'capital': capital,
        'final': final,
        'final_unit': 'USDT',
        'profit': profit,
        'profit_pct': profit_pct,
        'profit_toman': _number(row.get('net_toman')),
        'rate': rate,
        'gross_pct': gross_pct,
        'costs_pct': costs_pct,
        'other_costs_toman': other,
        'other_costs_pct': other_pct,
        'profit_after_other': profit_after_other,
        'pct_after_other': pct_after_other,
        'price_buffer_pct': profit_pct,
        'breakeven_capital': _number(taker.get('breakeven_capital')),
        'minimum_capital': _number(taker.get('minimum_capital')),
        'limited_by_visible_depth': bool(taker.get('limited_by_visible_depth')),
        'transfer_minutes': (row.get('transfer_time') or {}).get('minutes'),
        'transfer_estimated': (row.get('transfer_time') or {}).get('estimated', True),
        'safety_margin': _number(taker.get('safety_margin')),
        'fee_mode': 'taker',
        'reconciled': (None if final is None or capital is None or profit is None
                       else abs(capital + profit - final) <= max(1e-9, abs(final) * 1e-9)),
    }
    receipt['updated_at'] = row.get('updated_at')
    return receipt


def to_text(receipt, fmt=lambda value, digits: _fmt(value, digits)):
    """Plain-Persian text version of the receipt, for the copy button."""
    lines = []
    title_route = receipt.get('route_label') or ''
    lines.append(f"رسید سفر معامله — {receipt.get('coin') or ''} | {title_route}")
    lines.append(f"شبکه: {receipt.get('network')} | حالت: {receipt.get('mode_label')}")
    lines.append('')
    for step in receipt.get('steps') or []:
        unit_in = UNITS.get(step.get('unit_in'), step.get('unit_in') or '')
        unit_out = UNITS.get(step.get('unit_out'), step.get('unit_out') or '')
        digits = 6 if step.get('unit_out') == 'coin' else 2
        lines.append(f"{step['n']}. {step['title']} ({step['venue_label']})")
        lines.append(f"   ورودی: {fmt(step.get('amount_in'), digits)} {unit_in}"
                     f" → خروجی: {fmt(step.get('amount_out'), digits)} {unit_out}")
        if step.get('cost') is not None:
            cost_digits = 6 if (step.get('unit_out') == 'coin') else 2
            extra = '' if step.get('cost_pct') is None else f" ({fmt(step['cost_pct'], 3)}٪)"
            lines.append(f"   هزینه این مرحله: {fmt(step['cost'], cost_digits)} {unit_out}{extra}")
        lines.append(f"   کارمزد و شبکه: {step['confidence_label']}")
    totals = receipt.get('totals') or {}
    lines.append('')
    lines.append(f"سرمایه شروع: {fmt(totals.get('capital'), 2)} USDT")
    lines.append(f"مبلغ نهایی: {fmt(totals.get('final'), 2)} USDT")
    lines.append(f"سود خالص: {fmt(totals.get('profit'), 2)} USDT "
                 f"({fmt(totals.get('profit_pct'), 2)}٪)")
    if totals.get('profit_toman') is not None:
        lines.append(f"سود به تومان: {fmt(totals.get('profit_toman'), 0)} تومان")
    if totals.get('other_costs_toman'):
        lines.append(f"هزینه‌های دیگر: {fmt(totals['other_costs_toman'], 0)} تومان "
                     f"({fmt(totals.get('other_costs_pct'), 2)}٪)")
    if totals.get('costs_pct') is not None:
        lines.append(f"جمع کارمزد و لغزش: {fmt(totals['costs_pct'], 2)} واحد درصد از اختلاف خام")
    if totals.get('breakeven_capital') is not None:
        lines.append(f"سرمایه سربه‌سر: {fmt(totals['breakeven_capital'], 2)} USDT")
    if totals.get('minimum_capital') is not None:
        lines.append(f"کمترین سرمایه به‌صرفه: {fmt(totals['minimum_capital'], 2)} USDT")
    lines.append('')
    lines.append('چک‌لیست قبل از معامله:')
    for item in receipt.get('checklist') or []:
        lines.append('  ✓ ' + item)
    lines.append('')
    lines.append(receipt.get('disclaimer') or DISCLAIMER)
    return '\n'.join(lines)


def to_csv(rows):
    """CSV of receipt steps (used by the export button)."""
    import csv
    import io
    stream = io.StringIO()
    columns = ['n', 'stage', 'venue', 'title', 'unit_in', 'amount_in', 'unit_out',
               'amount_out', 'cost', 'cost_pct', 'confidence']
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows or [])
    return '\ufeff' + stream.getvalue()
