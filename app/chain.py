"""A small monotone piecewise-linear pipeline used by the Iran <-> Bitunix cycles.

Every stage is a strictly increasing function with an inverse and a list of input-side
breakpoints (where its slope changes). Because each stage is piecewise linear, the composed
profit function is piecewise linear too, so all breakpoints can be mapped back to the
starting capital exactly instead of guessing with a binary search.
"""
import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from .calculation import InsufficientDepth, buy, sell


class ChainError(ValueError):
    pass


def quantity_for_proceeds(target, bids):
    """Inverse of :func:`app.calculation.sell`: how many coins must be sold for ``target``."""
    if target <= 0:
        return 0.0
    proceeds, quantity = 0.0, 0.0
    for price, available in bids:
        value = price * available
        if proceeds + value >= target:
            return quantity + (target - proceeds) / price
        proceeds += value
        quantity += available
    raise InsufficientDepth('عمق سفارش‌های فروش کافی نیست')


def cumulative(values):
    total, result = 0.0, []
    for value in values:
        total += value
        result.append(total)
    return result


@dataclass
class Stage:
    name: str
    label: str
    unit_in: str
    unit_out: str
    forward: Callable[[float], float]
    inverse: Callable[[float], Optional[float]]
    breakpoints: list = field(default_factory=list)
    max_input: float = math.inf
    kind: str = ''
    meta: dict = field(default_factory=dict)


def buy_stage(name, label, asks, fee_pct, unit_in='quote', unit_out='coin', **meta):
    """Spend ``unit_in`` on the ask side, then deduct a percentage trading fee."""
    fee = float(fee_pct) / 100.0

    def forward(capital):
        return buy(capital, asks) * (1 - fee)

    def inverse(quantity):
        if quantity <= 0:
            return 0.0
        return cost_or_none(quantity / (1 - fee), asks)

    costs = cumulative(price * qty for price, qty in asks)
    return Stage(name, label, unit_in, unit_out, forward, inverse, costs, costs[-1],
                 kind='buy', meta=meta)


def sell_stage(name, label, bids, fee_pct, unit_in='coin', unit_out='quote', **meta):
    fee = float(fee_pct) / 100.0

    def forward(quantity):
        return sell(quantity, bids) * (1 - fee)

    def inverse(proceeds):
        if proceeds <= 0:
            return 0.0
        return quantity_for_proceeds(proceeds / (1 - fee), bids)

    quantities = cumulative(qty for _, qty in bids)
    return Stage(name, label, unit_in, unit_out, forward, inverse, quantities, quantities[-1],
                 kind='sell', meta=meta)


def fixed_stage(name, label, amount, unit, **meta):
    """Pay a fixed network withdrawal fee (in the stage's own unit)."""
    amount = float(amount)

    def forward(value):
        result = value - amount
        if result <= 0:
            raise ChainError(f'مقدار پس از کارمزد برداشت «{label}» کافی نیست')
        return result

    def inverse(value):
        return value + amount

    return Stage(name, label, unit, unit, forward, inverse, [amount], math.inf,
                 kind='fixed', meta={**meta, 'amount': amount})


def scale_stage(name, label, factor, unit_in, unit_out, **meta):
    factor = float(factor)
    if not math.isfinite(factor) or factor <= 0:
        raise ChainError('ضریب تبدیل نامعتبر است')
    return Stage(name, label, unit_in, unit_out, lambda x: x * factor, lambda y: y / factor,
                 [], math.inf, kind='scale', meta=meta)


def cost_or_none(quantity, asks):
    from .capital import cost_for_quantity
    return cost_for_quantity(quantity, asks)


class Chain:
    def __init__(self, stages):
        self.stages = list(stages)
        if not self.stages:
            raise ChainError('زنجیره محاسبه خالی است')

    def run(self, capital):
        if capital is None or capital <= 0 or not math.isfinite(capital):
            raise ChainError('سرمایه باید عددی مثبت باشد')
        value, records = float(capital), []
        for stage in self.stages:
            previous = value
            try:
                value = stage.forward(value)
            except InsufficientDepth:
                raise
            if value is None or not math.isfinite(value):
                raise ChainError('محاسبه مرحله «%s» ممکن نشد' % stage.label)
            records.append({'name': stage.name, 'label': stage.label, 'value': value,
                            'unit': stage.unit_out, 'kind': stage.kind, 'meta': stage.meta,
                            'input': previous})
        return value, records

    def map_back(self, index, value):
        for stage in reversed(self.stages[:index]):
            if value is None:
                return None
            try:
                value = stage.inverse(value)
            except (ValueError, ZeroDivisionError):
                # The value is beyond that stage's visible capacity: no mapping exists.
                return None
        return value

    def minimum_capital(self):
        """Smallest starting capital at which every fixed withdrawal fee stays payable."""
        floor = 0.0
        for index, stage in enumerate(self.stages):
            if stage.kind != 'fixed':
                continue
            amount = stage.meta.get('amount')
            if amount is None:
                continue
            mapped = self.map_back(index, amount)
            if mapped is not None and math.isfinite(mapped):
                floor = max(floor, mapped)
        return floor

    def capacity(self):
        """Largest starting capital for which every stage has enough book/liquidity."""
        caps = []
        for index, stage in enumerate(self.stages):
            if stage.max_input is None or not math.isfinite(stage.max_input):
                continue
            mapped = self.map_back(index, stage.max_input)
            if mapped is not None and mapped > 0:
                caps.append(mapped)
        return min(caps) if caps else math.inf

    def breakpoints(self, upper=None, limit=600):
        points = set()
        for index, stage in enumerate(self.stages):
            for value in stage.breakpoints:
                mapped = self.map_back(index, value)
                if mapped is None or not math.isfinite(mapped) or mapped <= 0:
                    continue
                if upper is not None and mapped > upper * (1 + 1e-12):
                    continue
                points.add(mapped)
        ordered = sorted(points)
        if len(ordered) > limit:
            step = len(ordered) / limit
            ordered = [ordered[int(i * step)] for i in range(limit)]
        if upper is not None and math.isfinite(upper):
            ordered.append(upper)
        return sorted({p for p in ordered if p > 0})


