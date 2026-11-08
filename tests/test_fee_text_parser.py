"""The Fee Assistant parser: real pastes work, broken lines are reported, nothing is guessed."""
from app import fee_text


def parse(text, exchange='nobitex', kind='auto'):
    return fee_text.parse_any(text, exchange, kind)


def test_a_clean_table_is_read_line_by_line():
    result = parse('USDT  TRC20  1  10\nBTC  BTC  0.0002  0.001')
    assert [(row['coin'], row['network'], row['withdrawal'], row['minimum'])
            for row in result['rows']] == [('USDT', 'TRC20', 1.0, 10.0),
                                           ('BTC', 'BTC', 0.0002, 0.001)]
    assert result['errors'] == []
    assert all(row['confidence'] == 'manual' for row in result['rows'])


def test_single_spaces_and_persian_digits_are_understood():
    result = parse('تتر TRC20 ۱ ۱۰')
    assert result['rows'][0]['coin'] == 'USDT'
    assert result['rows'][0]['withdrawal'] == 1.0
    assert result['rows'][0]['minimum'] == 10.0


def test_a_comma_decimal_mark_is_read_as_a_decimal_point():
    result = parse('USDT TRC20 0,5 10')
    assert result['rows'][0]['withdrawal'] == 0.5


def test_csv_input_is_accepted():
    result = parse('coin,network,fee,minimum\nUSDT,TRC20,1,10\n', kind='csv')
    assert result['rows'][0]['coin'] == 'USDT'
    assert result['rows'][0]['minimum'] == 10.0


def test_csv_rows_with_the_wrong_shape_are_reported():
    result = parse('BTC,TRC20\nUSDT,TRC20,1,10', kind='csv')
    assert len(result['rows']) == 1
    assert 'سه یا چهار ستون' in result['errors'][0]['message']


def test_a_broken_line_never_becomes_a_fee():
    result = parse('سلام دنیا\nUSDT TRC20 x y')
    assert result['rows'] == []
    assert result['errors']


def test_header_rows_are_skipped_without_noise():
    result = parse('Coin Network Fee Min\nUSDT TRC20 1 10')
    assert len(result['rows']) == 1
    assert result['errors'] == []


def test_duplicate_rows_in_one_paste_are_reported_once():
    result = parse('USDT TRC20 1 10\nUSDT TRC20 2 20')
    assert len(result['rows']) == 1
    assert 'تکراری' in result['errors'][0]['message']


def test_a_zero_fee_is_a_real_fee_not_missing_data():
    result = parse('USDT TRC20 0 10')
    assert result['rows'][0]['withdrawal'] == 0.0


def test_a_minimum_smaller_than_the_fee_is_swapped():
    result = parse('BTC BTC 0.001 0.0002')
    assert result['rows'][0]['withdrawal'] == 0.0002
    assert result['rows'][0]['minimum'] == 0.001


def test_unknown_network_is_reported():
    result = parse('USDT XYZ99 1 10')
    assert result['rows'] == []
    assert 'شبکه' in result['errors'][0]['message']
