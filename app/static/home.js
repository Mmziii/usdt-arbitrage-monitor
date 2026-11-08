/* Home screen logic: one question per card, plain Persian, no invented numbers.
   Nothing here opens a dialog on page load; dialogs are opened by an explicit click.
   The markup this file drives is home.html; the numbers all come from the server. */
'use strict';

const App = (() => {
  const FA = '۰۱۲۳۴۵۶۷۸۹';
  const state = {
    home: null,
    receipt: null,
    receiptKey: null,
    started: false,
    step: 0,
    wizard: null,
    paused: false,
    toastTimer: null,
    poll: null,
    clock: null,
    loadingReceipt: false,
  };

  /* ------------------------------------------------------------ helpers */
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

  function group(text) {
    return text.replace(/\B(?=(\d{3})+(?!\d))/g, '٬');
  }

  function decimal(value, digits) {
    const number = Number(value);
    if (value === null || value === undefined || !isFinite(number)) return null;
    let text = Math.abs(number).toFixed(digits);
    if (digits > 0) text = text.replace(/\.?0+$/, '');
    if (text === '' || text === '-') text = '0';
    return (number < 0 ? '−' : '') + group(text);
  }

  function money(value, digits) {
    const text = decimal(value, digits);
    return text === null ? '—' : fa(text);
  }

  function toman(value) {
    return money(value, 0) + ' تومان';
  }

  function usdt(value) {
    return money(value, 2) + ' USDT';
  }

  function percent(value, digits) {
    const text = decimal(value, digits === undefined ? 2 : digits);
    if (text === null) return '—';
    return fa((Number(value) > 0 ? '+' : '') + text) + '٪';
  }

  function minutes(value) {
    if (value === null || value === undefined) return 'نامعلوم';
    const number = Number(value);
    if (!isFinite(number)) return 'نامعلوم';
    if (number < 60) return fa(Math.round(number)) + ' دقیقه';
    const hours = Math.floor(number / 60);
    const rest = Math.round(number % 60);
    return fa(hours) + ' ساعت' + (rest ? ' و ' + fa(rest) + ' دقیقه' : '');
  }

  function parseAmount(raw) {
    let text = String(raw === undefined || raw === null ? '' : raw).trim();
    if (!text) return null;
    text = text.replace(/[۰-۹]/g, (digit) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(digit)))
      .replace(/[٠-٩]/g, (digit) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(digit)))
      .replace(/[,٬\s]/g, '').replace(/٫/g, '.');
    let multiplier = 1;
    if (/میلیارد/.test(text)) multiplier = 1e9;
    else if (/میلیون/.test(text)) multiplier = 1e6;
    else if (/هزار/.test(text)) multiplier = 1e3;
    const match = text.match(/-?\d+(?:\.\d+)?/);
    if (!match) return null;
    const value = Number(match[0]) * multiplier;
    return isFinite(value) && value > 0 ? value : null;
  }

  async function api(path, options) {
    const response = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...(options || {}),
    });
    let body = null;
    try { body = await response.json(); } catch (error) { body = null; }
    if (!response.ok) {
      const detail = body && body.detail;
      const text = typeof detail === 'string' ? detail : friendlyStatus(response.status);
      const failure = new Error(text);
      failure.status = response.status;
      throw failure;
    }
    return body;
  }

  function friendlyStatus(status) {
    if (status === 429) return 'درخواست‌های زیادی فرستاده شد؛ چند لحظه صبر کنید.';
    if (status === 404) return 'این مورد پیدا نشد؛ صفحه را دوباره بار کنید.';
    if (status >= 500) return 'سرور نتوانست پاسخ بدهد؛ دوباره تلاش کنید.';
    return 'درخواست انجام نشد؛ دوباره تلاش کنید.';
  }

  function friendly(error) {
    if (error && error.message) return error.message;
    return 'ارتباط برقرار نشد؛ اینترنت یا فیلترشکن را بررسی کنید.';
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

  /* ------------------------------------------------------------- header */
  function renderHeader(data) {
    const button = $('connectionBtn');
    const text = $('connectionText');
    if (!button || !text) return;
    let mode = 'ok';
    let label = 'متصل';
    if (data.error) {
      mode = 'error';
      label = 'قطعی موقت';
    } else if (!data.age && data.age !== 0) {
      mode = 'waiting';
      label = 'در حال اتصال…';
    }
    if (data.paused) {
      mode = 'paused';
      label = 'متوقف';
    }
    button.dataset.state = mode;
    text.textContent = label;
    const pause = $('pauseBtn');
    if (pause) {
      pause.textContent = data.paused ? 'ادامه' : 'توقف';
      pause.setAttribute('aria-pressed', data.paused ? 'true' : 'false');
    }
    state.paused = Boolean(data.paused);
    renderCountdown(data);
  }

  function renderCountdown(data) {
    const box = $('countdown');
    if (!box) return;
    if (data && data.paused) { box.textContent = 'متوقف'; return; }
    const next = data ? Number(data.next_refresh) : NaN;
    if (!isFinite(next)) { box.textContent = '—'; return; }
    box.textContent = next > 0 ? fa(Math.round(next)) + ' ثانیه' : 'در حال به‌روزرسانی';
  }

  /* -------------------------------------------------------------- setup */
  function renderSetup(data) {
    const box = $('setupSummary');
    const setup = data.setup || {};
    if (!box) return;
    box.textContent = '';
    (setup.exchange_labels || []).forEach((label) => box.appendChild(make('span', 'chip on', label)));
    if (setup.money_label) box.appendChild(make('span', 'chip', setup.money_label));
    if (setup.mode_label) box.appendChild(make('span', 'chip', setup.mode_label));
    const capital = (data.capital || {}).usdt;
    if (capital) box.appendChild(make('span', 'chip', 'سرمایه: ' + usdt(capital)));
    const tomanValue = (data.capital || {}).toman;
    if (tomanValue) box.appendChild(make('span', 'chip', '≈ ' + toman(tomanValue)));
    if (!(setup.exchange_labels || []).length) {
      box.appendChild(make('span', 'chip', 'صرافی‌ها را انتخاب کنید'));
    }
  }

  /* ------------------------------------------------------------- banner */
  function renderBanner(data) {
    const banner = $('banner');
    const list = $('bannerItems');
    if (!banner || !list) return;
    const info = data.banner || {};
    list.textContent = '';
    const items = info.items || [];
    if (!items.length || info.dismissed) {
      banner.hidden = true;
      return;
    }
    items.forEach((item) => {
      const row = make('li', '', item.text);
      if (item.page) {
        const link = make('a', 'small', ' →');
        link.href = item.page === 'fees' ? '/fees' : '/';
        link.title = 'رفتن به این بخش';
        link.addEventListener('click', (event) => {
          if (item.page === 'setup') {
            event.preventDefault();
            openWizard();
          }
        });
        row.appendChild(link);
      }
      list.appendChild(row);
    });
    banner.hidden = false;
  }

  /* -------------------------------------------------------------- result */
  function renderResult(data) {
    const best = data.best;
    const body = $('resultBody');
    const loading = $('resultLoading');
    const errorBox = $('resultError');
    if (loading) loading.hidden = true;
    if (errorBox) errorBox.hidden = true;
    if (!best) {
      if (body) body.hidden = true;
      const section = $('receiptSection');
      if (section) section.hidden = true;
      renderEmpty(data);
      return;
    }
    if (body) body.hidden = false;
    renderEmpty(data);

    const decision = best.decision || {};
    const badge = $('resultBadge');
    if (badge) {
      badge.className = 'badge tone-' + (decision.tone || 'unknown');
    }
    const icon = $('verdictIcon');
    if (icon) icon.textContent = decision.icon || '؟';
    const label = $('verdictLabel');
    if (label) label.textContent = decision.label || 'نامطمئن';
    const text = $('verdictText');
    if (text) text.textContent = best.summary_text || '';

    const route = $('verdictRoute');
    if (route) {
      const numbers = best.numbers || {};
      const mode = (best.receipt || {}).mode_label || '';
      route.textContent = [best.route_label, mode].filter(Boolean).join(' · ')
        + (numbers.net_pct === null || numbers.net_pct === undefined
          ? '' : ' · سود خالص ' + percent(numbers.net_pct));
    }

    const numbers = best.numbers || {};
    setText('netToman', numbers.profit_toman === null || numbers.profit_toman === undefined
      ? '—' : toman(numbers.profit_toman));
    setText('netPct', percent(numbers.net_after_other !== undefined && numbers.net_after_other !== null
      ? numbers.net_after_other : numbers.net_pct));
    setText('profitUsdt', numbers.profit_usdt === null || numbers.profit_usdt === undefined
      ? '—' : usdt(numbers.profit_usdt));
    setText('totalTime', minutes(numbers.transfer_minutes));
    const confidence = best.confidence || {};
    setText('confidenceLevel', confidence.label || '—');
    const confidenceCell = $('confidenceLevel');
    if (confidenceCell) {
      confidenceCell.title = (confidence.reasons || []).join('؛ ');
      confidenceCell.className = 'confidence-' + (confidence.level || 'low');
    }
    const tomanCell = $('netToman');
    if (tomanCell && tomanCell.parentElement) {
      const value = Number(numbers.net_after_other !== undefined && numbers.net_after_other !== null
        ? numbers.net_after_other : numbers.net_pct);
      tomanCell.parentElement.className = value > 0 ? 'good' : (value <= 0 ? 'bad' : '');
    }

    renderChecks(decision.checks || []);
    renderReceiptInline(best.receipt || {}, best.key);
  }

  function setText(id, text) {
    const node = $(id);
    if (node) node.textContent = text;
  }

  function renderChecks(checks) {
    const list = $('checks');
    if (!list) return;
    list.textContent = '';
    const marks = { ok: '✓', warn: '⚠', fail: '✗', info: '•' };
    checks.forEach((check) => {
      const item = make('li', check.status || 'info');
      item.appendChild(make('span', 'mark', marks[check.status] || '•'));
      const body = make('span');
      body.appendChild(make('b', '', check.title || ''));
      body.appendChild(make('span', 'why', check.text || ''));
      item.appendChild(body);
      list.appendChild(item);
    });
  }

  function renderEmpty(data) {
    const card = $('emptyCard');
    if (!card) return;
    const info = data.empty || {};
    if (!data.empty) { card.hidden = true; return; }
    card.hidden = false;
    setText('emptyText', info.message || 'فعلاً فرصت سوددهی نیست.');
    const last = $('emptyLast');
    if (last) {
      if (info.last_profitable_at) {
        const stamp = new Date(Number(info.last_profitable_at) * 1000);
        last.textContent = 'آخرین فرصت بالای حاشیه ایمنی: '
          + fa(stamp.toLocaleDateString ? stamp.toLocaleDateString('fa-IR') : '');
      } else {
        last.textContent = 'در ' + fa(info.window_days || 7) + ' روز گذشته فرصتی بالای حاشیه ایمنی ثبت نشده است.';
      }
    }
    const toggle = $('notifyToggle');
    if (toggle) toggle.checked = Boolean(info.notify);
  }

  /* --------------------------------------------------------------- gauge */
  function renderGauge(data) {
    const box = $('gaugeBody');
    if (!box) return;
    box.textContent = '';
    const gauge = data.gauge || {};
    if (!gauge.ready) {
      box.appendChild(make('p', 'lead', gauge.message || 'برای این بخش حداقل ۲۴ ساعت داده لازم است'));
      box.appendChild(make('p', 'hint', 'تا آن موقع، عدد سود همین لحظه در بالا نشان داده می‌شود و '
        + 'حدس نمی‌زنیم این فرصت خوب است یا نه.'));
      return;
    }
    box.appendChild(make('p', 'lead', gauge.message || ''));
    const track = make('div', 'gauge-track');
    track.setAttribute('role', 'img');
    track.setAttribute('aria-label', gauge.message || '');
    const low = Number(gauge.typical_low);
    const high = Number(gauge.typical_high);
    const worst = Number(gauge.worst);
    const best = Number(gauge.best);
    const current = Number(gauge.current);
    const values = [low, high, worst, best, current].filter((value) => isFinite(value));
    const min = values.length ? Math.min(...values) : 0;
    const max = values.length ? Math.max(...values) : 1;
    const span = max - min || 1;
    const place = (value) => Math.min(100, Math.max(0, ((value - min) / span) * 100));
    if (isFinite(low) && isFinite(high)) {
      const range = make('div', 'gauge-range');
      range.style.insetInlineStart = place(low) + '%';
      range.style.width = Math.max(2, place(high) - place(low)) + '%';
      track.appendChild(range);
    }
    if (isFinite(current)) {
      const marker = make('div', 'gauge-now');
      marker.style.insetInlineStart = place(current) + '%';
      track.appendChild(marker);
    }
    box.appendChild(track);
    const legend = make('div', 'gauge-legend');
    legend.appendChild(make('span', '', 'الان: ' + percent(gauge.current)));
    if (isFinite(low) && isFinite(high)) {
      legend.appendChild(make('span', '', 'محدوده معمول: ' + percent(low) + ' تا ' + percent(high)));
    }
    if (isFinite(best)) legend.appendChild(make('span', '', 'بهترین: ' + percent(best)));
    if (isFinite(worst)) legend.appendChild(make('span', '', 'بدترین: ' + percent(worst)));
    legend.appendChild(make('span', '', fa(gauge.hours || 0) + ' ساعت داده'));
    box.appendChild(legend);
    box.appendChild(make('p', 'hint', gauge.note || 'این نمودار تاریخچه ثبت‌شده است، نه پیش‌بینی.'));
  }

  /* ------------------------------------------------------------- receipt */
  const UNIT_LABELS = { coin: 'واحد ارز', USDT: 'USDT', toman: 'تومان' };

  function confidenceTag(step) {
    const level = step.confidence || 'unknown';
    const label = step.confidence_label || 'نامعلوم';
    const cls = step.confidence_stale ? 'stale' : level;
    return make('span', 'tag ' + cls, step.confidence_stale ? label + ' · نیاز به بررسی' : label);
  }

  function receiptFragment(receipt) {
    const wrap = document.createDocumentFragment();
    if (!receipt || receipt.ok === false) {
      const note = make('p', 'lead', (receipt && receipt.error) || 'برای این مسیر محاسبه کامل ممکن نیست.');
      wrap.appendChild(note);
      wrap.appendChild(make('p', 'hint', 'تا وقتی کارمزد برداشت و شبکه این ارز معلوم نشود، '
        + 'عدد سود نشان نمی‌دهیم.'));
      return wrap;
    }
    const steps = receipt.steps || [];
    steps.forEach((step) => {
      const card = make('div', 'step');
      const head = make('div', 'step-head');
      const title = make('div');
      title.appendChild(make('span', 'step-no', fa(step.n)));
      title.appendChild(document.createTextNode(' ' + (step.title || step.action || '')));
      head.appendChild(title);
      head.appendChild(make('span', 'chip', step.venue_label || ''));
      card.appendChild(head);

      const flow = make('div', 'step-flow');
      const unitIn = UNIT_LABELS[step.unit_in] || step.unit_in || '';
      const unitOut = UNIT_LABELS[step.unit_out] || step.unit_out || '';
      const digitsOut = step.unit_out === 'coin' ? 6 : 2;
      flow.appendChild(make('span', 'num', money(step.amount_in, step.unit_in === 'toman' ? 0 : 6) + ' ' + unitIn));
      flow.appendChild(make('span', 'muted', '→'));
      flow.appendChild(make('span', 'num', money(step.amount_out, digitsOut) + ' ' + unitOut));
      card.appendChild(flow);

      const meta = make('div', 'step-meta');
      if (step.cost !== null && step.cost !== undefined) {
        const digits = step.unit_out === 'coin' ? 6 : 0;
        let cost = 'هزینه این مرحله: ' + money(step.cost, digits) + ' ' + unitOut;
        if (step.cost_pct !== null && step.cost_pct !== undefined) {
          cost += ' (' + percent(step.cost_pct, 3) + ')';
        }
        meta.appendChild(make('span', '', cost));
      }
      if (/^withdraw_/.test(step.stage || '')) {
        const total = (receipt.totals || {}).transfer_minutes;
        if (total !== null && total !== undefined) {
          meta.appendChild(make('span', '', 'زمان تقریبی شبکه: ' + minutes(total)));
        }
      }
      meta.appendChild(confidenceTag(step));
      card.appendChild(meta);
      wrap.appendChild(card);
    });

    const totals = receipt.totals || {};
    const grid = make('div', 'totals');
    const cells = [
      ['سرمایه شروع', usdt(totals.capital)],
      ['مبلغ نهایی', usdt(totals.final)],
      ['سود خالص', usdt(totals.profit) + ' (' + percent(totals.profit_pct) + ')'],
      ['سود به تومان', toman(totals.profit_toman)],
      ['جمع کارمزد و لغزش', totals.costs_pct === null || totals.costs_pct === undefined
        ? '—' : percent(totals.costs_pct) + ' واحد درصد'],
      ['هزینه‌های دیگر', toman(totals.other_costs_toman || 0)],
      ['سرمایه سربه‌سر', usdt(totals.breakeven_capital)],
      ['کمترین سرمایه به‌صرفه', usdt(totals.minimum_capital)],
    ];
    cells.forEach(([caption, value]) => {
      const cell = make('div');
      cell.appendChild(make('b', 'num', value));
      cell.appendChild(make('small', '', caption));
      grid.appendChild(cell);
    });
    wrap.appendChild(grid);

    if (totals.reconciled === true) {
      wrap.appendChild(make('p', 'reconciled', '✓ جمع خروجی‌ها دقیقاً با سرمایه و سود می‌خواند.'));
    } else if (totals.reconciled === false) {
      wrap.appendChild(make('p', 'reconciled bad',
        '✗ اعداد این رسید با هم نمی‌خوانند؛ به این مسیر اعتماد نکنید و به ما خبر دهید.'));
    }
    if (totals.limited_by_visible_depth) {
      wrap.appendChild(make('p', 'hint', 'عمق بازار کمتر از سرمایه شماست؛ با این مبلغ '
        + 'احتمالاً قیمت بدتری می‌گیرید.'));
    }

    const lists = make('div', 'lists');
    const risks = make('div');
    risks.appendChild(make('h3', '', 'چه چیزی می‌تواند خراب شود؟'));
    const riskList = make('ul');
    (receipt.risks || []).forEach((risk) => riskList.appendChild(make('li', '', risk.text || risk)));
    risks.appendChild(riskList);
    const checks = make('div');
    checks.appendChild(make('h3', '', 'قبل از شروع، این‌ها را تیک بزنید'));
    const checkList = make('ul');
    (receipt.checklist || []).forEach((item) => checkList.appendChild(make('li', '', item)));
    checks.appendChild(checkList);
    lists.appendChild(risks);
    lists.appendChild(checks);
    wrap.appendChild(lists);
    if (receipt.disclaimer) wrap.appendChild(make('p', 'hint', receipt.disclaimer));
    return wrap;
  }

  function renderReceiptInline(receipt, key) {
    const section = $('receiptSection');
    const box = $('receiptInline');
    if (!box || !section) return;
    state.receipt = receipt;
    state.receiptKey = key || null;
    box.textContent = '';
    box.appendChild(receiptFragment(receipt));
    section.hidden = false;
    setText('receiptMode', (receipt || {}).mode_label || '');
    const csv = $('csvInline');
    if (csv && key) csv.href = '/api/receipt.csv?key=' + encodeURIComponent(key);
    const simulate = $('simulateInline');
    if (simulate) simulate.disabled = !(receipt || {}).ok;
  }

  async function openReceipt(key) {
    if (!key || state.loadingReceipt) return;
    const dialog = $('receiptDialog');
    const box = $('receiptBody');
    if (!dialog || !box) return;
    let receipt = null;
    if (state.receiptKey === key && state.receipt) {
      receipt = state.receipt;
    } else {
      state.loadingReceipt = true;
      box.textContent = '';
      box.appendChild(make('p', 'muted', 'در حال ساختن رسید…'));
      openDialog(dialog);
      try {
        const data = await api('/api/receipt?key=' + encodeURIComponent(key));
        receipt = data.receipt;
      } catch (error) {
        box.textContent = '';
        box.appendChild(make('p', 'lead', friendly(error)));
        state.loadingReceipt = false;
        return;
      }
      state.loadingReceipt = false;
      state.receipt = receipt;
      state.receiptKey = key;
    }
    box.textContent = '';
    box.appendChild(receiptFragment(receipt || {}));
    setText('receiptDialogTitle', (receipt && receipt.route_label)
      ? 'رسید: ' + receipt.coin + ' — ' + receipt.route_label : 'رسید مسیر');
    const csv = $('csvLink');
    if (csv) csv.href = '/api/receipt.csv?key=' + encodeURIComponent(key);
    const simulate = $('simulateBtn');
    if (simulate) simulate.disabled = !(receipt || {}).ok;
    openDialog(dialog);
  }

  function receiptText() {
    const receipt = state.receipt || {};
    const lines = ['رسید مسیر ' + (receipt.coin || '') + ' — ' + (receipt.route_label || '')];
    (receipt.steps || []).forEach((step) => {
      lines.push(step.n + '. ' + (step.title || '') + ' (' + (step.venue_label || '') + ')');
      lines.push('   ' + money(step.amount_in, 6) + ' ' + (step.unit_in || '')
        + ' → ' + money(step.amount_out, 6) + ' ' + (step.unit_out || '')
        + ' | کارمزد: ' + (step.confidence_label || ''));
    });
    const totals = receipt.totals || {};
    lines.push('سود خالص: ' + usdt(totals.profit) + ' (' + percent(totals.profit_pct) + ')');
    if (totals.profit_toman !== null && totals.profit_toman !== undefined) {
      lines.push('سود به تومان: ' + toman(totals.profit_toman));
    }
    lines.push(receipt.disclaimer || '');
    return lines.join('\n');
  }

  async function copyReceipt() {
    const text = receiptText();
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const area = document.createElement('textarea');
        area.value = text;
        document.body.appendChild(area);
        area.select();
        document.execCommand('copy');
        document.body.removeChild(area);
      }
      toast('متن رسید کپی شد.');
    } catch (error) {
      toast('کپی نشد؛ متن را دستی انتخاب کنید.');
    }
  }

  async function saveSimulation() {
    if (!state.receiptKey) return;
    try {
      await api('/api/simulations', {
        method: 'POST',
        body: JSON.stringify({ key: state.receiptKey }),
      });
      toast('به‌عنوان معامله آزمایشی ذخیره شد؛ نتیجه بعداً با قیمت واقعی مقایسه می‌شود.');
    } catch (error) {
      toast(friendly(error));
    }
  }

  /* -------------------------------------------------------------- others */
  function renderOthers(data) {
    const section = $('othersSection');
    const grid = $('othersGrid');
    if (!section || !grid) return;
    grid.textContent = '';
    const others = data.others || [];
    if (!others.length) { section.hidden = true; return; }
    others.forEach((option) => {
      const card = make('button', 'option');
      card.type = 'button';
      const top = make('span', 'top-line');
      top.appendChild(make('b', '', option.coin || ''));
      top.appendChild(make('span', 'tag ' + (option.tone || ''), (option.icon || '') + ' ' + (option.label || '')));
      card.appendChild(top);
      card.appendChild(make('span', 'muted small', option.route_label || ''));
      card.appendChild(make('span', 'muted small', (option.venues || []).filter(Boolean).join(' ← ')));
      card.appendChild(make('span', 'num',
        percent(option.net_after_other !== undefined && option.net_after_other !== null
          ? option.net_after_other : option.net_pct) + ' سود خالص'));
      card.addEventListener('click', () => openReceipt(option.key));
      grid.appendChild(card);
    });
    section.hidden = false;
  }

  /* ---------------------------------------------------------------- fees */
  function renderFeesHint(data) {
    const card = $('feesHint');
    const text = $('feesText');
    if (!card || !text) return;
    const needs = data.fees || {};
    if (!needs.text) {
      card.hidden = false;
      text.textContent = 'کارمزدهای لازم برای مسیرهای مهم ثبت شده‌اند. اگر صرافی کارمزد را '
        + 'عوض کند، همین‌جا به شما می‌گوییم.';
      const link = $('feesLink');
      if (link) link.textContent = 'دیدن کارمزدها';
    } else {
      card.hidden = false;
      text.textContent = needs.text;
      const link = $('feesLink');
      if (link) link.textContent = needs.action || 'رفتن به کارمزدها';
    }
  }

  /* ---------------------------------------------------------------- load */
  async function load() {
    try {
      const data = await api('/api/home');
      const wizard = $('wizard');
      if (!wizard || !wizard.open) state.wizard = null;
      state.home = data;
      render(data);
      setText('tagline', 'تتر و ارز دیجیتال بین صرافی‌های ایرانی و بیت‌یونیکس');
    } catch (error) {
      const loading = $('resultLoading');
      if (loading) loading.hidden = true;
      const body = $('resultBody');
      if (body) body.hidden = true;
      const errorBox = $('resultError');
      if (errorBox) {
        errorBox.hidden = false;
        errorBox.textContent = friendly(error);
      }
      const button = $('connectionBtn');
      if (button) button.dataset.state = 'error';
      setText('connectionText', 'قطعی موقت');
    }
    schedulePoll();
  }

  function render(data) {
    renderHeader(data);
    renderBanner(data);
    renderSetup(data);
    renderResult(data);
    renderGauge(data);
    renderOthers(data);
    renderFeesHint(data);
  }

  function schedulePoll() {
    clearTimeout(state.poll);
    const interval = (state.home && state.home.interval ? Number(state.home.interval) : 15);
    state.poll = setTimeout(() => {
      if (!state.paused) load();
      else schedulePoll();
    }, Math.max(5000, interval * 1000));
  }

  async function togglePause() {
    const next = !state.paused;
    try {
      await api('/api/overview/pause', { method: 'POST', body: JSON.stringify({ paused: next }) });
      state.paused = next;
      if (state.home) state.home.paused = next;
      renderHeader(state.home || {});
      if (!next) load();
    } catch (error) {
      toast(friendly(error));
    }
  }

  async function refresh() {
    const button = $('refreshBtn');
    if (button) button.disabled = true;
    try {
      await api('/api/overview/refresh', { method: 'POST', body: '{}' });
      await load();
      toast('به‌روزرسانی شد.');
    } catch (error) {
      toast(friendly(error));
    } finally {
      if (button) button.disabled = false;
    }
  }

  /* -------------------------------------------------------------- wizard */
  function wizardState() {
    if (state.wizard) return state.wizard;
    const data = state.home || {};
    const setup = data.setup || {};
    state.wizard = {
      exchanges: (setup.exchanges || ['wallex', 'nobitex', 'bitunix']).slice(),
      money: setup.money || 'toman_iran',
      capital: (data.capital || {}).toman || 10_000_000,
      unit: 'toman',
      notify: Boolean(setup.notify),
      interval: (data.interval || 15),
    };
    return state.wizard;
  }

  const MONEY_OPTIONS = [
    ['toman_iran', 'تومان در ایران'],
    ['usdt', 'تتر (USDT)'],
    ['coins_both', 'موجودی در هر دو صرافی'],
  ];
  const EXCHANGE_NAMES = { wallex: 'والکس', nobitex: 'نوبیتکس', bitunix: 'بیت‌یونیکس' };
  const QUICK_AMOUNTS = ['۱ میلیون', '۵ میلیون', '۱۰ میلیون', '۵۰ میلیون', '۱۰۰ میلیون', '۱۰۰ دلار'];

  function renderWizard() {
    const wizard = wizardState();
    const body = $('wizardBody');
    if (!body) return;
    body.textContent = '';
    const steps = $('wizardSteps');
    if (steps) {
      Array.from(steps.children).forEach((node, index) => {
        node.className = index === state.step ? 'on' : '';
      });
    }
    setText('wizardTitle', 'راه‌اندازی — مرحله ' + fa(state.step + 1) + ' از ۳');
    const back = $('wizardBack');
    if (back) back.hidden = state.step === 0;
    const next = $('wizardNext');
    if (next) next.textContent = state.step === 2 ? 'تمام' : 'بعدی';

    if (state.step === 0) {
      const field = make('div', 'field');
      field.appendChild(make('label', '', 'در کدام صرافی‌ها حساب دارید؟'));
      const choices = make('div', 'choices');
      Object.keys(EXCHANGE_NAMES).forEach((name) => {
        const label = make('label', 'choice');
        const box = document.createElement('input');
        box.type = 'checkbox';
        box.value = name;
        box.checked = wizard.exchanges.indexOf(name) !== -1;
        box.addEventListener('change', () => {
          const index = wizard.exchanges.indexOf(name);
          if (box.checked && index === -1) wizard.exchanges.push(name);
          if (!box.checked && index !== -1) wizard.exchanges.splice(index, 1);
        });
        label.appendChild(box);
        label.appendChild(document.createTextNode(EXCHANGE_NAMES[name]));
        choices.appendChild(label);
      });
      field.appendChild(choices);
      body.appendChild(field);

      const moneyField = make('div', 'field');
      moneyField.appendChild(make('label', '', 'پولت الان کجاست؟'));
      const moneyChoices = make('div', 'choices');
      MONEY_OPTIONS.forEach(([value, text]) => {
        const label = make('label', 'choice');
        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.name = 'money';
        radio.value = value;
        radio.checked = wizard.money === value;
        radio.addEventListener('change', () => { wizard.money = value; });
        label.appendChild(radio);
        label.appendChild(document.createTextNode(text));
        moneyChoices.appendChild(label);
      });
      moneyField.appendChild(moneyChoices);
      moneyField.appendChild(make('p', 'hint', 'اگر پول در هر دو طرف هست، انتقال لازم نیست و '
        + 'سود بدون کارمزد انتقال حساب می‌شود.'));
      body.appendChild(moneyField);
      body.appendChild(make('p', 'hint', 'هیچ‌جا وارد حساب صرافی نمی‌شویم و سفارشی ثبت نمی‌کنیم.'));
      return;
    }

    if (state.step === 1) {
      const field = make('div', 'field');
      field.appendChild(make('label', '', 'چقدر می‌خواهی جابه‌جا کنی؟'));
      const input = document.createElement('input');
      input.type = 'text';
      input.id = 'wizardCapital';
      input.inputMode = 'decimal';
      input.placeholder = 'مثلاً ۵۰ میلیون';
      input.value = wizard.unit === 'toman' ? String(wizard.capital) : String(wizard.capital);
      field.appendChild(input);
      const quick = make('div', 'quick');
      QUICK_AMOUNTS.forEach((text) => {
        const button = make('button', 'quick-btn', text);
        button.type = 'button';
        button.addEventListener('click', () => {
          input.value = text;
          const parsed = parseAmount(text);
          if (parsed) {
            wizard.capital = /دلار|USDT|تتر/.test(text) ? parsed : parsed;
            wizard.unit = /دلار|USDT|تتر/.test(text) ? 'USDT' : 'toman';
            renderWizard();
          }
        });
        quick.appendChild(button);
      });
      field.appendChild(quick);
      const unit = document.createElement('select');
      unit.id = 'wizardUnit';
      [['toman', 'تومان'], ['USDT', 'تتر (USDT)']].forEach(([value, text]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = text;
        option.selected = wizard.unit === value;
        unit.appendChild(option);
      });
      unit.addEventListener('change', () => { wizard.unit = unit.value; });
      field.appendChild(unit);
      field.appendChild(make('p', 'hint', '«۵۰ میلیون» را هم می‌فهمیم. این عدد فقط برای محاسبه '
        + 'سود و عمق بازار است.'));
      body.appendChild(field);
      return;
    }

    const field = make('div', 'field');
    field.appendChild(make('label', '', 'وقتی فرصت خوب پیدا شد خبرت کنم؟'));
    const label = make('label', 'choice');
    const toggle = document.createElement('input');
    toggle.type = 'checkbox';
    toggle.id = 'wizardNotify';
    toggle.checked = Boolean(wizard.notify);
    toggle.addEventListener('change', () => { wizard.notify = toggle.checked; });
    label.appendChild(toggle);
    label.appendChild(document.createTextNode('یک پیام کوتاه داخل همین برنامه نشان بده'));
    field.appendChild(label);
    const refreshField = make('div', 'field');
    refreshField.appendChild(make('label', '', 'هر چند وقت قیمت‌ها را بخوانم؟'));
    const select = document.createElement('select');
    select.id = 'wizardInterval';
    [['10', 'هر ۱۰ ثانیه'], ['15', 'هر ۱۵ ثانیه'], ['30', 'هر ۳۰ ثانیه'], ['60', 'هر دقیقه']]
      .forEach(([value, text]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = text;
        option.selected = String(wizard.interval) === value;
        select.appendChild(option);
      });
    select.addEventListener('change', () => { wizard.interval = Number(select.value); });
    refreshField.appendChild(select);
    body.appendChild(field);
    body.appendChild(refreshField);
    body.appendChild(make('p', 'hint', 'کارمزدها را هم می‌توانی بعداً در صفحه «کارمزدها» با '
      + 'یک کلیک از صفحه رسمی صرافی وارد کنی.'));
  }

  function openWizard(step) {
    state.step = step || 0;
    if (!state.wizard) wizardState();
    renderWizard();
    openDialog($('wizard'));
  }

  function wizardBack() {
    if (state.step > 0) {
      state.step -= 1;
      renderWizard();
    }
  }

  async function wizardNext() {
    const wizard = wizardState();
    if (state.step === 0) {
      if (!wizard.exchanges.length) {
        toast('حداقل یک صرافی را انتخاب کنید.');
        return;
      }
      state.step = 1;
      renderWizard();
      return;
    }
    if (state.step === 1) {
      const input = $('wizardCapital');
      const unit = $('wizardUnit');
      const parsed = input ? parseAmount(input.value) : null;
      if (!parsed) {
        toast('مبلغ را به تومان یا تتر بنویسید؛ مثلاً ۵۰ میلیون.');
        return;
      }
      wizard.capital = parsed;
      wizard.unit = unit ? unit.value : 'toman';
      state.step = 2;
      renderWizard();
      return;
    }
    const select = $('wizardInterval');
    if (select) wizard.interval = Number(select.value) || wizard.interval;
    const toggle = $('wizardNotify');
    if (toggle) wizard.notify = toggle.checked;
    await saveSetup(true);
  }

  async function saveSetup(complete) {
    const wizard = wizardState();
    try {
      await api('/api/setup', {
        method: 'PUT',
        body: JSON.stringify({
          exchanges: wizard.exchanges,
          money: wizard.money,
          capital: wizard.capital,
          capital_unit: wizard.unit,
          notify: Boolean(wizard.notify),
          interval: wizard.interval,
          complete: Boolean(complete),
        }),
      });
      closeDialog($('wizard'));
      toast('ذخیره شد.');
      await load();
    } catch (error) {
      toast(friendly(error));
    }
  }

  async function setNotify(value) {
    const wizard = wizardState();
    wizard.notify = Boolean(value);
    await saveSetup(false);
  }

  /* --------------------------------------------------------------- boot */
  function bind() {
    const on = (id, event, handler) => {
      const node = $(id);
      if (node) node.addEventListener(event, handler);
    };
    on('pauseBtn', 'click', togglePause);
    on('refreshBtn', 'click', refresh);
    on('setupEdit', 'click', () => openWizard(0));
    on('receiptBtn', 'click', () => {
      const best = (state.home || {}).best;
      if (best) openReceipt(best.key);
    });
    on('receiptClose', 'click', () => closeDialog($('receiptDialog')));
    on('wizardClose', 'click', () => closeDialog($('wizard')));
    on('wizardBack', 'click', wizardBack);
    on('wizardNext', 'click', wizardNext);
    on('copyReceipt', 'click', copyReceipt);
    on('copyInline', 'click', copyReceipt);
    on('simulateBtn', 'click', saveSimulation);
    on('simulateInline', 'click', saveSimulation);
    on('bannerClose', 'click', dismissBanner);
    on('notifyToggle', 'change', (event) => setNotify(event.target.checked));
    on('themeBtn', 'click', cycleTheme);
    on('connectionBtn', 'click', () => { window.location.href = '/dashboard#diagnostics'; });
  }

  async function dismissBanner() {
    const banner = $('banner');
    if (banner) banner.hidden = true;
    const signature = ((state.home || {}).banner || {}).signature || '';
    try {
      await api('/api/ui', { method: 'PUT', body: JSON.stringify({
        values: { setup_banner_dismissed: signature },
      }) });
    } catch (error) { /* silence: the banner is already hidden */ }
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const button = $('themeBtn');
    if (button) button.title = 'حالت: ' + ({ system: 'هماهنگ با سیستم', light: 'روشن', dark: 'تاریک' }[theme] || theme);
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
    bind();
    // Every dialog starts closed; the user opens them.
    ['wizard', 'receiptDialog'].forEach((id) => closeDialog($(id)));
    load();
  }

  return {
    init, load, render, openReceipt, openWizard, wizardNext, wizardBack, saveSetup,
    setNotify, togglePause, refresh, dismissBanner, cycleTheme, parseAmount,
    number: money, percent, state, renderWizard,
  };
})();

if (typeof window !== 'undefined') {
  window.App = App;
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => App.init());
    } else {
      App.init();
    }
  }
}
