"""Market-position gauge: where does today's best net % sit inside the last days?

This is a description of recorded history, never a forecast. Until enough history exists the
gauge says so instead of showing a made-up position.
"""
MIN_HOURS = 24
TEXT_NOT_READY = 'برای این بخش حداقل ۲۴ ساعت داده لازم است'


def _clean(values):
    numbers = []
    for value in values or []:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number and abs(number) != float('inf'):
            numbers.append(number)
    return numbers


def percentile(values, current):
    """Share of recorded values that are worse (lower) than ``current``, 0..100."""
    numbers = _clean(values)
    if not numbers or current is None:
        return None
    below = sum(1 for value in numbers if value < current)
    equal = sum(1 for value in numbers if value == current)
    return round((below + 0.5 * equal) / len(numbers) * 100, 1)


def _quantile(sorted_values, fraction):
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    weight = position - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def position(samples, current=None, min_hours=MIN_HOURS, window_hours=None):
    """``samples`` is a list of ``{'timestamp', 'net_pct'}`` over the recorded window."""
    clean = []
    for sample in samples or []:
        value = None
        stamp = None
        if isinstance(sample, dict):
            value = sample.get('net_pct', sample.get('value'))
            stamp = sample.get('timestamp')
        else:
            value = sample
        numbers = _clean([value])
        if not numbers:
            continue
        clean.append({'timestamp': stamp, 'net_pct': numbers[0]})
    values = [item['net_pct'] for item in clean]
    stamps = [float(item['timestamp']) for item in clean
              if isinstance(item['timestamp'], (int, float))]
    hours = 0.0
    if len(stamps) >= 2:
        hours = max(0.0, (max(stamps) - min(stamps)) / 3600.0)
    if current is None and values:
        current = values[-1]
    current = None if current is None else float(current)
    result = {'ready': False, 'hours': round(hours, 1), 'samples': len(values),
              'window_hours': window_hours, 'current': current,
              'message': TEXT_NOT_READY, 'note': 'این نمودار تاریخچه ثبت‌شده است، نه پیش‌بینی.'}
    if len(values) < 2 or hours < min_hours or current is None:
        return result
    ordered = sorted(values)
    result.update(
        ready=True,
        message=f'بهتر از {percentile(values, current):.1f}٪ از زمان‌های همین بازه',
        percentile=percentile(values, current),
        typical_low=round(_quantile(ordered, 0.25), 3),
        typical_high=round(_quantile(ordered, 0.75), 3),
        median=round(_quantile(ordered, 0.5), 3),
        best=round(max(values), 3), worst=round(min(values), 3),
        last=round(values[-1], 3),
    )
    return result


def from_history(rows, current=None, min_hours=MIN_HOURS, window_hours=None):
    """Group ``best_history`` rows by scan timestamp and take the best of each scan."""
    by_stamp = {}
    for row in rows or []:
        stamp = row.get('timestamp')
        value = row.get('net_pct')
        if stamp is None or value is None:
            continue
        numbers = _clean([value])
        try:
            stamp = float(stamp)
        except (TypeError, ValueError):
            continue
        if not numbers:
            continue
        by_stamp.setdefault(stamp, []).append(numbers[0])
    samples = [{'timestamp': stamp, 'net_pct': max(values)}
               for stamp, values in sorted(by_stamp.items())]
    return position(samples, current, min_hours, window_hours)
