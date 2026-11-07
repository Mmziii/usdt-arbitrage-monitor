/* Ranking rules: ranking on first render, hysteresis, freeze, new rows, filters.
   Plain node, no DOM: `node tests/sort_order_test.cjs` */
const assert = require('node:assert/strict');
const Sort = require('../app/static/sort.js');

const row = (key, net, extra) => Object.assign({key, coin: key.split(':')[1], net_pct: net,
  net_quote: net, flags: {}}, extra || {});

// 1. A fresh page is ranked by profit, descending.
const first = [row('A:ETH:w', 1), row('A:BTC:w', 3), row('A:SOL:w', 2)];
assert.deepEqual(Sort.orderRows(first, [], .05), ['A:BTC:w', 'A:SOL:w', 'A:ETH:w']);

// 2. Movements smaller than the hysteresis gap never reorder the list.
const tiny = [row('A:BTC:w', 3.01), row('A:SOL:w', 2), row('A:ETH:w', 1)];
assert.deepEqual(Sort.orderRows(tiny, ['A:BTC:w', 'A:SOL:w', 'A:ETH:w'], .05),
  ['A:BTC:w', 'A:SOL:w', 'A:ETH:w']);
const tinyClimb = [row('A:BTC:w', 3), row('A:SOL:w', 3.02), row('A:ETH:w', 1)];
assert.deepEqual(Sort.orderRows(tinyClimb, ['A:BTC:w', 'A:SOL:w', 'A:ETH:w'], .05),
  ['A:BTC:w', 'A:SOL:w', 'A:ETH:w'], 'a 0.02 point lead is not worth a jump');

// 3. A real improvement does move the row, and a chain of passes can carry it far.
const climb = [row('A:BTC:w', 1), row('A:SOL:w', 1.5), row('A:ETH:w', 9)];
assert.deepEqual(Sort.orderRows(climb, ['A:BTC:w', 'A:SOL:w', 'A:ETH:w'], .05),
  ['A:ETH:w', 'A:SOL:w', 'A:BTC:w']);
const smallImprovement = [row('A:BTC:w', 1), row('A:SOL:w', 1.2)];
assert.deepEqual(Sort.orderRows(smallImprovement, ['A:BTC:w', 'A:SOL:w'], .05),
  ['A:SOL:w', 'A:BTC:w'], '0.2 points is above the 0.05 gap');

// 4. Freeze (an infinite gap) keeps the previous order exactly, whatever the profits do.
const frozen = [row('A:BTC:w', -50), row('A:SOL:w', 50)];
assert.deepEqual(Sort.orderRows(frozen, ['A:BTC:w', 'A:SOL:w'], Infinity),
  ['A:BTC:w', 'A:SOL:w']);

// 5. A brand-new row joins at the end but still climbs when it is clearly better.
const withNew = [row('A:BTC:w', 1), row('A:SOL:w', 2), row('A:XRP:w', 8)];
assert.deepEqual(Sort.orderRows(withNew, ['A:BTC:w', 'A:SOL:w'], .05),
  ['A:XRP:w', 'A:SOL:w', 'A:BTC:w']);
assert.deepEqual(Sort.orderRows(withNew, ['A:BTC:w', 'A:SOL:w'], Infinity),
  ['A:BTC:w', 'A:SOL:w', 'A:XRP:w'], 'frozen lists append new rows, never reshuffle');

// 6. Rows that disappear are dropped from the remembered order; unknown keys are ignored.
assert.deepEqual(Sort.orderRows([row('A:SOL:w', 2)], ['A:GONE:w', 'A:SOL:w'], .05), ['A:SOL:w']);
assert.deepEqual(Sort.orderRows([row('A:SOL:w', 2)], ['A:GONE:w'], .05), ['A:SOL:w']);

