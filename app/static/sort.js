/* Pure ordering / filtering helpers for the overview table.
   Loaded as a plain script in the browser and required directly by the node tests. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.Sort = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const NO_VALUE = -1e9;

  function score(row) {
    if (!row) return NO_VALUE;
    if (Number.isFinite(row.net_pct)) return row.net_pct;
    if (Number.isFinite(row.reference_pct)) return row.reference_pct - 1000;
    if (Number.isFinite(row.gross_pct)) return row.gross_pct - 1000;
    return NO_VALUE;
  }

  /**
   * Sort rows by profit descending while ignoring movements smaller than `hysteresis`
   * percentage points. The previous order is kept for rows that already existed, so tiny
   * fluctuations never make the list jump.
   */
  function orderRows(rows, previousOrder, hysteresis) {
    const gap = Math.max(0, Number(hysteresis) || 0);
    const byKey = new Map();
    rows.forEach(function (row) { byKey.set(row.key, row); });
    const previous = (previousOrder || []).filter(function (key) { return byKey.has(key); });
    const seen = new Set(previous);
    // A page refresh keeps the order the user was looking at; brand-new rows join at the
    // end, ranked by profit among themselves, and may then climb through the gap checks.
    const fresh = rows.filter(function (row) { return !seen.has(row.key); })
      .sort(function (a, b) {
        const diff = score(b) - score(a);
        return diff !== 0 ? diff : String(a.key).localeCompare(String(b.key));
      });
    const order = previous.concat(fresh.map(function (row) { return row.key; }));
    if (!previous.length) {
      // First render (or a completely new result set): rank by profit.
      order.sort(function (a, b) {
        const diff = score(byKey.get(b)) - score(byKey.get(a));
        return diff !== 0 ? diff : String(a).localeCompare(String(b));
      });
      return order;
    }
    // Bubble passes: swap only when a row is better by more than the hysteresis gap.
    // An infinite gap (the "freeze order" switch) never swaps, so the order is locked.
    for (let pass = 0; pass < order.length; pass++) {
      let swapped = false;
      for (let i = 0; i < order.length - 1; i++) {
        const a = byKey.get(order[i]);
        const b = byKey.get(order[i + 1]);
        if (score(b) > score(a) + gap) {
          const tmp = order[i];
          order[i] = order[i + 1];
          order[i + 1] = tmp;
          swapped = true;
        }
      }
      if (!swapped) break;
    }
    return order;
  }

  function newlyProfitable(rows, previousProfit) {
    const keys = [];
    (rows || []).forEach(function (row) {
      const now = Number(row.net_quote);
      const before = previousProfit instanceof Map ? previousProfit.get(row.key) : undefined;
      if (Number.isFinite(now) && now > 0 && !(Number.isFinite(before) && before > 0)) {
        keys.push(row.key);
      }
    });
    return keys;
  }

  function applyFilters(rows, filters) {
    const f = filters || {};
    const search = String(f.search || '').trim().toUpperCase();
    const minProfit = f.minProfit === '' || f.minProfit == null ? null : Number(f.minProfit);
    const minCapacity = f.minCapacity === '' || f.minCapacity == null ? null : Number(f.minCapacity);
    return (rows || []).filter(function (row) {
      if (search && String(row.coin || '').toUpperCase().indexOf(search) === -1) return false;
      if (f.iran && row.iran !== f.iran) return false;
      if (f.quote && row.quote !== f.quote) return false;
      if (f.route) {
        if (f.route === 'classic' ? row.kind !== 'classic' : row.route !== f.route) return false;
      }
      if (f.mode && (row.trading_mode || 'transfer') !== f.mode) return false;
      if (minProfit != null && !(Number.isFinite(row.net_pct) && row.net_pct >= minProfit)) return false;
      if (minCapacity != null) {
        const cap = Number.isFinite(row.max_profitable_capital) ? row.max_profitable_capital
          : (Number.isFinite(row.liquidity) ? row.liquidity : null);
        if (cap == null || cap < minCapacity) return false;
      }
      if (f.hideGross && row.flags && row.flags.gross_only) return false;
      if (f.hideStale && row.flags && row.flags.stale) return false;
      return true;
    });
  }

  function barPercent(value, maxAbs) {
    const limit = Math.abs(Number(maxAbs) || 0);
    if (!Number.isFinite(value) || limit <= 0) return 0;
    return Math.max(0, Math.min(100, Math.abs(Number(value)) / limit * 100));
  }

  return {score: score, orderRows: orderRows, newlyProfitable: newlyProfitable,
          applyFilters: applyFilters, barPercent: barPercent, NO_VALUE: NO_VALUE};
});
