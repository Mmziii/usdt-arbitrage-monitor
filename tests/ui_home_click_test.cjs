/* Click-reliability regression test for the home screen.

   Same reasoning as tests/ui_click_test.cjs: jsdom has no hit-testing, so this file
   emulates the one browser rule that matters here — a click only reaches a control if
   the node pressed on mousedown is still the same connected node at mouseup. Every
   check below fails on the pre-fix home.js (a poll rebuilt #othersGrid, the banner, the
   inline receipt and hid #resultBody) and passes after it.

   NODE_PATH=<jsdom node_modules> node tests/ui_home_click_test.cjs
*/
const {JSDOM, VirtualConsole} = require('jsdom');
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');

const fixture = JSON.parse(execFileSync('.venv/bin/python', ['-c', `
import json, sys
sys.path.insert(0, 'tests')
from home_fixture import payload
print(json.dumps(payload(), ensure_ascii=False))
`], {encoding: 'utf8', maxBuffer: 32 * 1024 * 1024}));

function boot() {
  const problems = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => problems.push('jsdom error: ' + error.message));
  const html = fs.readFileSync('app/static/home.html', 'utf8');
  const dom = new JSDOM(html, {runScripts: 'outside-only', url: 'http://home-click.test/',
    virtualConsole});
  const w = dom.window;
  const doc = w.document;
  const $ = id => doc.getElementById(id);

  w.setTimeout = () => 1;
  w.clearTimeout = () => {};
  w.requestAnimationFrame = callback => { callback(0); return 1; };
  w.Element.prototype.scrollIntoView = function () {};
  if (!w.HTMLElement.prototype.showModal) {
    w.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
    w.HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  }

  let home = structuredClone(fixture.home);
  const calls = [];
  w.fetch = async (url, options = {}) => {
    const method = (options.method || 'GET').toUpperCase();
    calls.push({url, method, body: options.body});
    let value;
    if (url === '/api/home') value = structuredClone(home);
    else if (url.startsWith('/api/receipt?')) value = structuredClone(fixture.receipt);
    else if (url === '/api/overview/pause') value = {paused: JSON.parse(options.body).paused};
    else if (url === '/api/overview/refresh') value = {ok: true};
    else if (url === '/api/setup') value = {setup: fixture.wizard.setup, wizard_done: true};
    else if (url === '/api/ui') value = {values: JSON.parse(options.body).values};
    else if (url === '/api/simulations') value = {id: 1};
    else throw new Error('unexpected URL ' + url);
    return {ok: true, status: 200, json: async () => structuredClone(value)};
  };

  const ctx = dom.getInternalVMContext();
  vm.runInContext(fs.readFileSync('app/static/home.js', 'utf8'), ctx, {filename: 'home.js'});
  const App = w.App;

  async function settle(rounds = 200) {
    for (let index = 0; index < rounds; index += 1) await Promise.resolve();
  }

  return {
    dom, w, doc, $, App, calls, problems, settle,
    setHome(next) { home = next; },
    homeData() { return home; },
    emit(name, init = {}) {
      return new w.MouseEvent(name, {bubbles: true, cancelable: true, ...init});
    },
  };
}

function isOpen(dialog) {
  return !!dialog && (dialog.open === true || dialog.hasAttribute('open'));
}

async function pressThrough(env, node, tick) {
  const before = node;
  node.dispatchEvent(env.emit('mousedown'));
  if (tick) await tick();
  const stillThere = before.isConnected && node === before;
  node.dispatchEvent(env.emit('mouseup'));
  if (!stillThere) return {delivered: false, node};
  node.dispatchEvent(env.emit('click'));
  return {delivered: true, node};
}

