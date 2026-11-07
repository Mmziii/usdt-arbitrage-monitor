/* Full control-and-dismissal smoke test for the dashboard, with the real stylesheet.
   jsdom is the only browser DOM available in this sandbox (no Chromium/Playwright), and it
   applies the CSS cascade, so `getComputedStyle` catches "[hidden] does not hide" bugs.

   NODE_PATH=<jsdom node_modules> node tests/ui_controls_smoke.cjs
*/
const {JSDOM, VirtualConsole} = require('jsdom');
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');

const pkg = JSON.parse(execFileSync('.venv/bin/python', ['tests/ui_fixture.py'],
  {encoding: 'utf8', maxBuffer: 32 * 1024 * 1024}));

const problems = [];
process.on('unhandledRejection', reason => problems.push('unhandled rejection: ' + reason));
const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', error => problems.push('jsdom error: ' + error.message));

const css = fs.readFileSync('app/static/ui.css', 'utf8');
const html = fs.readFileSync('app/static/dashboard.html', 'utf8')
  .replace('<link rel="stylesheet" href="/static/ui.css">', '<style>\n' + css + '\n</style>');
assert.ok(html.indexOf('<style>') !== -1, 'stylesheet is inlined for cascade checks');

const dom = new JSDOM(html, {runScripts: 'outside-only', url: 'http://fixture.test/',
  virtualConsole, pretendToBeVisual: true});
const w = dom.window;
const doc = w.document;
const $ = id => doc.getElementById(id);

w.setTimeout = () => 1;
w.clearTimeout = () => {};
w.setInterval = () => 1;
w.clearInterval = () => {};
w.requestAnimationFrame = callback => { callback(0); return 1; };
w.confirm = () => true;
w.prompt = () => 'فیلتر آزمایشی';

let ui = structuredClone(pkg.ui);
let cfg = structuredClone(pkg.overview.scanner);
let settings = structuredClone(pkg.settings);
let fees = structuredClone(pkg.fees);
let wizard = structuredClone(pkg.wizard);
let currentDiagnostics = pkg.diagnostics;
let overview = structuredClone(pkg.overview);
const calls = [];
const errorText = [];

function payloadFor(url, options) {
  if (url === '/api/overview') return {...structuredClone(overview), scanner: structuredClone(cfg),
    ui: structuredClone(ui)};
  if (url === '/api/wizard') return structuredClone(wizard);
  if (url === '/api/ui') {
    if (options.method === 'PUT') ui = {...ui, ...JSON.parse(options.body).values};
    return ui;
  }
  if (url === '/api/scanner/settings') {
    if (options.method === 'PUT') cfg = JSON.parse(options.body);
    return cfg;
  }
  if (url === '/api/settings') {
    if (options.method === 'PUT') settings = JSON.parse(options.body);
    return settings;
  }
  if (url === '/api/scanner/fees') {
    if (options.method === 'PUT') fees = JSON.parse(options.body);
    return fees;
  }
  if (url === '/api/diagnostics') return structuredClone(currentDiagnostics);
  if (url === '/api/diagnostics/test') return {ok: true, results: []};
  if (url === '/api/simulations') return structuredClone(pkg.simulations);
  if (url === '/api/journal') return structuredClone(pkg.journal);
  if (url.startsWith('/api/overview/detail')) return structuredClone(pkg.detail);
  if (url.startsWith('/api/overview/visible')) return {visible: 1};
  if (url === '/api/overview/pause') return {paused: JSON.parse(options.body).paused};
  if (url === '/api/overview/refresh') return {ok: true};
  if (url.startsWith('/api/amount')) return {ok: true, value: 50_000_000, currency: 'toman'};
  if (url === '/api/connection') return structuredClone(settings);
  if (url.startsWith('/api/plan')) return structuredClone(pkg.detail.plan);
  throw new Error('Unexpected URL ' + url);
}

w.fetch = async function (url, options = {}) {
  const entry = {url, method: (options.method || 'GET'), body: options.body || null};
  calls.push(entry);
  const value = payloadFor(url, options);
  return {ok: true, status: 200, text: async () => JSON.stringify(value),
          json: async () => structuredClone(value)};
};

const ctx = dom.getInternalVMContext();
w.addEventListener('error', event => errorText.push(String(event.message)));

for (const file of ['sort.js', 'ui.js', 'drawer.js', 'panels.js']) {
  try {
    vm.runInContext(fs.readFileSync('app/static/' + file, 'utf8'), ctx, {filename: file});
  } catch (error) {
    problems.push(file + ' failed to load: ' + error.message);
  }
}

