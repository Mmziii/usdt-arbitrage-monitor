"""Market gauge: a description of recorded history, never a forecast."""
from app import gauge

HOUR = 3600


def samples(values, start=0.0, step=HOUR):
    return [{'timestamp': start + index * step, 'net_pct': value}
            for index, value in enumerate(values)]


def test_percentile_counts_the_share_of_weaker_moments():
    values = [1, 2, 3, 4]
    assert gauge.percentile(values, 2.5) == 50.0
    assert gauge.percentile(values, 5) == 100.0
    assert gauge.percentile(values, 0) == 0.0
    assert gauge.percentile([], 1) is None


def test_not_enough_history_says_so_instead_of_inventing_a_position():
    result = gauge.position(samples([1, 2, 3]), current=2)
    assert result['ready'] is False
    assert result['message'] == gauge.TEXT_NOT_READY
    assert 'percentile' not in result


def test_less_than_two_samples_is_never_ready():
    result = gauge.position([{'timestamp': 0, 'net_pct': 1}], current=1)
    assert result['ready'] is False


def test_a_full_day_of_history_gives_a_position_and_a_range():
    values = [0.5 + index * 0.1 for index in range(48)]      # 47 hours of data
    result = gauge.position(samples(values), current=9.0)
    assert result['ready'] is True
    assert result['percentile'] == 100.0
    assert result['best'] == max(values)
    assert result['typical_low'] <= result['median'] <= result['typical_high']
    assert 'بهتر از' in result['message'] and '٪' in result['message']


def test_a_middle_value_is_described_honestly():
    values = [1, 2, 3, 4, 5, 6] * 8                        # 47 hours
    result = gauge.position(samples(values), current=3.5)
    assert result['ready'] is True
    assert 0 < result['percentile'] < 100
    assert result['note'] and 'پیش‌بینی' in result['note']


def test_from_history_takes_the_best_net_of_each_scan():
    rows = []
    for index in range(30):
        stamp = index * HOUR
        rows.append({'timestamp': stamp, 'net_pct': 1.0, 'key': 'a'})
        rows.append({'timestamp': stamp, 'net_pct': 2.0, 'key': 'b'})
    result = gauge.from_history(rows, current=2.0)
    assert result['ready'] is True
    assert result['samples'] == 30
    assert result['percentile'] == 50.0


def test_junk_values_are_ignored_not_averaged_in():
    rows = [{'timestamp': 0, 'net_pct': None}, {'timestamp': HOUR, 'net_pct': 'x'},
            {'timestamp': 2 * HOUR, 'net_pct': 1.5}]
    result = gauge.from_history(rows, current=1.5)
    assert result['ready'] is False
    assert result['samples'] == 1


def test_window_is_reported_so_the_user_knows_what_is_compared():
    values = [1 + index * 0.01 for index in range(48)]
    result = gauge.position(samples(values), current=1.2, window_hours=168)
    assert result['window_hours'] == 168
