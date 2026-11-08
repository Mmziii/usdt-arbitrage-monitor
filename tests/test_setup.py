"""Setup answers decide which routes are usable and whether a transfer happens at all."""
from app import setup

ROW_WALLEX = {'key': 'A:BTC:wallex', 'coin': 'BTC', 'venue_pair': ['bitunix', 'wallex'],
              'route_label': 'خرید در بیت‌یونیکس، فروش در ایران'}
ROW_NOBITEX = {'key': 'A:ETH:nobitex', 'coin': 'ETH', 'venue_pair': ['bitunix', 'nobitex'],
               'route_label': 'خرید در بیت‌یونیکس، فروش در ایران'}


def test_defaults_fill_in_a_missing_setup():
    result = setup.normalize({})
    assert result['exchanges'] == ['wallex', 'nobitex', 'bitunix']
    assert result['money'] == 'toman_iran'
    assert result['capital_toman'] > 0


def test_unknown_exchange_names_are_dropped():
    result = setup.normalize({'exchanges': ['wallex', 'kraken']})
    assert result['exchanges'] == ['wallex']


def test_money_on_both_sides_means_no_transfer():
    assert setup.trading_mode({'money': 'coins_both'}) == 'prefunded'
    assert setup.trading_mode({'money': 'usdt'}) == 'transfer'
    assert setup.trading_mode({'money': 'toman_iran'}) == 'transfer'


def test_a_route_needing_an_exchange_the_user_does_not_have_is_excluded():
    allowed, reason = setup.route_allowed(ROW_NOBITEX, {'exchanges': ['wallex', 'bitunix']})
    assert allowed is False
    assert 'نوبیتکس' in reason


def test_a_route_with_both_accounts_is_allowed():
    allowed, reason = setup.route_allowed(ROW_WALLEX, {'exchanges': ['wallex', 'bitunix']})
    assert allowed is True and reason == ''


def test_filtering_keeps_the_allowed_rows_and_explains_the_rest():
    result = setup.filter_rows([ROW_WALLEX, ROW_NOBITEX],
                               {'exchanges': ['wallex', 'bitunix']})
    assert [row['key'] for row in result['rows']] == ['A:BTC:wallex']
    assert result['excluded'][0]['key'] == 'A:ETH:nobitex'
    assert 'حساب' in result['excluded'][0]['reason']


def test_summary_translates_the_answers_for_the_ui():
    summary = setup.summary({'exchanges': ['wallex', 'bitunix'], 'money': 'coins_both'})
    assert summary['exchange_labels'] == ['والکس', 'بیت‌یونیکس']
    assert summary['mode'] == 'prefunded'
    assert summary['mode_label'] == 'بدون انتقال (موجودی از پیش)'
    assert {option['value'] for option in summary['money_options']} == set(setup.MONEY)


def test_a_route_without_venues_is_excluded():
    allowed, reason = setup.route_allowed({'key': 'x', 'coin': 'BTC'}, {})
    assert allowed is False
    assert 'مشخص نیست' in reason
