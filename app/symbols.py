"""Conservative ticker matching: never infer a contract or a token multiplier."""
import re

# Tickers with documented collision/migration risks require manual review.
AMBIGUOUS = {'PAY', 'GAS', 'HOT', 'ONE', 'LUNA', 'LUNC', 'UST', 'USTC', 'POL', 'MATIC'}


def normalize(symbol):
    value = str(symbol).strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{2,20}', value):
        raise ValueError('Invalid symbol')
    return value


def review_reason(symbol):
    if symbol in AMBIGUOUS:
        return 'نماد مبهم یا تغییر نام؛ بررسی دارایی لازم است'
    if re.match(r'^\d+', symbol):
        return 'نماد ضریب‌دار؛ تطبیق واحد و قرارداد لازم است'
    return None
