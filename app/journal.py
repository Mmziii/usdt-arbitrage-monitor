"""Local manual trade journal: records real trades so they can be compared with estimates."""
import csv
import io
import math
import re
import time

from .symbols import normalize

ROUTES = ('A', 'B', 'direct_iran_to_bitunix', 'direct_bitunix_to_iran', 'classic', 'other')
MODES = ('transfer', 'prefunded')
DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class JournalError(ValueError):
    pass


def validate(values, now=None):
    """Validate a manual entry. Nothing is inferred; bad input is rejected in Persian."""
    now = time.time() if now is None else now
    date = str(values.get('date') or '').strip()
    if not DATE_PATTERN.match(date):
        raise JournalError('تاریخ باید به شکل ۲۰۲۵-۰۳-۰۱ باشد')
    try:
        time.strptime(date, '%Y-%m-%d')
    except ValueError:
        raise JournalError('تاریخ معتبر نیست')
    try:
        coin = normalize(values.get('coin'))
    except ValueError:
        raise JournalError('نماد ارز نامعتبر است')
    route = values.get('route') or 'other'
    if route not in ROUTES:
        raise JournalError('مسیر نامعتبر است')
    mode = values.get('mode') or 'transfer'
    if mode not in MODES:
        raise JournalError('حالت معامله نامعتبر است')

    def number(key, label):
        value = values.get(key)
        if value is None or value == '':
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise JournalError(f'{label} باید عدد باشد')
        if not math.isfinite(value):
            raise JournalError(f'{label} نامعتبر است')
        return value

    capital = number('capital', 'سرمایه')
    final_amount = number('final_amount', 'مبلغ نهایی')
    profit = number('profit', 'سود')
    if capital is not None and capital <= 0:
        raise JournalError('سرمایه باید مثبت باشد')
    if profit is None and capital is not None and final_amount is not None:
        profit = final_amount - capital
    fees = values.get('fees')
    if fees is not None and not isinstance(fees, str):
        fees = str(fees)
    note = values.get('note')
    if note is not None and not isinstance(note, str):
        note = str(note)
    return {'date': date, 'coin': coin, 'route': route, 'mode': mode, 'capital': capital,
            'final_amount': final_amount, 'profit': profit,
            'fees': (fees or '')[:200], 'note': (note or '')[:500], 'created': now}


def export_csv(rows):
    stream = io.StringIO()
    columns = ['id', 'date', 'coin', 'route', 'mode', 'capital', 'final_amount', 'profit',
               'fees', 'note']
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return '\ufeff' + stream.getvalue()
