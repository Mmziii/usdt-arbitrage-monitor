/* Detail drawer: cycle breakdown, trade plan, both order books, history and fee sources. */
(function () {
  'use strict';
  const App = window.App;
  const $ = App.$;

  const DRAWER_TABS = ['breakdown', 'plan', 'books', 'history', 'fees'];

  App.openDrawer = async function (key) {
    const drawer = $('drawer');
    if (!drawer) return;
    App.state.drawerKey = key;
    App.state.drawerTab = 'breakdown';
    drawer.hidden = false;
    $('drawerBody').innerHTML = '<p class="loading">در حال خواندن دفتر سفارش…</p>';
    $('drawerTitle').textContent = 'جزئیات';
    $('drawerSub').textContent = '';
    try {
      const detail = await App.api('/api/overview/detail?key=' + encodeURIComponent(key));
      App.state.drawer = detail;
      App.renderDrawerHead();
      App.renderDrawerTab('breakdown');
      App.markVisible();
      App.load(false);
    } catch (error) {
      $('drawerBody').innerHTML = '<p class="message error">خطا: ' + App.esc(error.message) + '</p>';
      App.error(error);
    }
  };

  App.closeDrawer = function () {
    if ($('drawer')) $('drawer').hidden = true;
    App.state.drawerKey = null;
    App.state.drawer = null;
    App.markVisible();
  };

  App.markVisible = function () {
    const keys = App.state.drawerKey ? [App.state.drawerKey] : [];
    fetch('/api/overview/visible', App.post({ keys: keys })).catch(function () { /* optional */ });
  };

  App.renderDrawerHead = function () {
    const detail = App.state.drawer;
    if (!detail) return;
    const row = detail.row || {};
    $('drawerTitle').textContent = row.coin + ' · ' + (row.quote === 'toman' ? 'بازار تومان' : 'بازار USDT');
    const parts = [row.route_label || ''];
    if (row.venue_pair) parts.push(row.venue_pair.map(App.exchangeLabel).join(' ← '));
    parts.push(row.trading_mode === 'prefunded' ? 'موجودی از پیش' : 'انتقال');
    $('drawerSub').textContent = parts.filter(Boolean).join(' · ');
    $('drawer').querySelectorAll('[data-drawer-tab]').forEach(function (button) {
      button.setAttribute('aria-selected', String(button.dataset.drawerTab === App.state.drawerTab));
      button.onclick = function () { App.renderDrawerTab(button.dataset.drawerTab); };
    });
  };

  App.renderDrawerTab = function (tab) {
    if (DRAWER_TABS.indexOf(tab) === -1) tab = 'breakdown';
    App.state.drawerTab = tab;
    $('drawer').querySelectorAll('[data-drawer-tab]').forEach(function (button) {
      button.setAttribute('aria-selected', String(button.dataset.drawerTab === tab));
    });
    const detail = App.state.drawer;
    const body = $('drawerBody');
    if (!detail) { body.innerHTML = ''; return; }
    if (tab === 'breakdown') body.innerHTML = App.breakdownHtml(detail);
    else if (tab === 'plan') { body.innerHTML = App.planHtml(detail); App.bindPlan(detail); }
    else if (tab === 'books') body.innerHTML = App.booksHtml(detail);
    else if (tab === 'history') { body.innerHTML = '<div id="drawerChart"></div>'; App.drawHistory(detail); }
    else body.innerHTML = App.feesHtml(detail);
    if (tab === 'fees') App.bindNetwork(detail);
  };

  const UNIT = { coin: 'واحد ارز', USDT: 'USDT', toman: 'تومان' };

  App.breakdownHtml = function (detail) {
    const row = detail.row || {};
    const analysis = (row.detail && row.detail.taker) || row.taker || {};
    const plan = detail.plan || {};
    const parts = [];
    if (row.error) parts.push('<p class="message error">' + App.esc(row.error) + '</p>');
    if (analysis.ok) {
      parts.push('<h3>مراحل چرخه با سرمایه فعلی</h3><ol class="steps-list">' +
        (analysis.steps || []).map(function (step) {
          return '<li><span class="stage">' + App.esc(step.label) + '</span><br>' +
            '<span class="num">' + App.fmt(step.value, step.unit === 'coin' ? 6 : 2) + ' ' +
            App.esc(UNIT[step.unit] || step.unit) + '</span></li>';
        }).join('') + '</ol>');
      parts.push('<h3>نتیجه</h3><dl class="kv">' +
        App.kv('سرمایه شروع', App.fmt(analysis.capital, 2) + ' USDT') +
        App.kv('نتیجه نهایی', App.fmt(analysis.final, 2) + ' ' + (row.quote === 'toman' ? 'تومان' : 'USDT')) +
        App.kv('سود خالص', App.fmt(analysis.profit, 2) + ' (' + App.fmtPct(analysis.profit_pct) + ')') +
        App.kv('سود به تومان', App.fmt(row.net_toman, 0) + ' تومان') +
        App.kv('وضعیت', App.VERDICT_TEXT[row.verdict] || '—') +
        App.kv('حاشیه ایمنی', App.fmt(analysis.safety_margin, 2) + '٪') +
        App.kv('میکر (فرضی)', App.fmtPct(row.maker_pct)) +
        App.kv('بیشترین سرمایه سودده', analysis.limited_by_visible_depth ? 'محدود به عمق قابل مشاهده' : App.fmt(analysis.max_profitable_capital, 2)) +
        App.kv('سرمایه با بیشترین سود', App.fmt(analysis.profit_maximizing_capital, 2)) +
        App.kv('سرمایه سربه‌سر', App.fmt(analysis.breakeven_capital, 2)) +
        App.kv('اختلاف خام', App.fmtPct(row.gross_pct)) +
        '</dl>');
      if (analysis.rebalancing) {
        parts.push('<h3>هزینه بازتوازن (جدا از سود)</h3><dl class="kv">' +
          App.kv('هزینه یک نوبت بازتوازن', analysis.rebalancing.total == null ? 'نامعلوم' : App.fmt(analysis.rebalancing.total, 2) + ' USDT') +
          App.kv('سرشکن هر معامله', analysis.rebalancing.per_trade == null ? 'نامعلوم' : App.fmt(analysis.rebalancing.per_trade, 3) + ' USDT') +
          App.kv('سود پس از سرشکن', analysis.rebalancing.profit_after == null ? 'نامعلوم' : App.fmt(analysis.rebalancing.profit_after, 2) + ' USDT') +
          '</dl>' + (analysis.rebalancing.incomplete ? '<p class="muted small">کارمزد برداشت لازم برای محاسبه بازتوازن وارد نشده است؛ صفر فرض نمی‌شود.</p>' : ''));
      }
      const conversion = row.conversion || (row.detail && row.detail.conversion);
      if (conversion) {
        parts.push('<h3>تبدیل تتر/تومان</h3><dl class="kv">' +
          App.kv('نرخ استفاده‌شده', App.fmt(conversion.rate, 0) + ' تومان برای هر تتر') +
          App.kv('منبع', App.exchangeLabel(conversion.exchange) + ' · ' + (conversion.side === 'ask' ? 'خرید (ask)' : 'فروش (bid)')) +
          App.kv('زمان داده', App.fmtTime(conversion.timestamp)) +
          App.kv('نرخ مؤثر با عمق', App.fmt(row.effective_rate || row.detail.effective_rate, 2)) +
          '</dl>');
      }
    } else {
      parts.push('<p class="muted">برای این مسیر، محاسبه کامل ممکن نیست. ' +
        App.esc(analysis.error || 'دفتر سفارش کافی نیست') + '</p>');
      if (row.gross_pct != null) {
        parts.push('<p>اختلاف خام فعلی: <strong>' + App.fmtPct(row.gross_pct) + '</strong> (بدون کارمزد و برداشت؛ سود نیست).</p>');
      }
    }
    const warnings = (plan.warnings || []).slice(0, 3);
    if (warnings.length) {
      parts.push('<div class="muted small">' + warnings.map(text => '• ' + App.esc(text)).join('<br>') + '</div>');
    }
    parts.push('<p class="muted small">داده‌ها تخمینی از دفتر سفارش ' + App.fmtTime(row.updated_at) +
      ' هستند. این برنامه سفارش ثبت نمی‌کند.</p>');
    return parts.join('');
  };

  App.kv = function (key, value) {
    return '<dt>' + App.esc(key) + '</dt><dd>' + value + '</dd>';
  };

  App.planHtml = function (detail) {
    const plan = detail.plan || {};
    const row = detail.row || {};
    const parts = [];
    if (!plan.ok) {
      parts.push('<p class="muted">' + App.esc((plan.warnings || []).join(' ') || 'طرح معامله برای این ردیف آماده نیست.') + '</p>');
    } else {
      parts.push('<h3>گام‌ها</h3><ol class="steps-list">' + plan.steps.map(function (step) {
        return '<li><span class="stage">گام ' + App.fmt(step.n) + ': ' + App.esc(step.title) + '</span>' +
          '<br><span class="num">' + App.fmt(step.amount, step.unit === 'coin' ? 6 : 2) + ' ' +
          App.esc(UNIT[step.unit] || step.unit) + '</span></li>';
      }).join('') + '</ol>');
      if (plan.expected) {
        parts.push('<h3>نتیجه مورد انتظار</h3><dl class="kv">' +
          App.kv('سرمایه', App.fmt(plan.expected.capital, 2) + ' USDT') +
          App.kv('نتیجه', App.fmt(plan.expected.final, 2)) +
          App.kv('سود', App.fmt(plan.expected.profit, 2) + ' (' + App.fmtPct(plan.expected.profit_pct) + ')') +
          App.kv('سود به تومان', App.fmt(plan.expected.profit_toman, 0) + ' تومان') +
          '</dl>');
      }
      parts.push('<h3>چک‌لیست پیش از معامله</h3><ul class="checklist">' + plan.checklist.map(function (item, index) {
        return '<li><input type="checkbox" id="check-' + index + '" aria-label="' + App.esc(item.text) + '">' +
          '<label for="check-' + index + '">' + App.esc(item.text) + '</label></li>';
      }).join('') + '</ul>');
    }
    if ((plan.warnings || []).length) {
      parts.push('<div class="banner warning" style="margin:0">' + plan.warnings.map(text => App.esc(text)).join('<br>') + '</div>');
    }
    if (row.kind === 'classic') {
      parts.push('<p class="muted small">معامله آزمایشی برای مسیرهای بیت‌یونیکس فعال است.</p>');
    } else if (plan.ok) {
      parts.push('<h3>معامله آزمایشی</h3>' +
        '<p class="muted small">قیمت‌ها و نتیجه فعلی ذخیره می‌شود. بعد از زمان انتخاب‌شده، دفتر سفارش دوباره خوانده و نتیجه واقعی ثبت می‌شود. هیچ سفارشی ثبت نمی‌شود.</p>' +
        '<div class="filters"><label>زمان آزمایش<select id="simDelay">' +
        '<option value="">زمان تخمینی انتقال</option><option value="30">۳۰ ثانیه بعد</option>' +
        '<option value="60">۱ دقیقه بعد</option><option value="300">۵ دقیقه بعد</option>' +
        '</select></label><p><button type="button" id="simCreate">ثبت معامله آزمایشی</button></p></div>');
    }
    return parts.join('');
  };

  App.bindPlan = function (detail) {
    const button = $('simCreate');
    if (!button) return;
    button.onclick = async function () {
      try {
        const delay = $('simDelay').value;
        const body = { key: detail.row.key };
        if (delay) body.delay_seconds = Number(delay);
        await App.api('/api/simulations', App.post(body));
        App.message('معامله آزمایشی ثبت شد؛ نتیجه بعد از زمان تعیین‌شده محاسبه می‌شود.');
      } catch (error) { App.error(error); }
    };
  };

  App.booksHtml = function (detail) {
    const books = detail.books || {};
    const keys = Object.keys(books);
    if (!keys.length) {
      return '<p class="muted">دفتر سفارش تازه‌ای در دسترس نیست. «به‌روزرسانی الان» را بزنید تا دوباره خوانده شود.</p>';
    }
    return keys.map(function (key) {
      const book = books[key];
      const [exchange, pair] = key.split(':');
      const [coin, quote] = (pair || '').split('/');
      const label = App.exchangeLabel(exchange) + ' · ' + coin + ' / ' +
        (quote === 'toman' ? 'تومان' : quote);
      const asks = (book.asks || []).slice(0, 8);
      const bids = (book.bids || []).slice(0, 8);
      return '<div class="book-block"><h3>' + App.esc(label) + '</h3>' +
        '<p class="muted small">منبع: ' + App.esc(book.source) + ' · کیفیت: ' +
        App.esc(book.quality === 'depth' ? 'دفتر کامل' : 'فقط بهترین قیمت') +
        ' · زمان داده: ' + App.fmtTime(book.timestamp) +
        (book.timestamp_reliable ? '' : ' (زمان دریافت محلی)') + '</p>' +
        '<div class="book"><div><h4>فروشندگان (ask)</h4><table><thead><tr><th>قیمت</th><th>مقدار</th></tr></thead><tbody>' +
        asks.map(row => '<tr><td>' + App.fmt(row[0], 6) + '</td><td>' + App.fmt(row[1], 6) + '</td></tr>').join('') +
        '</tbody></table></div><div><h4>خریداران (bid)</h4><table><thead><tr><th>قیمت</th><th>مقدار</th></tr></thead><tbody>' +
        bids.map(row => '<tr><td>' + App.fmt(row[0], 6) + '</td><td>' + App.fmt(row[1], 6) + '</td></tr>').join('') +
        '</tbody></table></div></div></div>';
    }).join('');
  };

  App.drawHistory = function (detail) {
    const holder = $('drawerChart');
    if (!holder) return;
    const rows = detail.history || [];
    const width = 960, height = 230, padLeft = 60, padRight = 14, padTop = 14, padBottom = 26;
    if (rows.length < 2) {
      holder.innerHTML = '<p class="empty">برای این بازار هنوز تاریخچه‌ای ثبت نشده است. بعد از چند به‌روزرسانی دوباره نگاه کنید.</p>';
      return;
    }
    const values = rows.flatMap(row => [Number(row.spread_a), Number(row.spread_b)])
      .filter(value => Number.isFinite(value));
    const low = Math.min.apply(null, values.concat([0])) - .1;
    const high = Math.max.apply(null, values.concat([0])) + .1;
    const x = index => padLeft + index * (width - padLeft - padRight) / Math.max(1, rows.length - 1);
    const y = value => padTop + (high - value) * (height - padTop - padBottom) / Math.max(.0001, high - low);
    const grid = [low, (low + high) / 2, high].map(function (value) {
      return '<line x1="' + padLeft + '" x2="' + (width - padRight) + '" y1="' + y(value) + '" y2="' + y(value) + '" stroke="var(--border)"/>' +
        '<text x="' + (padLeft - 8) + '" y="' + (y(value) + 4) + '" fill="var(--muted)" text-anchor="end" font-size="11">' + App.toFa(value.toFixed(2)) + '٪</text>';
    }).join('');
    const series = [['spread_a', 'var(--green)', 'والکس ← نوبیتکس'], ['spread_b', 'var(--link)', 'نوبیتکس ← والکس']]
      .map(function (item) {
        const points = rows.map((row, index) =>
          x(index) + ',' + y(Number(row[item[0]]))).join(' ');
        return '<polyline fill="none" stroke="' + item[1] + '" stroke-width="2" points="' + points + '"/>';
      }).join('');
    holder.innerHTML = '<svg class="chart" viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="نمودار اختلاف قیمت بین دو صرافی ایرانی">' +
      grid + series + '</svg><p class="muted small">اختلاف خام بین دو صرافی ایرانی در همین ارز (پیش از کارمزد). سبز: والکس ← نوبیتکس، آبی: نوبیتکس ← والکس.</p>';
  };

  App.feesHtml = function (detail) {
    const row = detail.row || {};
    const sources = row.fee_sources || {};
    const parts = [];
    parts.push('<h3>منبع کارمزد معاملاتی</h3><dl class="kv">' +
      Object.keys(sources).map(name => App.kv(App.exchangeLabel(name.split(':')[0]) + (name.indexOf(':conversion') !== -1 ? ' (تبدیل)' : ''),
        sources[name] === 'global' ? 'کارمزد سراسری' : 'سطح: ' + App.esc(String(sources[name]).replace('tier:', '')))).join('') +
      '</dl>');
    const conversion = row.conversion;
    if (conversion) {
      parts.push('<h3>نرخ تبدیل</h3><dl class="kv">' +
        App.kv('نرخ', App.fmt(conversion.rate, 0) + ' تومان/تتر') +
        App.kv('صرافی منبع', App.exchangeLabel(conversion.exchange)) +
        App.kv('سمت دفتر', conversion.side === 'ask' ? 'خرید (ask)' : 'فروش (bid)') +
        App.kv('زمان', App.fmtTime(conversion.timestamp)) +
        '</dl>');
    }
    parts.push('<h3>شبکه انتقال</h3>');
    const networks = row.networks || [];
    if (networks.length) {
      parts.push('<label>شبکه مشترک برای ' + App.esc(row.coin) + '<select id="drawerNetwork">' +
        networks.map(name => '<option value="' + App.esc(name) + '"' + (name === row.network ? ' selected' : '') + '>' + App.esc(name) + '</option>').join('') +
        '</select></label><p class="muted small">با تغییر شبکه، کارمزد برداشت همان شبکه از جدول شما خوانده می‌شود.</p>');
    } else {
      parts.push('<p class="muted small">شبکه مشترک ثبت نشده است. در تنظیمات، برای این ارز ردیف هر دو صرافی را وارد و پشتیبانی را علامت بزنید.</p>' +
        '<p><a href="/settings">رفتن به تنظیمات پیشرفته</a></p>');
    }
    parts.push('<p class="muted small">کارمزدها را خودتان در تنظیمات وارد می‌کنید؛ برنامه هیچ عددی را حدس نمی‌زند.</p>');
    return parts.join('');
  };

  App.bindNetwork = function (detail) {
    const select = $('drawerNetwork');
    if (!select) return;
    select.onchange = async function () {
      try {
        const cfg = await App.api('/api/scanner/settings');
        cfg.networks = cfg.networks || {};
        cfg.networks[detail.row.coin] = select.value;
        await App.api('/api/scanner/settings', App.put(cfg));
        await App.openDrawer(detail.row.key);
      } catch (error) { App.error(error); }
    };
  };
})();
