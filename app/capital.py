"""Exact breakpoints of the depth-walking, piecewise-linear profit function."""
from .calculation import outcome


def cost_for_quantity(quantity, asks):
    cost = 0.0
    for price, available in asks:
        take = min(quantity, available)
        cost += price * take
        quantity -= take
        if quantity <= 1e-10:
            return cost
    return None


def capital_limits(asks, bids, bf, sf, withdrawal=0, minimum=0, margin=0,
                   quote_balance=None, coin_balance=None):
    factor = 1 - bf
    max_received = sum(q for _, q in bids) + withdrawal
    if coin_balance is not None:
        max_received = min(max_received, coin_balance + withdrawal)
    max_bought = min(sum(q for _, q in asks), max_received / factor)
    upper = cost_for_quantity(max_bought, asks)
    depth_upper = upper
    if quote_balance is not None:
        upper = min(upper, quote_balance)
    balance_limited = upper < depth_upper or (coin_balance is not None and coin_balance < sum(q for _, q in bids))
    knots = {0., upper}
    cumulative = 0.
    for p, q in asks:
        cumulative += p * q
        if cumulative < upper:
            knots.add(cumulative)
    cumulative = 0.
    for _, q in [(0, 0)] + bids:
        cumulative += q
        c = cost_for_quantity((cumulative + withdrawal) / factor, asks)
        if c is not None and c <= upper:
            knots.add(c)
    lower = cost_for_quantity(max(minimum, withdrawal) / factor, asks)
    if lower is None or lower >= upper:
        return dict(max_profitable_capital=None, profit_maximizing_capital=None, limited_by_visible_depth=False)
    knots.add(lower)
    points = []
    for c in sorted(knots):
        if c < lower:
            continue
        try:
            profit = outcome(c, asks, bids, bf, sf, withdrawal, minimum)['profit'] if c > lower or (c > 0 and minimum > withdrawal) else -c
        except ValueError:
            continue
        points.append((c, profit))
    if not points:
        return dict(max_profitable_capital=None, profit_maximizing_capital=None, limited_by_visible_depth=False)
    best = max(points, key=lambda p: p[1])
    last = None
    for (a, pa), (b, pb) in zip(points, points[1:]):
        ya, yb = pa - a * margin / 100, pb - b * margin / 100
        if yb > 0:
            last = b
        elif ya > 0:
            last = a + (b-a) * ya / (ya-yb)
    limited = last == upper and not balance_limited
    return dict(max_profitable_capital=None if limited else last,
                profit_maximizing_capital=best[0] if best[1] > 0 else None,
                limited_by_visible_depth=limited, visible_capital=upper)
