"""The decision engine: four verdicts, the reason checklist, and no hidden certainty."""
from app import decision

GOOD_FEES = [{'name': 'کارمزد خرید', 'confidence': 'manual', 'stale': False},
             {'name': 'کارمزد برداشت BTC', 'confidence': 'auto', 'stale': False}]


def context(**overrides):
    base = {'status': 'ok', 'net_pct': 3.2, 'gross_pct': 4.0, 'margin': .3,
            'depth_ok': True, 'capital_ok': None, 'fees': GOOD_FEES,
            'transfer_minutes': 30, 'lifetime_minutes': 120, 'data_age': 5,
            'stale_seconds': 120, 'other_costs_pct': 0.0}
    base.update(overrides)
    return base


def checks(result):
    return {item['title']: item for item in result['checks']}


def test_a_clean_opportunity_says_go():
    result = decision.decide(context())
    assert result['verdict'] == 'go'
    assert result['label'] == 'برو' and result['icon'] == '✔'
    assert result['tone'] == 'good'
    assert result['confidence'] == 'high' and result['confidence_label'] == 'بالا'
    assert checks(result)['سود بعد از همه کارمزدها']['status'] == 'ok'


def test_profit_below_the_safety_margin_says_wait():
    result = decision.decide(context(net_pct=.1))
    assert result['verdict'] == 'wait'
    assert checks(result)['حاشیه ایمنی']['status'] == 'warn'
    assert 'حاشیه ایمنی' in checks(result)['حاشیه ایمنی']['text']


def test_a_negative_net_says_no():
    result = decision.decide(context(net_pct=-1.4))
    assert result['verdict'] == 'no'
    assert result['label'] == 'نه'
    assert checks(result)['سود بعد از همه کارمزدها']['status'] == 'fail'


def test_missing_fees_make_it_unsure_and_block_the_number():
    fees = GOOD_FEES + [{'name': 'کارمزد برداشت تتر', 'confidence': 'unknown', 'stale': False}]
    result = decision.decide(context(net_pct=None, fees=fees))
    assert result['verdict'] == 'unsure'
    assert result['label'] == 'نامطمئن'
    assert checks(result)['کارمزدها']['status'] == 'fail'
    assert 'نامعلوم' in checks(result)['کارمزدها']['text']
    assert result['confidence'] == 'low'


def test_estimated_fees_cap_the_verdict_at_wait():
    fees = [{'name': 'کارمزد خرید', 'confidence': 'estimated', 'stale': False},
            {'name': 'کارمزد فروش', 'confidence': 'manual', 'stale': False}]
    result = decision.decide(context(fees=fees))
    assert result['verdict'] == 'wait'
    assert checks(result)['کارمزدها']['status'] == 'warn'
    assert 'تخمینی' in checks(result)['کارمزدها']['text']


def test_stale_fees_cap_the_verdict_at_wait():
    fees = [{'name': 'کارمزد برداشت BTC', 'confidence': 'manual', 'stale': True}]
    result = decision.decide(context(fees=fees))
    assert result['verdict'] == 'wait'
    assert 'بررسی دوباره' in checks(result)['کارمزدها']['text']


def test_old_prices_are_a_blocking_failure():
    result = decision.decide(context(data_age=900))
    assert result['verdict'] == 'unsure'
    assert checks(result)['تازگی قیمت‌ها']['status'] == 'fail'


def test_a_route_without_depth_is_blocking():
    result = decision.decide(context(depth_ok=False, net_pct=None, status='depth needed'))
    assert result['verdict'] == 'unsure'
    assert checks(result)['عمق بازار']['status'] == 'fail'


def test_capital_beyond_visible_depth_is_blocking():
    result = decision.decide(context(capital_ok=False))
    assert result['verdict'] == 'unsure'
    assert 'عمق قابل مشاهده' in checks(result)['عمق بازار']['text']


def test_a_short_lived_opportunity_says_wait():
    result = decision.decide(context(lifetime_minutes=5, transfer_minutes=60))
    assert result['verdict'] == 'wait'
    assert checks(result)['عمر فرصت']['status'] == 'warn'
    assert '60' in checks(result)['عمر فرصت']['text']


def test_other_costs_are_subtracted_and_shown():
    result = decision.decide(context(net_pct=1.0, other_costs_pct=2.0))
    assert result['verdict'] == 'no'
    assert checks(result)['هزینه‌های دیگر']['status'] == 'warn'
    assert result['numbers']['net_after_other_pct'] == -1.0


def test_without_history_it_says_so_instead_of_guessing():
    result = decision.decide(context(lifetime_minutes=None))
    assert checks(result)['عمر فرصت']['status'] == 'info'
    assert 'تاریخچه' in checks(result)['عمر فرصت']['text']


def test_gross_spread_is_reported_separately_from_the_net_number():
    result = decision.decide(context(net_pct=3.2, gross_pct=4.0))
    text = checks(result)['اختلاف خام در برابر سود خالص']['text']
    assert '4' in text and '3.2' in text


def test_default_margin_applies_when_none_is_given():
    result = decision.decide(context(margin=None, net_pct=.2))
    assert result['numbers']['margin'] == decision.DEFAULT_MARGIN
    assert result['verdict'] == 'wait'


def test_every_verdict_has_a_label_and_an_icon():
    assert set(decision.VERDICTS) == {'go', 'wait', 'no', 'unsure'}
    assert set(decision.ICONS) == set(decision.VERDICTS)
    assert set(decision.TONES) == set(decision.VERDICTS)


def test_summary_text_matches_each_verdict():
    go = decision.summary_text(decision.decide(context()), 'BTC', ['bitunix', 'wallex'])
    assert 'BTC' in go and '%' in go or '٪' in go
    no = decision.summary_text(decision.decide(context(net_pct=-1)), 'BTC')
    assert 'سود نمی‌دهد' in no
    unsure = decision.summary_text(decision.decide(context(net_pct=None, fees=[])))
    assert 'داده' in unsure
