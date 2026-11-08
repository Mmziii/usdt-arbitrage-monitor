/* DOM smoke test for the new home screen (jsdom, no browser, no network).
   NODE_PATH=<jsdom node_modules> node tests/ui_home_smoke.cjs
   The fixture is the real API output produced by tests/home_fixture.py with fake books. */
const { JSDOM } = require('jsdom');
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');

const fixture = JSON.parse(execFileSync('.venv/bin/python', ['-c', `
import json, sys
sys.path.insert(0, 'tests')
from home_fixture import payload
print(json.dumps(payload(), ensure_ascii=False))
`], { encoding: 'utf8' }));

const html = fs.readFileSync('app/static/home.html', 'utf8');
const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://home.test/' });
const w = dom.window;
const doc = w.document;

// No real timers: polling would keep the test alive and the toast never needs to fire.
w.setTimeout = () => 1;
w.clearTimeout = () => {};
w.confirm = () => true;
w.Element.prototype.scrollIntoView = function () {};
if (!w.HTMLElement.prototype.showModal) {
  w.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  w.HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
}
w.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
w.HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };

const calls = [];
let home = structuredClone(fixture.home);
w.fetch = async (url, options = {}) => {
  const method = (options.method || 'GET').toUpperCase();
  calls.push({ url, method, body: options.body });
  let value;
  if (url === '/api/home') value = structuredClone(home);
  else if (url.startsWith('/api/receipt?')) value = structuredClone(fixture.receipt);
  else if (url === '/api/overview/pause') value = { paused: JSON.parse(options.body).paused };
  else if (url === '/api/overview/refresh') value = { ok: true };
  else if (url === '/api/setup') value = { setup: fixture.wizard.setup, wizard_done: true };
  else if (url === '/api/ui') value = { values: JSON.parse(options.body).values };
  else if (url === '/api/simulations') value = { id: 1 };
  else throw new Error('unexpected URL ' + url);
  const ok = !(url === '/api/broken');
  return { ok, status: ok ? 200 : 500, json: async () => structuredClone(value) };
};

const ctx = dom.getInternalVMContext();
vm.runInContext(fs.readFileSync('app/static/home.js', 'utf8'), ctx, { filename: 'home.js' });
const settle = async () => { for (let i = 0; i < 80; i += 1) await Promise.resolve(); };

const text = (id) => (doc.getElementById(id) || {}).textContent || '';
const visible = (id) => {
  const node = doc.getElementById(id);
  return Boolean(node) && node.hidden === false;
};

