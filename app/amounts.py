"""Parse human-friendly amounts written by a non-technical Persian user.

Examples that must work: ``50 میلیون``, ``۵۰ میلیون``, ``50M``, ``2.5 میلیارد``,
``5,000,000``, ``100 هزار``, ``250 usdt``.
"""
import math
import re

DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')

MULTIPLIERS = {
    'هزار': 1e3, 'یک هزار': 1e3, 'k': 1e3, 'thousand': 1e3,
    'میلیون': 1e6, 'ملیون': 1e6, 'میلیون‌': 1e6, 'm': 1e6, 'million': 1e6,
    'میلیارد': 1e9, 'milyard': 1e9, 'b': 1e9, 'billion': 1e9, 'میلیاردی': 1e9,
}

CURRENCIES = {
    'تومان': 'toman', 'تومن': 'toman', 'تومنی': 'toman', 'toman': 'toman', 'tm': 'toman',
    'ت': 'toman', 'ریال': 'rial', 'rial': 'rial',
    'دلار': 'USDT', 'تتر': 'USDT', 'usdt': 'USDT', 'دلاری': 'USDT',
}

MAX_AMOUNT = 1e15


class AmountError(ValueError):
    pass


def normalize_text(text):
    return str(text or '').translate(DIGITS).replace('٫', '.').replace('،', ',').strip()


def parse_amount(text, default_currency=None):
    """Return ``{'value': float, 'currency': 'toman'|'USDT'|'rial'|None, 'raw': text}``."""
    raw = str(text or '')
    cleaned = normalize_text(raw).lower()
    if not cleaned:
        raise AmountError('مبلغ را وارد کنید؛ مثلاً 50 میلیون')
    currency = None
    for word, code in sorted(CURRENCIES.items(), key=lambda item: -len(item[0])):
        if word in cleaned:
            currency = code
            cleaned = cleaned.replace(word, ' ')
            break
    multiplier = 1.0
    scaled = False
    for word, factor in sorted(MULTIPLIERS.items(), key=lambda item: -len(item[0])):
        if re.search(r'(?<![a-z])' + re.escape(word) + r'(?![a-z])', cleaned):
            multiplier = factor
            cleaned = re.sub(r'(?<![a-z])' + re.escape(word) + r'(?![a-z])', ' ', cleaned)
            scaled = True
            break
    cleaned = cleaned.replace(' ', '').replace(',', '').replace('_', '')
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)(?:[a-z]*)([مم]?)(?:یلیون)?', cleaned)
    if not match:
        match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)[^\d]*', cleaned)
    if not match:
        raise AmountError('مبلغ را متوجه نشدم؛ نمونه درست: 50 میلیون یا 50000000')
    number = float(match.group(1))
    if scaled and multiplier == 1e6 and match.group(2):
        multiplier = 1e6
    value = number * multiplier
    if not math.isfinite(value) or value <= 0 or value > MAX_AMOUNT:
        raise AmountError('مبلغ باید عددی مثبت و کمتر از ۱۰ به توان ۱۵ باشد')
    if currency == 'rial':
        value /= 10
        currency = 'toman'
    return {'value': value, 'currency': currency or default_currency, 'raw': raw,
            'multiplier': multiplier}


def format_amount(value, digits=0):
    """Thousands separators with Latin digits; the UI localizes to Persian digits."""
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return '—'
    return f'{value:,.{digits}f}'
