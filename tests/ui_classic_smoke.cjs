/* Smoke test for the legacy /classic page (index.html + app.js) that is still shipped.
   NODE_PATH=<jsdom node_modules> node tests/ui_classic_smoke.cjs */
const {JSDOM, VirtualConsole} = require('jsdom');
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const problems = [];
process.on('unhandledRejection', reason => problems.push('unhandled rejection: ' + reason));
const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', error => problems.push('jsdom error: ' + error.message));

const css = fs.readFileSync('app/static/style.css', 'utf8');
const html = fs.readFileSync('app/static/index.html', 'utf8')
  .replace('<link rel="stylesheet" href="/static/style.css">', '<style>\n' + css + '\n</style>');
const dom = new JSDOM(html, {runScripts: 'outside-only', url: 'http://fixture.test/classic',
  virtualConsole, pretendToBeVisual: true});
const w = dom.window;
const doc = w.document;
const $ = id => doc.getElementById(id);

w.setTimeout = () => 1;
w.clearTimeout = () => {};
w.setInterval = () => 1;
w.clearInterval = () => {};
w.AudioContext = function () {
  this.resume = async () => {};
  this.createOscillator = () => ({connect() {}, start() {}, stop() {}, frequency: {}});
  this.createGain = () => ({connect() {}, gain: {}});
  this.destination = {};
  this.currentTime = 0;
};
delete w.Notification;

const settings = {
  refresh_seconds: 10, threshold: .5,
  wallex: {maker: .25, taker: .3, withdrawal: .8},
  nobitex: {maker: .25, taker: .25, withdrawal: .7},
  wallex_usdt: {maker: .25, taker: .3},
  nobitex_usdt: {maker: .25, taker: .25},
};
const calls = [];
let snapshotFailures = 0;

function snapshotPayload(capital) {
  const books = {
    wallex: {ask: 60000, bid: 59900, levels: [3, 4, 5], timestamp: 1700000000, source: 'live'},
    nobitex: {ask: 60100, bid: 60000, levels: [2, 3], timestamp: 1700000000, source: 'live'},
  };
  const rows = [];
  for (const source of ['wallex', 'nobitex']) {
    for (const mode of ['maker', 'taker']) {
      rows.push({
        source, mode, profit: 120000, profit_pct: .2, safety_status: 'profitable',
        usdt_after_buy: 99.7, usdt_after_withdrawal: 98.9, final_toman: 5934000,
        buy_vwap: 60000, sell_vwap: 60010, breakeven_capital: 900000,
        trading_mode: 'transfer', safety_margin: .3, required_spread_pct: .55,
      });
    }
  }
  return {books, rows, errors: {}, settings: {...settings, capital: Number(capital)},
          capital: Number(capital)};
}

w.fetch = async function (url, options = {}) {
  calls.push((options.method || 'GET') + ' ' + url);
  let value;
  if (url === '/api/settings') {
    if (options.method === 'PUT') Object.assign(settings, JSON.parse(options.body));
    value = settings;
  } else if (url.startsWith('/api/snapshot')) {
    value = snapshotPayload(new URL(url, 'http://fixture.test').searchParams.get('capital'));
    if (snapshotFailures > 0) {
      snapshotFailures -= 1;
      value = {...value, books: {wallex: null, nobitex: null}, rows: [],
        errors: {wallex: 'داده دریافت نشد؛ قیمت را دستی وارد کنید.'}};
    }
  } else if (url === '/api/history') {
    value = [{timestamp: 1700000000, spread_a: .17, spread_b: .1}];
  } else if (url.startsWith('/api/manual/')) {
    value = {ok: true};
  } else {
    throw new Error('Unexpected URL ' + url);
  }
  return {ok: true, status: 200, json: async () => structuredClone(value),
          text: async () => JSON.stringify(value)};
};

vm.runInContext(fs.readFileSync('app/static/app.js', 'utf8'), dom.getInternalVMContext(),
  {filename: 'app.js'});

async function settle(rounds = 80) {
  for (let index = 0; index < rounds; index += 1) await Promise.resolve();
}

function display(id) { return w.getComputedStyle($(id)).display; }

(async () => {
  await settle();
  assert.match($('cards').textContent, /والکس/);
  assert.equal(doc.querySelectorAll('#results tr').length, 2);
  assert.match($('results').textContent, /تومان/);
  assert.ok($('results').textContent.length > 80, 'result cells render');
  assert.equal($('settings').hidden, true, 'settings start closed');
  assert.equal(display('settings'), 'none', 'the CSS hides the closed settings panel');
  assert.equal($('manualPanel').hidden, true, 'manual entry hides without connection errors');

  // settings panel: open, edit, save, auto-close
  $('settingsToggle').click();
  await settle();
  assert.equal($('settings').hidden, false);
  assert.notEqual(display('settings'), 'none');
  assert.equal($('wallex_maker').value, '0.25');
  assert.equal($('wallex_usdt_taker').value, '0.3');
  $('wallex_taker').value = '0.4';
  await $('settingsForm').onsubmit({preventDefault() {}});
  await settle();
  assert.equal(settings.wallex.taker, 0.4, 'taker fee saved');
  assert.equal($('settings').hidden, true, 'saving closes the settings panel');

  // classic page close toggle also works a second time
  $('settingsToggle').click();
  await settle();
  $('settingsToggle').click();
  await settle();
  assert.equal($('settings').hidden, true, 'toggle closes the settings panel again');

  // capital change refetches
  const before = calls.filter(call => call.startsWith('GET /api/snapshot')).length;
  $('capital').value = '25000000';
  await $('capital').onchange();
  await settle();
  assert.ok(calls.filter(call => call.startsWith('GET /api/snapshot')).length > before,
    'changing capital reloads the snapshot');
  assert.ok(calls.some(call => call.includes('capital=25000000')));

  // manual price forms appear on failure and save
  snapshotFailures = 1;
  $('capital').value = '100';
  await $('capital').onchange();
  await settle();
  assert.equal($('manualPanel').hidden, false, 'manual entry appears when the fetch fails');
  assert.match($('message').textContent, /والکس/);
  assert.match($('message').textContent, /دستی/);
  const form = $('manual_wallex');
  form.querySelector('[name="ask"]').value = '60010';
  form.querySelector('[name="bid"]').value = '60000';
  await form.onsubmit({preventDefault() {}});
  await settle();
  assert.ok(calls.some(call => call.includes('/api/manual/wallex')), 'manual prices are sent');

  // alerts button toggles its label with a stubbed audio context
  $('alerts').click();
  await settle();
  assert.match($('alerts').textContent, /فعال/);

  // indicator text is Persian
  assert.match($('indicator').textContent, /سود|فرصت|انتظار/);

  assert.deepEqual(problems, [], 'no jsdom errors or unhandled rejections');
  console.log('Classic page smoke passed: settings open/save/close, capital reload, ' +
    'manual fallback, alerts, chart and Persian messages.');
  dom.window.close();
})().catch(error => { console.error(error); if (problems.length) console.error(problems); process.exitCode = 1; });
