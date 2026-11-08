/* DOM smoke test for the fees page and the paste assistant (jsdom, no network).
   NODE_PATH=<jsdom node_modules> node tests/ui_fees_smoke.cjs */
const { JSDOM } = require('jsdom');
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');

const fixture = JSON.parse(execFileSync('.venv/bin/python', ['-c', `
import json, sys
sys.path.insert(0, 'tests')
from home_fixture import payload
print(json.dumps(payload()['fees'], ensure_ascii=False))
`], { encoding: 'utf8' }));

const dom = new JSDOM(fs.readFileSync('app/static/fees.html', 'utf8'),
  { runScripts: 'outside-only', url: 'http://fees.test/fees' });
const w = dom.window;
const doc = w.document;
w.setTimeout = () => 1;
w.clearTimeout = () => {};
w.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
w.HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };

const calls = [];
const preview = {
  rows: [{ exchange: 'nobitex', coin: 'USDT', network: 'TRC20', withdrawal: 1,
    minimum: 10, supported: true, confidence: 'manual', source: 'assistant' }],
  errors: [{ line: 2, text: '12 34', message: 'نماد ارز پیدا نشد؛ این خط ذخیره نمی‌شود.' }],
  exchange: 'nobitex',
};
const refreshResult = { skipped: false, saved: 0, results: [
  { exchange: 'nobitex', ok: false, attempted: true, message: 'اتصال برقرار نشد.' },
  { exchange: 'wallex', ok: false, attempted: false, message: 'منبع خودکار نداریم.' },
  { exchange: 'bitunix', ok: false, attempted: false, message: 'منبع خودکار نداریم.' },
] };

w.fetch = async (url, options = {}) => {
  const method = (options.method || 'GET').toUpperCase();
  calls.push({ url, method, body: options.body });
  let value;
  if (url === '/api/fees') value = structuredClone(fixture);
  else if (url === '/api/fees/parse') value = structuredClone(preview);
  else if (url === '/api/fees/save') value = { saved: 1, rows: fixture.rows };
  else if (url === '/api/fees/refresh') value = structuredClone(refreshResult);
  else throw new Error('unexpected URL ' + url);
  return { ok: true, status: 200, json: async () => structuredClone(value) };
};

const ctx = dom.getInternalVMContext();
vm.runInContext(fs.readFileSync('app/static/fees.js', 'utf8'), ctx, { filename: 'fees.js' });
const settle = async () => { for (let i = 0; i < 60; i += 1) await Promise.resolve(); };
const text = (id) => (doc.getElementById(id) || {}).textContent || '';

(async () => {
  await settle();

  // nothing open on load
  assert.equal(doc.querySelectorAll('dialog[open]').length, 0);
  assert.equal([...doc.querySelectorAll('.nav a')].map((a) => a.getAttribute('href')).join(','),
    '/,/fees,/guide,/settings,/dashboard');
  assert.equal(doc.querySelector('.nav a[aria-current="page"]').textContent, 'کارمزدها');

  // the recorded fee table
  const rows = doc.querySelectorAll('#feesBody tbody tr');
  assert.equal(rows.length, fixture.rows.length);
  assert.match(text('feesBody'), /تأیید خودکار|تأیید دستی|تخمینی|نامعلوم/);
  assert.match(text('feesSummary'), /تأیید خودکار/);
  assert.match(text('feesCount'), /نیاز به بررسی|ردیف/);

  // transaction fees and their honesty label
  assert.equal(doc.querySelectorAll('#tradingBody tbody tr').length, fixture.trading.length);
  assert.match(text('tradingBody'), /تخمینی/);

  // sources are labelled as confirmed / unconfirmed, never guessed
  assert.equal(doc.querySelectorAll('#sourcesBody tbody tr').length, 3);
  assert.match(text('sourcesBody'), /تأیید نشده/);
  assert.ok(doc.querySelector('#sourcesBody a[href^="https://"]') ||
    doc.querySelectorAll('#sourcesBody a').length >= 3);

  // the assistant: paste -> preview -> save
  doc.getElementById('assistantBtn').click();
  assert.ok(doc.getElementById('feeDialog').open);
  assert.equal(doc.querySelectorAll('dialog[open]').length, 1);
  doc.getElementById('feeExchange').value = 'nobitex';
  doc.getElementById('feeText').value = 'USDT  TRC20  1  10\n12 34';
  doc.getElementById('feePreviewBtn').click();
  await settle();
  assert.match(text('feePreviewBody'), /USDT/);
  assert.match(text('feeErrors'), /خط ۲/);
  assert.equal(doc.getElementById('feeSaveBtn').disabled, false);
  const parseCall = calls.find((call) => call.url === '/api/fees/parse');
  assert.equal(JSON.parse(parseCall.body).exchange, 'nobitex');

  doc.getElementById('feeSaveBtn').click();
  await settle();
  const saveCall = calls.find((call) => call.url === '/api/fees/save');
  assert.ok(saveCall);
  const savedRows = JSON.parse(saveCall.body).rows;
  assert.equal(savedRows.length, 1);
  assert.equal(savedRows[0].coin, 'USDT');
  assert.equal(savedRows[0].network, 'TRC20');
  assert.equal(savedRows[0].withdrawal, 1);
  assert.ok(!doc.getElementById('feeDialog').open, 'the dialog closes after saving');

  // the automatic refresh explains that it failed instead of inventing fees
  doc.getElementById('autoBtn').click();
  await settle();
  assert.match(text('toast'), /دستیار کارمزد|خوانده شد/);
  assert.ok(calls.some((call) => call.url === '/api/fees/refresh' && call.method === 'POST'));

  console.log('ui_fees_smoke: ok — fee table, confidence tags, sources, assistant, save');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
