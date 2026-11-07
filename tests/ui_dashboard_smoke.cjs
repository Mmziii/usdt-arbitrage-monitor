/* Dashboard DOM smoke test (jsdom): NODE_PATH=<jsdom> node tests/ui_dashboard_smoke.cjs
   Runs the real static scripts against real Python fixtures; no live exchange calls, no browser. */
const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');

const fixture = JSON.parse(execFileSync('.venv/bin/python', ['tests/ui_fixture.py'],
  {encoding: 'utf8', maxBuffer: 32 * 1024 * 1024}));

const dom = new JSDOM(fs.readFileSync('app/static/dashboard.html', 'utf8'),
  {runScripts: 'outside-only', url: 'http://fixture.test/'});
const w = dom.window;
const doc = w.document;

w.setTimeout = () => 1;
w.clearTimeout = () => {};
w.setInterval = () => 1;
w.clearInterval = () => {};
w.requestAnimationFrame = callback => { callback(0); return 1; };
w.confirm = () => true;
w.prompt = () => 'فیلتر آزمایشی';

let ui = structuredClone(fixture.ui);
let cfg = structuredClone(fixture.overview.scanner);
let settings = structuredClone(fixture.settings);
let fees = structuredClone(fixture.fees);
const journal = structuredClone(fixture.journal.rows);
const calls = [];

function overviewPayload() {
  return {...structuredClone(fixture.overview), scanner: structuredClone(cfg), ui: structuredClone(ui)};
}

w.fetch = async function (url, options = {}) {
  calls.push((options.method || 'GET') + ' ' + url);
  let value;
  if (url === '/api/overview') value = overviewPayload();
  else if (url === '/api/wizard') value = structuredClone(fixture.wizard);
  else if (url === '/api/ui') {
    if (options.method === 'PUT') ui = {...ui, ...JSON.parse(options.body).values};
    value = ui;
  } else if (url === '/api/scanner/settings') {
    if (options.method === 'PUT') cfg = JSON.parse(options.body);
    value = cfg;
  } else if (url === '/api/settings') {
    if (options.method === 'PUT') settings = JSON.parse(options.body);
    value = settings;
  } else if (url === '/api/scanner/fees') {
    if (options.method === 'PUT') fees = JSON.parse(options.body);
    value = fees;
  } else if (url === '/api/diagnostics') value = structuredClone(fixture.diagnostics);
  else if (url === '/api/diagnostics/test') value = {ok: false, results: [{
    exchange: 'wallex', label: 'والکس', ok: false, markets: 1,
    steps: [{step: 'فهرست بازارها', ok: false, url: 'https://api.wallex.ir/v1/markets',
             status: 429, elapsed_ms: 90, message: 'درخواست‌ها زیاد است.', action: 'کمی صبر کنید.', preview: '{"success":false}'}],
    clock: {level: 'ok', message: 'ساعت درست است.', action: ''}}]};
  else if (url === '/api/simulations') value = structuredClone(fixture.simulations);
  else if (url.startsWith('/api/simulations/')) value = {ok: true};
  else if (url.startsWith('/api/journal/')) value = {ok: true};
  else if (url === '/api/backup') value = {app: 'usdt-arbitrage-monitor', version: 2, fees: 3};
  else if (url === '/api/backup/restore') value = {ok: true, fees: 3};
  else if (url === '/api/journal') {
    if (options.method === 'POST') {
      const body = JSON.parse(options.body);
      journal.unshift({id: journal.length + 1, ...body});
      value = {id: journal.length, rows: journal};
    } else value = {rows: journal};
  } else if (url.startsWith('/api/overview/detail')) value = structuredClone(fixture.detail);
  else if (url.startsWith('/api/overview/visible')) value = {visible: 1};
  else if (url === '/api/overview/pause') value = {paused: JSON.parse(options.body).paused};
  else if (url === '/api/overview/refresh') value = {ok: true};
  else if (url.startsWith('/api/amount')) value = {ok: true, value: 50_000_000, currency: 'toman'};
  else if (url === '/api/connection') value = structuredClone(settings);
  else if (url.startsWith('/api/plans')) value = structuredClone(fixture.detail.plan);
  else throw new Error('Unexpected URL ' + url);
  return {ok: true, status: 200, text: async () => JSON.stringify(value),
          json: async () => structuredClone(value)};
};

