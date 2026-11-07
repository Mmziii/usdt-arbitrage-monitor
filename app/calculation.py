"""Depth-aware estimates; fees deducted from purchased USDT and sale proceeds."""
class InsufficientDepth(ValueError):
    pass


def buy(capital, asks):
    remaining, quantity = capital, 0.0
    for price, available in asks:
        spend = min(remaining, price * available)
        quantity += spend / price
        remaining -= spend
        if remaining <= max(1e-7, capital * 1e-12):
            return quantity
    raise InsufficientDepth('عمق سفارش‌های خرید کافی نیست')


def sell(quantity, bids):
    remaining, proceeds = quantity, 0.0
    for price, available in bids:
        take = min(remaining, available)
        proceeds += take * price
        remaining -= take
        if remaining <= max(1e-9, quantity * 1e-12):
            return proceeds
    raise InsufficientDepth('عمق سفارش‌های فروش کافی نیست')


def outcome(capital, asks, bids, buy_fee, sell_fee, withdrawal, minimum=0):
    received = buy(capital, asks) * (1 - buy_fee)
    if received < minimum:
        raise ValueError('مقدار کمتر از حداقل برداشت است')
    transferable = received - withdrawal
    if transferable <= 0:
        raise ValueError('دارایی پس از کارمزد برای برداشت کافی نیست')
    gross = sell(transferable, bids)
    final = gross * (1 - sell_fee)
    profit = final - capital
    return dict(coin_after_buy=received, coin_after_withdrawal=transferable, final_quote=final,
                usdt_after_buy=received, usdt_after_withdrawal=transferable,
                final_toman=final, profit=profit, profit_pct=profit / capital * 100,
                buy_vwap=capital / (received / (1 - buy_fee)), sell_vwap=gross / transferable,
                required_spread_pct=((capital / (transferable * (1 - sell_fee))) / asks[0][0] - 1) * 100)


def breakeven(asks, bids, bf, sf, withdrawal, minimum=0):
    # Profit is piecewise linear. Include every buy and sell depth boundary;
    # unlike a binary search this also finds profitable windows before deeper losses.
    knots = [0.0]
    total, quantity = 0.0, 0.0
    for p, q in asks:
        total += p * q
        knots.append(total)
    minimum_capital = 0.0
    if minimum > 0:
        target = minimum / (1 - bf)
        remaining, cost = target, 0.0
        for p, aq in asks:
            take = min(remaining, aq)
            cost += take * p
            remaining -= take
        if remaining <= 1e-8:
            minimum_capital = cost
            knots.append(cost)
        else:
            return None
    sell_q = 0.0
    for _, q in [(0, 0)] + bids:
        sell_q += q
        target = (sell_q + withdrawal) / (1 - bf)
        remaining, cost = target, 0.0
        for p, aq in asks:
            take = min(remaining, aq)
            cost += take * p
            remaining -= take
        if remaining <= 1e-8:
            knots.append(cost)
    knots = sorted(set(knots))
    previous = None
    for c in knots:
        if c <= 0:
            continue
        try:
            profit = outcome(c, asks, bids, bf, sf, withdrawal, minimum)['profit']
        except ValueError:
            # At transfer threshold the limiting profit is -capital.
            if buy(c, asks) * (1 - bf) < max(minimum, withdrawal + 1e-8):
                profit = -c
            else:
                continue
        if profit >= -1e-7:
            if previous and previous[1] < 0:
                x, y = previous
                return max(minimum_capital, x + (c - x) * (-y) / (profit - y))
            return c
        previous = c, profit
    return None


def calculate(capital, source, destination, source_fees, destination_fees, mode):
    bf, sf = source_fees[mode] / 100, destination_fees[mode] / 100
    result = outcome(capital, source.asks, destination.bids, bf, sf, source_fees['withdrawal'], source_fees.get('minimum', 0))
    result['breakeven_capital'] = breakeven(source.asks, destination.bids, bf, sf, source_fees['withdrawal'], source_fees.get('minimum', 0))
    return result
