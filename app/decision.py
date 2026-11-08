"""One pure function answers the home screen's only question: "is now a good moment?"

Inputs are plain dictionaries so the rules can be unit-tested without a network, a book or a
database. Nothing here predicts the future: every check is about the numbers that exist
right now, how fresh they are and how sure we are about the fees behind them.
"""
import math

VERDICTS = {'go': 'برو', 'wait': 'صبر کن', 'no': 'نه', 'unsure': 'نامطمئن'}
ICONS = {'go': '✔', 'wait': '⏳', 'no': '✕', 'unsure': '؟'}
TONES = {'go': 'good', 'wait': 'warn', 'no': 'bad', 'unsure': 'unknown'}
DEFAULT_MARGIN = 0.3
DEFAULT_STALE_SECONDS = 120

CHECK_OK, CHECK_WARN, CHECK_FAIL, CHECK_INFO = 'ok', 'warn', 'fail', 'info'


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _check(status, title, text):
    return {'status': status, 'title': title, 'text': text}


def fee_verdict(fees):
    """Summarise the confidence of the fees a route needs.

    ``fees`` is a list of ``{'name', 'confidence', 'stale'}``.
    """
    entries = list(fees or [])
    unknown = [item for item in entries if item.get('confidence') == 'unknown']
    estimated = [item for item in entries if item.get('confidence') == 'estimated']
    stale = [item for item in entries if item.get('stale')]
    if unknown:
        return {'level': 'low', 'blocking': unknown, 'estimated': estimated, 'stale': stale}
    if estimated or stale:
        return {'level': 'medium', 'blocking': [], 'estimated': estimated, 'stale': stale}
    return {'level': 'high', 'blocking': [], 'estimated': [], 'stale': []}