const ctx = dom.getInternalVMContext();
for (const file of ['sort.js', 'ui.js', 'drawer.js', 'panels.js']) {
  vm.runInContext(fs.readFileSync('app/static/' + file, 'utf8'), ctx, {filename: file});
}

async function settle() {
  for (let index = 0; index < 60; index += 1) await Promise.resolve();
}

function text(id) { return doc.getElementById(id).textContent; }
function visible(id) { return doc.getElementById(id).hidden === false; }

(async () => {
  await vm.runInContext('App.init(); App.initPanels();', ctx);
  await settle();

  // --- opportunities table -------------------------------------------------
  assert.ok(doc.querySelectorAll('#rows tr').length >= 2, 'rows render');
  assert.match(text('summaryCards'), /فرصت‌های سودده/);
  assert.match(doc.getElementById('tableHead').textContent, /ارز/);
  assert.ok(doc.querySelector('#rows tr [data-pin]'), 'pin button exists');
  assert.match(doc.getElementById('rows').textContent, /۸\.۷۶/, 'net percent uses Persian digits');

  // --- filters -------------------------------------------------------------
  const search = doc.getElementById('filterSearch');
  search.value = 'NOPE';
  await vm.runInContext('App.renderTable(false)', ctx);
  assert.equal(doc.querySelectorAll('#rows tr').length, 0);
  assert.equal(visible('emptyState'), true);
  search.value = 'BTC';
  await vm.runInContext('App.renderTable(false)', ctx);
  assert.ok(doc.querySelectorAll('#rows tr').length >= 2);
  search.value = '';
  await vm.runInContext('App.renderTable(false)', ctx);

  // --- detail drawer -------------------------------------------------------
  await vm.runInContext("App.openDrawer('A:BTC:wallex')", ctx);
  await settle();
  assert.equal(visible('drawer'), true);
  assert.match(text('drawerTitle'), /BTC/);
  assert.match(text('drawerBody'), /مراحل چرخه/);
  assert.match(text('drawerBody'), /سود خالص/);
  doc.querySelector('[data-drawer-tab="plan"]').click();
  assert.match(text('drawerBody'), /گام/);
  assert.match(text('drawerBody'), /چک‌لیست/);
  doc.querySelector('[data-drawer-tab="books"]').click();
  assert.match(text('drawerBody'), /فروشندگان/);
  assert.match(text('drawerBody'), /بیت‌یونیکس/);
  doc.querySelector('[data-drawer-tab="history"]').click();
  assert.ok(doc.querySelector('#drawerBody svg.chart'), 'history chart drawn');
  doc.querySelector('[data-drawer-tab="fees"]').click();
  assert.match(text('drawerBody'), /شبکه انتقال/);
  assert.equal(doc.getElementById('drawerNetwork').value, 'TRC20');
  doc.getElementById('drawerClose').click();
  assert.equal(doc.getElementById('drawer').hidden, true);

  // --- diagnostics ---------------------------------------------------------
  await vm.runInContext("App.switchTab('diagnostics')", ctx);
  await settle();
  await vm.runInContext('App.renderDiagnostics()', ctx);
  await settle();
  assert.equal(doc.querySelectorAll('#diagCards .diag-card').length, 2);
  assert.match(text('diagCards'), /والکس/);
  assert.match(text('diagCards'), /۴۵۱/);
  assert.match(text('diagCards'), /VPN/);
  assert.equal(visible('diagClock'), false, 'no warning banner when the clock is fine');
  assert.match(text('diagCards'), /اختلاف ساعت/);
  assert.match(text('budgetTable'), /باقی‌مانده/);
  assert.match(text('reasonCatalog'), /درخواست موفق بود/);

  await vm.runInContext('App.runTests(document.getElementById("testAll"))', ctx);
  await settle();
  assert.match(text('testResults'), /والکس/);
  assert.match(text('testResults'), /فهرست بازارها/);

  const form = doc.getElementById('connectionForm');
  doc.getElementById('proxyUrl').value = 'socks5://127.0.0.1:1080';
  doc.getElementById('userAgent').value = 'TraderBot/Test';
  await form.onsubmit({preventDefault() {}});
  await settle();
  assert.ok(calls.some(call => call === 'PUT /api/connection'), 'connection settings saved');

  // --- simulations ---------------------------------------------------------
  await vm.runInContext("App.switchTab('simulations')", ctx);
  await settle();
  assert.equal(doc.querySelectorAll('#simRows tr').length, 2);
  assert.match(text('simSummary'), /میانگین اختلاف/);
  assert.match(text('simRows'), /در انتظار/);
  assert.match(text('simRows'), /محاسبه نتیجه/);

  // --- journal -------------------------------------------------------------
  await vm.runInContext("App.switchTab('journal')", ctx);
  await settle();
  assert.equal(doc.querySelectorAll('#journalRows tr').length, 1);
  const journalForm = doc.getElementById('journalForm');
  doc.getElementById('journalCoin').value = 'eth';
  await journalForm.onsubmit({preventDefault() {}});
  await settle();
  assert.ok(calls.some(call => call === 'POST /api/journal'), 'journal entry posted');
  assert.ok(doc.querySelectorAll('#journalRows tr').length >= 2);

  // --- setup ---------------------------------------------------------------
  await vm.runInContext("App.switchTab('setup')", ctx);
  await settle();
  assert.equal(doc.querySelectorAll('#feeForm [data-fee]').length, 10);
  assert.equal(doc.querySelectorAll('#networkFeeRows tr').length, fees.length);
  const maker = doc.querySelector('#feeForm [data-fee="bitunix"][data-quote="USDT"][data-field="maker"]');
  maker.value = '0.06';
  doc.getElementById('feeSave').click();
  await settle();
  assert.equal(settings.bitunix_usdt.maker, 0.06);
  assert.ok(calls.some(call => call === 'PUT /api/settings'));
  doc.getElementById('networkFeeSave').click();
  await settle();
  assert.ok(calls.some(call => call === 'PUT /api/scanner/fees'));

  // --- capital presets -----------------------------------------------------
  await vm.runInContext("App.switchTab('opportunities')", ctx);
  await settle();
  const before = cfg.capital_usdt;
  doc.querySelector('#capitalPresets button').click();
  await settle();
  assert.notEqual(cfg.capital_usdt, before, 'toman preset recalculated USDT capital');

  // --- wizard --------------------------------------------------------------
  await vm.runInContext('App.openWizard(1)', ctx);
  await settle();
  assert.equal(visible('wizard'), true);
  assert.match(text('wizardBody'), /سرمایه USDT/);
  await vm.runInContext('App.wizardForward()', ctx);
  await settle();
  assert.match(text('wizardBody'), /میکر/);
  await vm.runInContext('App.wizardForward()', ctx);
  await settle();
  assert.match(text('wizardBody'), /شبکه/);
  await vm.runInContext('App.wizardForward()', ctx);
  await settle();
  assert.match(text('wizardBody'), /User-Agent/);
  await vm.runInContext('App.wizardBack()', ctx);
  await settle();
  assert.match(text('wizardBody'), /شبکه/);
  await vm.runInContext('App.openWizard(5)', ctx);
  await settle();
  await settle();
  assert.match(text('wizardBody'), /راه‌اندازی|تکمیل|موارد/);
  doc.getElementById('wizardClose').click();
  assert.equal(doc.getElementById('wizard').hidden, true);

  // --- pause ---------------------------------------------------------------
  doc.getElementById('pauseButton').click();
  await settle();
  assert.ok(calls.some(call => call === 'POST /api/overview/pause'));
  assert.match(text('pauseButton'), /ادامه/);

  // --- simulation settle and delete ---------------------------------------
  await vm.runInContext("App.switchTab('simulations')", ctx);
  await settle();
  const pendingId = doc.querySelector('[data-sim-settle]').dataset.simSettle;
  doc.querySelector('[data-sim-settle]').click();
  await settle();
  assert.ok(calls.some(call => call === 'POST /api/simulations/' + pendingId + '/settle'),
    'settle button posts to the settle route');
  doc.querySelector('[data-sim-delete]').click();
  await settle();
  assert.ok(calls.some(call => call.startsWith('DELETE /api/simulations/')),
    'delete button removes the simulation');

  // --- journal delete ------------------------------------------------------
  await vm.runInContext("App.switchTab('journal')", ctx);
  await settle();
  doc.querySelector('[data-journal-delete]').click();
  await settle();
  assert.ok(calls.some(call => call.startsWith('DELETE /api/journal/')),
    'journal rows can be removed');

  // --- backup, restore and CSV links --------------------------------------
  const backupLink = doc.querySelector('a[href="/api/backup"]');
  const csvLink = doc.querySelector('a[href="/api/journal.csv"]');
  assert.ok(backupLink && csvLink, 'backup and CSV download links exist');
  const restoreInput = doc.getElementById('restoreFile');
  assert.ok(restoreInput && restoreInput.onchange, 'the restore input is wired');
  // jsdom's FileReader runs on window timers, which this smoke freezes; a tiny stand-in
  // keeps the handler code (JSON parse, confirm, POST) under test.
  vm.runInContext('window.FileReader = function () { const self = this;' +
    ' this.readAsText = function (file) { self.result = file.__text;' +
    ' if (self.onload) self.onload(); }; };', ctx);
  const backup = {app: 'usdt-arbitrage-monitor', version: 2, fees: 3};
  restoreInput.onchange({target: {files: [{__text: JSON.stringify(backup)}]}});
  await settle(200);
  assert.ok(calls.some(call => call === 'POST /api/backup/restore'),
    'a backup file is posted to the restore route');
  assert.match(text('message'), /بازگردانی/);
  restoreInput.onchange({target: {files: [{__text: 'not json'}]}});
  await settle(200);
  assert.match(text('message'), /قابل خواندن نیست/);
  assert.equal(calls.filter(call => call === 'POST /api/backup/restore').length, 1,
    'a broken file never reaches the server');

  // --- one failing exchange must not break the page ------------------------
  const savedErrors = fixture.overview.errors;
  fixture.overview.errors = {wallex: 'اتصال به والکس برقرار نشد؛ داده قدیمی است.'};
  await vm.runInContext('App.load(false)', ctx);
  await settle();
  assert.ok(doc.querySelectorAll('#rows tr').length > 0, 'rows still render with one bad exchange');
  assert.match(text('message'), /والکس/);
  assert.match(text('message'), /داده قدیمی است/, 'the reason itself is shown');
  assert.doesNotMatch(text('message'), /\[object Object\]/, 'errors are formatted, not coerced');
  fixture.overview.errors = savedErrors;
  await vm.runInContext('App.load(false)', ctx);
  await settle();

  console.log('Dashboard DOM smoke passed: table, filters, drawer tabs, diagnostics, ' +
    'simulations (settle/delete), journal (add/delete), setup fees, backup/restore, ' +
    'capital presets, wizard, pause, one failing exchange.');
  dom.window.close();
})().catch(error => { console.error(error); process.exitCode = 1; });
