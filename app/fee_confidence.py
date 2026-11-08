"""Fee confidence: every fee row knows where it came from and how old it is.

Levels (Persian labels are what the user sees):

``auto``       تأیید خودکار — read from the exchange's own public response, with a date
``manual``     تأیید دستی   — typed or pasted by the user, with a date
``estimated``  تخمینی       — a shipped rough default, never presented as exact
``unknown``    نامعلوم      — no value at all

Nothing in this module invents a number: a fee without a value stays ``unknown`` and keeps
blocking the net-profit verdict.
"""
import math
import time

CONFIDENCE = ('auto', 'manual', 'estimated', 'unknown')
LABELS = {'auto': 'تأیید خودکار', 'manual': 'تأیید دستی',
          'estimated': 'تخمینی', 'unknown': 'نامعلوم'}
SHORT = {'auto': 'خودکار', 'manual': 'دستی', 'estimated': 'تخمینی', 'unknown': 'نامعلوم'}
REVIEW_TEXT = 'نیاز به بررسی دوباره'
DEFAULT_STALE_DAYS = 14


def normalize(value):
    text = str(value or '').strip().lower()
    return text if text in CONFIDENCE else 'manual'


def label(value):
    return LABELS.get(normalize(value), LABELS['manual'])


def age_days(fetched_at, now=None):
    if not fetched_at:
        return None
    now = time.time() if now is None else now
    try:
        seconds = float(now) - float(fetched_at)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds):
        return None
    return max(0.0, seconds / 86400.0)


def is_stale(fetched_at, stale_days=DEFAULT_STALE_DAYS, now=None):
    """True when a value is old enough that the user should look at it again."""
    age = age_days(fetched_at, now)
    if age is None:
        return False
    return age > max(0.0, float(stale_days))


def describe(row, now=None, stale_days=DEFAULT_STALE_DAYS):
    """Public metadata for one fee row; safe to JSON-serialize into the UI."""
    confidence = normalize(row.get('confidence'))
    has_value = row.get('withdrawal') is not None
    if not has_value:
        confidence = 'unknown'
    fetched = row.get('fetched_at')
    age = age_days(fetched, now)
    stale = has_value and is_stale(fetched, stale_days, now)
    if not has_value:
        status = 'نامعلوم'
    elif stale:
        status = REVIEW_TEXT
    elif age is None and confidence in ('manual', 'auto'):
        status = 'بدون تاریخ ثبت'
    else:
        status = label(confidence)
    return {'confidence': confidence, 'label': label(confidence), 'status': status,
            'source': row.get('source') or '', 'fetched_at': fetched,
            'age_days': None if age is None else round(age, 2),
            'stale': bool(stale),
            'needs_review': bool(stale or not has_value or (has_value and age is None)),
            'note': row.get('note') or ''}


def annotate(rows, now=None, stale_days=DEFAULT_STALE_DAYS):
    """Copy of ``rows`` with a ``meta`` block added to every row."""
    return [{**row, 'meta': describe(row, now, stale_days)} for row in (rows or [])]


def confidence_score(levels):
    """0..2 score for one fee set: 2 = confirmed, 1 = rough, 0 = missing."""
    scores = []
    for level in levels:
        if level == 'auto' or level == 'manual':
            scores.append(2)
        elif level == 'estimated':
            scores.append(1)
        else:
            scores.append(0)
    return min(scores) if scores else 0


def route_confidence(entries):
    """Combine the fees a route needs into one of high / medium / low.

    ``entries`` is a list of ``describe()`` dicts (one per fee the route actually uses).
    """
    if not entries:
        return {'level': 'low', 'label': 'پایین', 'score': 0,
                'reasons': ['هیچ کارمزدی برای این مسیر تأیید نشده است.']}
    reasons = []
    score = 2
    for entry in entries:
        value = confidence_score([entry.get('confidence')])
        score = min(score, value)
        name = entry.get('name') or entry.get('source') or 'کارمزد'
        if entry.get('confidence') == 'unknown':
            reasons.append(name + ': نامعلوم')
        elif entry.get('stale'):
            reasons.append(name + ': ' + REVIEW_TEXT)
        elif entry.get('confidence') == 'estimated':
            reasons.append(name + ': تخمینی')
    level = {2: 'high', 1: 'medium', 0: 'low'}.get(score, 'low')
    return {'level': level, 'label': {'high': 'بالا', 'medium': 'متوسط', 'low': 'پایین'}[level],
            'score': score,
            'reasons': reasons or ['کارمزدهای لازم تأیید شده‌اند.']}


def merge_rows(existing, incoming):
    """Upsert by (exchange, coin, network) without losing rows the incoming list omits."""
    merged = {(row['exchange'], row['coin'], row['network']): dict(row) for row in existing}
    for row in incoming:
        key = (row['exchange'], row['coin'], row['network'])
        before = merged.get(key, {})
        merged[key] = {**before, **{k: v for k, v in row.items() if v is not None}}
    return sorted(merged.values(), key=lambda row: (row['coin'], row['network'], row['exchange']))


# Shipped trading-fee defaults. A value that still equals one of these was never
# confirmed by the user, so it is shown as "تخمینی" and never supports a "برو" verdict.
SHIPPED_TRADING = {
    ('wallex', 'toman'): (0.25, 0.3),
    ('nobitex', 'toman'): (0.25, 0.25),
    ('wallex', 'USDT'): (0.25, 0.3),
    ('nobitex', 'USDT'): (0.25, 0.25),
    ('bitunix', 'USDT'): None,
}


def trading_fee_tag(settings, exchange, quote, name=None, now=None,
                    stale_days=DEFAULT_STALE_DAYS):
    """Confidence metadata for one exchange's trading fee (maker/taker)."""
    from .tiers import active_fees
    try:
        fees = active_fees(settings, exchange, quote)
    except (AttributeError, KeyError, TypeError):
        fees = {}
    maker, taker = fees.get('maker'), fees.get('taker')
    source = fees.get('fee_source') or 'global'
    name = name or ('کارمزد معامله ' + exchange)
    if maker is None or taker is None:
        return {'name': name, 'confidence': 'unknown', 'label': LABELS['unknown'],
                'status': 'نامعلوم', 'source': source, 'fetched_at': None,
                'age_days': None, 'stale': False, 'needs_review': True, 'note': '',
                'values': {'maker': maker, 'taker': taker}}
    shipped = SHIPPED_TRADING.get((exchange, quote))
    if source.startswith('tier:'):
        confidence = 'manual'
    elif shipped is not None and abs(float(maker) - shipped[0]) < 1e-9 and \
            abs(float(taker) - shipped[1]) < 1e-9:
        confidence = 'estimated'
    else:
        confidence = 'manual'
    return {'name': name, 'confidence': confidence, 'label': LABELS[confidence],
            'status': LABELS[confidence] if confidence != 'estimated' else 'تخمینی',
            'source': source, 'fetched_at': None, 'age_days': None,
            'stale': False, 'needs_review': confidence == 'unknown', 'note': '',
            'values': {'maker': maker, 'taker': taker}}
