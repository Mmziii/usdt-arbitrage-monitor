"""Persian explanations for failed market-data requests, plus clock-skew checks.

Every message says *what happened* and *what the user can try*, because the target user is
non-technical and runs the app on Windows.
"""
import time

from .net import budgets

STATUS_LABELS = {'ok': 'سالم', 'error': 'خطا', 'stale': 'داده قدیمی', 'unknown': 'نامعلوم',
                 'paused': 'متوقف'}

# code -> (message, action)
REASONS = {
    'ok': ('درخواست موفق بود.', ''),
    'http_429': ('صرافی می‌گوید درخواست‌ها زیاد است (محدودیت نرخ).',
                 'فاصله به‌روزرسانی را بیشتر کنید یا چند دقیقه صبر کنید؛ برنامه خودش عقب می‌کشد.'),
    'http_4xx': ('صرافی درخواست را نپذیرفت (خطای ۴xx).',
                 'آدرس را در مرورگر باز کنید؛ اگر صفحه تغییر کرده، نسخه برنامه به‌روزرسانی لازم دارد.'),
    'http_5xx': ('خطای داخلی صرافی (۵xx).', 'چند دقیقه بعد دوباره «تست اتصال» را بزنید.'),
    'blocked': ('صرافی دسترسی را بست (۴۰۱/۴۰۳/۴۵۱).',
                'VPN یا پروکسی را خاموش کنید، سپس دوباره تست کنید. اگر باز هم بسته بود، صرافی دسترسی این کشور را محدود کرده است.'),
    'timeout': ('پاسخ صرافی در زمان مجاز نرسید.',
                'اتصال اینترنت و VPN را بررسی کنید؛ اگر VPN روشن است آن را خاموش کنید و دوباره تست کنید.'),
    'network': ('اتصال به صرافی برقرار نشد.',
                'اینترنت را بررسی کنید، VPN را خاموش کنید، و آدرس را در مرورگر باز کنید.'),
    'not_json': ('پاسخ صرافی JSON معتبر نبود (احتمالاً صفحه خطا، کپچا یا بلاک).',
                 'آدرس را در مرورگر باز کنید. اگر صفحه بلاک/کپچا دیدید VPN را خاموش کنید یا کمی بعد دوباره تست کنید.'),
    'shape': ('ساختار پاسخ با مستندات صرافی نمی‌خواند.',
              'پاسخ خام را در همین صفحه ببینید؛ اگر صرافی قالب را تغییر داده، نسخه برنامه به‌روزرسانی لازم دارد.'),
    'missing_field': ('یکی از فیلدهای لازم در پاسخ صرافی وجود ندارد.',
                      'پاسخ خام را ببینید. ممکن است بازار بسته یا نماد حذف شده باشد.'),
    'unexpected_unit': ('واحد قیمت با انتظار نمی‌خواند (احتمالاً ریال به‌جای تومان یا برعکس).',
                        'این مورد را گزارش کنید؛ برنامه برای جلوگیری از محاسبه سود غلط، داده را رد می‌کند.'),
    'stale_timestamp': ('زمان داده صرافی قدیمی است و برای محاسبه سود استفاده نمی‌شود.',
                        'ساعت ویندوز را همگام کنید (Settings > Time & Language > Sync now) و دوباره تست کنید.'),
    'timestamp_unreliable': ('صرافی زمان معتبری نفرستاد؛ زمان دریافت محلی استفاده می‌شود.',
                             'اگر ساعت ویندوز درست باشد، این حالت مشکلی ایجاد نمی‌کند.'),
    'empty_book': ('دفتر سفارش خالی بود.', 'کمی بعد دوباره تست کنید؛ ممکن است بازار تازه باز شده باشد.'),
    'crossed_book': ('دفتر سفارش غیرعادی بود (خرید بالاتر از فروش).',
                     'داده برای محاسبه سود استفاده نمی‌شود؛ چند ثانیه بعد دوباره تست کنید.'),
    'unsuccessful_status': ('صرافی پاسخ را «ناموفق» علامت زده است.',
                            'آدرس را در مرورگر باز کنید و پیام صرافی را ببینید.'),
    'symbol_missing': ('نماد در پاسخ صرافی پیدا نشد.',
                       '«به‌روزرسانی بازارها» را در صفحه عیب‌یابی بزنید تا فهرست بازارها دوباره خوانده شود.'),
    'budget': ('سهمیه درخواست این صرافی پر شده است؛ برنامه عمداً صبر می‌کند.',
               'چند لحظه صبر کنید. برای درخواست کمتر، فاصله به‌روزرسانی را بیشتر کنید.'),
    'unknown': ('خطای ناشناخته.', 'دوباره تست کنید و اگر تکرار شد پاسخ خام را ببینید.'),
}