async function settle(rounds = 80) {
  for (let index = 0; index < rounds; index += 1) await Promise.resolve();
}

function display(id) {
  return w.getComputedStyle($(id)).display;
}

function assertHidden(id, why) {
  assert.equal($(id).hidden, true, id + ' should have hidden=true (' + why + ')');
  assert.equal(display(id), 'none', id + ' must not render while hidden (' + why + ')');
}

function assertVisible(id, why) {
  assert.equal($(id).hidden, false, id + ' should have hidden=false (' + why + ')');
  assert.notEqual(display(id), 'none', id + ' must render when open (' + why + ')');
}

function key(name) {
  doc.dispatchEvent(new w.KeyboardEvent('keydown', {key: name, bubbles: true, cancelable: true}));
}

function mouseDown(node) {
  node.dispatchEvent(new w.MouseEvent('mousedown', {bubbles: true, cancelable: true}));
}

function lastCall(method, url) {
  return calls.filter(call => call.method === method && call.url === url).pop();
}

(async () => {
  await vm.runInContext('App.init(); App.initPanels();', ctx);
  await settle();

  // ---------------------------------------------------------------- hidden contract
  for (const id of ['wizard', 'manualDrawer', 'drawer', 'helpPop', 'menuPanel']) {
    assertHidden(id, 'closed on first load');
  }
  assert.equal($('message').hidden, true, 'empty message stays hidden');

  // --------------------------------------------------------------- setup banner X
  assertVisible('setupBanner', 'the fixture is missing setup items');
  mouseDown($('setupBannerAction'));            // not the close button: banner stays
  assertVisible('setupBanner', 'action button must not dismiss the notice');
  $('setupBannerClose').click();
  await settle();
  assertHidden('setupBanner', 'the X button closes the notice');
  const uiSave = lastCall('PUT', '/api/ui');
  assert.ok(uiSave && JSON.parse(uiSave.body).values.setup_banner_dismissed,
    'the dismissal signature is persisted through /api/ui');
  await vm.runInContext('App.load(false)', ctx);
  await settle();
  assertHidden('setupBanner', 'a refresh does not resurrect a dismissed notice');
  wizard = {...wizard, missing: wizard.missing.concat(['کارمزد برداشت تتر در والکس'])};
  await vm.runInContext('App.load(false)', ctx);
  await settle();
  assertVisible('setupBanner', 'a changed missing list shows the notice again');

  // ------------------------------------------------------------------ menu toggle
  $('menuToggle').click();
  assertVisible('menuPanel', 'menu opens');
  assert.equal($('menuToggle').getAttribute('aria-expanded'), 'true');
  mouseDown($('main'));
  assertHidden('menuPanel', 'outside click closes the menu');
  assert.equal($('menuToggle').getAttribute('aria-expanded'), 'false');
  $('menuToggle').click();
  key('Escape');
  assertHidden('menuPanel', 'Escape closes the menu');

  // ------------------------------------------------------------- drawer open/close
  const row = doc.querySelector('#rows tr[data-key]');
  assert.ok(row, 'a data row exists');
  const rowKey = row.dataset.key;
  row.focus();
  row.click();
  await settle();
  assertVisible('drawer', 'row click opens the drawer');
  assert.equal(doc.activeElement && doc.activeElement.id, 'drawerClose',
    'focus moves into the drawer');
  assert.match($('drawerBody').textContent, /مراحل چرخه/);

  $('drawerClose').click();
  await settle();
  assertHidden('drawer', 'the X button closes the drawer');
  assert.equal(doc.activeElement && doc.activeElement.dataset.key, rowKey,
    'focus returns to the row that opened the drawer');

  row.click();
  await settle();
  assertVisible('drawer', 'drawer reopens');
  key('Escape');
  await settle();
  assertHidden('drawer', 'Escape closes the drawer');
  assert.equal(doc.activeElement && doc.activeElement.dataset.key, rowKey,
    'focus returns to the row after Escape');

  row.click();
  await settle();
  assertVisible('drawer', 'drawer reopens for the outside click check');
  mouseDown($('main'));
  await settle();
  assertHidden('drawer', 'clicking outside closes the drawer');

  row.click();
  await settle();
  assertVisible('drawer', 'a row click must not close the drawer it just opened');
  mouseDown($('drawerBody'));
  assertVisible('drawer', 'clicking inside the drawer keeps it open');
  $('drawerClose').click();
  await settle();

  // ------------------------------------------------------------------- message
  await vm.runInContext("App.message('ارتباط با صرافی قطع شد', true)", ctx);
  assertVisible('message', 'an error message is shown');
  assert.equal($('message').className, 'message error');
  $('messageClose').click();
  assertHidden('message', 'the X button dismisses the message');
  await vm.runInContext("App.message('ارتباط با صرافی قطع شد', true)", ctx);
  assertHidden('message', 'the same error does not pop back on the next poll');
  const realNow = w.Date.now;
  w.Date.now = () => realNow() + 121000;
  await vm.runInContext("App.message('ارتباط با صرافی قطع شد', true)", ctx);
  w.Date.now = realNow;
  assertVisible('message', 'the same error returns after the reopen delay');
  await vm.runInContext("App.message('دلیل تازه: محدودیت نرخ', true)", ctx);
  assertVisible('message', 'a changed error is shown immediately');
  await vm.runInContext('App.message("")', ctx);
  assertHidden('message', 'an empty message hides the box');

  // -------------------------------------------------------------------- wizard
  $('wizardOpen').focus();
  $('wizardOpen').click();
  await settle();
  assertVisible('wizard', 'the wizard button opens the wizard');
  assert.equal(doc.activeElement && doc.activeElement.id, 'wizardClose',
    'focus moves to the wizard close button');
  key('Escape');
  await settle();
  assertHidden('wizard', 'Escape closes the wizard');
  assert.equal(doc.activeElement && doc.activeElement.id, 'wizardOpen',
    'focus returns to the wizard button');

  $('wizardOpen').click();
  await settle();
  $('wizardNext').click();
  await settle();
  assert.match($('wizardBody').textContent, /میکر/);
  $('wizardPrev').click();
  await settle();
  assert.match($('wizardBody').textContent, /سرمایه USDT/);
  $('wizardClose').click();
  await settle();
  assertHidden('wizard', 'the X button closes the wizard');
  $('wizardOpen').click();
  await settle();
  mouseDown($('wizard'));
  await settle();
  assertHidden('wizard', 'clicking the backdrop closes the wizard');

  // -------------------------------------------------------------- manual prices
  $('manualOpen').focus();
  $('manualOpen').click();
  assertVisible('manualDrawer', 'the manual entry button opens the modal');
  assert.equal(doc.activeElement && doc.activeElement.id, 'manualClose');
  $('manualClose').click();
  assertHidden('manualDrawer', 'the X button closes the manual modal');
  assert.equal(doc.activeElement && doc.activeElement.id, 'manualOpen',
    'focus returns to the manual entry button');
  $('manualOpen').click();
  key('Escape');
  assertHidden('manualDrawer', 'Escape closes the manual modal');
  $('manualOpen').click();
  mouseDown($('manualDrawer'));
  assertHidden('manualDrawer', 'clicking the backdrop closes the manual modal');

  // -------------------------------------------------------------------- tooltips
  const help = doc.querySelector('.help');
  assert.ok(help, 'help icons exist');
  help.click();
  assertVisible('helpPop', 'clicking a help icon shows the explanation');
  key('Escape');
  assertHidden('helpPop', 'Escape hides the explanation');
  help.click();
  doc.body.click();
  assertHidden('helpPop', 'clicking elsewhere hides the explanation');

  // ----------------------------------------------------------------------- tabs
  for (const tab of ['simulations', 'journal', 'diagnostics', 'setup', 'opportunities']) {
    await vm.runInContext("App.switchTab('" + tab + "')", ctx);
    await settle();
    const shown = ['simulations', 'journal', 'diagnostics', 'setup', 'opportunities']
      .filter(name => !$('tab-' + name).hidden);
    assert.deepEqual(shown, [tab], 'exactly one tab is visible: ' + tab);
    assert.match($('tab-' + tab).textContent.trim(), /./, tab + ' tab has content');
  }
  await vm.runInContext("App.switchTab('diagnostics')", ctx);
  await settle();
  await vm.runInContext('App.renderDiagnostics()', ctx);
  await settle();
  assert.match($('diagCards').textContent, /والکس/);
  assert.equal($('diagClock').hidden, true, 'no clock warning means no warning banner');
  const warnDiagnostics = structuredClone(pkg.diagnostics);
  warnDiagnostics.exchanges.wallex.clock = {level: 'warn', skew_seconds: 95,
    message: 'ساعت ویندوز شما حدود ۹۵ ثانیه با ساعت صرافی اختلاف دارد.',
    action: 'ساعت ویندوز را همگام کنید.', checked_at: 1, samples: 2};
  currentDiagnostics = warnDiagnostics;
  await vm.runInContext('App.renderDiagnostics()', ctx);
  await settle();
  assertVisible('diagClock', 'a clock skew warning is shown');
  assert.match($('diagClock').textContent, /همگام/);
  currentDiagnostics = pkg.diagnostics;
  await vm.runInContext('App.renderDiagnostics()', ctx);
  await settle();
  assertHidden('diagClock', 'the warning disappears when the skew is fixed');
  await vm.runInContext("App.switchTab('setup')", ctx);
  await settle();
  assert.equal(doc.querySelectorAll('#feeForm [data-fee]').length, 10);
  assert.equal(doc.querySelectorAll('#networkFeeRows tr').length, fees.length);

  // ------------------------------------------------- view, theme, font, digits
  await vm.runInContext("App.switchTab('opportunities')", ctx);
  await settle();
  $('viewAdvanced').click();
  await settle();
  assert.equal($('viewAdvanced').getAttribute('aria-pressed'), 'true');
  assert.ok(doc.querySelectorAll('#tableHead th').length >= 10, 'advanced view has more columns');
  $('viewSimple').click();
  await settle();
  assert.equal($('viewSimple').getAttribute('aria-pressed'), 'true');

  const themeBefore = doc.documentElement.dataset.theme;
  $('themeToggle').click();
  await settle();
  assert.notEqual(doc.documentElement.dataset.theme, themeBefore, 'theme cycles');
  assert.ok(lastCall('PUT', '/api/ui'), 'theme change is saved');

  $('fontScale').value = 'large';
  $('fontScale').dispatchEvent(new w.Event('change', {bubbles: true}));
  await settle();
  assert.equal(doc.documentElement.style.getPropertyValue('--font-base'), '19px');
  assert.equal(JSON.parse(lastCall('PUT', '/api/ui').body).values.font_scale, 'large');

  $('digits').value = 'en';
  $('digits').dispatchEvent(new w.Event('change', {bubbles: true}));
  await settle();
  await vm.runInContext('App.renderTable(false)', ctx);
  assert.match($('rows').textContent, /8\.760/, 'Latin digits after switching');
  $('digits').value = 'fa';
  $('digits').dispatchEvent(new w.Event('change', {bubbles: true}));
  await settle();
  await vm.runInContext('App.renderTable(false)', ctx);
  assert.match($('rows').textContent, /۸\.۷۶۰/, 'Persian digits after switching back');

  // ------------------------------------------------------------ freeze and order
  $('freezeButton').click();
  await settle();
  assert.equal($('freezeButton').getAttribute('aria-pressed'), 'true');
  const orderFrozen = await vm.runInContext('App.state.order.join("|")', ctx);
  const flipped = structuredClone(overview.rows);
  flipped[0].net_pct = -50;
  flipped[0].net_quote = -50;
  flipped[1].net_pct = 50;
  flipped[1].net_quote = 50;
  overview = {...overview, rows: flipped};
  await vm.runInContext('App.load(false)', ctx);
  await settle();
  assert.equal(await vm.runInContext('App.state.order.join("|")', ctx), orderFrozen,
    'freeze keeps the previous order even when profits change');
  $('freezeButton').click();
  await settle();
  await vm.runInContext('App.load(false)', ctx);
  await settle();
  assert.notEqual(await vm.runInContext('App.state.order.join("|")', ctx), orderFrozen,
    'unfreezing lets the table re-rank');
  overview = {...overview, rows: structuredClone(pkg.overview.rows)};
  await vm.runInContext('App.load(false)', ctx);
  await settle();

  // ------------------------------------------------------------ filters and pins
  $('filterSearch').value = 'NOPE';
  $('filterSearch').dispatchEvent(new w.Event('input', {bubbles: true}));
  assert.equal(doc.querySelectorAll('#rows tr').length, 0);
  assertVisible('emptyState', 'an empty filter result is explained');
  $('filterSearch').value = '';
  $('filterSearch').dispatchEvent(new w.Event('input', {bubbles: true}));
  assert.ok(doc.querySelectorAll('#rows tr').length >= 2);

  $('filterHideGross').checked = true;
  $('filterHideGross').dispatchEvent(new w.Event('change', {bubbles: true}));
  await settle();
  assert.ok(JSON.parse(lastCall('PUT', '/api/ui').body).values.last_filter.hideGross === true,
    'filters are remembered');

  const pin = doc.querySelector('#rows [data-pin]');
  const pinCoin = pin.dataset.pin;
  pin.click();
  await settle();
  const pins = JSON.parse(lastCall('PUT', '/api/ui').body).values.pins;
  assert.ok(Array.isArray(pins), 'pins are saved as a list');
  assert.ok(!pins.includes(pinCoin), 'clicking a pinned coin unpins it');

  $('presetSave').click();
  await settle();
  const presets = JSON.parse(lastCall('PUT', '/api/ui').body).values.presets;
  assert.equal(presets.length, 1, 'the current filter is stored as a preset');
  $('presetSelect').value = '0';
  $('presetSelect').dispatchEvent(new w.Event('change', {bubbles: true}));
  await settle();
  assert.equal($('filterSearch').value, presets[0].filters.search || '');

  const column = doc.querySelector('#columnChooser [data-column]');
  column.checked = false;
  column.dispatchEvent(new w.Event('change', {bubbles: true}));
  await settle();
  assert.ok(JSON.parse(lastCall('PUT', '/api/ui').body).values.columns.length >= 1);

  // ---------------------------------------------------------- capital and amount
  const capitalBefore = cfg.capital_toman;
  $('capitalInput').value = '50 میلیون';
  $('capitalInput').dispatchEvent(new w.Event('change', {bubbles: true}));
  await settle();
  assert.ok(calls.some(call => call.url.startsWith('/api/amount')), 'the typed amount is parsed');
  assert.notEqual(cfg.capital_toman, capitalBefore, 'typed capital is applied');
  assert.equal(cfg.capital_toman, 50_000_000);
  doc.querySelector('#capitalPresets button').click();
  await settle();
  assert.ok(calls.filter(call => call.method === 'PUT' && call.url === '/api/scanner/settings').length >= 2);

  // ------------------------------------------------------------ refresh / pause
  $('refreshButton').click();
  await settle();
  assert.ok(calls.some(call => call.url === '/api/overview/refresh' && call.method === 'POST'));
  $('pauseButton').click();
  await settle();
  assert.ok(calls.some(call => call.url === '/api/overview/pause' && call.method === 'POST'));
  assert.match($('pauseButton').textContent, /ادامه/);
  assert.equal($('pauseChip').hidden, false, 'the stopped chip appears');
  assert.notEqual(display('pauseChip'), 'none');
  $('pauseButton').click();
  await settle();
  assert.match($('pauseButton').textContent, /توقف/);
  assertHidden('pauseChip', 'the stopped chip disappears when running');

  // -------------------------------------------------------- keyboard shortcuts
  doc.querySelector('#filterSearch').blur();
  key('/');
  assert.equal(doc.activeElement && doc.activeElement.id, 'filterSearch', '/ focuses search');
  doc.querySelector('#filterSearch').blur();
  key('f');
  await settle();
  assert.ok(['true', 'false'].includes($('freezeButton').getAttribute('aria-pressed')));

  // ------------------------------------------------------------ drawer + refresh
  doc.querySelector('#rows tr[data-key]').click();
  await settle();
  assertVisible('drawer', 'drawer opens again');
  const scrollBefore = $('drawer').scrollTop;
  await vm.runInContext('App.load(false)', ctx);
  await settle();
  assertVisible('drawer', 'a refresh cycle does not close the drawer');
  assert.equal($('drawer').scrollTop, scrollBefore, 'the drawer keeps its scroll position');
  assert.equal(doc.activeElement && doc.activeElement.id, 'drawerClose',
    'the refresh does not steal focus from the drawer');
  $('drawerClose').click();
  await settle();

  // -------------------------------------------------------------------- summary
  for (const id of ['wizard', 'manualDrawer', 'drawer', 'helpPop', 'menuPanel']) {
    assertHidden(id, 'closed again at the end of the run');
  }
  assert.deepEqual(errorText, [], 'no window errors');
  assert.deepEqual(problems, [], 'no jsdom errors or unhandled rejections');
  console.log('Controls smoke passed: 20 close/dismiss paths, tabs, toggles, filters, ' +
    'pins, presets, capital, freeze, keyboard, refresh-while-open; CSS cascade verified.');
  dom.window.close();
})().catch(error => { console.error(error); if (problems.length) console.error(problems); process.exitCode = 1; });