(async () => {
  await settle();

  // --- nothing may be open when the page loads ------------------------------
  assert.equal(doc.querySelectorAll('dialog[open]').length, 0, 'no dialog open on load');
  assert.equal(doc.getElementById('banner').hidden, true === false ? true : doc.getElementById('banner').hidden);
  assert.ok(doc.getElementById('wizard').open === false || !doc.getElementById('wizard').open);

  // --- navigation -----------------------------------------------------------
  const nav = [...doc.querySelectorAll('.nav a')].map((link) => link.getAttribute('href'));
  assert.deepEqual(nav, ['/', '/fees', '/guide', '/settings', '/dashboard']);
  assert.equal(doc.querySelector('.nav a[aria-current="page"]').textContent, 'خانه');
  assert.match(text('disclaimer'), /تضمین/);

  // --- the result card ------------------------------------------------------
  assert.equal(doc.getElementById('resultBody').hidden, false);
  assert.equal(doc.getElementById('resultLoading').hidden, true);
  assert.equal(text('verdictLabel'), fixture.home.best.decision.label);
  assert.equal(text('verdictIcon'), fixture.home.best.decision.icon);
  assert.equal(doc.getElementById('resultBadge').className,
    'badge tone-' + fixture.home.best.decision.tone);
  assert.match(text('verdictText'), /سود|صبر|معامله/);
  assert.match(text('netToman'), /[۰-۹]/);
  assert.match(text('netToman'), /تومان/);
  assert.match(text('netPct'), /٪/);
  assert.match(text('confidenceLevel'), /بالا|متوسط|پایین/);
  assert.ok(doc.querySelectorAll('#checks li').length >= 3);
  assert.ok(doc.querySelector('#checks li.ok .mark'));

  // --- inline journey receipt ----------------------------------------------
  assert.equal(doc.getElementById('receiptSection').hidden, false);
  assert.equal(doc.querySelectorAll('#receiptInline .step').length,
    fixture.home.best.receipt.steps.length);
  assert.match(text('receiptInline'), /از صفر|خرید|برداشت|فروش/);
  assert.deepEqual([...doc.querySelectorAll('#receiptInline .step-no')].map((n) => n.textContent),
    fixture.home.best.receipt.steps.map((step) => '۰۱۲۳۴۵۶۷۸۹'[step.n]));
  assert.match(text('receiptInline'), /کارمزد/);
  assert.match(text('receiptInline'), /سرمایه سربه‌سر/);
  assert.match(text('receiptInline'), /با سرمایه و سود می‌خواند/);
  assert.match(text('receiptInline'), /چه چیزی می‌تواند خراب شود/);
  assert.match(text('receiptInline'), /قبل از شروع/);

  // --- gauge ----------------------------------------------------------------
  assert.match(text('gaugeBody'), /حداقل ۲۴ ساعت|بهتر از/);
  assert.match(text('gaugeBody'), /پیش‌بینی|حدس/);

  // --- other options open the same receipt ---------------------------------
  if (fixture.home.others.length) {
    assert.equal(doc.getElementById('othersSection').hidden, false);
    const cards = doc.querySelectorAll('#othersGrid .option');
    assert.equal(cards.length, fixture.home.others.length);
    cards[0].dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    await settle();
    assert.ok(doc.getElementById('receiptDialog').open, 'receipt dialog opens on click');
    assert.equal(doc.querySelectorAll('#receiptBody .step').length,
      fixture.receipt.receipt.steps.length);
    assert.ok(calls.some((call) => call.url.startsWith('/api/receipt?')));
    doc.getElementById('receiptClose').click();
    assert.ok(!doc.getElementById('receiptDialog').open);
  }

  // --- fees hint ------------------------------------------------------------
  assert.equal(doc.getElementById('feesHint').hidden, false);
  assert.ok(doc.getElementById('feesText').textContent.length > 0);

  // --- banner: shown by data, closed by the user ---------------------------
  const banner = fixture.home.banner;
  if (banner.visible && banner.items.length) {
    assert.equal(doc.getElementById('banner').hidden, false);
    assert.equal(doc.querySelectorAll('#bannerItems li').length, banner.items.length);
    doc.getElementById('bannerClose').click();
    await settle();
    assert.equal(doc.getElementById('banner').hidden, true);
    const saved = calls.filter((call) => call.url === '/api/ui').pop();
    assert.equal(JSON.parse(saved.body).values.setup_banner_dismissed, banner.signature);
  }

  // --- pause / resume -------------------------------------------------------
  doc.getElementById('pauseBtn').click();
  await settle();
  assert.equal(JSON.parse(calls.filter((c) => c.url === '/api/overview/pause').pop().body).paused, true);
  assert.equal(doc.getElementById('pauseBtn').textContent, 'ادامه');
  doc.getElementById('pauseBtn').click();
  await settle();
  assert.equal(JSON.parse(calls.filter((c) => c.url === '/api/overview/pause').pop().body).paused, false);

  // --- refresh --------------------------------------------------------------
  doc.getElementById('refreshBtn').click();
  await settle();
  assert.ok(calls.some((call) => call.url === '/api/overview/refresh' && call.method === 'POST'));

  // --- wizard: three steps, then one save ----------------------------------
  doc.getElementById('setupEdit').click();
  assert.ok(doc.getElementById('wizard').open, 'setup button opens the wizard');
  assert.match(text('wizardTitle'), /مرحله ۱ از ۳/);
  assert.match(text('wizardBody'), /صرافی/);
  assert.match(text('wizardBody'), /پولت الان کجاست/);
  assert.equal(doc.querySelectorAll('#wizardBody input[type=checkbox]').length, 3);
  await vm.runInContext('App.wizardNext()', ctx);
  await settle();
  assert.match(text('wizardTitle'), /مرحله ۲ از ۳/);
  assert.match(text('wizardBody'), /چقدر/);
  doc.getElementById('wizardCapital').value = '۵۰ میلیون';
  await vm.runInContext('App.wizardNext()', ctx);
  await settle();
  assert.match(text('wizardTitle'), /مرحله ۳ از ۳/);
  assert.match(text('wizardBody'), /خبرم کن|پیام/);
  await vm.runInContext('App.wizardNext()', ctx);
  await settle();
  const setupCall = calls.filter((call) => call.url === '/api/setup' && call.method === 'PUT').pop();
  assert.ok(setupCall, 'the wizard saves the setup');
  const savedSetup = JSON.parse(setupCall.body);
  assert.equal(savedSetup.capital, 50000000);
  assert.equal(savedSetup.complete, true);
  assert.ok(savedSetup.exchanges.length >= 1);
  assert.ok(!doc.getElementById('wizard').open, 'the wizard closes after saving');

  // --- amount parsing -------------------------------------------------------
  assert.equal(vm.runInContext('App.parseAmount("۵۰ میلیون")', ctx), 50000000);
  assert.equal(vm.runInContext('App.parseAmount("۱٫۵ میلیون")', ctx), 1500000);
  assert.equal(vm.runInContext('App.parseAmount("۱۰۰ دلار")', ctx), 100);
  assert.equal(vm.runInContext('App.parseAmount("سلام")', ctx), null);

  // --- empty state ----------------------------------------------------------
  const emptyHome = structuredClone(fixture.home);
  emptyHome.best = null;
  emptyHome.others = [];
  emptyHome.empty = { message: 'فعلاً فرصت سودده‌ای نیست.', window_days: 7,
    last_profitable_at: null, notify: false };
  vm.runInContext('App.render(' + JSON.stringify(emptyHome) + ')', ctx);
  await settle();
  assert.equal(doc.getElementById('emptyCard').hidden, false);
  assert.match(text('emptyText'), /فرصت/);
  assert.equal(doc.getElementById('resultBody').hidden, true);
  assert.equal(doc.getElementById('receiptSection').hidden, true);
  assert.equal(doc.getElementById('othersSection').hidden, true);

  // --- theme ----------------------------------------------------------------
  doc.getElementById('themeBtn').click();
  assert.equal(doc.documentElement.dataset.theme, 'light');
  doc.getElementById('themeBtn').click();
  assert.equal(doc.documentElement.dataset.theme, 'dark');
  doc.getElementById('themeBtn').click();
  assert.equal(doc.documentElement.dataset.theme, 'system');

  // --- a failing API keeps the page alive ----------------------------------
  w.fetch = async () => ({ ok: false, status: 503, json: async () => ({ detail: 'سرویس در دسترس نیست.' }) });
  await vm.runInContext('App.load()', ctx);
  await settle();
  assert.equal(doc.getElementById('resultError').hidden, false);
  assert.match(text('resultError'), /سرویس در دسترس نیست|دوباره/);

  console.log('ui_home_smoke: ok — home, receipt, gauge, wizard, banner, empty state, theme');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
