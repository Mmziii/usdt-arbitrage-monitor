/* Click-reliability regression test for the dashboard.

   The symptom: on a real laptop a button often needs one or two extra clicks while the
   page keeps polling. A browser dispatches `click` on the nearest common inclusive
   ancestor of the mousedown and mouseup targets; if the periodic re-render detached the
   mousedown node in between, the click is dispatched on a detached node and no handler
   runs. jsdom has no hit-testing and no layout, so this file emulates exactly that one
   rule (mousedown target must still be the same, connected node at mouseup) and asserts
   node identity instead of pretending to measure pixels.

   Every test here fails on the pre-fix code and passes after the fix.

   NODE_PATH=<jsdom node_modules> node tests/ui_click_test.cjs
*/
const {JSDOM, VirtualConsole} = require('jsdom');
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');

const pkg = JSON.parse(execFileSync('.venv/bin/python', ['tests/ui_fixture.py'],
  {encoding: 'utf8', maxBuffer: 32 * 1024 * 1024}));

function boot() {
  const problems = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => problems.push('jsdom error: ' + error.message));
  const css = fs.readFileSync('app/static/ui.css', 'utf8');
  const html = fs.readFileSync('app/static/dashboard.html', 'utf8')
    .replace('<link rel="stylesheet" href="/static/ui.css">', '<style>\n' + css + '\n</style>');
  const dom = new JSDOM(html, {runScripts: 'outside-only', url: 'http://click.test/',
    virtualConsole, pretendToBeVisual: true});
  const w = dom.window;
  const doc = w.document;
  const $ = id => doc.getElementById(id);

  w.setTimeout = () => 1;
  w.clearTimeout = () => {};
  w.setInterval = () => 1;
  w.clearInterval = () => {};
  w.requestAnimationFrame = callback => { callback(0); return 1; };
  w.cancelAnimationFrame = () => {};
  w.confirm = () => true;
  w.prompt = () => 'فیلتر آزمایشی';

  let ui = structuredClone(pkg.ui);
  let overview = structuredClone(pkg.overview);
  let cfg = structuredClone(pkg.overview.scanner);
  let wizard = structuredClone(pkg.wizard);
  const calls = [];

  function payloadFor(url, options = {}) {
    if (url === '/api/overview') {
      return {...structuredClone(overview), scanner: structuredClone(cfg), ui: structuredClone(ui)};
    }
    if (url === '/api/wizard') return structuredClone(wizard);
    if (url === '/api/ui') {
      if (options.method === 'PUT') ui = {...ui, ...JSON.parse(options.body).values};
      return structuredClone(ui);
    }
    if (url === '/api/scanner/settings') {
      if (options.method === 'PUT') cfg = JSON.parse(options.body);
      return structuredClone(cfg);
    }
    if (url === '/api/scanner/fees') return structuredClone(pkg.fees);
    if (url === '/api/settings') return structuredClone(pkg.settings);
    if (url === '/api/diagnostics') return structuredClone(pkg.diagnostics);
    if (url === '/api/diagnostics/test') return {ok: true, results: []};
    if (url.startsWith('/api/overview/detail')) return structuredClone(pkg.detail);
    if (url.startsWith('/api/overview/visible')) return {visible: 1};
    if (url === '/api/overview/pause') return {paused: true};
    if (url === '/api/overview/refresh') return {ok: true};
    if (url === '/api/simulations') return structuredClone(pkg.simulations);
    if (url === '/api/journal') return structuredClone(pkg.journal);
    if (url.startsWith('/api/amount')) return {ok: true, value: 50e6, currency: 'toman'};
    if (url === '/api/connection') return structuredClone(pkg.settings);
    if (url.startsWith('/api/plan')) return structuredClone(pkg.detail.plan);
    throw new Error('Unexpected URL ' + url);
  }

  w.fetch = async function (url, options = {}) {
    calls.push({url, method: options.method || 'GET', body: options.body || null});
    const value = payloadFor(url, options);
    return {ok: true, status: 200, text: async () => JSON.stringify(value),
      json: async () => structuredClone(value)};
  };

  const ctx = dom.getInternalVMContext();
  for (const file of ['sort.js', 'ui.js', 'drawer.js', 'panels.js']) {
    vm.runInContext(fs.readFileSync('app/static/' + file, 'utf8'), ctx, {filename: file});
  }
  const App = w.App;

  async function settle(rounds = 120) {
    for (let index = 0; index < rounds; index += 1) await Promise.resolve();
  }

  return {
    dom, w, doc, $, App, ctx, calls, problems,
    settle,
    setData(next) { overview = next; },
    data() { return overview; },
    setRows(rows) { overview = {...overview, rows}; },
    emit(name, init = {}) {
      return new w.MouseEvent(name, {bubbles: true, cancelable: true, ...init});
    },
  };
}