def _interpolate(a, ya, b, yb):
    if yb == ya:
        return b
    return a + (b - a) * (0 - ya) / (yb - ya)


def _ladder(low, high, count=24):
    """Geometric probe points, only used where no finer breakpoint exists."""
    if not math.isfinite(high) or high <= 0:
        return []
    low = max(low, high / 1e6, 1e-9)
    if low >= high:
        return []
    ratio = (high / low) ** (1 / max(1, count - 1))
    points, value = [], low
    for _ in range(count):
        if value >= high:
            break
        points.append(value)
        value *= ratio
    return points


def analyse(chain, capital, margin=0.0, limit=None, points_limit=600, envelope=True):
    """Evaluate one capital and the size envelope of the whole chain.

    All breakpoints of every stage are mapped back to the starting capital, so the profit
    function is sampled exactly where its slope changes. A geometric ladder is added only
    to give the envelope shape for very shallow books; adjacent samples in the merged list
    can never straddle a breakpoint, so linear interpolation between them is exact.
    """
    report = {'ok': False, 'capital': capital, 'trading_mode': None}
    try:
        final, records = chain.run(capital)
    except InsufficientDepth as exc:
        return {**report, 'reason': 'insufficient depth', 'error': str(exc)}
    except (ChainError, ValueError, ZeroDivisionError) as exc:
        return {**report, 'reason': 'error', 'error': str(exc)}
    profit = final - capital
    upper = chain.capacity()
    external_limit = None
    if limit is not None and math.isfinite(limit):
        external_limit = limit
        upper = min(upper, limit)
    low = chain.minimum_capital()
    points = set()
    if envelope and math.isfinite(upper) and upper > 0:
        points.update(chain.breakpoints(upper, points_limit))
        points.update(_ladder(max(low, 1e-9), upper))
    if low > 0:
        points.add(low * (1 + 1e-9))
    points = sorted(point for point in points if point > 0)
    samples = []
    for point in points:
        try:
            samples.append((point, chain.run(point)[0] - point))
        except (ValueError, ZeroDivisionError):
            samples.append((point, None))
    max_profitable = None
    trough = None
    for (a, pa), (b, pb) in zip(samples, samples[1:]):
        if pa is None or pb is None:
            trough = None
            continue
        ya, yb = pa - a * margin / 100, pb - b * margin / 100
        if trough is None and ya > 0:
            max_profitable = a
        if yb > 0:
            max_profitable = b
        elif ya > 0:
            max_profitable = _interpolate(a, ya, b, yb)
        trough = b
    limited = (max_profitable is not None and math.isfinite(upper)
               and abs(max_profitable - upper) <= max(1e-9, upper * 1e-9)
               and external_limit is None)
    feasible = [(point, value) for point, value in samples if value is not None]
    best = max(feasible, key=lambda item: item[1]) if feasible else None
    breakeven = None
    previous = None
    for point, value in samples:
        if value is None:
            previous = None
            continue
        if value >= -1e-9:
            if previous is not None and previous[1] < 0:
                breakeven = _interpolate(previous[0], previous[1], point, value)
            else:
                breakeven = point
            break
        previous = (point, value)
    profit_pct = profit / capital * 100 if capital else 0.0
    return {**report, 'ok': True, 'final': final, 'profit': profit, 'profit_pct': profit_pct,
            'steps': records, 'max_profitable_capital': None if limited else max_profitable,
            'limited_by_visible_depth': limited,
            'profit_maximizing_capital': best[0] if best and best[1] > 0 else None,
            'breakeven_capital': breakeven, 'visible_capital': upper,
            'minimum_capital': low,
            'required_improvement_pct': max(0.0, -profit_pct)}
