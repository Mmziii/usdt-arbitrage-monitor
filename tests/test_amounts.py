"""Human-friendly amount parsing: Persian words, Persian digits, commas, rial conversion."""
import pytest

from app.amounts import AmountError, format_amount, parse_amount


@pytest.mark.parametrize('text,value,currency', [
    ('50 میلیون', 50_000_000, None),
    ('۵۰ میلیون', 50_000_000, None),
    ('2.5 میلیارد', 2_500_000_000, None),
    ('100 هزار', 100_000, None),
    ('5,000,000', 5_000_000, None),
    ('1,234,567', 1_234_567, None),
    ('250 usdt', 250, 'USDT'),
    ('۵۰ میلیون تومان', 50_000_000, 'toman'),
    ('50M', 50_000_000, None),
    ('3b', 3_000_000_000, None),
])
def test_parse_amount_words(text, value, currency):
    parsed = parse_amount(text)
    assert parsed['value'] == pytest.approx(value)
    assert parsed['currency'] == currency
    assert parsed['raw'] == text


def test_rial_is_converted_to_toman():
    parsed = parse_amount('۵۰ میلیون ریال')
    assert parsed['value'] == pytest.approx(5_000_000)
    assert parsed['currency'] == 'toman'


def test_default_currency_is_used_when_the_text_has_none():
    assert parse_amount('100', default_currency='USDT')['currency'] == 'USDT'
    assert parse_amount('100 usdt', default_currency='toman')['currency'] == 'USDT'


@pytest.mark.parametrize('text', ['', '   ', 'abc', 'خیلی', '0', '-5', '0 تومان'])
def test_bad_amounts_are_rejected_in_persian(text):
    with pytest.raises(AmountError) as error:
        parse_amount(text)
    assert any('\u0600' <= char <= '\u06ff' for char in str(error.value))


def test_amounts_above_the_limit_are_rejected():
    with pytest.raises(AmountError):
        parse_amount('9999999999999999')


def test_format_amount_uses_latin_digits_and_separators():
    assert format_amount(1_234_567) == '1,234,567'
    assert format_amount(1234.5, 2) == '1,234.50'
    assert format_amount(None) == '—'
    assert format_amount(float('inf')) == '—'