/* ---------------------------------------------------------------- browser emulation */

/* Returns {delivered, node} after running `tick` between mousedown and mouseup.
   Blink: `click` goes to the nearest common inclusive ancestor of the two targets, so a
   detached mousedown node means the press is swallowed. We model "still under the
   pointer" as "the very same node object is still connected". */
async function pressThrough(env, node, tick) {
  const {w} = env;
  const before = node;
  node.dispatchEvent(env.emit('mousedown'));
  if (tick) await tick();
  const stillThere = before.isConnected && node === before;
  const mouseup = env.emit('mouseup');
  node.dispatchEvent(mouseup);
  if (!stillThere) return {delivered: false, node};
  node.dispatchEvent(env.emit('click'));
  return {delivered: true, node};
}

function countCalls(target, name) {
  const original = target[name];
  const counter = {n: 0};
  target[name] = function patched() {
    counter.n += 1;
    return original.apply(this, arguments);
  };
  counter.restore = () => { target[name] = original; };
  return counter;
}

(async () => {
  const env = boot();
  const {App, $, doc, w} = env;
  await vm.runInContext('App.init(); App.initPanels();', env.ctx);
  await env.settle();

  const results = [];
  function record(name, ok, detail) {
    results.push({name, ok, detail});
  }

  /* ------------------------------------------------- A. one click per press, always */

  async function controlCase(name, selector, {handler = null, effect = null} = {}) {
    const node = typeof selector === 'string' ? doc.querySelector(selector) : selector;
    assert.ok(node, name + ': control exists (' + selector + ')');
    const counter = handler ? countCalls(App, handler) : null;
    const outcome = await pressThrough(env, node, async () => {
      await vm.runInContext('App.load(false)', env.ctx);
      await env.settle();
    });
    await env.settle();
    if (counter) counter.restore();
    const runs = counter ? counter.n : (outcome.delivered ? 1 : 0);
    const effectOk = effect ? effect() === true : true;
    record(name, outcome.delivered && runs === 1 && effectOk,
      'delivered=' + outcome.delivered + ' handlerRuns=' + runs + ' effect=' + effectOk);
    return outcome;
  }

  async function closeLayers() {
    // Twice: a drawer request started by an earlier row click can finish in between.
    for (let round = 0; round < 3; round += 1) {
      for (const id of ['drawer', 'wizard', 'manualDrawer', 'menuPanel']) {
        const node = $(id);
        if (node && !node.hidden) node.hidden = true;
      }
      App.state.press = null;
      await env.settle(200);
    }
    doc.activeElement && doc.activeElement.blur && doc.activeElement.blur();
  }

  await controlCase('دکمه توقف (pause)', '#pauseButton',
    {effect: () => App.state.paused === true});
  await controlCase('قفل ترتیب (freeze sorting)', '#freezeButton');
  await controlCase('نمایش ساده/پیشرفته', '#viewSimple');
  await controlCase('نمایش ساده/پیشرفته (پیشرفته)', '#viewAdvanced');
  await controlCase('پوسته (theme)', '#themeToggle', {handler: 'saveUi'});
  await controlCase('اندازه متن (font size)', '#fontScale');
  await controlCase('چیپ صرافی در نوار بالا', '#exchangeChips .chip', {handler: 'switchTab'});
  await controlCase('چیپ وضعیت در کارت خلاصه', '#summaryChips .chip', {handler: 'switchTab'});
  await controlCase('مبلغ سریع سرمایه (capital preset)', '#capitalPresets button', {handler: 'applyCapital'});
  await controlCase('چیپ فیلتر (پنهان‌کردن اختلاف خام)', '#filterHideGross');
  await controlCase('بستن پیام راه‌اندازی (banner X)', '#setupBannerClose');
  await controlCase('ورود دستی (manual open)', '#manualOpen', {handler: 'openManual'});
  await controlCase('بستن ورود دستی', '#manualClose', {handler: 'closeManual'});
  await controlCase('راه‌اندازی بعدی (wizard next)', '#wizardNext', {handler: 'wizardForward'});
  await controlCase('راه‌اندازی قبلی (wizard back)', '#wizardPrev', {handler: 'wizardBack'});
  await controlCase('ذخیره کارمزد (fee save)', '#feeSave');
  await controlCase('تب عیب‌یابی از منو', '#menuToggle', {handler: 'toggleMenu'});
  await controlCase('ستاره پین ردیف', '#rows [data-pin]', {handler: 'togglePin'});
  await controlCase('ردیف → جزئیات', '#rows tr[data-key]', {handler: 'openDrawer'});

  /* ---------------------------------------------------- B. twenty renders, one click */

  for (let round = 0; round < 20; round += 1) {
    await vm.runInContext('App.load(false)', env.ctx);
    await env.settle();
  }
  let counter = countCalls(App, 'openDrawer');
  doc.querySelector('#rows tr[data-key]').click();
  await env.settle();
  record('۲۰ به‌روزرسانی پشت‌سرهم → یک کلیک، یک اقدام (ردیف)',
    counter.n === 1, 'handlerRuns=' + counter.n);
  counter.restore();

  counter = countCalls(App, 'togglePin');
  doc.querySelector('#rows [data-pin]').click();
  await env.settle();
  record('۲۰ به‌روزرسانی پشت‌سرهم → یک کلیک، یک اقدام (پین)',
    counter.n === 1, 'handlerRuns=' + counter.n);
  counter.restore();

  /* ------------------------------------------- C. identity/focus survive a refresh */

  {
    await closeLayers();
    await vm.runInContext("App.switchTab('opportunities')", env.ctx);
    await env.settle();
    const row = doc.querySelector('#rows tr[data-key]');
    row.focus();
    const focusWorked = doc.activeElement === row;
    const before = row;
    const mutations = [];
    const observer = new w.MutationObserver(list => mutations.push(...list));
    observer.observe($('rows'), {childList: true, subtree: true, attributes: true, characterData: true});
    await vm.runInContext('App.load(false)', env.ctx);
    await env.settle();
    observer.takeRecords().forEach(item => mutations.push(item));
    observer.disconnect();
    record('به‌روزرسانی بدون تغییر داده، ردیف را دست‌نخورده می‌گذارد',
      before === doc.querySelector('#rows tr[data-key]') && before.isConnected
        && doc.activeElement === before && mutations.length === 0,
      'sameNode=' + (before.isConnected && before === doc.querySelector('#rows tr[data-key]'))
        + ' focusKept=' + (doc.activeElement === before)
        + ' active=' + (doc.activeElement.id || doc.activeElement.tagName)
        + ' focusWorked=' + focusWorked
        + ' mutations=' + mutations.length);
  }

  {
    // A press in progress must hold the render back, then apply the newest data afterwards.
    await closeLayers();
    await vm.runInContext("App.switchTab('opportunities')", env.ctx);
    await env.settle();
    const row = doc.querySelector('#rows tr[data-key]');
    const cell = row.querySelector('.pct');
    const key = row.dataset.key;
    const before = cell.textContent;
    row.dispatchEvent(env.emit('mousedown'));
    const fresh = structuredClone(env.data());
    fresh.rows = fresh.rows.map(item => item.key === key
      ? {...item, net_pct: 42.4242, net_quote: 999999} : item);
    env.setData(fresh);
    await vm.runInContext('App.load(false)', env.ctx);
    await env.settle();
    const duringPress = doc.querySelector('#rows tr[data-key="' + key + '"]');
    const heldBack = duringPress === row && duringPress.querySelector('.pct').textContent === before;
    const blockedAfterLoad = App.blockingInteraction ? App.blockingInteraction() : 'n/a';
    row.dispatchEvent(env.emit('mouseup'));
    await env.settle(400);
    const afterRelease = doc.querySelector('#rows tr[data-key="' + key + '"]');
    const applied = afterRelease === row && /۴۲\.۴۲۴|42\.424/.test(afterRelease.querySelector('.pct').textContent);
    record('کلیک نگه‌داشته‌شده رندر را عقب می‌اندازد و بعد از رها شدن اعمال می‌شود',
      heldBack && applied, 'heldBack=' + heldBack + ' appliedAfterRelease=' + applied
        + ' blockedBy=' + blockedAfterLoad + ' stillPending='
        + (App.hasPendingRender ? App.hasPendingRender() : 'n/a')
        + ' text=' + JSON.stringify((doc.querySelector('#rows tr[data-key="' + key + '"] .pct') || {}).textContent || ''));
  }

  {
    // ... and the same while the pointer merely hovers: rows must keep their identity.
    const tbody = $('rows');
    tbody.dispatchEvent(new w.Event('mouseenter'));
    const row = doc.querySelector('#rows tr[data-key]');
    const fresh = structuredClone(env.data());
    fresh.rows = fresh.rows.map(item => ({...item, net_pct: (Number(item.net_pct) || 0) + 0.5}));
    env.setData(fresh);
    await vm.runInContext('App.load(false)', env.ctx);
    await env.settle();
    const same = doc.querySelector('#rows tr[data-key]') === row && row.isConnected;
    tbody.dispatchEvent(new w.Event('mouseleave'));
    await env.settle(200);
    record('اشاره‌گر روی جدول، گره ردیف را جایگزین نمی‌کند', same, 'sameNode=' + same);
  }

  {
    // While the pointer holds the order still, the rank column must agree with what is
    // actually on screen (1, 2, 3 … top to bottom), never claim a hidden order.
    await closeLayers();
    await vm.runInContext("App.switchTab('opportunities')", env.ctx);
    await env.settle();
    const tbody = $('rows');
    tbody.dispatchEvent(new w.Event('mouseenter'));
    const fresh = structuredClone(env.data());
    fresh.rows = fresh.rows.slice().reverse().map((row, index) => (
      {...row, net_pct: 30 - index, net_quote: 1000 - index}));
    env.setData(fresh);
    await vm.runInContext('App.load(false)', env.ctx);
    await env.settle();
    const ranks = Array.from(tbody.children).map(node => node.children[0].textContent);
    const expected = Array.from({length: tbody.children.length}, (unused, index) =>
      String(index + 1).replace(/[0-9]/g, digit => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]));
    tbody.dispatchEvent(new w.Event('mouseleave'));
    await env.settle(200);
    record('شماره رتبه در حین هاور با ترتیب دیده‌شده می‌خواند',
      JSON.stringify(ranks) === JSON.stringify(expected),
      'ranks=' + JSON.stringify(ranks) + ' expected=' + JSON.stringify(expected));
  }

  /* --------------------------------------------------------------- D. performance */

  {
    const env2 = boot();
    const many = [];
    for (let index = 0; index < 400; index += 1) {
      const base = structuredClone(pkg.overview.rows[index % pkg.overview.rows.length]);
      many.push({...base, key: base.key + ':' + index, coin: base.coin + index,
        net_pct: (Number(base.net_pct) || 1) + index / 100});
    }
    env2.setRows(many);
    await vm.runInContext('App.init(); App.initPanels();', env2.ctx);
    await env2.settle();

    const tbody = env2.$('rows');
    const start = process.hrtime.bigint();
    await vm.runInContext('App.load(false)', env2.ctx);
    await env2.settle();
    const firstMs = Number(process.hrtime.bigint() - start) / 1e6;
    const observer2 = new env2.w.MutationObserver(() => {});
    observer2.observe(env2.$('rows'), {childList: true, subtree: true, attributes: true, characterData: true});
    const cheap = process.hrtime.bigint();
    await vm.runInContext('App.load(false)', env2.ctx);
    await env2.settle();
    const unchangedMs = Number(process.hrtime.bigint() - cheap) / 1e6;
    const unchangedGone = observer2.takeRecords().length;
    observer2.disconnect();

    const shown = tbody.children.length;
    const more = env2.$('moreRows');
    const moreLabel = more ? more.textContent : '';
    const capped = shown <= 200 && more && !more.hidden && moreLabel.trim().length > 0;
    let afterMore = shown;
    if (more) {
      more.click();
      await env2.settle();
      afterMore = tbody.children.length;
    }
    record('۴۰۰ ردیف: رندر اول زیر بودجه زمان (jsdom، این ماشین)', firstMs < 900,
      'firstRender=' + firstMs.toFixed(1) + 'ms budget=900ms');
    record('به‌روزرسانی بدون تغییر داده هیچ گره‌ای نمی‌سازد', unchangedGone === 0 && unchangedMs < 60,
      'mutations=' + unchangedGone + ' unchanged=' + unchangedMs.toFixed(1) + 'ms budget=60ms');
    record('فهرست طولانی محدود می‌شود و «نمایش بیشتر» دارد',
      capped && afterMore > shown, 'shown=' + shown + ' afterMore=' + afterMore
        + ' label=' + JSON.stringify(moreLabel.slice(0, 40)));
    env2.dom.window.close();
  }

  /* ------------------------------------------------------------------- report */

  let failed = 0;
  for (const item of results) {
    if (!item.ok) failed += 1;
    console.log((item.ok ? 'ok   ' : 'FAIL ') + item.name + ' — ' + item.detail);
  }
  if (env.problems.length) console.log('jsdom problems: ' + env.problems.join(' | '));
  console.log('\n' + (results.length - failed) + '/' + results.length + ' click-reliability checks passed');
  env.dom.window.close();
  if (failed) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
