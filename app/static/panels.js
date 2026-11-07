/* Panels: diagnostics, simulations, journal, setup and the step-by-step wizard. */
(function () {
  'use strict';
  const App = window.App;
  const $ = App.$;

  const WIZARD_STEPS = [
    'سرمایه و حالت معامله', 'کارمزد معاملاتی', 'کارمزد برداشت و شبکه', 'اتصال', 'پایان',
  ];
  const FEE_ROWS = [
    ['wallex', 'toman', 'والکس · بازار تومان'],
    ['nobitex', 'toman', 'نوبیتکس · بازار تومان'],
    ['wallex', 'USDT', 'والکس · بازار USDT'],
    ['nobitex', 'USDT', 'نوبیتکس · بازار USDT'],
    ['bitunix', 'USDT', 'بیت‌یونیکس · بازار USDT'],
  ];
  const SIM_STATUS = { pending: 'در انتظار', done: 'انجام شد', unavailable: 'داده نبود' };

  App.number = function (value, digits) {
    return value == null || value === '' || !Number.isFinite(Number(value)) ? '—' : App.fmt(value, digits == null ? 2 : digits);
  };

  // ------------------------------------------------------------------ diagnostics
  App.renderDiagnostics = async function () {
    if (!$('diagCards')) return;
    $('diagCards').innerHTML = '<p class="loading">در حال خواندن وضعیت اتصال…</p>';
    try {
      const data = await App.api('/api/diagnostics');
      App.state.diagnostics = data;
      App.fillDiagnostics(data);
    } catch (error) {
      $('diagCards').innerHTML = '<p class="message error">' + App.esc(error.message) + '</p>';
    }
  };

  App.fillDiagnostics = function (data) {
    const extra = data.extra || {};
    const cards = Object.keys(data.exchanges || {}).map(function (name) {
      const entry = data.exchanges[name];
      const request = entry.last_request || {};
      const budget = entry.budget || {};
      const clock = entry.clock || {};
      const rows = [
        ['آخرین موفقیت', entry.last_success ? App.ageText(entry.last_success_age) + ' پیش' : 'هنوز موفق نبوده'],
        ['آدرس آخرین درخواست', request.url ? '<span dir="ltr">' + App.esc(request.url) + '</span>' : '—'],
        ['کد HTTP', request.status == null ? '—' : App.fmt(request.status)],
        ['زمان پاسخ', request.elapsed_ms == null ? '—' : App.fmt(request.elapsed_ms, 0) + ' میلی‌ثانیه'],
        ['JSON معتبر', request.json_ok == null ? '—' : (request.json_ok ? 'بله' : 'نه')],
        ['دلیل', request.reason ? App.esc(App.reasonText(request.reason)) : '—'],
        ['تلاش', request.attempt == null ? '—' : App.fmt(request.attempt)],
        ['اختلاف ساعت', clock.skew_seconds == null ? '—' : App.fmt(clock.skew_seconds, 1) + ' ثانیه'],
        ['سهمیه درخواست', budget.limit == null ? '—' :
          App.fmt(budget.used) + ' از ' + App.fmt(budget.limit) + ' در هر ' + App.fmt(budget.window_seconds) + ' ثانیه'],
      ];
      const errorBlock = entry.error
        ? '<div class="banner error-inline">' + App.esc(entry.error.message) +
          (entry.error.action ? '<br><span class="muted small">' + App.esc(entry.error.action) + '</span>' : '') + '</div>'
        : '';
      const preview = request.preview
        ? '<details><summary>پیش‌نمایش پاسخ خام</summary><pre dir="ltr" class="raw">' + App.esc(request.preview) + '</pre></details>'
        : '';
      return '<article class="diag-card"><header><h3>' + App.esc(entry.label || name) + '</h3>' +
        '<span class="chip status-' + App.esc(entry.status) + '">' + App.esc(App.diagStatus(entry.status)) + '</span></header>' +
        errorBlock + '<dl class="kv">' + rows.map(row => App.kv(row[0], row[1])).join('') + '</dl>' + preview +
        '</article>';
    });
    $('diagCards').innerHTML = cards.join('') || '<p class="empty">صرافی‌ای ثبت نشده است.</p>';

    const clocks = Object.keys(data.exchanges || {}).map(name => data.exchanges[name].clock || {})
      .filter(clock => clock.level === 'warn');
    const clockBox = $('diagClock');
    if (clockBox) {
      if (clocks.length) {
        clockBox.hidden = false;
        clockBox.innerHTML = clocks.map(clock =>
          '<strong>' + App.esc(clock.message) + '</strong><br><span class="small">' + App.esc(clock.action) + '</span>').join('<hr>');
      } else {
        clockBox.hidden = data.generated_at == null;
        clockBox.innerHTML = '<span class="muted small">اختلاف ساعت صرافی‌ها در محدوده امن است' +
          (extra.clock_skew_warning_seconds ? ' (آستانه ' + App.fmt(extra.clock_skew_warning_seconds) + ' ثانیه)' : '') + '.</span>';
      }
    }

    const budgets = data.budgets || {};
    if ($('budgetTable')) {
      $('budgetTable').innerHTML = '<table class="rows"><thead><tr><th>صرافی</th><th>مصرف</th><th>باقی‌مانده</th>' +
        '<th>کل درخواست</th><th>ناموفق</th><th>عقب‌کشیدن</th></tr></thead><tbody>' +
        Object.keys(budgets).map(function (name) {
          const item = budgets[name];
          return '<tr><td>' + App.esc(App.exchangeLabel(name)) + '</td><td>' + App.fmt(item.used) + '</td><td>' +
            App.fmt(item.remaining) + '</td><td>' + App.fmt(item.total) + '</td><td>' + App.fmt(item.failed) +
            '</td><td>' + (item.backing_off ? App.fmt(item.backoff_seconds, 1) + ' ثانیه صبر' : 'خیر') + '</td></tr>';
        }).join('') + '</tbody></table>';
    }

    const catalog = data.reason_catalog || {};
    if ($('reasonCatalog')) {
      $('reasonCatalog').innerHTML = Object.keys(catalog).map(function (code) {
        const item = catalog[code];
        return '<p><strong>' + App.esc(item.message) + '</strong><br><span class="small">' + App.esc(item.action || '') + '</span></p>';
      }).join('');
    }

    const form = $('connectionForm');
    if (form && !form.dataset.ready) {
      $('proxyUrl').value = extra.proxy && extra.proxy !== 'None' ? (extra.proxy === '***' ? '' : extra.proxy) : '';
      $('userAgent').value = extra.user_agent || '';
      $('maxAge').value = extra.max_timestamp_age_seconds || 120;
      $('skewWarn').value = extra.clock_skew_warning_seconds || 60;
      form.onsubmit = async function (event) {
        event.preventDefault();
        try {
          const body = {
            proxy_url: $('proxyUrl').value.trim() || null,
            user_agent: $('userAgent').value.trim() || null,
            max_timestamp_age_seconds: Number($('maxAge').value) || null,
            clock_skew_warning_seconds: Number($('skewWarn').value) || null,
          };
          await App.api('/api/connection', App.put(body));
          App.message('تنظیمات اتصال ذخیره شد.');
          App.renderDiagnostics();
        } catch (error) { App.error(error); }
      };
      form.dataset.ready = '1';
    }
  };

  App.reasonText = function (code) {
    const catalog = (App.state.diagnostics && App.state.diagnostics.reason_catalog) || {};
    return (catalog[code] && catalog[code].message) || code;
  };

  App.diagStatus = function (status) {
    const names = { ok: 'سالم', error: 'خطا', stale: 'داده قدیمی', unknown: 'نامعلوم', paused: 'متوقف' };
    return names[status] || status || 'نامعلوم';
  };

  App.runTests = async function (button) {
    const target = $('testResults');
    if (!target) return;
    if (button) button.disabled = true;
    target.innerHTML = '<p class="loading">در حال تست صرافی‌ها… (چند ثانیه طول می‌کشد)</p>';
    try {
      const data = await App.api('/api/diagnostics/test', { method: 'POST' });
      target.innerHTML = data.results.map(function (result) {
        return '<article class="test-card"><h3>' + App.esc(result.label) + ' ' +
          (result.ok ? '<span class="chip status-ok">سالم</span>' : '<span class="chip status-error">مشکل دارد</span>') +
          '</h3><ol>' + result.steps.map(function (step) {
          return '<li><strong>' + App.esc(step.step) + '</strong> — ' + (step.ok ? 'موفق' : 'ناموفق') +
            '<br><span class="small" dir="ltr">' + App.esc(step.url) + '</span>' +
            '<br><span class="small">' + App.esc(step.message) + ' ' + App.esc(step.action || '') + '</span>' +
            (step.preview ? '<details><summary>پاسخ خام</summary><pre dir="ltr" class="raw">' + App.esc(step.preview) + '</pre></details>' : '') +
            '</li>';
        }).join('') + '</ol>' + (result.clock && result.clock.level === 'warn'
          ? '<div class="banner warning small">' + App.esc(result.clock.message) + ' ' + App.esc(result.clock.action) + '</div>' : '') +
          '</article>';
      }).join('');
      App.renderDiagnostics();
    } catch (error) {
      target.innerHTML = '<p class="message error">' + App.esc(error.message) + '</p>';
    } finally {
      if (button) button.disabled = false;
    }
  };

  // ------------------------------------------------------------------ simulations
  App.renderSimulations = async function () {
    if (!$('simRows')) return;
    try {
      const data = await App.api('/api/simulations');
      const rows = data.rows || [];
      const summary = data.summary || {};
      $('simSummary').innerHTML = [
        ['ثبت‌شده', App.fmt(summary.count || 0), ''],
        ['در انتظار', App.fmt(summary.pending || 0), ''],
        ['انجام‌شده', App.fmt(summary.done || 0), ''],
        ['میانگین اختلاف', App.number(summary.average_difference, 2) + ' USDT', 'سود واقعی منهای سود انتظار'],
        ['سهم سودده', summary.profitable_share == null ? '—' : App.fmt(summary.profitable_share, 0) + '٪', 'از معاملات انجام‌شده'],
        ['بدترین اختلاف', App.number(summary.worst_difference, 2), ''],
      ].map(item => '<article class="card"><h3>' + item[0] + '</h3><p class="big">' + item[1] + '</p>' +
        (item[2] ? '<p class="muted small">' + item[2] + '</p>' : '') + '</article>').join('');
      $('simRows').innerHTML = rows.map(function (row) {
        const difference = row.difference == null ? null : row.difference;
        return '<tr data-sim="' + App.esc(row.id) + '"><td>' + App.fmtTime(row.created) + '</td><td>' + App.esc(row.coin) +
          '</td><td>' + App.esc(row.route_label || row.route) + '</td><td>' + App.number(row.capital, 2) + ' ' + App.esc(row.unit || 'USDT') +
          '</td><td>' + App.number(row.expected_profit, 2) + '<br><span class="muted small">' + App.fmtPct(row.expected_pct) + '</span></td>' +
          '<td>' + App.number(row.actual_profit, 2) + '<br><span class="muted small">' + (row.actual_pct == null ? '' : App.fmtPct(row.actual_pct)) + '</span></td>' +
          '<td class="' + (difference == null ? '' : difference >= 0 ? 'good' : 'bad') + '">' + App.number(difference, 2) + '</td>' +
          '<td>' + App.esc(SIM_STATUS[row.status] || row.status_label || row.status) +
          (row.note ? '<br><span class="muted small">' + App.esc(row.note) + '</span>' : '') + '</td>' +
          '<td class="row-actions">' + (row.status === 'pending'
            ? '<button type="button" class="ghost" data-sim-settle="' + App.esc(row.id) + '">محاسبه نتیجه</button>'
            : '') + '<button type="button" class="ghost danger" data-sim-delete="' + App.esc(row.id) + '">حذف</button></td></tr>';
      }).join('');
      $('simEmpty').hidden = rows.length > 0;
      $('simRows').querySelectorAll('[data-sim-settle]').forEach(function (button) {
        button.onclick = async function () {
          button.disabled = true;
          try {
            await App.api('/api/simulations/' + encodeURIComponent(button.dataset.simSettle) + '/settle', { method: 'POST' });
            await App.renderSimulations();
          } catch (error) { App.error(error); button.disabled = false; }
        };
      });
      $('simRows').querySelectorAll('[data-sim-delete]').forEach(function (button) {
        button.onclick = async function () {
          if (!window.confirm('این معامله آزمایشی حذف شود؟')) return;
          try {
            await App.api('/api/simulations/' + encodeURIComponent(button.dataset.simDelete), { method: 'DELETE' });
            await App.renderSimulations();
          } catch (error) { App.error(error); }
        };
      });
    } catch (error) {
      $('simRows').innerHTML = '<tr><td colspan="9" class="message error">' + App.esc(error.message) + '</td></tr>';
    }
  };

  // ---------------------------------------------------------------------- journal
  App.renderJournal = async function () {
    if (!$('journalRows')) return;
    try {
      const data = await App.api('/api/journal');
      const rows = data.rows || [];
      $('journalRows').innerHTML = rows.map(function (row) {
        return '<tr><td>' + App.esc(row.date) + '</td><td>' + App.esc(row.coin) + '</td><td>' + App.esc(row.route) +
          '</td><td>' + App.number(row.capital, 2) + '</td><td>' + App.number(row.final_amount, 2) +
          '</td><td class="' + (row.profit == null ? '' : row.profit >= 0 ? 'good' : 'bad') + '">' + App.number(row.profit, 2) +
          '</td><td>' + App.esc(row.fees || '—') + '</td><td>' + App.esc(row.note || '') +
          '</td><td class="row-actions"><button type="button" class="ghost danger" data-journal-delete="' +
          App.esc(row.id) + '">حذف</button></td></tr>';
      }).join('');
      $('journalEmpty').hidden = rows.length > 0;
      $('journalRows').querySelectorAll('[data-journal-delete]').forEach(function (button) {
        button.onclick = async function () {
          if (!window.confirm('این ردیف دفتر حذف شود؟')) return;
          try {
            await App.api('/api/journal/' + encodeURIComponent(button.dataset.journalDelete), { method: 'DELETE' });
            await App.renderJournal();
          } catch (error) { App.error(error); }
        };
      });
    } catch (error) {
      $('journalRows').innerHTML = '<tr><td colspan="9" class="message error">' + App.esc(error.message) + '</td></tr>';
    }
  };

  App.bindJournal = function () {
    const form = $('journalForm');
    if (!form || form.dataset.ready) return;
    form.dataset.ready = '1';
    if ($('journalDate') && !$('journalDate').value) {
      const now = new Date();
      $('journalDate').value = now.toISOString().slice(0, 10);
    }
    form.onsubmit = async function (event) {
      event.preventDefault();
      const number = id => ($(id) && $(id).value !== '') ? Number($(id).value) : null;
      const body = {
        date: $('journalDate').value,
        coin: ($('journalCoin').value || '').trim().toUpperCase(),
        route: $('journalRoute').value,
        mode: $('journalMode').value,
        capital: number('journalCapital'),
        final_amount: number('journalFinal'),
        profit: number('journalProfit'),
        fees: ($('journalFees').value || '').trim() || null,
        note: ($('journalNote').value || '').trim() || null,
      };
      try {
        await App.api('/api/journal', App.post(body));
        form.reset();
        $('journalDate').value = new Date().toISOString().slice(0, 10);
        App.message('معامله در دفتر ثبت شد.');
        await App.renderJournal();
      } catch (error) { App.error(error); }
    };
  };

  // ------------------------------------------------------------------------ setup
  App.renderSetup = async function () {
    if (!$('feeForm')) return;
    try {
      const [settings, fees] = await Promise.all([App.api('/api/settings'), App.api('/api/scanner/fees')]);
      App.state.settings = settings;
      App.state.feeRows = fees || [];
      $('feeForm').innerHTML = FEE_ROWS.map(function (row) {
        const exchange = row[0], quote = row[1];
        const key = quote === 'toman' ? exchange : exchange + '_usdt';
        const value = settings[key] || {};
        return '<fieldset><legend>' + App.esc(row[2]) + '</legend>' +
          '<label>میکر ٪<input type="number" step="any" min="0" max="99" data-fee="' + exchange + '" data-quote="' + quote +
          '" data-field="maker" value="' + (value.maker == null ? '' : App.esc(value.maker)) + '"></label>' +
          '<label>تیکر ٪<input type="number" step="any" min="0" max="99" data-fee="' + exchange + '" data-quote="' + quote +
          '" data-field="taker" value="' + (value.taker == null ? '' : App.esc(value.taker)) + '"></label></fieldset>';
      }).join('');
      App.renderNetworkFees(App.state.feeRows);
    } catch (error) {
      $('feeForm').innerHTML = '<p class="message error">' + App.esc(error.message) + '</p>';
    }
  };

  App.networkRowHtml = function (row) {
    const options = ['wallex', 'nobitex', 'bitunix'].map(name =>
      '<option value="' + name + '"' + (name === row.exchange ? ' selected' : '') + '>' + App.exchangeLabel(name) + '</option>').join('');
    return '<td><select data-net="exchange">' + options + '</select></td>' +
      '<td><input data-net="coin" value="' + App.esc(row.coin || '') + '" maxlength="20" placeholder="USDT"></td>' +
      '<td><input data-net="network" value="' + App.esc(row.network || '') + '" maxlength="40" placeholder="TRC20"></td>' +
      '<td><input data-net="withdrawal" type="number" step="any" min="0" value="' + (row.withdrawal == null ? '' : App.esc(row.withdrawal)) + '"></td>' +
      '<td><input data-net="minimum" type="number" step="any" min="0" value="' + (row.minimum == null ? '' : App.esc(row.minimum)) + '"></td>' +
      '<td><input data-net="supported" type="checkbox"' + (row.supported ? ' checked' : '') + '></td>' +
      '<td class="row-actions"><button type="button" class="ghost danger" data-net-remove="1">حذف</button></td>';
  };

  App.bindNetworkRow = function (tr) {
    const button = tr.querySelector('[data-net-remove]');
    if (button) button.onclick = function () { tr.remove(); };
  };

  App.renderNetworkFees = function (rows) {
    const tbody = $('networkFeeRows');
    if (!tbody) return;
    const list = rows.length ? rows : [{ exchange: 'wallex', coin: '', network: '', withdrawal: null, minimum: null, supported: true }];
    tbody.innerHTML = list.map(function (row) {
      return '<tr data-network-row="1">' + App.networkRowHtml(row) + '</tr>';
    }).join('');
    tbody.querySelectorAll('tr').forEach(App.bindNetworkRow);
  };

  App.bindSetup = function () {
    if (!$('feeForm')) return;
    if ($('feeSave') && !$('feeSave').dataset.ready) {
      $('feeSave').dataset.ready = '1';
      $('feeSave').onclick = async function () {
        const base = App.state.settings || await App.api('/api/settings');
        const payload = JSON.parse(JSON.stringify(base));
        let missing = 0;
        $('feeForm').querySelectorAll('[data-fee]').forEach(function (input) {
          const exchange = input.dataset.fee, quote = input.dataset.quote, field = input.dataset.field;
          const key = quote === 'toman' ? exchange : exchange + '_usdt';
          payload[key] = payload[key] || {};
          payload[key][field] = input.value === '' ? null : Number(input.value);
          if (input.value === '' && exchange !== 'bitunix') missing += 1;
        });
        try {
          App.state.settings = await App.api('/api/settings', App.put(payload));
          App.message(missing
            ? 'ذخیره شد؛ ' + App.fmt(missing) + ' کارمزد خالی ماند و تا پر شدنش سود خالص محاسبه نمی‌شود.'
            : 'کارمزدهای معاملاتی ذخیره شد.');
          App.renderSetup();
        } catch (error) { App.error(error); }
      };
    }
    if ($('networkFeeAdd') && !$('networkFeeAdd').dataset.ready) {
      $('networkFeeAdd').dataset.ready = '1';
      $('networkFeeAdd').onclick = function () {
        const tbody = $('networkFeeRows');
        const tr = document.createElement('tr');
        tr.dataset.networkRow = '1';
        tr.innerHTML = App.networkRowHtml({ exchange: 'bitunix', coin: '', network: '',
          withdrawal: null, minimum: null, supported: true });
        tbody.appendChild(tr);
        App.bindNetworkRow(tr);
        const coin = tr.querySelector('[data-net="coin"]');
        if (coin) coin.focus();
      };
    }
    if ($('networkFeeSave') && !$('networkFeeSave').dataset.ready) {
      $('networkFeeSave').dataset.ready = '1';
      $('networkFeeSave').onclick = async function () {
        const rows = [];
        const seen = new Set();
        let problem = '';
        $('networkFeeRows').querySelectorAll('tr').forEach(function (tr) {
          const get = key => tr.querySelector('[data-net="' + key + '"]');
          const coin = (get('coin').value || '').trim().toUpperCase();
          const network = (get('network').value || '').trim().toUpperCase();
          if (!coin && !network && !get('withdrawal').value) return;
          if (!coin || !network) { problem = problem || 'ارز و شبکه هر دو لازم است.'; return; }
          const key = get('exchange').value + ':' + coin + ':' + network;
          if (seen.has(key)) { problem = problem || 'ردیف تکراری: ' + coin + ' ' + network; return; }
          seen.add(key);
          rows.push({
            exchange: get('exchange').value, coin: coin, network: network,
            withdrawal: get('withdrawal').value === '' ? null : Number(get('withdrawal').value),
            minimum: get('minimum').value === '' ? null : Number(get('minimum').value),
            supported: get('supported').checked,
          });
        });
        if (problem) { App.message(problem, true); return; }
        try {
          App.state.feeRows = await App.api('/api/scanner/fees', App.put(rows));
          App.message('جدول کارمزد برداشت ذخیره شد (' + App.fmt(rows.length) + ' ردیف).');
          App.renderNetworkFees(App.state.feeRows);
        } catch (error) { App.error(error); }
      };
    }
    if ($('restoreFile') && !$('restoreFile').dataset.ready) {
      $('restoreFile').dataset.ready = '1';
      $('restoreFile').onchange = function (event) {
        const file = event.target.files && event.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = async function () {
          let parsed = null;
          try { parsed = JSON.parse(String(reader.result)); } catch (error) { parsed = null; }
          if (!parsed) { App.message('فایل پشتیبان قابل خواندن نیست.', true); return; }
          if (!window.confirm('تنظیمات فعلی با فایل پشتیبان جایگزین شود؟')) return;
          try {
            const result = await App.api('/api/backup/restore', App.post(parsed));
            App.message('تنظیمات بازگردانی شد (' + App.fmt(result.fees) + ' ردیف کارمزد). صفحه دوباره خوانده می‌شود.');
            setTimeout(function () { window.location.reload(); }, 800);
          } catch (error) { App.error(error); }
        };
        reader.readAsText(file);
      };
    }
  };

  // ------------------------------------------------------------------------ wizard
  App.openWizard = async function (step) {
    const modal = $('wizard');
    if (!modal) return;
    App.state.wizardStep = Math.max(1, Math.min(WIZARD_STEPS.length, step || 1));
    modal.hidden = false;
    try {
      const [settings, scanner, fees] = await Promise.all([
        App.api('/api/settings'), App.api('/api/scanner/settings'), App.api('/api/scanner/fees')]);
      App.state.settings = settings;
      App.state.scanner = scanner;
      App.state.feeRows = fees || [];
    } catch (error) {
      App.message(error.message, true);
    }
    App.renderWizard();
  };

  App.renderWizard = function () {
    const step = App.state.wizardStep;
    $('wizardSteps').innerHTML = WIZARD_STEPS.map(function (title, index) {
      const number = index + 1;
      return '<li class="' + (number === step ? 'active' : number < step ? 'done' : '') + '">' +
        App.fmt(number) + '. ' + App.esc(title) + '</li>';
    }).join('');
    const settings = App.state.settings || {};
    const scanner = App.state.scanner || {};
    const body = $('wizardBody');
    if (step === 1) {
      body.innerHTML = '<p class="muted small">سرمایه‌ای که در هر معامله استفاده می‌کنید. برنامه با همین مبلغ، سود و لغزش را حساب می‌کند.</p>' +
        '<div class="filters"><label>سرمایه USDT<input id="wizCapital" type="number" step="any" min="1" value="' +
        App.esc(scanner.capital_usdt || 100) + '"></label>' +
        '<label>سرمایه تومان<input id="wizCapitalToman" type="number" step="any" min="1000" value="' +
        App.esc(scanner.capital_toman || 10000000) + '"></label>' +
        '<label>حالت پیش‌فرض<select id="wizMode"><option value="transfer"' +
        (scanner.trading_mode !== 'prefunded' ? ' selected' : '') + '>انتقال بین صرافی‌ها</option>' +
        '<option value="prefunded"' + (scanner.trading_mode === 'prefunded' ? ' selected' : '') +
        '>موجودی از پیش در دو صرافی</option></select></label></div>';
    } else if (step === 2) {
      body.innerHTML = '<p class="muted small">کارمزد تیکر و میکر هر صرافی و هر بازار را از صفحه کارمزد صرافی خودتان وارد کنید. ' +
        'تا کارمزد بیت‌یونیکس خالی باشد، سود خالص محاسبه نمی‌شود.</p>' +
        '<div class="fee-grid">' + FEE_ROWS.map(function (row) {
          const exchange = row[0], quote = row[1];
          const key = quote === 'toman' ? exchange : exchange + '_usdt';
          const value = settings[key] || {};
          return '<fieldset><legend>' + App.esc(row[2]) + '</legend>' +
            '<label>میکر ٪<input type="number" step="any" min="0" max="99" data-wiz-fee="' + key + '" data-field="maker" value="' +
            (value.maker == null ? '' : App.esc(value.maker)) + '"></label>' +
            '<label>تیکر ٪<input type="number" step="any" min="0" max="99" data-wiz-fee="' + key + '" data-field="taker" value="' +
            (value.taker == null ? '' : App.esc(value.taker)) + '"></label></fieldset>';
        }).join('') + '</div>';
    } else if (step === 3) {
      body.innerHTML = '<p class="muted small">برای هر ارز، شبکه‌ای که هر دو طرف پشتیبانی می‌کنند و کارمزد برداشت همان شبکه را وارد کنید. ' +
        'خالی گذاشتن یعنی «نامعلوم»؛ برنامه صفر فرض نمی‌کند.</p>' +
        '<div class="filters"><label>ارز<input id="wizCoin" value="USDT" maxlength="20"></label>' +
        '<label>شبکه<input id="wizNetwork" value="TRC20" maxlength="40"></label>' +
        '<label>کارمزد برداشت در بیت‌یونیکس<input id="wizBitunixFee" type="number" step="any" min="0" placeholder="نامعلوم"></label>' +
        '<label>حداقل برداشت بیت‌یونیکس<input id="wizBitunixMin" type="number" step="any" min="0"></label>' +
        '<label>کارمزد برداشت در صرافی ایرانی<input id="wizIranFee" type="number" step="any" min="0" placeholder="نامعلوم"></label>' +
        '<label>حداقل برداشت ایرانی<input id="wizIranMin" type="number" step="any" min="0"></label></div>' +
        '<p class="muted small">ردیف‌ها برای والکس و نوبیتکس هر دو ثبت می‌شوند؛ بعداً در تنظیمات می‌توانید جدا کنید.</p>' +
        '<div class="muted small">ردیف‌های فعلی: ' + (App.state.feeRows || []).length + '</div>';
    } else if (step === 4) {
      body.innerHTML = '<p class="muted small">اگر صرافی درخواست‌های برنامه را مسدود کند، User-Agent را عوض کنید. ' +
        'برای شبکه محدود، پروکسی HTTP/SOCKS وارد کنید. این مقادیر فقط روی همین رایانه ذخیره می‌شوند.</p>' +
        '<div class="filters"><label class="wide">آدرس پروکسی<input id="wizProxy" dir="ltr" placeholder="socks5://127.0.0.1:1080" value="' +
        App.esc(settings.proxy_url || '') + '"></label>' +
        '<label class="wide">User-Agent<input id="wizAgent" dir="ltr" value="' + App.esc(settings.user_agent || '') + '"></label></div>' +
        '<p><button type="button" id="wizTest">تست اتصال صرافی‌ها</button></p><div id="wizTestResults" class="test-results"></div>';
      const testButton = $('wizTest');
      testButton.onclick = function () {
        const box = $('wizTestResults');
        box.innerHTML = '<p class="loading">در حال تست…</p>';
        App.api('/api/diagnostics/test', { method: 'POST' }).then(function (data) {
          box.innerHTML = data.results.map(function (result) {
            return '<p>' + App.esc(result.label) + ': ' +
              (result.ok ? '<span class="chip status-ok">سالم</span>' : '<span class="chip status-error">مشکل</span>') +
              ' ' + result.steps.map(step => App.esc(step.message)).join(' ') + '</p>';
          }).join('');
        }).catch(function (error) { box.innerHTML = '<p class="message error">' + App.esc(error.message) + '</p>'; });
      };
    } else {
      body.innerHTML = '<p class="loading">در حال بررسی کامل بودن تنظیمات…</p>';
      App.api('/api/wizard').then(function (data) {
        $('wizardBody').innerHTML = data.complete
          ? '<div class="banner ok">همه موارد لازم وارد شده است. از تب «فرصت‌ها» شروع کنید.</div>'
          : '<div class="banner warning">موارد باقی‌مانده:<ul>' + data.missing.map(item => '<li>' + App.esc(item) + '</li>').join('') +
            '</ul>می‌توانید بعداً از تب «تنظیمات» تکمیل کنید؛ تا آن زمان ردیف‌های ناقص با برچسب «فقط اختلاف خام» نمایش داده می‌شوند.</div>' +
            '<p class="muted small">این برنامه فقط داده عمومی می‌خواند: هیچ کلید API و هیچ سفارشی ثبت نمی‌شود.</p>';
      }).catch(function (error) {
        $('wizardBody').innerHTML = '<p class="message error">' + App.esc(error.message) + '</p>';
      });
    }
    $('wizardPrev').disabled = step === 1;
    $('wizardNext').textContent = step === WIZARD_STEPS.length ? 'پایان' : 'بعدی';
  };

  App.wizardBack = function () {
    if (App.state.wizardStep > 1) {
      App.state.wizardStep -= 1;
      App.renderWizard();
    }
  };

  App.wizardFinish = async function () {
    $('wizard').hidden = true;
    try {
      await App.saveUi({ wizard_done: true });
      App.message('راه‌اندازی ذخیره شد.');
    } catch (error) { App.error(error); }
    App.load(false);
  };

  App.wizardForward = async function () {
    const step = App.state.wizardStep;
    try {
      if (step === 1) {
        const scanner = JSON.parse(JSON.stringify(App.state.scanner || {}));
        scanner.capital_usdt = Number($('wizCapital').value) || scanner.capital_usdt || 100;
        scanner.capital_toman = Number($('wizCapitalToman').value) || scanner.capital_toman || 10000000;
        scanner.trading_mode = $('wizMode').value;
        App.state.scanner = await App.api('/api/scanner/settings', App.put(scanner));
      } else if (step === 2) {
        const payload = JSON.parse(JSON.stringify(App.state.settings || {}));
        $('wizardBody').querySelectorAll('[data-wiz-fee]').forEach(function (input) {
          const key = input.dataset.wizFee;
          payload[key] = payload[key] || {};
          payload[key][input.dataset.field] = input.value === '' ? null : Number(input.value);
        });
        App.state.settings = await App.api('/api/settings', App.put(payload));
      } else if (step === 3) {
        const coin = ($('wizCoin').value || '').trim().toUpperCase();
        const network = ($('wizNetwork').value || '').trim().toUpperCase();
        const bitunixFee = $('wizBitunixFee').value === '' ? null : Number($('wizBitunixFee').value);
        const bitunixMin = $('wizBitunixMin').value === '' ? null : Number($('wizBitunixMin').value);
        const iranFee = $('wizIranFee').value === '' ? null : Number($('wizIranFee').value);
        const iranMin = $('wizIranMin').value === '' ? null : Number($('wizIranMin').value);
        if (coin && network && (bitunixFee != null || iranFee != null)) {
          const rows = (App.state.feeRows || []).filter(row => !(row.coin === coin && row.network === network));
          rows.push({ exchange: 'bitunix', coin: coin, network: network, withdrawal: bitunixFee, minimum: bitunixMin, supported: true });
          ['wallex', 'nobitex'].forEach(function (name) {
            rows.push({ exchange: name, coin: coin, network: network, withdrawal: iranFee, minimum: iranMin, supported: true });
          });
          App.state.feeRows = await App.api('/api/scanner/fees', App.put(rows));
        }
      } else if (step === 4) {
        await App.api('/api/connection', App.put({
          proxy_url: ($('wizProxy').value || '').trim() || null,
          user_agent: ($('wizAgent').value || '').trim() || null,
        }));
      }
    } catch (error) {
      App.error(error);
      return;
    }
    if (step === WIZARD_STEPS.length) { App.wizardFinish(); return; }
    App.state.wizardStep = step + 1;
    App.renderWizard();
  };

  // ------------------------------------------------------------------------ manual
  App.openManual = function () {
    const modal = $('manualDrawer');
    if (!modal) return;
    modal.hidden = false;
    $('manualForms').innerHTML = ['wallex', 'nobitex'].map(function (name) {
      return '<fieldset><legend>' + App.exchangeLabel(name) + '</legend>' +
        '<label>قیمت فروش صرافی (ask، تومان)<input id="manual-ask-' + name + '" type="number" step="any" min="1"></label>' +
        '<label>قیمت خرید صرافی (bid، تومان)<input id="manual-bid-' + name + '" type="number" step="any" min="1"></label>' +
        '<p><button type="button" data-manual="' + name + '">ثبت قیمت دستی</button></p></fieldset>';
    }).join('');
    $('manualForms').querySelectorAll('[data-manual]').forEach(function (button) {
      button.onclick = async function () {
        const name = button.dataset.manual;
        const ask = Number($('manual-ask-' + name).value);
        const bid = Number($('manual-bid-' + name).value);
        try {
          await App.api('/api/manual/' + name, App.put({ ask: ask, bid: bid }));
          App.message('قیمت دستی ' + App.exchangeLabel(name) + ' ثبت شد.');
          App.closeManual();
          App.load(false);
        } catch (error) { App.error(error); }
      };
    });
  };

  App.closeManual = function () {
    const modal = $('manualDrawer');
    if (modal) modal.hidden = true;
  };

  // -------------------------------------------------------------------------- init
  App.initPanels = function () {
    if ($('drawerClose')) $('drawerClose').onclick = function () { App.closeDrawer(); };
    if ($('wizardOpen')) $('wizardOpen').onclick = function () { App.openWizard(1); };
    if ($('wizardClose')) $('wizardClose').onclick = function () { $('wizard').hidden = true; };
    if ($('wizardPrev')) $('wizardPrev').onclick = function () { App.wizardBack(); };
    if ($('wizardNext')) $('wizardNext').onclick = function () { App.wizardForward(); };
    if ($('manualOpen')) $('manualOpen').onclick = function () { App.openManual(); };
    if ($('manualClose')) $('manualClose').onclick = function () { App.closeManual(); };
    if ($('testAll')) $('testAll').onclick = function () { App.runTests($('testAll')); };
    if ($('diagRefresh')) $('diagRefresh').onclick = function () { App.renderDiagnostics(); };
    if ($('simRefresh')) $('simRefresh').onclick = function () { App.renderSimulations(); };
    App.bindJournal();
    App.bindSetup();
    $('wizard').addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && event.target.tagName === 'INPUT') { event.preventDefault(); App.wizardForward(); }
    });
  };
})();