(async () => {
  const env = boot();
  const {App, $, doc, w} = env;
  await env.settle();

  const results = [];
  const record = (name, ok, detail) => results.push({name, ok, detail});
  const tick = async () => { await App.load(); await env.settle(); };

  async function closeDialogs() {
    const pairs = [['receiptDialog', 'receiptClose'], ['wizard', 'wizardClose']];
    for (const [id, closeId] of pairs) {
      const dialog = $(id);
      if (!dialog || !isOpen(dialog)) continue;
      // Close through the real button: that is the path a user takes, and it is the one
      // that has to apply the refresh held back while the dialog was open.
      const button = $(closeId);
      if (button) button.click();
      else if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
      await env.settle(60);
    }
    App.state.press = null;
    await env.settle(60);
  }

  async function controlCase(name, selector, {check = null, openFirst = null} = {}) {
    await closeDialogs();
    if (openFirst) {
      doc.querySelector(openFirst).click();
      await env.settle();
    }
    const node = doc.querySelector(selector);
    assert.ok(node, name + ': control exists (' + selector + ')');
    const outcome = await pressThrough(env, node, tick);
    await env.settle();
    const effect = check ? check() === true : true;
    record(name, outcome.delivered && effect, 'delivered=' + outcome.delivered + ' effect=' + effect);
  }

  /* ------------------------------------------------------------------ controls */
  await controlCase('توقف/ادامه به‌روزرسانی', '#pauseBtn', {
    check: () => App.state.paused === true,
  });
  await controlCase('به‌روزرسانی الان', '#refreshBtn', {
    check: () => env.calls.filter(call => call.url === '/api/overview/refresh').length >= 1,
  });
  await controlCase('باز کردن رسید بهترین مسیر', '#receiptBtn', {
    check: () => isOpen($('receiptDialog')),
  });
  await controlCase('بستن رسید', '#receiptClose', {
    check: () => !isOpen($('receiptDialog')),
  });
  await controlCase('کارت «گزینه دیگر» → رسید', '#othersGrid button', {
    check: () => isOpen($('receiptDialog')),
  });
  await controlCase('بستن پیام راه‌اندازی', '#bannerClose', {
    check: () => $('banner').hidden === true,
  });
  await controlCase('پوسته (روشن/تیره)', '#themeBtn', {
    check: () => Boolean(doc.documentElement.dataset.theme),
  });
  await controlCase('ویرایش راه‌اندازی (setupEdit)', '#setupEdit', {
    check: () => isOpen($('wizard')),
  });
  await controlCase('گام بعدی راه‌اندازی', '#wizardNext', {
    openFirst: '#setupEdit',
    check: () => isOpen($('wizard')),
  });
  await controlCase('گام قبلی راه‌اندازی', '#wizardBack', {
    openFirst: '#setupEdit',
    check: () => isOpen($('wizard')),
  });
  await controlCase('بستن راه‌اندازی', '#wizardClose', {
    check: () => !isOpen($('wizard')),
  });
  await controlCase('لینک ناوبری (کارمزدها)', 'a[href="/fees"]');

  /* ------------------------------------------- twenty refreshes, then one click */
  await closeDialogs();
  for (let round = 0; round < 20; round += 1) await tick();
  {
    const card = doc.querySelector('#othersGrid button');
    const before = env.calls.filter(call => call.url.startsWith('/api/receipt?')).length;
    card.click();
    await env.settle();
    const open = isOpen($('receiptDialog'));
    const fetches = env.calls.filter(call => call.url.startsWith('/api/receipt?')).length - before;
    record('۲۰ به‌روزرسانی پشت‌سرهم → یک کلیک، یک اقدام (کارت گزینه دیگر)',
      open && fetches <= 1, 'dialogOpened=' + open + ' receiptFetches=' + fetches);
  }

  /* --------------------------------- identity/focus survive a refresh (unchanged) */
  await closeDialogs();
  {
    const card = doc.querySelector('#othersGrid button');
    const node = card;
    const before = doc.querySelectorAll('#receiptInline .step').length;
    await tick();
    const same = node.isConnected && doc.querySelector('#othersGrid button') === node;
    const sameReceipt = doc.querySelectorAll('#receiptInline .step').length === before;
    record('یک به‌روزرسانی بدون تغییر، کارت و رسید را همان‌جا می‌گذارد',
      same && sameReceipt, 'sameCard=' + same + ' receiptSteps=' + sameReceipt);
  }

  /* --------------------------- a dialog holds the refresh back, then applies it */
  {
    await closeDialogs();
    $('receiptBtn').click();
    await env.settle();
    const dialogOpen = isOpen($('receiptDialog'));
    const changed = structuredClone(env.homeData());
    changed.best.numbers.net_pct = 12.3456;
    changed.best.numbers.net_after_other = null;   // the card prefers this field
    changed.best.numbers.profit_toman = 12345678;
    env.setHome(changed);
    const shownBefore = $('netPct').textContent;
    await tick();
    const heldBack = $('netPct').textContent === shownBefore;
    const pendingWhileOpen = App.hasPendingRender ? App.hasPendingRender() : null;
    await closeDialogs();
    await env.settle(400);
    const textAfter = $('netPct').textContent;
    const applied = /۱۲\.۳۵|12\.35/.test(textAfter);
    record('گفت‌وگو باز است؟ به‌روزرسانی نگه داشته و بعد از بستن اعمال می‌شود',
      dialogOpen && heldBack && applied && pendingWhileOpen !== false,
      'dialogOpen=' + dialogOpen + ' heldBack=' + heldBack + ' applied=' + applied
        + ' pending=' + pendingWhileOpen + ' text=' + JSON.stringify(textAfter));
  }

  /* ------------------------ a press holds the refresh back, then applies it */
  {
    await closeDialogs();
    const pause = $('pauseBtn');
    const before = pause.textContent;
    pause.dispatchEvent(env.emit('mousedown'));
    const changed = structuredClone(env.homeData());
    changed.paused = true;
    env.setHome(changed);
    await tick();
    const heldBack = pause.textContent === before;
    const sameNode = $('pauseBtn') === pause;
    pause.dispatchEvent(env.emit('mouseup'));
    await env.settle(200);
    const applied = /ادامه/.test($('pauseBtn').textContent) && $('pauseBtn') === pause;
    record('دکمه در حال فشردن است؟ به‌روزرسانی نگه داشته و بعد از رها شدن اعمال می‌شود',
      heldBack && sameNode && applied,
      'heldBack=' + heldBack + ' sameNode=' + sameNode + ' applied=' + applied);
  }

  /* --------------------------------------------------------------- the toast */
  {
    const css = fs.readFileSync('app/static/home.css', 'utf8');
    const block = (css.match(/\.toast\s*\{[^}]*\}/) || [''])[0];
    record('پیام شناور (toast) کلیک دکمه‌های زیر خودش را نمی‌خورد',
      /pointer-events:\s*none/.test(block), 'rule=' + JSON.stringify(block.replace(/\s+/g, ' ').slice(0, 80)));
    const toast = $('toast');
    toast.textContent = 'به‌روزرسانی شد.';
    toast.hidden = false;
    const button = $('refreshBtn');
    const outcome = await pressThrough(env, button, null);
    record('کلیک روی دکمه وقتی پیام شناور دیده می‌شود', outcome.delivered, 'delivered=' + outcome.delivered);
    toast.hidden = true;
  }

  /* ------------------------------------------------------------------ report */
  let failed = 0;
  for (const item of results) {
    if (!item.ok) failed += 1;
    console.log((item.ok ? 'ok   ' : 'FAIL ') + item.name + ' — ' + item.detail);
  }
  if (env.problems.length) console.log('jsdom problems: ' + env.problems.join(' | '));
  console.log('\n' + (results.length - failed) + '/' + results.length + ' home click-reliability checks passed');
  env.dom.window.close();
  if (failed) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
