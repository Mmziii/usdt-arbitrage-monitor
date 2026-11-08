/* Fees page: what we know, how sure we are, and the paste assistant.
   A fee is never invented: unknown stays unknown and keeps blocking the net number. */
'use strict';

const Fees = (() => {
  const FA = '۰۱۲۳۴۵۶۷۸۹';
  const state = {
    data: null,
    preview: null,
    started: false,
    toastTimer: null,
  };

  function $(id) { return document.getElementById(id); }

  function make(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function fa(text) {
    return String(text === undefined || text === null ? '' : text)
      .replace(/[0-9]/g, (digit) => FA[Number(digit)]);
  }

  function number(value, digits) {
    const parsed = Number(value);
    if (value === null || value === undefined || !isFinite(parsed)) return '—';
    let text = Math.abs(parsed).toFixed(digits === undefined ? 6 : digits);
    if (digits > 0) text = text.replace(/\.?0+$/, '');
    if (!text) text = '0';
    text = text.replace(/\B(?=(\d{3})+(?!\d))/g, '٬');
    return fa((parsed < 0 ? '−' : '') + text);
  }

  function date(value) {
    if (!value) return 'بدون تاریخ';
    try {
      return fa(new Date(Number(value) * 1000).toLocaleDateString('fa-IR'));
    } catch (error) {
      return 'بدون تاریخ';
    }
  }

  // A request that never answers must not leave a button disabled for ever.
  const API_TIMEOUT_MS = 15000;

  async function api(path, options) {
    const request = { headers: { 'Content-Type': 'application/json' }, ...(options || {}) };
    let timer = null;
    if (!request.signal && typeof AbortController === 'function') {
      const controller = new AbortController();
      request.signal = controller.signal;
      timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
    }
    let response;
    try {
      response = await fetch(path, request);
    } catch (error) {
      if (timer) clearTimeout(timer);
      throw new Error(error && error.name === 'AbortError'
        ? 'پاسخ سرور دیر رسید؛ دوباره تلاش کنید.'
        : 'ارتباط با سرور برنامه برقرار نشد؛ دوباره تلاش کنید.');
    }
    if (timer) { clearTimeout(timer); timer = null; }
    let body = null;
    try { body = await response.json(); } catch (error) { body = null; }
    if (!response.ok) {
      const detail = body && body.detail;
      throw new Error(typeof detail === 'string' ? detail
        : (response.status >= 500 ? 'سرور پاسخ نداد؛ دوباره تلاش کنید.' : 'درخواست انجام نشد.'));
    }
    return body;
  }

  function toast(text) {
    const box = $('toast');
    if (!box) return;
    box.textContent = text;
    box.hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => { box.hidden = true; }, 3200);
  }

  function openDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.showModal === 'function') {
      try { dialog.showModal(); return; } catch (error) { /* fall through */ }
    }
    dialog.setAttribute('open', '');
  }

  function closeDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.close === 'function') {
      try { dialog.close(); return; } catch (error) { /* fall through */ }
    }
    dialog.removeAttribute('open');
  }

  /* --------------------------------------------------------------- tables */
  function table(headers, rows) {
    const wrap = make('div');
    wrap.style.overflowX = 'auto';
    const element = make('table');
    element.className = 'fee-table';
    element.style.width = '100%';
    element.style.borderCollapse = 'collapse';
    const head = make('thead');
    const headRow = make('tr');
    headers.forEach((header) => {
      const cell = make('th', '', header);
      cell.style.textAlign = 'start';
      cell.style.padding = '8px';
      cell.style.borderBottom = '1px solid var(--border)';
      headRow.appendChild(cell);
    });
    head.appendChild(headRow);
    element.appendChild(head);
    const body = make('tbody');
    rows.forEach((row) => {
      const tr = make('tr');
      row.forEach((value) => {
        const td = make('td');
        td.style.padding = '8px';
        td.style.borderBottom = '1px solid var(--border)';
        if (value instanceof Node) td.appendChild(value);
        else td.textContent = value === undefined || value === null ? '—' : String(value);
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    element.appendChild(body);
    wrap.appendChild(element);
    return wrap;
  }

  function confidenceTag(meta) {
    const level = meta.confidence || 'unknown';
    const cls = meta.stale ? 'stale' : level;
    const text = meta.stale ? (meta.label + ' · نیاز به بررسی') : (meta.status || meta.label);
    return make('span', 'tag ' + cls, text);
  }

  function renderSummary(data) {
    const box = $('feesSummary');
    if (!box) return;
    box.textContent = '';
    const counts = data.counts || {};
    box.appendChild(make('span', 'chip on', 'تأیید خودکار: ' + fa(counts.auto || 0)));
    box.appendChild(make('span', 'chip on', 'تأیید دستی: ' + fa(counts.manual || 0)));
    box.appendChild(make('span', 'chip', 'تخمینی: ' + fa(counts.estimated || 0)));
    box.appendChild(make('span', 'chip', 'نامعلوم: ' + fa(counts.unknown || 0)));
    if (data.stale) box.appendChild(make('span', 'chip', 'نیاز به بررسی: ' + fa(data.stale)));
    const last = data.last_auto ? date(data.last_auto) : 'هنوز';
    box.appendChild(make('span', 'chip', 'آخرین خواندن خودکار: ' + last));
    const needed = $('feesNeeded');
    if (needed) {
      needed.textContent = (data.needs && data.needs.text) ? data.needs.text
        : 'کارمزد ارزهای مهم ثبت شده است.';
    }
  }

  function renderFees(data) {
    const box = $('feesBody');
    if (!box) return;
    box.textContent = '';
    const rows = (data.rows || []).map((row) => {
      const meta = row.meta || {};
      return [
        row.exchange,
        row.coin,
        row.network,
        row.withdrawal === null || row.withdrawal === undefined ? 'نامعلوم' : number(row.withdrawal, 6),
        row.minimum === null || row.minimum === undefined ? '—' : number(row.minimum, 6),
        confidenceTag(meta),
        meta.age_days === null || meta.age_days === undefined ? 'بدون تاریخ' : fa(Math.round(meta.age_days)) + ' روز',
        meta.source || row.source || '',
      ];
    });
    if (!rows.length) {
      box.appendChild(make('p', 'muted', 'هنوز کارمزد برداشتی ثبت نشده است. با «دستیار کارمزد» '
        + 'یا خواندن خودکار شروع کنید.'));
    } else {
      box.appendChild(table(['صرافی', 'ارز', 'شبکه', 'کارمزد برداشت', 'حداقل برداشت',
        'وضعیت', 'عمر', 'منبع'], rows));
    }
    const count = $('feesCount');
    if (count) count.textContent = fa(rows.length) + ' ردیف · قدیمی‌تر از ' + fa(data.stale_days) + ' روز یعنی «نیاز به بررسی»';
  }

  function renderTrading(data) {
    const box = $('tradingBody');
    if (!box) return;
    box.textContent = '';
    const trading = data.trading || [];
    if (!trading.length) {
      box.appendChild(make('p', 'muted', 'کارمزد معامله را در تنظیمات وارد کنید.'));
      return;
    }
    const rows = trading.map((item) => [
      item.exchange, item.market, number(item.maker, 3), number(item.taker, 3),
      make('span', 'tag ' + (item.confidence || 'unknown'), item.label || ''),
      item.source || '',
    ]);
    box.appendChild(table(['صرافی', 'بازار', 'میکر ٪', 'تیکر ٪', 'وضعیت', 'منبع'], rows));
    box.appendChild(make('p', 'hint', 'کارمزدهایی که هنوز با مقدار پیش‌فرض برنامه یکی‌اند «تخمینی» '
      + 'هستند؛ تا آن‌ها را از صفحه رسمی صرافی تأیید نکنید، نتیجه «برو» نمی‌شود.'));
  }

  function renderSources(data) {
    const box = $('sourcesBody');
    if (!box) return;
    box.textContent = '';
    const sources = data.sources || {};
    const pages = data.pages || {};
    const rows = Object.keys(sources).map((name) => {
      const source = sources[name] || {};
      const status = source.status === 'confirmed' ? 'تأییدشده' : 'تأیید نشده';
      const endpoint = source.endpoint ? source.endpoint_name || source.endpoint : 'ندارد';
      const page = pages[name] || '';
      const link = make('a', '', page || '—');
      if (page) { link.href = page; link.target = '_blank'; link.rel = 'noopener'; }
      return [name, status, endpoint, link, source.note || source.doc || ''];
    });
    box.appendChild(table(['صرافی', 'وضعیت', 'نقطه پایانی عمومی', 'صفحه رسمی کارمزد', 'توضیح'], rows));
    box.appendChild(make('p', 'hint', '«تأیید نشده» یعنی ما این نقطه پایانی را با یک پاسخ واقعی '
      + 'نشانه‌گذاری نکرده‌ایم؛ نه اینکه کارمزد صرافی اشتباه است. برای همین همیشه راه دستی باز است.'));
  }

  async function load() {
    try {
      const data = await api('/api/fees');
      state.data = data;
      renderSummary(data);
      renderFees(data);
      renderTrading(data);
      renderSources(data);
    } catch (error) {
      toast(error.message);
    }
  }

  /* ------------------------------------------------------------- assistant */
  function currentExchange() {
    const select = $('feeExchange');
    return select ? select.value : 'nobitex';
  }

  function renderPageLink() {
    const link = $('feePageLink');
    const pages = (state.data || {}).pages || {};
    const url = pages[currentExchange()];
    if (link) {
      link.href = url || '/guide';
      link.textContent = url ? 'صفحه رسمی کارمزد ' + currentExchange() : 'راهنما';
    }
  }

  function openAssistant(exchange) {
    const dialog = $('feeDialog');
    const select = $('feeExchange');
    if (select && exchange) select.value = exchange;
    state.preview = null;
    const body = $('feePreviewBody');
    if (body) body.textContent = '';
    const errors = $('feeErrors');
    if (errors) errors.textContent = '';
    const save = $('feeSaveBtn');
    if (save) save.disabled = true;
    renderPageLink();
    openDialog(dialog);
  }

  async function preview() {
    const text = $('feeText');
    const body = $('feePreviewBody');
    const errors = $('feeErrors');
    const save = $('feeSaveBtn');
    if (!text || !body) return;
    if (!text.value.trim()) {
      toast('اول متن کارمزد یا CSV را بچسبانید.');
      return;
    }
    try {
      const data = await api('/api/fees/parse', {
        method: 'POST',
        body: JSON.stringify({ text: text.value, exchange: currentExchange(), kind: 'auto' }),
      });
      state.preview = data.rows || [];
      body.textContent = '';
      if (errors) {
        errors.textContent = '';
        (data.errors || []).forEach((item) => {
          errors.appendChild(make('p', 'hint', 'خط ' + fa(item.line) + ': ' + item.message));
        });
      }
      if (state.preview.length) {
        body.appendChild(make('h3', '', 'این ردیف‌ها ذخیره می‌شوند:'));
        body.appendChild(table(['ارز', 'شبکه', 'کارمزد برداشت', 'حداقل برداشت'],
          state.preview.map((row) => [row.coin, row.network, number(row.withdrawal, 6),
            row.minimum === null || row.minimum === undefined ? '—' : number(row.minimum, 6)])));
      } else {
        body.appendChild(make('p', 'muted', 'هیچ ردیف درستی در این متن پیدا نشد.'));
      }
      if (save) save.disabled = !state.preview.length;
      toast(fa(state.preview.length) + ' ردیف آماده ذخیره است.');
    } catch (error) {
      toast(error.message);
    }
  }

  async function save() {
    if (!state.preview || !state.preview.length) return;
    try {
      const data = await api('/api/fees/save', {
        method: 'POST',
        body: JSON.stringify({
          rows: state.preview.map((row) => ({
            exchange: row.exchange, coin: row.coin, network: row.network,
            withdrawal: row.withdrawal, minimum: row.minimum,
            supported: row.supported !== false, note: row.note || '',
          })),
        }),
      });
      toast(fa(data.saved) + ' ردیف ذخیره شد.');
      closeDialog($('feeDialog'));
      const text = $('feeText');
      if (text) text.value = '';
      state.preview = null;
      await load();
    } catch (error) {
      toast(error.message);
    }
  }

  async function refreshAuto() {
    const button = $('autoBtn');
    if (button) button.disabled = true;
    try {
      const data = await api('/api/fees/refresh', { method: 'POST', body: '{}' });
      const saved = (data.results || []).filter((item) => item.ok).length;
      toast(saved ? fa(data.saved) + ' ردیف از صرافی خوانده شد.'
        : 'هیچ صرافی‌ای پاسخ عمومی کارمزد نداد؛ از دستیار کارمزد استفاده کنید.');
      await load();
    } catch (error) {
      toast(error.message);
    } finally {
      if (button) button.disabled = false;
    }
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
  }

  function cycleTheme() {
    const order = ['system', 'light', 'dark'];
    const current = document.documentElement.dataset.theme || 'system';
    const next = order[(order.indexOf(current) + 1) % order.length];
    applyTheme(next);
    try { localStorage.setItem('home-theme', next); } catch (error) { /* private mode */ }
  }

  function init() {
    if (state.started) return;
    state.started = true;
    let theme = 'system';
    try { theme = localStorage.getItem('home-theme') || 'system'; } catch (error) { theme = 'system'; }
    applyTheme(theme);
    const on = (id, event, handler) => {
      const node = $(id);
      if (node) node.addEventListener(event, handler);
    };
    on('assistantBtn', 'click', () => openAssistant(currentExchange()));
    on('feeClose', 'click', () => closeDialog($('feeDialog')));
    on('feePreviewBtn', 'click', preview);
    on('feeSaveBtn', 'click', save);
    on('autoBtn', 'click', refreshAuto);
    on('themeBtn', 'click', cycleTheme);
    on('feeExchange', 'change', renderPageLink);
    closeDialog($('feeDialog'));
    load();
  }

  return { init, load, openAssistant, preview, save, refreshAuto, state, renderSources };
})();

if (typeof window !== 'undefined') {
  window.Fees = Fees;
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => Fees.init());
    } else {
      Fees.init();
    }
  }
}
