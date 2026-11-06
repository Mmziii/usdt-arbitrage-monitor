import pytest
from app.calculation import outcome, breakeven, InsufficientDepth


def test_hand_calculated():
    # 100000 / 1000 = 100 USDT; 1% buy => 99; withdraw 1 => 98;
    # sell at 1100 => 107800; 2% sell => 105644; profit 5644.
    r = outcome(100000, [(1000, 1000)], [(1100, 1000)], .01, .02, 1)
    assert r['usdt_after_buy'] == 99
    assert r['final_toman'] == 105644
    assert r['profit_pct'] == pytest.approx(5.644)
    expected = 1 * 1100 * .98 / (1100 / 1000 * .99 * .98 - 1)
    assert breakeven([(1000, 1000)], [(1100, 1000)], .01, .02, 1) == pytest.approx(expected)


def test_walk_both_sides():
    r = outcome(320, [(10, 10), (11, 20)], [(12, 5), (11, 30)], 0, 0, 1)
    assert r['usdt_after_buy'] == 30
    assert r['final_toman'] == 324
    assert r['profit'] == 4


def test_insufficient_and_withdrawal():
    with pytest.raises(InsufficientDepth):
        outcome(100, [(10, 1)], [(12, 10)], 0, 0, 0)
    with pytest.raises(InsufficientDepth):
        outcome(100, [(10, 20)], [(12, 1)], 0, 0, 0)
    with pytest.raises(ValueError):
        outcome(1, [(10, 20)], [(12, 20)], 0, 0, 1)


def test_no_breakeven():
    assert breakeven([(10, 100)], [(9, 100)], .003, .003, .8) is None


def test_profitable_window_before_deep_loss():
    b = breakeven([(10, 10), (100, 10)], [(12, 100)], 0, 0, 1)
    assert b == pytest.approx(60)