// 7. Score precedence: net, then reference spread, then gross, all penalised when unknown.
assert.equal(Sort.score(row('A:BTC:w', 2, {reference_pct: 9, gross_pct: 9})), 2);
assert.equal(Sort.score({key: 'x', reference_pct: 9, gross_pct: 9}), 9 - 1000);
assert.equal(Sort.score({key: 'x', gross_pct: 9}), 9 - 1000);
assert.equal(Sort.score({key: 'x'}), Sort.NO_VALUE);
assert.equal(Sort.score(null), Sort.NO_VALUE);
assert.ok(Sort.score({key: 'x', reference_pct: 9}) <
  Sort.score({key: 'y', net_pct: -0.1}), 'unknown rows rank below any known loss');

// 8. Filters: search, market, route, mode, profit, capacity, gross-only and stale.
const rows = [
  row('A:BTC:wallex', 2, {iran: 'wallex', quote: 'toman', route: 'A',
    trading_mode: 'transfer', max_profitable_capital: 500}),
  row('B:ETH:nobitex', .1, {iran: 'nobitex', quote: 'USDT', route: 'B',
    trading_mode: 'prefunded', max_profitable_capital: 50}),
  row('C:SOL:wallex', null, {iran: 'wallex', quote: 'toman', route: 'direct_iran_to_bitunix',
    trading_mode: 'transfer', flags: {gross_only: true}}),
  row('D:XRP:nobitex', 1, {iran: 'nobitex', quote: 'toman', route: 'classic',
    kind: 'classic', trading_mode: 'transfer', flags: {stale: true}}),
];
const keys = list => list.map(item => item.key);
assert.deepEqual(keys(Sort.applyFilters(rows, {})), keys(rows));
assert.deepEqual(keys(Sort.applyFilters(rows, {search: 'btc'})), ['A:BTC:wallex']);
assert.deepEqual(keys(Sort.applyFilters(rows, {iran: 'nobitex'})), ['B:ETH:nobitex', 'D:XRP:nobitex']);
assert.deepEqual(keys(Sort.applyFilters(rows, {quote: 'toman'})),
  ['A:BTC:wallex', 'C:SOL:wallex', 'D:XRP:nobitex']);
assert.deepEqual(keys(Sort.applyFilters(rows, {route: 'B'})), ['B:ETH:nobitex']);
assert.deepEqual(keys(Sort.applyFilters(rows, {route: 'classic'})), ['D:XRP:nobitex']);
assert.deepEqual(keys(Sort.applyFilters(rows, {mode: 'prefunded'})), ['B:ETH:nobitex']);
assert.deepEqual(keys(Sort.applyFilters(rows, {minProfit: 0})),
  ['A:BTC:wallex', 'B:ETH:nobitex', 'D:XRP:nobitex']);
assert.deepEqual(keys(Sort.applyFilters(rows, {minCapacity: 100})), ['A:BTC:wallex']);
assert.deepEqual(keys(Sort.applyFilters(rows, {hideGross: true})),
  ['A:BTC:wallex', 'B:ETH:nobitex', 'D:XRP:nobitex']);
assert.deepEqual(keys(Sort.applyFilters(rows, {hideStale: true})),
  ['A:BTC:wallex', 'B:ETH:nobitex', 'C:SOL:wallex']);

// 9. Bars are clamped to 0..100 and never produce NaN.
assert.equal(Sort.barPercent(5, 10), 50);
assert.equal(Sort.barPercent(-5, 10), 50);
assert.equal(Sort.barPercent(50, 10), 100);
assert.equal(Sort.barPercent(null, 10), 0);
assert.equal(Sort.barPercent(5, 0), 0);

// 10. "Newly profitable" compares with the previous quote profit, including null history.
assert.deepEqual(Sort.newlyProfitable([row('A:BTC:w', 1, {net_quote: 2}),
  row('A:ETH:w', -1, {net_quote: -2})], new Map([['A:BTC:w', -1]])), ['A:BTC:w']);
assert.deepEqual(Sort.newlyProfitable([row('A:BTC:w', 1, {net_quote: 2})],
  new Map([['A:BTC:w', 3]])), []);
assert.deepEqual(Sort.newlyProfitable([], new Map()), []);

console.log('Ranking tests passed: first render, hysteresis, freeze, new rows, ' +
  'filters, bars and newly-profitable detection.');
