"""Refresh strategy helpers: staleness, hot-row selection, request pacing.

Pure functions only, so the behaviour is easy to test and the scanner loop stays thin.
"""
import math
import time


def age_of(timestamp, now=None):
    if timestamp is None:
        return None
    now = time.time() if now is None else now
    return max(0.0, now - float(timestamp))


def is_stale(timestamp, stale_seconds=120, now=None):
    """Stale quotes are never used for profit — they are only shown, clearly marked."""
    age = age_of(timestamp, now)
    return age is None or age > stale_seconds


def rank_value(row):
    """Ranking value for hot-row selection.

    Net profit is used when it is known; otherwise the reference spread from tickers/last
    prices keeps a not-yet-depth-checked market eligible for a depth request.
    """
    for key in ('net_pct', 'reference_pct', 'gross_pct'):
        value = row.get(key)
        if value is not None and isinstance(value, (int, float)) and math.isfinite(value):
            return float(value)
    return None


def select_hot(rows, limit=20, visible=(), pinned=()):
    """Top-N by profit percentage plus every pinned or currently visible row.

    Returns row keys in priority order. Rows without any comparable value are skipped
    rather than being treated as zero-profit.
    """
    by_key = {row.get('key'): row for row in rows}
    chosen, seen = [], set()

    def add(key):
        if key in seen or key not in by_key:
            return
        seen.add(key)
        chosen.append(key)

    for key in list(pinned):
        add(key)
    for key in list(visible):
        add(key)
    ranked = []
    for row in rows:
        value = rank_value(row)
        if value is None or row.get('key') in seen:
            continue
        ranked.append((value, row.get('key')))
    ranked.sort(key=lambda item: item[0], reverse=True)
    for _, key in ranked[:max(0, int(limit))]:
        add(key)
    return chosen


def depth_targets(rows, hot_keys, book_keys_for_row, fresh, batch=6):
    """Which depth books to request this tick, in priority order.

    ``book_keys_for_row`` maps a row key to the depth book keys it needs and ``fresh`` is a
    callable telling whether a book is still fresh enough to reuse.
    """
    ordered, seen = [], set()
    for key in hot_keys:
        for book_key in book_keys_for_row.get(key, ()):  # keeps priority order
            if book_key in seen or fresh(book_key):
                continue
            seen.add(book_key)
            ordered.append(book_key)
            if len(ordered) >= max(1, int(batch)):
                return ordered
    return ordered