def describe(code, detail=''):
    message, action = REASONS.get(code, REASONS['unknown'])
    return {'code': code if code in REASONS else 'unknown', 'message': message,
            'action': action, 'detail': detail or ''}


def clock_check(skew_seconds, limit=60.0):
    """Compare the laptop clock with the exchange's HTTP Date header."""
    if skew_seconds is None:
        return {'level': 'unknown', 'skew_seconds': None,
                'message': 'اختلاف ساعت هنوز اندازه‌گیری نشده است.',
                'action': 'یک بار «تست اتصال» را بزنید.'}
    skew = float(skew_seconds)
    if abs(skew) > limit:
        return {'level': 'warn', 'skew_seconds': round(skew, 1),
                'message': f'ساعت ویندوز شما حدود {round(abs(skew))} ثانیه با ساعت صرافی اختلاف دارد'
                           f' ({"عقب" if skew > 0 else "جلو"}).',
                'action': 'ساعت ویندوز را همگام کنید: Settings > Time & Language > Sync now. '
                          'تا وقتی اختلاف بیش از ۶۰ ثانیه است، قانون «زمان قدیمی» نوبیتکس می‌تواند داده سالم را رد کند؛ '
                          'برنامه در این حالت داده را فقط بر اساس زمان دریافت محلی می‌سنجد.'}
    return {'level': 'ok', 'skew_seconds': round(skew, 1),
            'message': f'اختلاف ساعت حدود {round(abs(skew))} ثانیه است.', 'action': ''}


def build(monitor, clock_limit=60.0, exchange_labels=None, statuses=None, paused=False,
          extra=None):
    """Assemble the payload of the diagnostics page."""
    labels = exchange_labels or {}
    statuses = statuses or {}
    exchanges = {}
    names = sorted(set(list(monitor.logs.keys()) + list(monitor.endpoints.keys()) + list(statuses)))
    for name in names:
        last = monitor.last_failure.get(name)
        recent = monitor.log(name, 1)
        last_success = monitor.last_success.get(name)
        clock_state = monitor.clock_state.get(name, {})
        skew = clock_state.get('skew_seconds')
        entry = {
            'label': labels.get(name, name),
            'status': statuses.get(name, 'ok' if last_success else 'unknown'),
            'last_success': last_success,
            'last_success_age': None if last_success is None else round(time.time() - last_success, 1),
            'endpoints_in_use': monitor.endpoints.get(name, {}),
            'clock': {**clock_check(skew, clock_limit), 'checked_at': clock_state.get('checked_at'),
                      'samples': clock_state.get('samples', 0)},
            'last_request': recent[0] if recent else None,
            'log': monitor.log(name, 12),
            'budget': budgets().get(name).stats() if name in budgets() else None,
        }
        if last:
            entry['error'] = describe(last.reason, last.detail)
        exchanges[name] = entry
    return {'generated_at': time.time(), 'paused': paused,
            'exchanges': exchanges, 'budgets': {n: b.stats() for n, b in budgets().items()},
            'extra': extra or {}, 'reason_catalog': {k: describe(k) for k in REASONS}}