def decide(context):
    """Return ``{verdict, label, icon, tone, checks, confidence, summary, numbers}``."""
    context = context or {}
    margin = _num(context.get('margin'))
    margin = DEFAULT_MARGIN if margin is None else margin
    net_pct = _num(context.get('net_pct'))
    gross_pct = _num(context.get('gross_pct'))
    other_pct = _num(context.get('other_costs_pct')) or 0.0
    stale_seconds = _num(context.get('stale_seconds')) or DEFAULT_STALE_SECONDS
    age = _num(context.get('data_age'))
    depth_ok = context.get('depth_ok')
    capital_ok = context.get('capital_ok')
    status = str(context.get('status') or 'ok')
    fees = list(context.get('fees') or [])
    fee_state = fee_verdict(fees)
    lifetime = _num(context.get('lifetime_minutes'))
    transfer = _num(context.get('transfer_minutes'))
    net_after_other = None if net_pct is None else net_pct - other_pct

    checks = []
    blocking = False

    # 1. Are the prices fresh enough to talk about at all?
    if status in ('stale',):
        checks.append(_check(CHECK_FAIL, 'تازگی قیمت‌ها',
                             'قیمت‌های این مسیر قدیمی‌اند؛ تا به‌روزرسانی بعدی صبر کنید.'))
        blocking = True
    elif age is not None and age > stale_seconds:
        checks.append(_check(CHECK_FAIL, 'تازگی قیمت‌ها',
                             f'آخرین قیمت {round(age)} ثانیه پیش ثبت شده و کهنه است.'))
        blocking = True
    elif age is None:
        checks.append(_check(CHECK_WARN, 'تازگی قیمت‌ها', 'زمان آخرین قیمت معلوم نیست.'))
    else:
        checks.append(_check(CHECK_OK, 'تازگی قیمت‌ها',
                             f'قیمت‌ها {round(age)} ثانیه پیش خوانده شده‌اند.'))

    # 2. Is the whole journey computable? (fees, books, networks)
    if status in ('depth needed', 'error', 'fee unknown', 'minimum unknown',
                  'network unknown', 'no common network'):
        checks.append(_check(CHECK_FAIL, 'داده‌های لازم',
                             context.get('status_text') or
                             'برای این مسیر داده یا کارمزد لازم هنوز کامل نیست.'))
        blocking = True
    elif net_pct is None:
        checks.append(_check(CHECK_FAIL, 'داده‌های لازم', 'سود خالص این مسیر قابل محاسبه نیست.'))
        blocking = True

    # 3. Depth and capacity for this exact capital.
    if depth_ok is False:
        checks.append(_check(CHECK_FAIL, 'عمق بازار',
                             context.get('depth_text') or
                             'دفتر سفارش برای این سرمایه کافی نیست.'))
        blocking = True
    elif capital_ok is False:
        checks.append(_check(CHECK_FAIL, 'عمق بازار',
                             'سرمایه شما از عمق قابل مشاهده این بازار بیشتر است.'))
        blocking = True
    elif depth_ok is True:
        checks.append(_check(CHECK_OK, 'عمق بازار', 'عمق دفتر سفارش برای سرمایه شما کافی است.'))

    # 4. Profit after every cost, compared with the safety margin.
    if net_after_other is not None:
        pct = round(net_after_other, 2)
        if net_after_other <= 0:
            checks.append(_check(CHECK_FAIL, 'سود بعد از همه کارمزدها',
                                 f'{pct}٪ — با این هزینه‌ها این مسیر سود نمی‌دهد.'))
        elif net_after_other <= margin:
            checks.append(_check(CHECK_WARN, 'حاشیه ایمنی',
                                 f'{pct}٪ سود هست، ولی کمتر از حاشیه ایمنی {round(margin, 2)}٪ '
                                 'برای پوشش تغییر قیمت در زمان انتقال.'))
        else:
            checks.append(_check(CHECK_OK, 'سود بعد از همه کارمزدها',
                                 f'{pct}٪ سود خالص، بالاتر از حاشیه ایمنی {round(margin, 2)}٪.'))
        if other_pct:
            checks.append(_check(CHECK_WARN, 'هزینه‌های دیگر',
                                 f'{round(other_pct, 2)}٪ هزینه اضافه (مثل انتقال بانکی) از سود کم شد.'))

    # 5. Fee confidence.
    if fee_state['level'] == 'low':
        names = '، '.join(item.get('name') or 'کارمزد' for item in fee_state['blocking'])
        checks.append(_check(CHECK_FAIL, 'کارمزدها',
                             f'کارمزد نامعلوم: {names}. تا وارد نشود سود خالص را نمی‌گوییم.'))
        blocking = True
    elif fee_state['level'] == 'medium':
        parts = []
        if fee_state['estimated']:
            parts.append('تخمینی: ' + '، '.join(item.get('name') or 'کارمزد'
                                               for item in fee_state['estimated']))
        if fee_state['stale']:
            parts.append('نیاز به بررسی دوباره: ' + '، '.join(item.get('name') or 'کارمزد'
                                                              for item in fee_state['stale']))
        checks.append(_check(CHECK_WARN, 'کارمزدها', '؛ '.join(parts)))
    else:
        checks.append(_check(CHECK_OK, 'کارمزدها', 'کارمزدهای لازم تأیید شده و تازه‌اند.'))

    # 6. Typical lifetime of the opportunity versus the transfer time.
    if lifetime is not None and transfer is not None:
        if lifetime < transfer:
            checks.append(_check(CHECK_WARN, 'عمر فرصت',
                                 f'فرصت‌های این مسیر معمولاً {round(lifetime)} دقیقه دوام می‌آورند '
                                 f'ولی انتقال {round(transfer)} دقیقه طول می‌کشد.'))
        else:
            checks.append(_check(CHECK_OK, 'عمر فرصت',
                                 f'فرصت معمولاً {round(lifetime)} دقیقه دوام می‌آورد و انتقال '
                                 f'{round(transfer)} دقیقه است.'))
    elif transfer is not None:
        checks.append(_check(CHECK_INFO, 'عمر فرصت',
                             'هنوز تاریخچه کافی برای «چند دقیقه دوام می‌آورد» نداریم.'))
    else:
        checks.append(_check(CHECK_INFO, 'زمان انتقال',
                             'زمان انتقال این شبکه تنظیم نشده؛ برآورد زمان ممکن نیست.'))

    if gross_pct is not None and net_pct is not None:
        checks.append(_check(CHECK_INFO, 'اختلاف خام در برابر سود خالص',
                             f'اختلاف خام {round(gross_pct, 2)}٪ بود و پس از کارمزدها '
                             f'{round(net_pct, 2)}٪ ماند.'))

    # Verdict.
    if blocking:
        verdict = 'unsure'
    elif net_after_other is None:
        verdict = 'unsure'
    elif net_after_other <= 0:
        verdict = 'no'
    elif net_after_other <= margin:
        verdict = 'wait'
    elif fee_state['level'] == 'medium':
        verdict = 'wait'
    elif lifetime is not None and transfer is not None and lifetime < transfer:
        verdict = 'wait'
    else:
        verdict = 'go'

    confidence = fee_state['level']
    if blocking or age is None:
        confidence = 'low'
    return {
        'verdict': verdict, 'label': VERDICTS[verdict], 'icon': ICONS[verdict],
        'tone': TONES[verdict], 'checks': checks,
        'confidence': confidence,
        'confidence_label': {'high': 'بالا', 'medium': 'متوسط', 'low': 'پایین'}[confidence],
        'numbers': {'net_pct': net_pct, 'net_after_other_pct': net_after_other,
                    'gross_pct': gross_pct, 'margin': margin,
                    'other_costs_pct': other_pct, 'data_age': age,
                    'lifetime_minutes': lifetime, 'transfer_minutes': transfer},
        'estimate_only': True,
    }


def summary_text(result, coin=None, venue_pair=None):
    """One plain sentence for the big card."""
    verdict = result['verdict']
    numbers = result.get('numbers') or {}
    net = numbers.get('net_after_other_pct')
    pct = '—' if net is None else f'{net:+.2f}٪'
    where = ''
    if coin and venue_pair and len(venue_pair) >= 2:
        where = f' ({coin})'
    if verdict == 'go':
        return f'شرایط برای انجام این معامله مناسب است{where}: حدود {pct} سود خالص تخمینی.'
    if verdict == 'wait':
        return (f'این معامله الان {pct} سود نشان می‌دهد ولی هنوز به حاشیه ایمنی '
                'یا اطمینان کافی نرسیده؛ صبر کنید.')
    if verdict == 'no':
        return f'با هزینه‌های فعلی این مسیر سود نمی‌دهد ({pct}).'
    return 'برای قضاوت مطمئن، داده یا کارمزد بیشتری لازم است.'
