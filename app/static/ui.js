/* Main dashboard behaviour: polling, ranking with hysteresis, filters, theme and help. */
(function () {
  'use strict';

  const $ = id => document.getElementById(id);
  const App = window.App = {
    state: {
      data: null, ui: null, settings: null, filters: {}, order: [], prevProfit: new Map(),
      hover: false, freeze: false, paused: false, timer: null, countdownTimer: null,
      activeTab: 'opportunities', drawerKey: null, drawerTab: 'breakdown', drawer: null,
      wizardStep: 1, wizardDraft: null, loading: true, sounds: {}, audio: null,
      lastRender: 0, thresholdFired: {}, rowEls: new Map(), initialized: false,
      returnFocus: {}, messageDismissed: null, wizardBusy: false,
    },
  };

  const HELP = {
    maker: 'میکر یعنی سفارش شما در دفتر سفارش می‌نشیند و منتظر می‌ماند. کارمزدش کمتر است ولی ممکن است پر نشود.',
    taker: 'تیکر یعنی سفارش شما فوراً با بهترین سفارش موجود پر می‌شود. کارمزدش بیشتر است ولی سرعت دارد.',
    slippage: 'لغزش یعنی قیمت با بزرگ‌تر شدن حجم معامله بدتر می‌شود؛ برنامه با راه رفتن روی عمق دفتر سفارش آن را حساب می‌کند.',
    margin: 'حاشیه ایمنی درصدی است که سود باید از آن بیشتر باشد تا «ارزشش رو داره» حساب شود؛ برای پوشش حرکت قیمت در زمان انتقال.',
    rebalance: 'بازتوازن یعنی برگرداندن موجودی به صرافی مبدأ. در حالت «موجودی از پیش» هزینه‌اش جدا و سرشکن هر معامله نمایش داده می‌شود.',
    gross: 'اختلاف خام فقط قیمت خرید و فروش را مقایسه می‌کند، بدون کارمزد و بدون برداشت. سود خالص همه کارمزدها را کم می‌کند.',
    prefunded: 'موجودی از پیش یعنی در هر دو صرافی از قبل موجودی دارید و لازم نیست هر بار انتقال بزنید؛ فقط کارمزد معامله و لغزش می‌ماند.',
    capital: 'بیشترین سرمایه سودده بزرگ‌ترین مبلغی است که در عمق فعلی بازار هنوز سود می‌دهد.',
    breakeven: 'سرمایه سربه‌سر کوچک‌ترین مبلغی است که با آن سود صفر می‌شود؛ کمتر از آن زیان است.',
    depth: 'دفتر سفارش فهرست سفارش‌های خرید و فروش است. بدون آن، قیمت‌های سرِ دفتر فقط برای مقایسه تقریبی کافی‌اند.',
    conversion: 'برای مسیرهای تومانی، تومان باید به تتر تبدیل شود. نرخ و منبع آن (کدام صرافی، خرید یا فروش، چه زمانی) نمایش داده می‌شود.',
    hysteresis: 'برای اینکه فهرست با هر تغییر کوچک نپرد، جابه‌جایی کمتر از حد تعیین‌شده نادیده گرفته می‌شود.',
    clock: 'اگر ساعت ویندوز با ساعت صرافی اختلاف زیاد داشته باشد، قانون «داده قدیمی» نوبیتکس داده سالم را رد می‌کند.',
  };

  const TERMS = [
    ['maker', 'میکر'], ['taker', 'تیکر'], ['slippage', 'لغزش و عمق'],
    ['margin', 'حاشیه ایمنی'], ['rebalance', 'بازتوازن'], ['gross', 'خام و خالص'],
    ['prefunded', 'موجودی از پیش'], ['capital', 'بیشترین سرمایه سودده'],
    ['breakeven', 'سرمایه سربه‌سر'], ['depth', 'دفتر سفارش'],
    ['conversion', 'تبدیل تومان/تتر'], ['hysteresis', 'قفل ترتیب'],
    ['clock', 'اختلاف ساعت'],
  ];

  const VERDICT_TEXT = { worth: 'ارزشش رو داره', borderline: 'مرزی', no: 'فعلاً نه', unknown: 'داده کافی نیست' };
  const VERDICT_ICON = { worth: '✔', borderline: '≈', no: '✕', unknown: '؟' };
  const STATUS_TEXT = {
    ok: 'آماده', stale: 'داده قدیمی', 'depth needed': 'نیاز به عمق', error: 'خطا',
    'fee unknown': 'کارمزد نامعلوم', 'minimum unknown': 'حداقل برداشت نامعلوم',
    'network unknown': 'شبکه نامعلوم', 'no common network': 'شبکه مشترک ندارد',
    'insufficient depth': 'عمق ناکافی',
  };
  const EXCHANGE = { wallex: 'والکس', nobitex: 'نوبیتکس', bitunix: 'بیت‌یونیکس' };

  App.$ = $;
  App.HELP = HELP;
  App.EXCHANGE = EXCHANGE;
  App.VERDICT_TEXT = VERDICT_TEXT;

  // ------------------------------------------------------------------ helpers
  App.esc = value => String(value == null ? '' : value).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  App.toFa = text => String(text).replace(/[0-9]/g, d => '۰۱۲۳۴۵۶۷۸۹'[d]);

  App.fmt = function (value, digits) {
    digits = digits == null ? 0 : digits;
    if (value == null || value === '' || !Number.isFinite(Number(value))) return '—';
    const text = Number(value).toLocaleString('en-US', {
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    });
    return App.state.ui && App.state.ui.digits === 'en' ? text : App.toFa(text);
  };

  App.fmtPct = value => value == null || !Number.isFinite(Number(value)) ? '—' : App.fmt(value, 2) + '٪';

  App.fmtTime = function (epoch) {
    if (!epoch) return '—';
    try {
      return new Date(epoch * 1000).toLocaleTimeString('fa-IR');
    } catch (error) { return '—'; }
  };

  App.ageText = function (seconds) {
    if (seconds == null || !Number.isFinite(Number(seconds))) return '—';
    const value = Math.max(0, Number(seconds));
    if (value < 60) return App.fmt(Math.round(value)) + ' ثانیه';
    if (value < 3600) return App.fmt(Math.round(value / 60)) + ' دقیقه';
    return App.fmt(value / 3600, 1) + ' ساعت';
  };

  // Persian fallbacks for failures whose body is not our JSON envelope (429, 500, a dead
  // server, a timeout). Without them the banner showed English text such as "Failed to fetch".
  const HTTP_TEXT = {
    0: 'اتصال به سرور برقرار نشد؛ مطمئن شوید برنامه هنوز باز است.',
    400: 'درخواست نامعتبر بود؛ ورودی‌ها را بررسی کنید.',
    403: 'این درخواست مجاز نیست.',
    404: 'این بخش پیدا نشد؛ صفحه را دوباره بارگذاری کنید.',
    409: 'این عملیات با وضعیت فعلی سازگار نیست.',
    429: 'درخواست‌های زیادی فرستاده شد؛ چند لحظه صبر کنید.',
    500: 'خطای داخلی سرور؛ دوباره تلاش کنید.',
    502: 'سرور پاسخ درست نداد؛ دوباره تلاش کنید.',
    503: 'سرویس موقتاً در دسترس نیست؛ چند لحظه بعد دوباره تلاش کنید.',
    504: 'پاسخ سرور دیر رسید؛ دوباره تلاش کنید.',
  };
  App.HTTP_TEXT = HTTP_TEXT;
  App.API_TIMEOUT_MS = 20000;

  // `errors` arrives either as text or as {exchange: text}; printing the object showed
  // "[object Object]" where the user needed the reason.
  App.errorSummary = function (errors) {
    if (!errors) return '';
    if (typeof errors === 'string') return errors.trim();
    const parts = [];
    if (Array.isArray(errors)) {
      errors.forEach(function (item) {
        const text = App.errorSummary(item);
        if (text) parts.push(text);
      });
      return parts.join('، ');
    }
    if (typeof errors !== 'object') return String(errors);
    Object.keys(errors).forEach(function (key) {
      const value = errors[key];
      const text = typeof value === 'string' ? value
        : (value && (value.message || value.error)) || '';
      if (text) parts.push(App.exchangeLabel(key) + ': ' + text);
    });
    return parts.join('، ');
  };

  App.api = async function (url, options) {
    const request = Object.assign({}, options || {});
    let timer = null;
    if (!request.signal && typeof AbortController === 'function') {
      const controller = new AbortController();
      request.signal = controller.signal;
      timer = setTimeout(() => controller.abort(), App.API_TIMEOUT_MS);
    }
    const done = () => { if (timer) { clearTimeout(timer); timer = null; } };
    let response;
    try {
      response = await fetch(url, request);
    } catch (error) {
      done();
      throw new Error(error && error.name === 'AbortError'
        ? 'پاسخ سرور دیر رسید؛ دوباره تلاش کنید.' : HTTP_TEXT[0]);
    }
    done();
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (error) { data = null; }
    if (!response.ok) {
      const detail = data && (data.detail || data.message) ? (data.detail || data.message) : '';
      const message = typeof detail === 'string' && detail.trim() ? detail
        : (HTTP_TEXT[response.status] || ('خطا در ارتباط با سرور (' + response.status + ')'));
      throw new Error(message);
    }
    if (text && data === null) throw new Error('پاسخ سرور قابل خواندن نبود؛ دوباره تلاش کنید.');
    return data;
  };

  App.put = body => ({ method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  App.post = body => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  // A dismissed error comes back when the text changes or after this delay, so a real
  // problem is never hidden forever but the banner stops covering the page every poll.
  App.MESSAGE_REOPEN_MS = 120000;

  App.message = function (text, isError) {
    const node = $('message');
    if (!node) return;
    const value = text == null ? '' : String(text);
    const target = $('messageText') || node;
    if (!value) {
      node.hidden = true;
      node.className = 'message';
      target.textContent = '';
      App.state.messageDismissed = null;
      return;
    }
    const dismissed = App.state.messageDismissed;
    if (dismissed && dismissed.text === value && Date.now() - dismissed.at < App.MESSAGE_REOPEN_MS) {
      node.hidden = true;
      return;
    }
    if (dismissed && dismissed.text !== value) App.state.messageDismissed = null;
    target.textContent = value;
    node.className = 'message' + (isError ? ' error' : '');
    node.hidden = false;
  };

  App.error = error => App.message('خطا: ' + (error && error.message ? error.message : error), true);

  App.dismissMessage = function () {
    const node = $('message');
    if (!node) return;
    const text = ($('messageText') || node).textContent || '';
    node.hidden = true;
    App.state.messageDismissed = text ? { text: text, at: Date.now() } : null;
  };

  // ---------------------------------------------------------- overlays and focus
  App.showLayer = function (element, focusSelector) {
    if (!element) return;
    const active = document.activeElement;
    if (active && active !== element && !element.contains(active)) {
      App.state.returnFocus[element.id] = active;
    }
    element.hidden = false;
    const preferred = focusSelector ? element.querySelector(focusSelector) : null;
    const target = preferred || element.querySelector(
      'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])');
    if (target && typeof target.focus === 'function') target.focus();
  };

  App.hideLayer = function (element) {
    if (!element || element.hidden) return;
    element.hidden = true;
    const previous = App.state.returnFocus[element.id];
    delete App.state.returnFocus[element.id];
    if (previous && document.contains(previous) && typeof previous.focus === 'function') {
      previous.focus();
    }
  };

  App.isLayerOpen = element => !!element && !element.hidden;

  App.helpIcon = term => '<span class="help" tabindex="0" role="button" data-help="' + term +
    '" aria-label="توضیح ' + App.esc(term) + '" title="' + App.esc(HELP[term] || '') + '">؟</span>';

  App.exchangeLabel = name => EXCHANGE[name] || name || '—';
  App.statusText = status => STATUS_TEXT[status] || status || '—';

  App.verdict = function (row) {
    const verdict = row.verdict && VERDICT_TEXT[row.verdict] ? row.verdict : 'unknown';
    return { key: verdict, text: VERDICT_TEXT[verdict], icon: VERDICT_ICON[verdict] };
  };

  App.flags = function (row) {
    const flags = row.flags || {};
    const labels = [];
    if (flags.gross_only) labels.push('فقط اختلاف خام');
    if (flags.stale) labels.push('داده قدیمی');
    if (flags.prefunded) labels.push('موجودی از پیش');
    if (row.status && row.status !== 'ok') labels.push(App.statusText(row.status));
    return labels;
  };

  App.rowAccent = function (row, maxAbs) {
    const verdict = App.verdict(row).key;
    const ratio = maxAbs ? Math.min(1, Math.abs(Number(row.net_pct) || 0) / maxAbs) : 0;
    const alpha = row.flags && row.flags.gross_only ? 0.05 : 0.08 + ratio * 0.16;
    const colors = { worth: '55, 214, 122', borderline: '243, 201, 105', no: '255, 122, 133', unknown: '143, 163, 178' };
    return 'rgba(' + (colors[verdict] || colors.unknown) + ',' + alpha.toFixed(3) + ')';
  };

  App.barColor = function (row) {
    const verdict = App.verdict(row).key;
    return verdict === 'worth' ? 'var(--green)' : verdict === 'borderline' ? 'var(--yellow)'
      : verdict === 'no' ? 'var(--red)' : 'var(--gray)';
  };

  // ------------------------------------------------------------------ ui state
  App.saveUi = async function (patch) {
    const values = Object.assign({}, App.state.ui || {}, patch);
    App.state.ui = await App.api('/api/ui', App.put({ values: patch }));
    App.applyUi();
    return App.state.ui;
  };

  App.applyUi = function () {
    const ui = App.state.ui || {};
    const root = document.documentElement;
    root.dataset.theme = ui.theme || 'system';
    const sizes = { small: '16px', medium: '17px', large: '19px' };
    root.style.setProperty('--font-base', sizes[ui.font_scale] || sizes.medium);
    if ($('fontScale')) $('fontScale').value = ui.font_scale || 'medium';
    if ($('digits')) $('digits').value = ui.digits || 'fa';
    if ($('themeToggle')) {
      const names = { system: 'خودکار', light: 'روشن', dark: 'تیره' };
      $('themeToggle').textContent = 'پوسته: ' + (names[ui.theme] || names.system);
    }
    App.setView(ui.view || 'simple', false);
    App.state.freeze = !!ui.freeze_sort;
    if ($('freezeButton')) {
      $('freezeButton').setAttribute('aria-pressed', String(App.state.freeze));
      $('freezeButton').textContent = App.state.freeze ? 'ترتیب قفل است ❄' : 'قفل ترتیب ❄';
    }
    App.renderColumnsChooser();
    App.renderGlossary();
    App.renderPresets();
  };

  App.setView = function (view, save) {
    App.state.view = view;
    if ($('viewSimple')) $('viewSimple').setAttribute('aria-pressed', String(view === 'simple'));
    if ($('viewAdvanced')) $('viewAdvanced').setAttribute('aria-pressed', String(view === 'advanced'));
    if (save) App.saveUi({ view: view });
    if (App.state.data) App.renderTable();
  };

  // ------------------------------------------------------------------- summary
  App.renderSummary = function (data) {
    const summary = data.summary || {};
    const conversion = summary.conversion;
    const best = summary.best;
    const rateText = conversion
      ? App.fmt(conversion.bid, 0) + ' تومان'
      : 'نامعلوم';
    const rateSource = conversion
      ? App.exchangeLabel(conversion.exchange) + ' · ' + (conversion.side || '') + ' · ' + App.fmtTime(conversion.timestamp)
      : 'داده تتر/تومان در دسترس نیست';
    const cards = [
      ['فرصت‌های سودده', App.fmt(summary.profitable_count || 0), (summary.usable_count || 0) + ' ردیف قابل محاسبه'],
      ['بهترین فرصت', best ? App.fmtPct(best.net_pct) : '—',
        best ? App.esc(best.coin) + ' · ' + App.esc(best.route_label || '') : 'در این لحظه فرصت سوددهی نیست'],
      ['نرخ تتر / تومان', rateText, rateSource],
      ['وضعیت صرافی‌ها', '', ''],
    ];
    const html = cards.slice(0, 3).map(card =>
      '<article class="card"><h3>' + App.esc(card[0]) + '</h3><div class="big ' +
      (card[0] === 'بهترین فرصت' && best && best.net_pct > 0 ? 'positive' : '') + '">' +
      card[1] + '</div><p class="muted small">' + card[2] + '</p></article>').join('') +
      '<article class="card"><h3>وضعیت صرافی‌ها</h3><div class="chips" id="summaryChips"></div>' +
      '<p class="muted small">برای جزئیات، روی هر چیپ بزنید.</p></article>';
    $('summaryCards').innerHTML = html;
    const chips = $('summaryChips');
    const exchanges = summary.exchanges || {};
    Object.keys(exchanges).forEach(function (name) {
      const info = exchanges[name];
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'chip ' + (info.state || 'unknown');
      button.innerHTML = '<span class="dot ' + (info.state === 'ok' ? 'green' : info.state === 'error' ? 'red' : info.state === 'stale' ? 'yellow' : 'gray') + '"></span>' +
        App.esc(info.label || App.exchangeLabel(name)) + ' · ' + App.esc({ ok: 'سالم', stale: 'قدیمی', error: 'خطا', unknown: 'نامعلوم' }[info.state] || info.state);
      button.onclick = () => App.switchTab('diagnostics');
      chips.appendChild(button);
    });
    if (!Object.keys(exchanges).length) chips.innerHTML = '<span class="muted small">هنوز تست نشده</span>';
    App.state.paused = !!summary.paused;
    App.updatePauseUi();
    App.renderChips();
  };

  App.renderChips = function () {
    const data = App.state.data;
    if (!data) return;
    const status = (data.summary || {}).exchanges || {};
    const container = $('exchangeChips');
    if (!container) return;
    container.innerHTML = '';
    Object.keys(status).forEach(function (name) {
      const info = status[name];
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'chip ' + (info.state || 'unknown');
      chip.setAttribute('aria-label', (info.label || name) + ' ' + (info.state || ''));
      chip.innerHTML = '<span class="dot ' + (info.state === 'ok' ? 'green' : info.state === 'error' ? 'red' : info.state === 'stale' ? 'yellow' : 'gray') + '"></span>' +
        App.esc(info.label || App.exchangeLabel(name));
      chip.onclick = () => App.switchTab('diagnostics');
      container.appendChild(chip);
    });
  };

  // --------------------------------------------------------------------- table
  App.columns = [
    ['gross', 'اختلاف خام'], ['taker', 'تیکر'], ['maker', 'میکر'], ['safety', 'حاشیه ایمنی'],
    ['maxprofit', 'بیشترین سرمایه سودده'], ['bestcapital', 'سرمایه با بیشترین سود'],
    ['breakeven', 'سرمایه سربه‌سر'], ['liquidity', 'ظرفیت'], ['conversion', 'نرخ تبدیل'],
    ['mode', 'حالت و منبع کارمزد'], ['network', 'شبکه'], ['updated', 'به‌روزرسانی'],
    ['fees', 'کارمزدها'], ['verdict', 'حکم'],
  ];

  App.renderColumnsChooser = function () {
    const box = $('columnChooser');
    if (!box) return;
    const ui = App.state.ui || {};
    const selected = Array.isArray(ui.columns) && ui.columns.length
      ? ui.columns : App.columns.map(item => item[0]);
    box.innerHTML = App.columns.map(function (item) {
      const checked = selected.indexOf(item[0]) !== -1 ? 'checked' : '';
      return '<label class="check"><input type="checkbox" data-column="' + item[0] + '" ' + checked + '> ' + item[1] + '</label>';
    }).join('');
    box.querySelectorAll('[data-column]').forEach(function (input) {
      input.onchange = function () {
        const values = Array.from(box.querySelectorAll('[data-column]'))
          .filter(node => node.checked).map(node => node.dataset.column);
        App.saveUi({ columns: values }).then(() => App.renderTable()).catch(App.error);
      };
    });
  };

  App.selectedColumns = function () {
    const ui = App.state.ui || {};
    if (Array.isArray(ui.columns) && ui.columns.length) return ui.columns;
    return App.columns.map(item => item[0]);
  };

  App.readFilters = function () {
    return App.state.filters = {
      search: $('filterSearch').value,
      iran: $('filterIran').value,
      quote: $('filterQuote').value,
      route: $('filterRoute').value,
      mode: $('filterMode').value,
      minProfit: $('filterMinProfit').value,
      minCapacity: $('filterMinCapacity').value,
      hideGross: $('filterHideGross').checked,
      hideStale: $('filterHideStale').checked,
    };
  };

  App.writeFilters = function (filters) {
    const f = filters || {};
    $('filterSearch').value = f.search || '';
    $('filterIran').value = f.iran || '';
    $('filterQuote').value = f.quote || '';
    $('filterRoute').value = f.route || '';
    $('filterMode').value = f.mode || '';
    $('filterMinProfit').value = f.minProfit == null ? '' : f.minProfit;
    $('filterMinCapacity').value = f.minCapacity == null ? '' : f.minCapacity;
    $('filterHideGross').checked = !!f.hideGross;
    $('filterHideStale').checked = !!f.hideStale;
    App.readFilters();
  };

  App.headHtml = function () {
    const simple = App.state.view !== 'advanced';
    const cols = App.selectedColumns();
    const has = name => cols.indexOf(name) !== -1;
    let cells = ['<th scope="col">رتبه</th>', '<th scope="col">ارز</th>', '<th scope="col">مسیر</th>',
      '<th scope="col">سود خالص ' + App.helpIcon('margin') + '</th>',
      '<th scope="col">سود به تومان</th>', '<th scope="col">سود به USDT</th>',
      '<th scope="col">حکم</th>', '<th scope="col">نمودار سود</th>'];
    if (!simple) {
      if (has('gross')) cells.push('<th scope="col">اختلاف خام ' + App.helpIcon('gross') + '</th>');
      if (has('taker')) cells.push('<th scope="col">تیکر ' + App.helpIcon('taker') + '</th>');
      if (has('maker')) cells.push('<th scope="col">میکر (فرضی) ' + App.helpIcon('maker') + '</th>');
      if (has('safety')) cells.push('<th scope="col">حاشیه ایمنی</th>');
      if (has('maxprofit')) cells.push('<th scope="col">بیشترین سرمایه سودده ' + App.helpIcon('capital') + '</th>');
      if (has('bestcapital')) cells.push('<th scope="col">سرمایه با بیشترین سود</th>');
      if (has('breakeven')) cells.push('<th scope="col">سربه‌سر ' + App.helpIcon('breakeven') + '</th>');
      if (has('liquidity')) cells.push('<th scope="col">ظرفیت/نقدشوندگی</th>');
      if (has('conversion')) cells.push('<th scope="col">نرخ تبدیل ' + App.helpIcon('conversion') + '</th>');
      if (has('mode')) cells.push('<th scope="col">حالت و منبع کارمزد</th>');
      if (has('network')) cells.push('<th scope="col">شبکه</th>');
      if (has('updated')) cells.push('<th scope="col">به‌روزرسانی</th>');
      if (has('fees')) cells.push('<th scope="col">کارمزدها</th>');
    }
    return '<tr>' + cells.join('') + '</tr>';
  };

  App.capitalCell = function (row, amount, unit) {
    if (amount == null) return '—';
    const capital = Number(row.capital) || 0;
    const pct = capital ? App.fmt(Math.abs(amount) / capital * 100, 1) + '٪ سرمایه' : '';
    return App.fmt(amount, unit === 'toman' ? 0 : 2) + ' ' + (unit === 'toman' ? 'تومان' : 'USDT') +
      (pct ? '<br><small class="muted">' + pct + '</small>' : '');
  };

  App.rowHtml = function (row, index, maxAbs) {
    const verdict = App.verdict(row);
    const simple = App.state.view !== 'advanced';
    const cols = App.selectedColumns();
    const has = name => cols.indexOf(name) !== -1;
    const pinned = (App.state.ui.pins || []).indexOf(row.coin) !== -1;
    const profit = row.net_pct;
    const pctClass = profit == null ? 'neutral' : profit > 0 ? 'positive' : profit < 0 ? 'negative' : 'neutral';
    const flags = App.flags(row);
    const net = row.net_quote;
    const netToman = row.net_toman;
    const netUsdt = row.net_usdt;
    let cells = [
      '<td class="num">' + App.fmt(index + 1) + '</td>',
      '<td><span class="coin">' + App.esc(row.coin) + '</span> <span class="muted small">' + App.esc(row.quote === 'toman' ? 'تومان' : 'USDT') + '</span>' +
        '<button class="star" type="button" data-pin="' + App.esc(row.coin) + '" aria-label="' + (pinned ? 'حذف از پین' : 'پین کردن') + '" aria-pressed="' + pinned + '">' + (pinned ? '★' : '☆') + '</button>' +
        (flags.length ? '<br><small class="muted">' + App.esc(flags.join(' · ')) + '</small>' : '') + '</td>',
      '<td class="route">' + App.esc(row.route_label || '—') + '<br><small class="muted">' +
        App.esc(row.venue_pair ? row.venue_pair.map(App.exchangeLabel).join(' ← ') : '') + '</small></td>',
      '<td class="num pct ' + pctClass + '">' + (profit == null ? '—' : App.fmt(profit, 3) + '٪') +
        (net != null ? '<br><small class="muted">' + App.fmt(net, 2) + ' ' + (row.quote === 'toman' ? 'تومان' : 'USDT') + '</small>' : '') + '</td>',
      '<td class="num">' + App.capitalCell(row, netToman, 'toman') + '</td>',
      '<td class="num">' + App.capitalCell(row, netUsdt, 'usdt') + '</td>',
      '<td><span class="chip verdict ' + verdict.key + '">' + verdict.icon + ' ' + verdict.text + '</span>' +
        (row.error ? '<br><small class="muted">' + App.esc(row.error) + '</small>' : '') + '</td>',
      '<td class="bars"><div class="bar-track" role="img" aria-label="نسبت سود ' + App.esc(profit == null ? 'نامعلوم' : profit) + ' درصد">' +
        '<div class="bar-fill" style="width:' + (Sort.barPercent(profit, maxAbs)).toFixed(1) + '%;background:' + App.barColor(row) + '"></div></div></td>',
    ];
    if (!simple) {
      if (has('gross')) cells.push('<td class="num">' + App.fmtPct(row.gross_pct) + '</td>');
      if (has('taker')) cells.push('<td class="num">' + App.fmtPct(row.taker_pct) + '</td>');
      if (has('maker')) cells.push('<td class="num">' + App.fmtPct(row.maker_pct) + '</td>');
      if (has('safety')) cells.push('<td class="num">' + (row.safety_status === 'below safety margin' ? '<span class="chip verdict borderline">≈ مرزی</span>' : row.safety_status === 'profitable' ? '<span class="chip verdict worth">✔ بالای حاشیه</span>' : row.safety_status === 'unprofitable' ? '<span class="chip verdict no">✕ زیان</span>' : '—') + '</td>');
      if (has('maxprofit')) cells.push('<td class="num">' + (row.limited_by_visible_depth ? '<small class="muted">محدود به عمق قابل مشاهده</small>' : App.fmt(row.max_profitable_capital, 2)) + '</td>');
      if (has('bestcapital')) cells.push('<td class="num">' + App.fmt(row.profit_maximizing_capital, 2) + '</td>');
      if (has('breakeven')) cells.push('<td class="num">' + App.fmt(row.breakeven_capital, 2) + '</td>');
      if (has('liquidity')) cells.push('<td class="num">' + App.fmt(row.liquidity != null ? row.liquidity : row.max_profitable_capital, 0) + '</td>');
      if (has('conversion')) cells.push('<td class="num">' + App.fmt(row.local_rate || (row.conversion && row.conversion.rate), 0) + '<br><small class="muted">' + App.esc(row.conversion ? App.exchangeLabel(row.conversion.exchange) + ' · ' + (row.conversion.side === 'ask' ? 'خرید' : 'فروش') : '—') + '</small></td>');
      if (has('mode')) cells.push('<td class="num">' + (row.trading_mode === 'prefunded' ? 'موجودی از پیش' : 'انتقال') + '<br><small class="muted">' + App.esc(Object.keys(row.fee_sources || {}).map(name => App.exchangeLabel(name) + ': ' + (row.fee_sources[name] === 'global' ? 'سراسری' : 'سطح')).join(' / ')) + '</small></td>');
      if (has('network')) cells.push('<td class="num">' + App.esc(row.network || '—') + '</td>');
      if (has('updated')) cells.push('<td class="num">' + App.ageText(row.age) + '<br><small class="muted">' + App.fmtTime(row.updated_at) + '</small></td>');
      if (has('fees')) cells.push('<td class="num small">' + (row.transfer_time && row.transfer_time.minutes != null ? 'انتقال: ' + App.fmt(row.transfer_time.minutes, 1) + ' دقیقه' + (row.transfer_time.uses_default ? ' (پیش‌فرض)' : '') : 'زمان انتقال نامعلوم') + '</td>');
    }
    const style = '--row-bg:' + App.rowAccent(row, maxAbs);
    return '<tr class="row-open" data-key="' + App.esc(row.key) + '" tabindex="0" style="' + style + '">' + cells.join('') + '</tr>';
  };

  App.renderTable = function (animate) {
    const data = App.state.data;
    if (!data) return;
    const tbody = $('rows');
    const head = $('tableHead');
    head.innerHTML = App.headHtml();
    const filters = App.readFilters();
    const rows = Sort.applyFilters(data.rows || [], filters);
    const maxAbs = rows.reduce(function (max, row) {
      const value = Math.abs(Number(row.net_pct));
      return Number.isFinite(value) ? Math.max(max, value) : max;
    }, 0);
    // Freeze means "do not reorder": an infinite hysteresis gap keeps the previous order.
    const gap = App.state.freeze ? Infinity : App.hysteresis();
    let ordered = Sort.orderRows(rows, App.state.order, gap);
    App.state.order = ordered;
    const byKey = new Map(rows.map(row => [row.key, row]));
    const list = ordered.map(key => byKey.get(key)).filter(Boolean);
    const focusedKey = App.focusedRowKey();
    const wasProfit = App.state.prevProfit;
    const flashed = new Set(Sort.newlyProfitable(list, wasProfit));
    $('loadingState').hidden = !App.state.loading;
    $('emptyState').hidden = list.length > 0;
    if (!list.length) {
      $('emptyState').textContent = App.state.loading ? 'در حال دریافت قیمت‌ها…'
        : (data.errors ? 'دریافت داده ناموفق بود: ' + App.errorSummary(data.errors)
          : 'با این فیلترها ردیفی پیدا نشد. فیلترها را ساده‌تر کنید یا «به‌روزرسانی الان» را بزنید.');
    }
    if (!animate || !tbody.children.length || App.state.freeze || App.isHovering()) {
      tbody.innerHTML = list.map((row, index) => App.rowHtml(row, index, maxAbs)).join('');
      App.bindRows();
      App.restoreRowFocus(focusedKey);
    } else {
      App.animateTo(list, maxAbs);
    }
    list.forEach(function (row, index) {
      if (flashed.has(row.key)) {
        const node = tbody.querySelector('[data-key="' + cssEscape(row.key) + '"]');
        if (node) { node.classList.add('flash'); setTimeout(() => node.classList.remove('flash'), 2400); }
      }
    });
    if (flashed.size) {
      App.message('فرصت جدید سودده پیدا شد: ' + Array.from(flashed).map(key => (byKey.get(key) || {}).coin).filter(Boolean).join('، '));
      App.alert(Array.from(flashed).map(key => byKey.get(key)).filter(Boolean));
    }
    App.state.prevProfit = new Map(list.map(row => [row.key, row.net_quote]));
    App.state.loading = false;
  };

  App.hysteresis = function () {
    const value = App.state.data && App.state.data.scanner ? App.state.data.scanner.sort_hysteresis_pct : 0.05;
    return Number.isFinite(Number(value)) ? Number(value) : 0.05;
  };

  function cssEscape(value) {
    return String(value).replace(/["\\]/g, '\\$&');
  }
  App.cssEscape = cssEscape;

  // Hovering pauses the FLIP animation. The flag can stick after the table body is
  // replaced under the pointer, so the live :hover state wins whenever it is available.
  App.isHovering = function () {
    const tbody = $('rows');
    try {
      if (tbody && typeof tbody.matches === 'function' && tbody.matches(':hover')) return true;
    } catch (error) { /* jsdom and old browsers */ }
    return !!App.state.hover;
  };

  App.focusedRowKey = function () {
    const active = document.activeElement;
    if (!active || !active.closest) return null;
    const row = active.closest('#rows [data-key]');
    return row ? row.dataset.key : null;
  };

  App.restoreRowFocus = function (key) {
    if (!key) return;
    const tbody = $('rows');
    const node = tbody && tbody.querySelector('[data-key="' + cssEscape(key) + '"]');
    if (node && typeof node.focus === 'function') node.focus();
  };

  App.animateTo = function (list, maxAbs) {
    const tbody = $('rows');
    const before = new Map();
    Array.from(tbody.children).forEach(function (node) {
      before.set(node.dataset.key, node.getBoundingClientRect().top);
    });
    const existing = new Map(Array.from(tbody.children).map(node => [node.dataset.key, node]));
    const fragment = document.createDocumentFragment();
    list.forEach(function (row, index) {
      const node = existing.get(row.key) || document.createElement('tr');
      node.className = 'row-open';
      node.dataset.key = row.key;
      node.setAttribute('tabindex', '0');
      node.setAttribute('style', '--row-bg:' + App.rowAccent(row, maxAbs));
      const holder = document.createElement('tbody');
      holder.innerHTML = App.rowHtml(row, index, maxAbs);
      const fresh = holder.firstElementChild;
      node.innerHTML = fresh.innerHTML;
      fragment.appendChild(node);
    });
    tbody.innerHTML = '';
    tbody.appendChild(fragment);
    Array.from(tbody.children).forEach(function (node) {
      const start = before.get(node.dataset.key);
      if (start == null || typeof node.getBoundingClientRect !== 'function') return;
      const delta = start - node.getBoundingClientRect().top;
      if (!delta) return;
      node.style.transition = 'none';
      node.style.transform = 'translateY(' + delta.toFixed(1) + 'px)';
      requestAnimationFrame(function () {
        node.style.transition = 'transform .35s ease';
        node.style.transform = '';
      });
    });
    App.bindRows();
  };

  App.bindRows = function () {
    const tbody = $('rows');
    tbody.querySelectorAll('[data-pin]').forEach(function (button) {
      button.onclick = function (event) {
        event.stopPropagation();
        App.togglePin(button.dataset.pin);
      };
    });
    tbody.querySelectorAll('tr[data-key]').forEach(function (node) {
      node.onclick = function () { App.openDrawer(node.dataset.key); };
      node.onkeydown = function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          App.openDrawer(node.dataset.key);
        }
      };
    });
  };

  App.togglePin = function (coin) {
    const pins = (App.state.ui.pins || []).slice();
    const index = pins.indexOf(coin);
    if (index === -1) pins.push(coin); else pins.splice(index, 1);
    App.saveUi({ pins: pins }).then(() => {
      App.renderTable(false);
      App.load(true);
    }).catch(App.error);
  };

  App.alert = function (rows) {
    const ui = App.state.ui || {};
    const cfg = (App.state.data && App.state.data.scanner) || {};
    if (!ui.sound && !ui.desktop) return;
    const watchlist = (cfg.watchlist || []).map(value => String(value).toUpperCase());
    const threshold = Math.max(Number(cfg.threshold) || 0, 0);
    const hits = rows.filter(function (row) {
      if (!watchlist.length) return false;
      if (watchlist.indexOf(String(row.coin).toUpperCase()) === -1) return false;
      return Number(row.net_pct) > threshold;
    });
    if (!hits.length) return;
    hits.forEach(function (row) {
      if (ui.sound) App.beep();
      if (ui.desktop && 'Notification' in window) {
        try {
          if (Notification.permission === 'granted') {
            new Notification('فرصت ' + row.coin, { body: 'سود خالص از آستانه گذشت. وضعیت شبکه را بررسی کنید.' });
          }
        } catch (error) { /* notifications are optional */ }
      }
    });
  };

  App.beep = function () {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      App.state.audio = App.state.audio || new Ctx();
      const context = App.state.audio;
      if (context.state === 'suspended') context.resume();
      const osc = context.createOscillator();
      const gain = context.createGain();
      gain.gain.value = 0.08;
      osc.frequency.value = 760;
      osc.connect(gain);
      gain.connect(context.destination);
      osc.start();
      osc.stop(context.currentTime + 0.25);
    } catch (error) { /* audio is optional */ }
  };

  // ---------------------------------------------------------------- capital
  const CAPITAL_PRESETS = [
    { label: '۱۰ میلیون تومان', value: 10e6, currency: 'toman' },
    { label: '۵۰ میلیون تومان', value: 50e6, currency: 'toman' },
    { label: '۱۰۰ میلیون تومان', value: 100e6, currency: 'toman' },
    { label: '۵۰۰ میلیون تومان', value: 500e6, currency: 'toman' },
    { label: '۱۰۰ USDT', value: 100, currency: 'USDT' },
    { label: '۵۰۰ USDT', value: 500, currency: 'USDT' },
  ];

  App.renderCapital = function () {
    const cfg = (App.state.data && App.state.data.scanner) || {};
    const box = $('capitalPresets');
    if (!box) return;
    box.innerHTML = '';
    CAPITAL_PRESETS.forEach(function (preset) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = preset.label;
      button.onclick = () => App.applyCapital(preset.value, preset.currency);
      box.appendChild(button);
    });
    const currency = $('capitalCurrency').value || 'USDT';
    const value = currency === 'toman' ? cfg.capital_toman : cfg.capital_usdt;
    if (document.activeElement !== $('capitalInput')) {
      $('capitalInput').value = value == null ? '' : (currency === 'toman' ? App.fmt(value, 0) : App.fmt(value, 2));
    }
    const rate = App.state.data && App.state.data.summary && App.state.data.summary.conversion;
    $('capitalHint').textContent = rate
      ? 'نرخ تبدیل: ' + App.fmt(rate.bid, 0) + ' تومان برای هر تتر (منبع: ' + App.exchangeLabel(rate.exchange) + ')'
      : 'نرخ تتر/تومان در دسترس نیست؛ معادل‌سازی انجام نمی‌شود.';
  };

  App.applyCapital = async function (value, currency) {
    try {
      const cfg = Object.assign({}, App.state.data.scanner);
      const rate = (App.state.data.summary.conversion || {}).bid;
      if (currency === 'toman') {
        cfg.capital_toman = value;
        if (rate) cfg.capital_usdt = Math.round(value / rate * 100) / 100;
      } else {
        cfg.capital_usdt = value;
        if (rate) cfg.capital_toman = Math.round(value * rate);
      }
      const saved = await App.api('/api/scanner/settings', App.put(cfg));
      App.state.data.scanner = saved;
      App.message('سرمایه به‌روزرسانی شد: ' + App.fmt(cfg.capital_usdt, 2) + ' USDT و ' +
        App.fmt(cfg.capital_toman, 0) + ' تومان.');
      App.renderCapital();
      await App.load(true);
    } catch (error) { App.error(error); }
  };

  App.submitCapitalText = async function () {
    const text = $('capitalInput').value.trim();
    if (!text) return;
    try {
      const parsed = await App.api('/api/amount?text=' + encodeURIComponent(text));
      if (!parsed.ok) { App.message(parsed.error, true); return; }
      const currency = parsed.currency || $('capitalCurrency').value || 'USDT';
      $('capitalCurrency').value = currency === 'toman' ? 'toman' : 'USDT';
      await App.applyCapital(parsed.value, currency);
    } catch (error) { App.error(error); }
  };

  // ------------------------------------------------------------------ polling
  App.load = async function (showLoading) {
    if (showLoading && !App.state.data) {
      App.state.loading = true;
      if ($('loadingState')) $('loadingState').hidden = false;
    }
    try {
      const [data, wizard] = await Promise.all([App.api('/api/overview'), App.api('/api/wizard')]);
      App.state.data = data;
      App.state.settings = data.settings;
      if (!App.state.initialized) {
        App.state.ui = data.ui;
        App.applyUi();
        App.writeFilters(data.ui.last_filter || {});
        App.state.initialized = true;
      }
      App.renderSummary(data);
      App.renderTable(true);
      App.renderCapital();
      App.renderWizardBanner(wizard);
      App.message(data.errors ? 'آخرین دریافت بازار با خطا مواجه شد: ' +
        App.errorSummary(data.errors) : '');
      App.schedulePolling();
    } catch (error) {
      App.error(error);
      if ($('emptyState')) {
        $('emptyState').hidden = false;
        $('emptyState').textContent = 'ارتباط با سرور برنامه قطع است. صفحه را دوباره باز کنید.';
      }
      App.schedulePolling(true);
    }
  };

  App.schedulePolling = function (failed) {
    clearTimeout(App.state.timer);
    if (App.state.paused) return;
    const interval = (App.state.data && App.state.data.scanner && App.state.data.scanner.interval) || 10;
    App.state.timer = setTimeout(function () { App.load(false); }, Math.max(3, interval) * 1000);
    if ($('countdown')) {
      clearInterval(App.state.countdownTimer);
      let remaining = Math.max(1, interval);
      App.state.countdownTimer = setInterval(function () {
        remaining = Math.max(0, remaining - 1);
        $('countdown').textContent = App.state.paused ? 'متوقف' : App.fmt(remaining) + ' ثانیه';
      }, 1000);
      $('countdown').textContent = App.fmt(remaining) + ' ثانیه';
    }
  };

  App.updatePauseUi = function () {
    const button = $('pauseButton');
    if (button) {
      button.textContent = App.state.paused ? 'ادامه به‌روزرسانی ▶' : 'توقف به‌روزرسانی ⏸';
      button.setAttribute('aria-pressed', String(App.state.paused));
    }
    if ($('pauseChip')) $('pauseChip').hidden = !App.state.paused;
  };

  App.togglePause = async function () {
    try {
      const paused = !App.state.paused;
      await App.api('/api/overview/pause', App.post({ paused: paused }));
      App.state.paused = paused;
      App.updatePauseUi();
      if (paused) {
        clearTimeout(App.state.timer);
        clearInterval(App.state.countdownTimer);
        App.message('به‌روزرسانی متوقف شد. برای ادامه دوباره دکمه توقف را بزنید.');
      } else {
        App.message('به‌روزرسانی ادامه یافت.');
        App.load(false);
      }
    } catch (error) { App.error(error); }
  };

  App.refreshNow = async function () {
    try {
      App.message('در حال به‌روزرسانی…');
      await App.api('/api/overview/refresh', { method: 'POST' });
      await App.load(false);
      App.message('به‌روزرسانی انجام شد · ' + App.fmtTime(Date.now() / 1000));
    } catch (error) { App.error(error); }
  };

  // -------------------------------------------------------------------- tabs
  App.switchTab = function (name) {
    App.state.activeTab = name;
    ['opportunities', 'simulations', 'journal', 'diagnostics', 'setup'].forEach(function (tab) {
      const section = $('tab-' + tab);
      if (section) section.hidden = tab !== name;
    });
    if ($('menuPanel')) $('menuPanel').hidden = true;
    if (App.state.data) delete App.state.data; // force reload without re-initialising UI
    App.state.data = null;
    App.state.initialized = true;
    if (name === 'diagnostics' && App.renderDiagnostics) App.renderDiagnostics();
    if (name === 'simulations' && App.renderSimulations) App.renderSimulations();
    if (name === 'journal' && App.renderJournal) App.renderJournal();
    if (name === 'setup' && App.renderSetup) App.renderSetup();
    App.load(false);
  };

  // ------------------------------------------------------------------ presets
  App.renderPresets = function () {
    const select = $('presetSelect');
    if (!select) return;
    const presets = (App.state.ui && App.state.ui.presets) || [];
    select.innerHTML = '<option value="">— انتخاب —</option>' + presets.map(function (preset, index) {
      return '<option value="' + index + '">' + App.esc(preset.name) + '</option>';
    }).join('');
  };

  App.savePreset = async function () {
    const name = window.prompt('نام این فیلتر را بنویسید (مثلاً «فقط سودده»)');
    if (!name) return;
    const presets = ((App.state.ui && App.state.ui.presets) || []).slice();
    presets.push({ name: String(name).slice(0, 40), filters: App.readFilters() });
    try {
      await App.saveUi({ presets: presets.slice(-30) });
      App.message('فیلتر ذخیره شد.');
    } catch (error) { App.error(error); }
  };

  App.deletePreset = async function () {
    const index = Number($('presetSelect').value);
    const presets = ((App.state.ui && App.state.ui.presets) || []).slice();
    if (!presets[index]) return;
    presets.splice(index, 1);
    try {
      await App.saveUi({ presets: presets });
      App.message('فیلتر حذف شد.');
    } catch (error) { App.error(error); }
  };

  // -------------------------------------------------------------------- help
  App.renderGlossary = function () {
    const box = $('glossary');
    if (!box || box.children.length) return;
    box.innerHTML = TERMS.map(function (item) {
      return '<div class="help-term"><strong>' + item[1] + '</strong><span class="muted small">' +
        App.esc(HELP[item[0]]) + '</span></div>';
    }).join('');
  };

  App.showHelp = function (target) {
    const term = target.dataset.help;
    const pop = $('helpPop');
    if (!pop || !term) return;
    pop.textContent = HELP[term] || '';
    pop.hidden = false;
    const rect = target.getBoundingClientRect();
    const width = Math.min(320, window.innerWidth - 24);
    pop.style.width = width + 'px';
    const left = Math.min(Math.max(12, rect.left - width / 2), window.innerWidth - width - 12);
    pop.style.left = left + 'px';
    pop.style.top = (rect.bottom + 8) + 'px';
  };

  App.hideHelp = function () { if ($('helpPop')) $('helpPop').hidden = true; };

  // -------------------------------------------------------------------- boot
  App.bindGlobal = function () {
    if (App.state.bound) return;
    App.state.bound = true;
    $('menuToggle').onclick = function (event) {
      event.stopPropagation();
      App.toggleMenu();
    };
    if ($('messageClose')) $('messageClose').onclick = App.dismissMessage;
    document.querySelectorAll('[data-tab]').forEach(function (link) {
      link.onclick = function (event) {
        event.preventDefault();
        App.switchTab(link.dataset.tab);
      };
    });
    $('fontScale').onchange = () => App.saveUi({ font_scale: $('fontScale').value });
    $('digits').onchange = () => App.saveUi({ digits: $('digits').value });
    $('themeToggle').onclick = function () {
      const order = ['system', 'dark', 'light'];
      const current = (App.state.ui && App.state.ui.theme) || 'system';
      const next = order[(order.indexOf(current) + 1) % order.length];
      App.saveUi({ theme: next });
    };
    $('viewSimple').onclick = () => App.setView('simple', true);
    $('viewAdvanced').onclick = () => App.setView('advanced', true);
    $('pauseButton').onclick = App.togglePause;
    $('refreshButton').onclick = App.refreshNow;
    $('freezeButton').onclick = function () {
      App.state.freeze = !App.state.freeze;
      App.saveUi({ freeze_sort: App.state.freeze });
      App.renderTable(false);
      App.message(App.state.freeze ? 'ترتیب فهرست قفل شد.' : 'ترتیب فیلتر آزاد شد.');
    };
    $('filters').oninput = function () { App.renderTable(false); };
    $('filters').onchange = function () {
      const filters = App.readFilters();
      App.renderTable(false);
      App.saveUi({ last_filter: filters }).catch(function () { /* preferences are optional */ });
    };
    $('presetSave').onclick = App.savePreset;
    $('presetDelete').onclick = App.deletePreset;
    $('presetSelect').onchange = function () {
      const presets = (App.state.ui && App.state.ui.presets) || [];
      const preset = presets[Number($('presetSelect').value)];
      if (preset) { App.writeFilters(preset.filters); App.renderTable(false); }
    };
    $('capitalInput').onchange = App.submitCapitalText;
    $('capitalInput').onkeydown = function (event) { if (event.key === 'Enter') { event.preventDefault(); App.submitCapitalText(); } };
    $('capitalCurrency').onchange = function () { App.renderCapital(); };
    document.addEventListener('click', function (event) {
      const help = event.target.closest && event.target.closest('.help');
      if (help) { App.showHelp(help); event.preventDefault(); return; }
      if (!event.target.closest || !event.target.closest('.help-pop')) App.hideHelp();
    });
    // mousedown, not click: a row click opens the drawer after this event has passed,
    // so the freshly opened drawer (or menu) can never close itself.
    document.addEventListener('mousedown', function (event) {
      if (!event.target.closest || !event.target.closest('#menuPanel, #menuToggle')) App.closeMenu();
      const drawer = $('drawer');
      if (!App.isLayerOpen(drawer) || drawer.contains(event.target)) return;
      if (event.target.closest && event.target.closest('#wizard, #manualDrawer')) return;
      App.closeDrawer();
    });
    window.addEventListener('blur', function () { App.state.hover = false; });
    document.addEventListener('mouseout', function (event) {
      if (!event.relatedTarget) App.state.hover = false;
    });
    document.addEventListener('keydown', function (event) {
      const typing = /INPUT|SELECT|TEXTAREA/.test((event.target.tagName || '').toUpperCase());
      if (event.key === 'Escape') {
        App.hideHelp();
        App.closeMenu();
        if (App.isLayerOpen($('manualDrawer')) && App.closeManual) App.closeManual();
        else if (App.isLayerOpen($('wizard')) && App.closeWizard) App.closeWizard();
        else if (App.isLayerOpen($('drawer'))) App.closeDrawer();
      }
      if ((event.key === '/' || (event.ctrlKey && event.key.toLowerCase() === 'k')) && !typing) {
        event.preventDefault();
        $('filterSearch').focus();
      }
      if (event.key.toLowerCase() === 'f' && !typing && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        $('freezeButton').click();
      }
    });
    const tbody = $('rows');
    tbody.addEventListener('mouseenter', function () { App.state.hover = true; });
    tbody.addEventListener('mouseleave', function () { App.state.hover = false; });
    window.addEventListener('resize', function () { App.hideHelp(); });
  };

  App.toggleMenu = function (open) {
    const panel = $('menuPanel');
    if (!panel) return;
    const next = open == null ? panel.hidden : !!open;
    panel.hidden = !next;
    if ($('menuToggle')) $('menuToggle').setAttribute('aria-expanded', String(next));
  };

  App.closeMenu = function () { if ($('menuPanel') && !$('menuPanel').hidden) App.toggleMenu(false); };

  App.renderWizardBanner = function (wizard) {
    const banner = $('setupBanner');
    if (!banner) return;
    const missing = (wizard && wizard.missing) || [];
    if (!missing.length) {
      banner.hidden = true;
      return;
    }
    const signature = missing.join('|');
    $('setupMissing').textContent = 'موارد لازم: ' + missing.join('، ');
    $('setupBannerAction').onclick = function () { if (App.openWizard) App.openWizard(1); };
    // A dismissed notice stays closed for the same list of missing items, and comes back
    // as soon as the list changes (e.g. one fee fewer or one fee more is still missing).
    const ui = App.state.ui || {};
    const dismissed = ui.setup_banner_dismissed || '';
    if (dismissed === signature) {
      banner.hidden = true;
      return;
    }
    banner.hidden = false;
    if ($('setupBannerClose')) {
      $('setupBannerClose').onclick = function () {
        banner.hidden = true;
        App.saveUi({ setup_banner_dismissed: signature }).catch(function () { /* optional */ });
        App.message('این پیام بسته شد. هر وقت خواستید از دکمه «راه‌اندازی» تنظیمات را کامل کنید.');
      };
    }
  };

  App.init = function () {
    App.bindGlobal();
    App.load(true);
    // Deep link from the home screen's connection indicator: /dashboard#diagnostics
    if (typeof location !== 'undefined' && location.hash === '#diagnostics') {
      setTimeout(function () { App.switchTab('diagnostics'); }, 0);
    }
    fetch('/api/ui').then(response => response.json()).then(function (ui) {

      App.state.ui = ui;
      App.applyUi();
    }).catch(function () { /* defaults are fine */ });
  };
})();
