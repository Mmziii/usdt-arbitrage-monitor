# USDT arbitrage monitor
Local, read-only Wallex ↔ Nobitex monitor. No API keys, account access, orders or withdrawals. Persian RTL dashboard with bundled Vazirmatn (OFL license in `app/static/OFL.txt`). Requires Python 3.10+.

## شروع سریع در ویندوز (فارسی)
روی ویندوز فقط فایل **`start.bat`** را دوبار کلیک کنید. برنامه خودش محیط پایتون می‌سازد، پیش‌نیازها را نصب می‌کند و مرورگر را روی `http://127.0.0.1:8000` باز می‌کند. تا وقتی پنجره سیاه باز است برنامه روشن است؛ برای بستن، همان پنجره را ببندید.
- صفحه اصلی: `/` — «خانه»: یک سؤال، یک جواب (برو / صبر کن / نه / نامطمئن) + رسید «از صفر تا صد»
- `/fees` کارمزدها و دستیار کارمزد · `/guide` راهنمای فارسی · `/settings` تنظیمات
- `/dashboard` ابزارهای پیشرفته (جدول کامل، عیب‌یابی، شبیه‌سازی، دفتر معاملات)
- صفحات قدیمی: `/overview` (نمای همه بازارها) و `/classic` (داشبورد تتر/تومان)
این برنامه فقط داده عمومی می‌خواند: **بدون کلید API، بدون ورود به حساب، بدون ثبت سفارش**.

## Install & run (three commands)
Run from this repository directory:
```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m app
```
Open http://127.0.0.1:8000. On Windows replace `.venv/bin/python` with `.venv\Scripts\python.exe`. Stop with Ctrl+C. Keep the default loopback bind on your laptop: this is a local app, not a multi-user authenticated service.

If port 8000 is busy (Windows may report `[Errno 10048]`), choose a free port: replace the third command with `.venv/bin/python -m app --port 8001` and open `http://127.0.0.1:8001`. Alternatively, copy `.env.example` to `.env` and set `PORT=8001`, or set the `PORT` environment variable before running the third command (`export PORT=8001` on macOS/Linux; `$env:PORT = "8001"` in PowerShell). `--port` overrides the environment, which overrides `.env`; default is 8000. The runner does not terminate other processes. With direct Uvicorn, `python -m uvicorn app.main:app --host 127.0.0.1 --port 8001` also works; the app's `PORT` setting applies to `python -m app`, not Uvicorn's own CLI.

Optional: copy `.env.example` to `.env` before starting. Refresh defaults to 10 seconds; edit refresh interval, profit threshold and exchange fees in Settings (persisted in SQLite). Trading fees are global per exchange and quote market, defaulting to Wallex maker .25%, taker .3% and Nobitex maker/taker .25% in **each** market. Toman and USDT rates are independently editable and may differ. The original USDT/toman dashboard retains its editable legacy withdrawal defaults of .8 USDT (Wallex) and .7 USDT (Nobitex). SQLite database path defaults to `history.sqlite3`, relative to the working directory. Back up this file for history/settings; it is ignored by Git. History chart shows latest 1,000 samples; CSV exports up to 1,000,000 latest samples in chronological order with epoch UTC timestamps, toman prices, gross directional spreads and live/manual labels.

## Data sources
Official documentation checked November 2026:
- [Wallex depth](https://developers.wallex.ir/docs/basic-services-depth): public GET `https://api.wallex.ir/v1/depth?symbol=USDTTMN`; `result.ask/bid` objects with `price` and `quantity`. TMN prices are already toman. Documentation warns repeated depth polling can be rate limited; increase the refresh interval if needed.
- [Nobitex v3 order book](https://apidocs.nobitex.ir/market_data/دریافت-دفتر-سفارشات-نسخه-۳): public GET `https://apiv2.nobitex.ir/v3/orderbook/USDTIRT`; `asks/bids` arrays of price/USDT quantity. IRT prices in this API are **rial**, divided by ten for display/calculation. Exchange timestamps older than 120 seconds are rejected.

Requests have an 8-second timeout. Failed/invalid responses invalidate the previous live book, display a Persian error, and expose manual entry. Polling continues and live data automatically replaces manual values on recovery. Manual values persist only in memory, show their entry time, and assume unlimited liquidity at entered prices: they do NOT simulate slippage. Live history is recorded only when both live books succeed; manual snapshots are recorded on entry when both prices are available. Exchange connectivity could not be verified in the build sandbox (outbound exchange hosts are restricted); response adapters are covered by fixture tests. Wallex supplies no timestamp in the documented depth response; its timestamp is local receipt time.

## Calculation assumptions
Capital / ask depth → gross USDT → deduct buy fee in USDT → subtract source withdrawal USDT → sell across destination bid depth → deduct sell fee from toman proceeds. Insufficient depth or insufficient USDT for withdrawal gives an error, never a misleading partially filled profit. Both directions and both fee modes are calculated.

Maker results use the **same current depth with maker fee rates only**, as a hypothetical comparison. Immediate depth consumption is normally taker execution; maker fill price/timing is not guaranteed. The app does not predict future books during transfer. Fixed withdrawal fees must be checked against your chosen network.

Breakeven capital is the first zero-profit crossing inside supplied depth, found at piecewise-linear buy/sell boundaries (profit need not remain positive at larger sizes). Null means no crossing in available depth. Minimum required spread is the sell VWAP premium over the source best ask needed to break even at entered capital, including buy slippage and all fees; actual spread must be **greater** for positive profit. It is not a forecast of destination liquidity.

Enable alerts with the dashboard button: sound requires a user gesture, browser notifications require permission and a secure context (localhost qualifies). Alerts fire on crossing strictly above the configured net-profit threshold, not every refresh. Maker and manual estimates may trigger alerts; inspect their labels. No alerts while the page is closed. Settings/history remain local; no secrets are needed.

## Tests
`.venv/bin/python -m pytest -q`

Tests cover per-market global trading rates, two additional hand-calculated toman/USDT examples, pasted-fee parsing and preview, alternate-port startup, a hand-calculated 105,644 toman return from 100,000 capital, both-side depth walking, insufficient liquidity, withdrawal exhaustion, a profitable window before deeper losses, exchange formats/unit conversion, API failure/manual fallback, settings and CSV. Transfer time, adverse price movement, withdrawal limits/caps and maintaining toman balances on both exchanges remain operational risks, not modeled guarantees.

## Multi-coin overview
Open **نمای همه بازارها** from the existing dashboard (or `/overview`). The original USDT/toman dashboard, manual fallback and alerts remain accessible. Its trading fees are shared with the scanner’s toman-market rates; its USDT withdrawal values remain separate. The scanner is read-only and uses no credentials. It scans both directions for each exact common coin/quote pair, with separate capital values for toman and USDT. Nobitex `rls` / `IRT` prices are divided by ten; USDT quotes are not. Toman profit is converted at the average of the two current USDT/toman **bid** prices, shown in the table. Conversion is an indicative comparison, not an executable conversion; it is omitted if a fresh conversion rate is unavailable.

- [Wallex spot markets](https://api-docs.wallex.ir/) `GET https://api.wallex.ir/v1/markets`: symbol metadata and bulk `stats.bidPrice/askPrice`.
- [Nobitex market stats](https://apidocs.nobitex.ir/market_data/آمار-بازار) `GET https://apiv2.nobitex.ir/market/stats`: all spot markets and `bestBuy/bestSell`; `isClosed` markets are excluded. This endpoint is documented at 20 calls/minute.
- Depth on demand: `GET https://api.wallex.ir/v1/depth?symbol=...` and `GET https://apiv2.nobitex.ir/v3/orderbook/...` ([docs](https://apidocs.nobitex.ir/market_data/دریافت-دفتر-سفارشات-نسخه-۳)). At most two candidate markets are automatically checked per cycle, rotating through positive-gross-spread markets plus previously observed/failed depth and persisted active-opportunity markets; opening a detail view also fetches depth. Until depth is available, the overview does not claim a net result. Liquidity filtering uses the smaller of the total source ask and destination bid quote values in the fetched depth, an approximation, not a fill guarantee.

Discovery is cached in memory for six hours and can be refreshed manually. Overview defaults to 30 seconds. The scanner allows at most two concurrent requests per exchange and 18 requests per exchange per rolling minute (including retries), with exponential backoff on 429/5xx and network timeouts. The original dashboard's separate USDT depth poll is not included in this scanner budget. Requests time out after eight seconds. Tickers use local receipt time because the bulk fields used have no exchange timestamp; Nobitex depth uses `lastUpdate`, Wallex depth uses local receipt time. Quotes or depth older than 120 seconds are not used for profit. Bulk failure is shown globally; missing/invalid individual tickers are shown per market. The data and endpoints must be checked against live responses on your laptop.

Symbols are case-normalized and matched exactly; known collision/migration tickers and numeric-prefix tokens are excluded for review. No multiplier or renamed-token equivalence is guessed. Exact ticker equality alone cannot prove contract identity: always independently check the asset and network on both exchanges. The conservative rules may exclude valid assets and do not detect every possible ticker collision. A review list is displayed in the overview.

### Network fee table
The new table starts **empty**, including for USDT; the original dashboard's legacy USDT withdrawal defaults are not applied to the new scanner. We did not find a documented public endpoint providing a complete, reliable per-network fee and support table for both exchanges; no account APIs are used. Verify and enter the current information manually. Add one row for each exchange for the same uppercase coin and exact network identifier, set supported on both sides, and enter the source withdrawal fee and minimum in **coin units**. Unknown fee or minimum stays blank/null and blocks that direction's Transfer-mode net profit; an unknown minimum is reported separately from an unknown withdrawal fee; do not enter zero unless it is actually zero. No matching supported network blocks Transfer-mode profit, but not Pre-funded trades. The network selector chooses among configured common networks. Information entered here is not automatically updated for suspended withdrawals/deposits. JSON/CSV import replaces the whole table only when saved, and export downloads the currently edited table. SQLite persists the settings and fee table. Example JSON (illustrative values only, not exchange fees):

```json
[
  {"exchange":"wallex","coin":"BTC","network":"BTC","withdrawal":null,"minimum":null,"supported":true},
  {"exchange":"nobitex","coin":"BTC","network":"BTC","withdrawal":null,"minimum":null,"supported":true}
]
```

CSV columns are `exchange,coin,network,withdrawal,minimum,supported`; leave unknown numbers empty, use `true` or `false` for support. Search and exchange filters do not delete hidden rows. The missing-withdrawal-fee filter lists discovered coins even if they have no rows: a coin is included if at least one selected exchange has no supported row with a known withdrawal fee. An exchange filter restricts that check to the selected exchange; this filter does not establish that a common network exists.

For quick entry, paste one line per fee as `TRX, TRC20, wallex, 1` (or `TRX, TRC20, wallex, 1, 10` with minimum as the fifth column). The preview reports line errors and duplicates; nothing is saved by preview. After resolving all errors, apply to the table, verify it, then save the table. Updates preserve existing support and an existing minimum when the fifth column is omitted. Newly added rows have **support unchecked** and minimum unknown, never guessed; confirm both exchanges' network support and minimum withdrawal manually. Import and paste modify only the editor until Save.

Global maker/taker trading fees are shared by all coins of each exchange/quote pair; change all four pairs in the overview or the original dashboard settings. Existing saved toman rates are preserved on upgrade; new USDT rates start at the stated defaults. Legacy per-coin trading overrides are ignored and removed on the next scanner-settings save. In Mode A no result uses a missing withdrawal fee or unknown minimum. Mode B needs no per-trade network fee or support and can calculate without those fields. In Mode A, without a confirmed common network or known withdrawal fee, the overview labels the available ticker spread **gross only**, not net profit. The minimum withdrawal is checked against the post-buy-fee coin amount before subtracting the withdrawal fee. Maker uses the same immediate depth and is hypothetical.

The detail view includes top book levels, calculation steps, network selection, spread history and per-market CSV. All-market CSV is also available. Samples and original history are pruned periodically, including during overview fetch failures, according to the configurable retention period (default 30 days). CSV is limited to the latest million rows. Browser alerts are opt-in, trigger only when a watched coin's taker net result crosses the threshold, and run only while the overview is open. The original dashboard retains its own alert behavior. Liquidity, deposit minimums, memo/tag requirements, network confirmations, suspensions, delistings, and price changes during transfer remain risks to verify manually.


## Trading modes, safety and capital sizing
Use **`/overview`** for all new controls. Both modes retain taker and **hypothetical** maker estimates, separate toman/USDT fee rates, breakeven and required spread. A row selector overrides the global mode for that coin/quote/direction; choosing the global option removes the override. The original dashboard also respects the global mode and its USDT/toman route overrides; it keeps its legacy USDT withdrawal setting in Transfer mode. Its settings save preserves the new tier configuration.

- **A — Transfer (انتقال):** buy across asks, deduct buy fee in coin, subtract the source coin withdrawal fee, then sell across bids and deduct sell fee in quote. The network table still holds **withdrawal/minimum/support only**, never coin-specific trading fees. Global safety margin is **0.3 percentage points**, optionally overridden per coin. Green requires `profit_pct > margin`; `0 < profit_pct <= margin` is yellow **پایین‌تر از حاشیه ایمنی**; non-positive is red. Alerts also require exceeding the margin. The margin is a screening hurdle, not another fee deducted from profit and not a predicted price movement.
- **B — Pre-funded balances (موجودی از پیش):** buy and sell simultaneously from already held balances. Sale quantity equals purchased coin **after the buy fee**; no withdrawal or transfer delay is charged per trade. The optional asset-balance table supports quote (`toman` or `USDT`) and coin symbols on each exchange. Only source quote and destination coin constrain this direction. Values are manual assumptions, not fetched account balances; blank is unlimited, zero blocks that side. Without either limit the result explicitly says **موجودی‌ها محدود نشده‌اند**. No account endpoints, keys, orders or transfers are added.

### Separate rebalancing estimate in Mode B
The detail panel shows trade profit **before** rebalancing, a separate fixed transfer-cost estimate for one reset after **N trades (default 10)**, cost per trade (`reset_cost / N`), and profit after amortization. Reset coin moves **destination → source**, so its withdrawal fee is taken from the destination's configured coin/network entry and valued at the current destination best bid. Reset quote moves **source → destination**, using that source's quote withdrawal fee. Both components must be explicitly known; missing support/fee/minimum makes the total and after-rebalancing profit **unknown**, not zero. Known components remain visible.

For a USDT quote market, configure supported USDT network entries on both exchanges. For toman quote, the fee editor accepts the bookkeeping symbol **`TOMAN`** with a common user-defined network name such as `BANK`; withdrawal and minimum are in **toman**. Enter zero only after verifying it really is zero. These bank entries are manually supplied estimates, not a claim of blockchain support. This is a fixed-cost estimate, not a rebalance execution plan: it does not model conversion spreads, accumulated-size slippage, transfer capacity/minimum feasibility, tax or extra bridge fees. N trades means one reset, not N withdrawals. Network availability must be checked again before any real action.

### Estimated transfer times
The editable table starts with `default`, TRC20, BEP20 and ERC20 all **unknown (blank/null)**. No times are invented. Add network names manually. A network without a configured value uses `default`, which can itself be unknown. Every displayed time is labeled **estimated**; the detail view indicates default fallback. These times are used to compare observed lifetimes, not to guarantee settlement or automatically change the safety margin.

### Maximum capital and maximum absolute profit
The overview adds **بیشترین سرمایه سودده** and **سرمایه با بیشترین سود**; detail shows both for taker and maker. They are calculated independently of the selected test capital by visiting every ask-cost breakpoint and every destination bid-quantity breakpoint mapped back through the buy fee/withdrawal. Roots are interpolated within these linear segments, not found by a monotonic binary search. Entered Mode B balances also bound this domain. A row whose selected capital exceeds depth can still show capital analysis without reporting a partially filled trade profit.

Maximum-profitable capital uses `profit > 0` in B and `profit - capital * margin / 100 > 0` in A. A numeric crossing is the **boundary**: use a size just below it for a strict inequality. If the last visible point is still profitable and no tighter entered balance determines the bound, the UI shows **محدود به عمق قابل مشاهده** instead of pretending to know the global maximum. Profit-maximizing capital is the maximizer of *absolute unadjusted net trade profit in the visible, balance-feasible domain*, before Mode B amortization; it is not a promise about unseen depth. No profitable point yields a dash. Equal-profit ties choose the earliest breakpoint. Zero breakeven means no fixed cost and a non-negative initial marginal profit; it does not mean a zero-size trade can be executed. Capital and profit amounts include quote, toman and USDT equivalents; missing fresh USDT/toman conversion stays unknown.

## Opportunity lifetimes and statistics
Open the **آمار فرصت‌ها** tab in `/overview`; filter coin, mode and the network whose configured estimated time you want to compare. It shows overall/per-coin counts, active/closed counts, median and interpolated 90th percentile duration (seconds), best peak profit %, hourly counts (**UTC**), and the plain-language percentage lasting less than that transfer time (A only). Export events with **`/api/opportunities.csv`**; statistics are also at **`/api/opportunities`**.

The background scanner, not browser refreshes, records **taker profit before rebalancing** for the selected global/per-route mode. Positive means `net profit > 0`, **not** the safety-margin green threshold. The first observed positive sample starts an event (initial state is treated as non-positive); further positive samples update peak net profit % and capital at that peak. A configurable number of consecutive **fresh, confirmed** non-profitable depth observations closes it (default **2**), with end time at the first observation in the confirmed negative run. Same-book repeats, skipped depth work, errors, stale data and changed/removed mode/network contexts mark unknown gaps and reset the consecutive-negative counter; they never silently end an event. Coin/quote/direction/mode/network form independent tracking contexts.

SQLite stores start/end epoch timestamps, duration seconds, peak %, capital at peak **in that market's quote**, and the number of unknown gap observations. Open events have no final duration. Durations with any unknown gaps are **uncertain** and excluded from duration percentiles and the shorter-than-transfer share; counts, peaks and CSV retain them. This avoids treating a polling gap as proof of uninterrupted profitability. Missing transfer time or no eligible finished samples yields unknown, not 0%. A small sample or a coarse polling interval cannot prove a strategy is executable.

Depth polling is deliberately bounded to two markets per scanner cycle. Promising markets, previously depth-observed/failed markets and persisted active-event markets rotate; active markets are revisited even after restart and even when their raw spread turns negative. Many rows are therefore not observed each cycle, and lifetime results are **sampled observations, not continuous market truth**. Fee/balance/capital edits affect subsequent fresh observations; exported events do not snapshot the full settings history.

The existing retention-days setting (default 30) prunes price history, closed events older than the horizon, old states and events whose start predates retention even if still open. An event spanning the retention horizon can thus restart on the next positive observation. This bounds stored history rather than retaining an eternal open event. Deleted SQLite pages are reusable (the file need not immediately shrink); back up the database while the app is stopped. Old tables/settings are preserved and new event tables are created on startup.

## User-defined tiered fees
Tables start **empty**; no exchange tier schedule or 30-day volume is fetched or invented. In the tier editor enter exchange, quote market, tier name, 30-day volume threshold **in the quote currency**, maker % and taker %. Select **my current tier** separately for each exchange/quote pair. Selection is manual: thresholds document your schedule but do not automatically choose a tier. A matching selected tier overrides that pair's global maker/taker rates for every coin; blank or a removed/missing selected tier falls back to global. The row/detail fee-source indicator shows the actual active source. Global rates remain editable and are not overwritten by a tier.

Save applies the complete table and selections. Import **replaces and immediately saves** the tier table after confirmation and server validation; export downloads the **saved**, not unsaved, table. Review current selections after import. CSV headers are:

```text
exchange,quote,name,threshold,maker,taker
```

`exchange` is `wallex` or `nobitex`; `quote` is `toman` or `USDT`. JSON is an array of objects with those same keys. Empty JSON `[]` clears the table; a headers-only CSV does too. Duplicate exchange/quote/name entries and invalid/non-finite/negative fees are rejected; percentages must be below 100. API endpoints: `GET /api/tiers/export?format=csv|json`, `POST /api/tiers/import` with `{"format":"json","text":"[]"}`, and the existing settings endpoint for selecting tiers (`current_tiers` keys such as `wallex:toman`).

## Verification of this extension
Run `.venv/bin/python -m pytest -q`. Tests include hand-worked Mode B toman/USDT examples, separate rebalance amortization, balance caps, below-margin Transfer profit, multi-level capital roots (including sell-side breakpoints), tier fallbacks/import round trips, persistent opportunity start/end/unknown handling, pruning and API validation. The optional DOM smoke test uses **synthetic books calculated by the real backend**, no external exchange requests:

```sh
npm install --prefix .cache/ui-test jsdom@26 --no-audit --no-fund
NODE_PATH=.cache/ui-test/node_modules node tests/ui_smoke.cjs
NODE_PATH=.cache/ui-test/node_modules node tests/ui_dashboard_smoke.cjs
NODE_PATH=.cache/ui-test/node_modules node tests/ui_controls_smoke.cjs
NODE_PATH=.cache/ui-test/node_modules node tests/ui_classic_smoke.cjs
NODE_PATH=.cache/ui-test/node_modules node tests/ui_home_smoke.cjs
NODE_PATH=.cache/ui-test/node_modules node tests/ui_fees_smoke.cjs
node tests/sort_order_test.cjs
```

API-level checks live in `tests/test_api_sweep.py` (every route with valid/empty/malformed input, no 500, Persian messages), `tests/test_cycle_edges.py` (zero/tiny/oversized capital, withdrawal fee above the amount, missing fees, empty order books) and `tests/test_ui_state.py` / `tests/test_windows_launcher.py`. `DEBUG-REPORT.md` lists every bug fixed in the debug pass with its covering test.

This development-only tool is not needed to install/run the app. No CDNs or external frontend dependencies are used at runtime; the Vazirmatn font remains bundled. DOM checks are not a full visual/browser or live-market verification. Outbound exchange access is blocked in the build sandbox, so live schemas, network/fee accuracy, notifications, settlement times and actual execution could not be verified there.

### Laptop acceptance checklist
1. Use the three install/run commands above, open `/` and `/overview`, verify RTL layout, bundled font, manual fallback, history and existing settings.
2. Confirm live Wallex/Nobitex prices and freshness, including rial→toman conversion and USDT order books. Compare a few depth levels with the exchange websites.
3. Enter verified coin/network withdrawal/support/minimum data on both sides; in Transfer mode try a positive result below/above your safety margin and a per-coin override. Set real estimated transfer minutes; test an unknown network's fallback.
4. Switch global and individual route modes; enter source quote and destination coin balances, including zero, then clear them to check the unlimited label. Check both maker/taker and toman/USDT results against a hand calculation.
5. Verify reset fees in both directions, test N=10 and another N, and check before/after amortization. Deliberately remove one fee and confirm the total becomes unknown. Review bank-fee assumptions for TOMAN.
6. Compare maximum capital and profit-maximizing capital against visible book breakpoints; try selected capital beyond depth and confirm the separate sizing analysis remains available. Check conversion rates and the visible-depth limitation label.
7. Add only your actual tiers, select/deselect each exchange/quote pair, verify the source indicator and results, round-trip CSV/JSON, restart and confirm settings persist. Saving the original dashboard must not clear tiers.
8. Let the scanner observe opportunities; check the statistics tab/CSV, configured closing confirmations, unknown-gap handling during a network interruption, mode/network separation, UTC hours and retention. Allow enough finished gap-free observations before interpreting percentile/share statistics.
9. Verify opt-in browser sound/notifications and threshold crossings; remember alerts run only while the page is open and results are estimates, never executable orders.

## نسخه بیت‌یونیکس: چرخه کامل، داشبورد جدید، عیب‌یابی و شبیه‌سازی (فارسی)

این بخش کارهای مرحله سوم را توضیح می‌دهد. همان قاعده قبلی برقرار است: **فقط داده عمومی بازار، فقط خواندن، بدون کلید API، بدون سفارش و بدون دسترسی به حساب.**

### ۱. منبع داده بیت‌یونیکس (بازار اسپات، نه فیوچرز)
مستندات رسمی (بررسی‌شده آبان/نوامبر ۲۰۲۶): `https://www.bitunix.com/api-docs/` و بخش اسپات در `https://www.bitunix.com/api-docs/spots/en_us/`. دامنه عمومی: `https://openapi.bitunix.com`.
- `GET /api/spot/v1/common/coin_pair/list` → فهرست جفت‌ارزهای اسپات (پاسخ در `data`). برنامه از همین پاسخ نمادهای باز و **USDT** را برمی‌دارد و بقیه را رد می‌کند.
- `GET /api/spot/v1/market/last_price?symbol=BTCUSDT` → آخرین قیمت. این عدد **فقط مرجع** است (نه ask/bid)، پس هرگز به‌عنوان سود نمایش داده نمی‌شود.
- `GET /api/spot/v1/market/depth?symbol=BTCUSDT&precision=…` → دفتر سفارش؛ `data.asks/bids` آرایه‌ای از `{price, volume}` رشته‌ای و `ts`. پارامتر `precision` در مستندات الزامی است؛ برنامه آن را از فیلد `precisions` فهرست بازارها می‌خواند و اگر خالی بود حذف می‌کند.
- endpoint تیکرهای فیوچرز (`fapi.bitunix.com/api/v1/futures/market/tickers`) **استفاده نمی‌شود**، چون فیوچرز است.
- در مستندات، endpoint عمومی «قیمت همه نمادها یک‌جا» برای اسپات پیدا نشد؛ بنابراین برنامه حدس نمی‌زند و آخرین قیمت را برای مجموعه‌ای محدود و چرخشی از نمادها می‌گیرد (`ticker_batch`، پیش‌فرض ۱۲ در هر دور)، با اولویت ردیف‌های قابل مشاهده، پین‌شده و پراختلاف.
- فهرست `coin_pair/list` شامل کارمزد/حداقل برداشت شبکه هم هست، ولی برنامه **هیچ عدد کارمزدی را از آن پر نمی‌کند**؛ کارمزدها فقط دستی وارد می‌شوند.

### ۲. کشف فرصت بین سه صرافی و فهرست حذف‌شده‌ها
- بازارهای والکس و نوبیتکس (تومان و USDT) با بازارهای اسپات بیت‌یونیکس (USDT) فقط با **نماد دقیق** تطبیق داده می‌شوند.
- از هر بازار ایرانی، مسیرهای `A` (خرید در بیت‌یونیکس، فروش در ایران)، `B` (برعکس) و برای بازارهای USDT مسیرهای `direct_iran_to_bitunix` / `direct_bitunix_to_iran` ساخته می‌شود.
- نمادهای مشکوک (مثل توکن‌های عددی یا تغییرنام‌داده) در «فهرست حذف‌شده / نیازمند بررسی» با دلیل فارسی نمایش داده می‌شوند. هیچ ضریب یا معادل‌سازی حدس زده نمی‌شود.
- تطبیق نماد ثابت نمی‌کند قرارداد یکی است؛ پیش از هر اقدام واقعی، خودتان ارز و شبکه را در هر دو صرافی کنترل کنید.
- کشف بازارها ۶ ساعت در حافظه کش می‌شود و با «به‌روزرسانی الان» قابل تازه‌سازی است.

### ۳. محاسبه چرخه کامل و حالت‌ها
هر ردیف با سرمایه فعلی و از روی **دفتر سفارش واقعی** حساب می‌شود (راه‌رفتن روی عمق، نه فقط بهترین قیمت):
- **A**: خرید ارز با تتر در بیت‌یونیکس → کسر کارمزد خرید → کسر کارمزد برداشت ارز → فروش در بازار تومانی ایران → تبدیل تومان به تتر → کسر کارمزد برداشت تتر.
- **B**: خرید در ایران با تومان → کارمزد برداشت → فروش در بیت‌یونیکس → بازگشت تتر به ایران.
- **مسیرهای مستقیم بازار USDT**: بدون مرحله تبدیل تومان/تتر.
- **موجودی از پیش (Pre-funded)**: خرید و فروش هم‌زمان از موجودی‌های قبلی؛ هزینه بازتوازن **جدا** و سرشکن هر N معامله نمایش داده می‌شود، نه داخل سود هر معامله.

هر ردیف نشان می‌دهد: کارمزد از کدام منبع آمده (سراسری یا سطح)، نرخ تبدیل تومان/تتر با صرافی و سمت دفتر و زمان آن، نرخ مؤثر با عمق، اختلاف خام، سود خالص، سود به تومان، حاشیه ایمنی، بیشترین سرمایه سودده، سرمایه با بیشترین سود، سرمایه سربه‌سر، سن داده و شبکه.
- اگر کارمزد معاملاتی، کارمزد برداشت، حداقل برداشت یا شبکه مشترک **نامعلوم** باشد، سود خالص محاسبه نمی‌شود و ردیف با برچسب «فقط اختلاف خام» می‌ماند. صفر فرض نمی‌شود.
- داده قدیمی‌تر از `stale_seconds` (پیش‌فرض ۱۲۰ ثانیه) هرگز مبنای سود نیست.
- حکم ردیف: سبز «ارزشش رو داره» یعنی سود از حاشیه ایمنی بیشتر است؛ زرد «مرزی»؛ قرمز «فعلاً نه»؛ خاکستری «داده کافی نیست».
- نکات ریسک (تغییر قیمت در زمان انتقال، کارمزد شبکه، لغزش، حداقل برداشت، تعلیق شبکه) در جزئیات و «طرح معامله» آمده است. این برنامه هیچ‌کدام را تضمین نمی‌کند.

### ۴. استراتژی به‌روزرسانی (سبک و محترم به محدودیت صرافی‌ها)
- تیکرهای حجیم والکس و نوبیتکس هر `interval` ثانیه (پیش‌فرض ۱۰).
- دفتر سفارش کامل فقط برای «ردیف‌های داغ»: ۲۰ ردیف برتر + ردیف‌های پین‌شده + ردیفی که جزئیاتش باز است. هر دور حداکثر `depth_batch` (پیش‌فرض ۶) درخواست عمق، هر `depth_interval` ثانیه (پیش‌فرض ۵).
- بودجه درخواست مشترک و سراسری، جدا برای تیکر و عمق: والکس ۶۰ درخواست در دقیقه (۳ هم‌زمان)، نوبیتکس برای تیکر ۱۵ و برای عمق ۱۲۰ در دقیقه (۴ هم‌زمان)، بیت‌یونیکس ۶۰ (۳ هم‌زمان). با ۴۲۹ یا ۵xx عقب‌کشیدن نمایی دارد و از سقف عبور نمی‌کند.
- «توقف به‌روزرسانی» حلقه اسکن را متوقف می‌کند (و در SQLite ذخیره می‌شود). «قفل ترتیب» فقط ترتیب جدول را ثابت نگه می‌دارد.
- اگر چیزی خطا بدهد، ردیف‌های قبلی حذف نمی‌شوند؛ فقط سن داده و دلیل خطا نمایش داده می‌شود.

### ۵. داشبورد فارسی جدید
صفحه `/` پنج تب دارد و همه چیز با صفحه‌کلید و صفحه‌خوان قابل استفاده است:
- **فرصت‌ها**: کارت‌های خلاصه (تعداد سودده، بهترین فرصت، نرخ تتر، وضعیت صرافی‌ها)، جدول رتبه‌بندی‌شده با «قفل ترتیب» (هیسترزیس) تا با هر تغییر کوچک نپرد، جستجو، فیلترها (صرافی، بازار، مسیر، حالت، حداقل سود، حداقل ظرفیت، پنهان‌کردن ردیف‌های خام/قدیمی)، ذخیره و حذف فیلترها، ستاره پین، نوار رنگ برای سود.
- **حالت ساده / پیشرفته**: در حالت ساده فقط ستون‌های ضروری؛ در پیشرفته ستون‌های میکر، سهام، نرخ تبدیل، منبع کارمزد، شبکه و… و انتخاب ستون‌ها (ذخیره‌شده).
- **کادر سرمایه**: عدد را با متن آزاد بنویسید (`50 میلیون`، `۵۰ میلیون تومان`، `250 USDT`، `2.5 میلیارد`) یا از دکمه‌های آماده استفاده کنید. واحد انتخابی و معادل USDT/تومان بلافاصله محاسبه و ذخیره می‌شود.
- **کشوی جزئیات**: پنج تب — مراحل محاسبه، طرح معامله + چک‌لیست، دفتر سفارش هر دو طرف (۸ سطح اول)، نمودار تاریخچه اختلاف، منبع کارمزد و انتخاب شبکه.
- **پوسته و خوانایی**: روشن/تیره/خودکار، سه اندازه فونت، ارقام فارسی یا لاتین، فونت وزیرمتن همراه برنامه (بدون CDN و بدون تصویر بیرونی)، RTL کامل، احترام به `prefers-reduced-motion`.
- **کلیدها**: `/` یا `Ctrl+K` جستجو، `F` قفل ترتیب، `Esc` بستن پنجره‌ها.
- **راهنمای فارسی**: `/guide` (همچنین از منو).

### ۶. شبیه‌سازی و دفتر معاملات
- **معاملات آزمایشی**: در تب «طرح معامله» روی «ثبت معامله آزمایشی» بزنید. قیمت‌ها و نتیجه انتظاری همان لحظه ذخیره می‌شود؛ بعد از زمان انتقال (یا زمان انتخابی) دفتر سفارش دوباره خوانده و نتیجه **واقعی** ثبت می‌شود (سود واقعی و اختلاف). اگر داده نباشد، وضعیت «داده نبود» با دلیل ذخیره می‌شود، نه یک عدد ساختگی. هرگز سفارشی ثبت نمی‌شود.
- **دفتر معاملات دستی**: تاریخ، ارز، مسیر، حالت، سرمایه، مبلغ نهایی، سود (خالی = محاسبه خودکار `نهایی − سرمایه`)، کارمزد و یادداشت. خروجی CSV با UTF-8 BOM. فقط در SQLite همین رایانه ذخیره می‌شود.

### ۷. صفحه عیب‌یابی
برای هر صرافی: وضعیت، آخرین موفقیت، آدرس آخرین درخواست، کد HTTP، زمان پاسخ، معتبر بودن JSON، دلیل رد داده به فارسی + راه‌حل، شماره تلاش، اختلاف ساعت و سهمیه درخواست. «تست همه» سه صرافی را با فهرست بازارها، یک قیمت و یک دفتر سفارش می‌آزماید و **پیش‌نمایش ۵۰۰ کاراکتر اول پاسخ خام** را نشان می‌دهد. هشدار اختلاف ساعت با دستور همگام‌سازی ویندوز نمایش داده می‌شود. پروکسی، User-Agent و سقف سن داده از همین صفحه تغییر می‌کند (پروکسی در نمایش پوشانده می‌شود). واژه‌نامه دلایل خطا هم همان‌جاست.

### ۸. پشتیبان‌گیری
`GET /api/backup` یک فایل JSON با `{app, version, settings, scanner, fees, ui}` می‌دهد. «بازگردانی از فایل» در تب تنظیمات همان را اعتبارسنجی می‌کند و در صورت خطا **هیچ تغییری اعمال نمی‌شود** (HTTP 422 با پیام فارسی).

### ۹. APIهای جدید
`GET /api/overview`، `POST /api/overview/refresh`، `POST /api/overview/pause`، `POST /api/overview/visible`، `GET /api/overview/detail?key=`، `GET /api/plan?key=`، `GET /api/diagnostics`، `POST /api/diagnostics/test`، `PUT /api/connection`، `GET /api/amount?text=`، `GET|PUT /api/ui`، `GET /api/backup`، `POST /api/backup/restore`، `GET|POST|DELETE /api/simulations…`، `GET|POST|DELETE /api/journal…`، `GET /api/journal.csv`، `GET /api/wizard`.

### ۱۰. اجرا در ویندوز
`start.bat` را دوبار کلیک کنید. اگر پایتون نصب نباشد یا قدیمی‌تر از ۳.۱۰ باشد، پیام فارسی + نسخه نصب‌شده + لینک دانلود می‌دهد. برای اولین اجرا محیط `.venv` می‌سازد، `requirements.txt` را نصب می‌کند، `.env` را از نمونه کپی می‌کند و برنامه را روی `127.0.0.1:8000` بالا می‌آورد. اگر پورت ۸۰۰۰ مشغول باشد، خودش ۸۰۰۱ تا ۸۰۰۳ را امتحان می‌کند و آدرس درست را در همان پنجره چاپ می‌کند. بستن پنجره = بستن برنامه. اجرای دستی معادل همان سه دستور بخش اول است.

نکته‌ها: مسیر پوشه می‌تواند فاصله داشته باشد (همه مسیرها داخل `"..."` هستند)؛ فایل با CRLF و UTF-8 بدون BOM ذخیره شده و ابتدا `chcp 65001` می‌گیرد. اگر نصب بسته‌ها شکست خورد، پیام راهنما دستور نصب با آینه (mirror) دلخواه شما را چاپ می‌کند.

### ۱۱. تست‌ها
```sh
.venv/bin/python -m pytest -q
npm install --prefix .cache/ui-test jsdom@26 --no-audit --no-fund
NODE_PATH=.cache/ui-test/node_modules node tests/ui_smoke.cjs
NODE_PATH=.cache/ui-test/node_modules node tests/ui_dashboard_smoke.cjs
NODE_PATH=.cache/ui-test/node_modules node tests/ui_controls_smoke.cjs
NODE_PATH=.cache/ui-test/node_modules node tests/ui_classic_smoke.cjs
NODE_PATH=.cache/ui-test/node_modules node tests/ui_home_smoke.cjs
NODE_PATH=.cache/ui-test/node_modules node tests/ui_fees_smoke.cjs
node tests/sort_order_test.cjs
```
- pytest: **۳۱۸ تست** (محاسبات دستی چرخه A/B/pre-funded، محرومیت کارمزد نامعلوم، کشف مسیرها، بودجه/بک‌آف، عیب‌یابی و ساعت، تجزیه مبلغ فارسی، استراتژی داغ/کهنگی، هاب، شبیه‌سازی، دفتر معاملات، APIها و مهاجرت ذخیره‌سازی).
  - `tests/test_api_sweep.py`: همه مسیرهای HTTP با ورودی درست، خالی و خراب؛ هیچ ۵۰۰ و پیام فارسی.
  - `tests/test_cycle_edges.py`: سرمایه صفر/کوچک/بزرگ‌تر از عمق، کارمزد برداشت بیشتر از مبلغ، کارمزد نامعلوم و دفتر سفارش خالی.
  - `tests/test_ui_state.py`: ماندگاری «بستن پیام» در SQLite و رد ورودی خراب با پیام فارسی.
  - `tests/test_windows_launcher.py`: بازبینی متن `start.bat` (CRLF، UTF-8 بدون BOM، نقل‌قول مسیرها، تعادل پرانتزها، پورت جایگزین).
- `tests/ui_fixture.py` داده تست داشبورد را با **موتور واقعی پایتون** و دفترهای ساختگی می‌سازد؛ هیچ درخواست بیرونی ندارد.
- `tests/ui_dashboard_smoke.cjs` با jsdom صفحه‌های `/`, `/overview`, `/settings`, `/classic`, `/guide` و تعامل‌ها را می‌آزماید، `tests/ui_controls_smoke.cjs` همه راه‌های بستن/رد کردن، فوکوس، فریز، فیلترها و پیام‌های خطای فارسی HTTP را، `tests/ui_classic_smoke.cjs` صفحه `/classic` را و `tests/sort_order_test.cjs` قاعده رتبه‌بندی/هیسترزیس/فریز را (بدون DOM). jsdom فقط ابزار توسعه است و در اجرای برنامه لازم نیست.

### ۱۲. چیزهایی که در این محیط تأیید نشده است (صادقانه)
شاخه: `arena/47c6edfb-usdt-arbitrage-monitor` — گزارش کامل رفع اشکال: `DEBUG-REPORT.md`.
- **دسترسی زنده به صرافی‌ها در سندباکس ساخت مسدود است.** قالب پاسخ‌های بیت‌یونیکس، والکس و نوبیتکس فقط با fixture و مستندات آزمایش شده؛ نه با پاسخ واقعی امروز صرافی.
- **قالب نماد اسپات بیتیونیکس** (مثل `BTCUSDT` در برابر شکل دیگری) از مستندات قطعی برداشت نشده؛ برنامه نماد را از فیلد `symbol` پاسخ فهرست بازارها می‌خواند، ولی این باید روی لپ‌تاپ دیده شود.
- **پارامتر `precision` دفتر سفارش** و واحد زمان `ts` بیتیونیکس روی پاسخ واقعی تأیید نشده است.
- **نبود endpoint عمومی «همه تیکرها»** برای اسپات بیتیونیکس یک نتیجه جستجو در مستندات است؛ اگر وجود داشته باشد، فقط سرعت بهتر می‌شود، نه صحت محاسبه.
- **کارمزدها و شبکه‌ها** فقط از نقاط پایانی عمومی *مستند* خوانده می‌شوند و در این محیط هیچ‌کدام با پاسخ واقعی آزموده نشده‌اند (وضعیت هر منبع در `/api/fees` و بخش ۱۴.۴ صادقانه `unconfirmed` است). پیش‌فرض کارمزد معامله بیت‌یونیکس خالی و بقیه «تخمینی» برچسب می‌خورند. صحت اعداد واردشده مسئولیت کاربر است.
- **`start.bat` روی ویندوز واقعی اجرا نشده** (این محیط لینوکس است)؛ متن آن تست متنی دارد (CRLF، نقل‌قول، تعادل بلوک‌ها) ولی رفتار cmd.exe را فقط ویندوز نشان می‌دهد.
- **فونت کنسول ویندوز** ممکن است فارسی را درست نمایش ندهد (مثلاً Consolas)؛ همه پیام‌های `start.bat` انگلیسی هم دارند و این روی اجرای برنامه اثری ندارد.
- **مقادیر عددی فرم‌ها** با کیبورد فارسی/عربی در بعضی مرورگرها ممکن است جداکننده هزارگان بگذارند؛ برنامه رقم فارسی و انگلیسی و «میلیون» را می‌پذیرد، ولی اعداد جداکننده‌دار را یک‌بار روی لپ‌تاپ امتحان کنید.
- **بازنمایی فارسی/راست‌به‌چپ** فقط در jsdom بررسی شده؛ ظاهر واقعی مرورگر، فونت وزیرمتن و اعداد فارسی را روی لپ‌تاپ ببینید.
- **زمان انتقال و تأخیر شبکه** دستی وارد می‌شود؛ برنامه آن را حدس نمی‌زند و هیچ اندازه‌گیری زنده‌ای ندارد.
- **همه اعداد سود تخمینی‌اند.** حتی وقتی همه کارمزدها وارد شده باشند، قیمت در لحظه انتقال تغییر می‌کند.

#### چک‌لیست پذیرش روی لپ‌تاپ
1. `start.bat` را اجرا کنید؛ مرورگر باز شود و صفحه `/` بدون خطای کنسول بالا بیاید.
2. در تب «عیب‌یابی» دکمه «تست همه» را بزنید و ببینید هر سه صرافی چه می‌گویند. اگر ۴۵۱/۴۰۳ دیدید، VPN را خاموش کنید و دوباره تست بگیرید.
3. اختلاف ساعت را چک کنید؛ اگر هشدار داد ساعت ویندوز را همگام کنید.
4. کارمزد تیکر/میکر هر پنج ترکیب صرافی×بازار را از صفحه کارمزد خود صرافی وارد کنید، سپس برای یک ارز (مثلاً USDT روی TRC20) کارمزد و حداقل برداشت هر سه صرافی را ثبت کنید.
5. یک ردیف با سود مثبت پیدا کنید، جزئیاتش را باز کنید و **با ماشین‌حساب** مراحل را کنترل کنید (مبلغ‌ها، کارمزدها، نرخ تبدیل، سود).
6. یک ردیف را عمداً ناقص بگذارید (کارمزد خالی) و مطمئن شوید «فقط اختلاف خام» می‌شود.
7. یک معامله آزمایشی ثبت کنید و بعد از زمان انتقال، نتیجه واقعی و اختلافش را ببینید.
8. یک معامله واقعی کوچک در دفتر ثبت کنید و CSV بگیرید.
9. فایل پشتیبان بگیرید، یک تنظیم را عوض کنید، فایل را بازگردانید و مطمئن شوید تنظیمات برگشت.
10. «توقف به‌روزرسانی» را بزنید و ببینید درخواست‌ها متوقف می‌شوند (در تب عیب‌یابی سهمیه درخواست دیگر بالا نمی‌رود).
11. پیام راه‌اندازی بالای صفحه را با ✕ ببندید، صفحه را رفرش کنید و مطمئن شوید بسته می‌ماند؛ سپس ویزارد را باز کنید تا دوباره ظاهر شود.
12. کشوی جزئیات را با کلید Esc و با کلیک بیرون ببندید و ببینید فوکوس به همان ردیف برمی‌گردد.
13. اگر پورت ۸۰۰۰ مشغول بود (یک برنامه دیگر)، دوباره `start.bat` را بزنید و آدرس جدید (۸۰۰۱) را ببینید.

### ۱۳. رفع اشکال‌های این مرحله (خلاصه)
فهرست کامل با مکان، ریشه، اصلاح و تست پوشش‌دهنده در `DEBUG-REPORT.md` است. مهم‌ترین‌ها:
- دکمه ✕ کار نمی‌کرد چون `.modal{display:flex}` بر `hidden` غلبه می‌کرد؛ قانون سراسری `[hidden]{display:none!important}` اضافه شد و بیست مسیر بستن با jsdom و استایل واقعی آزموده شد.
- ترتیب ردیف‌ها با هر تازه‌سازی می‌پرید؛ رتبه‌بندی «هیسترزیس» و «فریز» بازنویسی شد (تست بدون DOM).
- دفتر سفارش خالی یک `IndexError` می‌داد و کل صفحه را ۵۰۰ می‌کرد؛ حالا «عمق ناکافی» با پیام فارسی است.
- خطاهای ۴۲۲ (اعتبارسنجی) و بعضی ۵۰۳ انگلیسی بودند؛ همه فارسی شدند (هندلر واحد + پیام‌های دامنه).
- در رابط کاربری، خطای شبکه/۴۲۹/۵۰۰ متن انگلیسی نشان می‌داد و خطای صرافی‌ها `[object Object]` چاپ می‌شد؛ هر دو اصلاح شد.
- `start.bat`: نقل‌قول تودرتوی باز کردن مرورگر (که cmd خراب می‌کند)، بازکردن مرورگر با `explorer`، بررسی نسخه پایتون، انتخاب پورت آزاد، و راهنمای نصب با آینه.

### ۱۴. بازطراحی برای کاربر غیرفنی: «خانه»، کارمزد و رسید (فارسی)

هدف این مرحله فقط یک چیز است: کسی که کدنویسی نمی‌داند در ده ثانیه بفهمد **الان وقت خوبی است یا نه**،
**بعد از همه کارمزدها چقدر می‌ماند** و **دقیقاً چه کاری به‌ترتیب انجام دهد**. همه محاسبات قبلی، آداپترها
و تست‌ها دست‌نخورده مانده‌اند؛ این مرحله یک لایه تصمیم و نمایش روی همان موتور است.

#### ۱۴.۱ صفحه‌ها و ناوبری
- `/` **خانه**: نوار بالا (نام برنامه، یک نشانگر اتصال که به عیب‌یابی می‌رود، شمارش معکوس، توقف، پوسته)
  + «وضعیت شما» + کارت نتیجه + گیج بازار + رسید «از صفر تا صد» + حداکثر ۵ گزینه دیگر + راهنمای کارمزد + پاورقی.
- `/fees` **کارمزدها**: جدول کارمزد برداشت با برچسب اطمینان و عمر، کارمزد معامله، جدول منابع هر صرافی،
  دکمه «خواندن خودکار» و «دستیار کارمزد».
- `/guide` راهنما (بدون جاوااسکریپت): جریان جدید، واژه‌نامه، ریسک‌ها.
- `/dashboard` همان داشبورد قبلی به‌عنوان «ابزارهای پیشرفته» (جدول کامل، پنج تب، عیب‌یابی، شبیه‌سازی).
- **هیچ پنجره/کشو/بنری در بارگذاری صفحه باز نمی‌شود**؛ همه دیالوگ‌ها فقط با کلیک باز می‌شوند و تست
  `tests/ui_home_smoke.cjs` این را با `dialog[open]` بررسی می‌کند. نوار «چه چیزی مانده» فقط وقتی
  موردی وجود دارد دیده می‌شود، با ✕ بسته می‌شود و امضای همان فهرست ذخیره می‌شود تا دوباره باز نشود.

#### ۱۴.۲ چهار تصمیم، همیشه با دلیل
`app/decision.py` یک تابع خالص `decide(context)` است که خانه، `/api/decide` و رسید همه از آن استفاده می‌کنند:

| نشان | معنی | شرط |
|---|---|---|
| ✔ برو | شرایط مناسب است | سود خالص > حاشیه ایمنی، داده تازه، عمق کافی، کارمزدهای لازم «تأیید» و تازه، عمر فرصت ≥ زمان انتقال |
| ⏳ صبر کن | سود هست ولی کافی/مطمئن نیست | سود بین صفر و حاشیه ایمنی، یا کارمزد تخمینی/قدیمی، یا عمر فرصت < زمان انتقال |
| ✕ نه | سود نمی‌دهد | سود خالص بعد از همه کارمزدها و «هزینه‌های دیگر» ≤ 0 |
| ؟ نامطمئن | نمی‌توان گفت | کارمزد نامعلوم، داده/شبکه ناقص، عمق ناکافی، قیمت کهنه |

زیر نشان، چک‌لیست فارسی با ✓/⚠/✗ می‌آید (تازگی قیمت، داده‌های لازم، عمق بازار، سود بعد از کارمزدها،
حاشیه ایمنی، کارمزدها، عمر فرصت، هزینه‌های دیگر، اختلاف خام در برابر سود خالص). آستانه‌ها
(`safety_margin`، `coin_margins`، `other_costs_toman`، `fee_stale_days`، `gauge_days`) در تنظیمات پیشرفته‌اند.

#### ۱۴.۳ رسید «از صفر تا صد»
`app/receipt.py` از همان `detail.taker.steps` موتور استفاده می‌کند؛ بنابراین عدد رسید هرگز با جدول
نمی‌تواند اختلاف داشته باشد. هر مرحله: شماره، کار (خرید/برداشت/فروش/تبدیل)، صرافی، مبلغ ورودی و خروجی
با واحد، هزینه همان مرحله (در واحد خروجی + درصد نسبت به بهترین قیمت همان دفتر)، زمان تقریبی شبکه و
برچسب اطمینان کارمزد. پایان رسید: سرمایه شروع، مبلغ نهایی (USDT و تومان)، سود خالص و درصد، جمع کارمزد و
لغزش، هزینه‌های دیگر (خط جدا)، سرمایه سربه‌سر، کمترین سرمایه به‌صرفه، «چه چیزی می‌تواند خراب شود» و
چک‌لیست. سه دکمه: کپی متن، ذخیره به‌عنوان معامله آزمایشی، خروجی CSV.

**قاعده بازبینی (invariant):** `capital + profit = final` و پیوستگی مانده هر مرحله
(`amount_in` مرحله بعد = `amount_out` مرحله قبل). اگر نخواند، خود رسید به کاربر هشدار می‌دهد. تست:
`tests/test_receipt_engine.py` (همین دو قاعده + تطابق با موتور + خطای صریح برای مسیر بدون کارمزد).

#### ۱۴.۴ کارمزدها: منبع، اطمینان و عمر
هر کارمزد چهار وضعیت دارد: **تأیید خودکار** (`auto`)، **تأیید دستی** (`manual`)، **تخمینی** (`estimated`)
و **نامعلوم** (`unknown`). کارمزد قدیمی‌تر از `fee_stale_days` (پیش‌فرض ۱۴ روز) «نیاز به بررسی دوباره»
می‌گیرد. در SQLite ستون‌های `confidence/source/fetched_at/note` به `network_fees` اضافه شده و مهاجرت
خودکار است (`migrate_fee_columns`)؛ پشتیبان‌های قدیمی هم بدون خطا بازگردانی می‌شوند.

| صرافی | خودکار؟ | نقطه پایانی/مستند | فیلدها | چه چیزی در دسترس نیست | راه جایگزین |
|---|---|---|---|---|---|
| نوبیتکس | تلاش می‌شود، **تأیید نشده** | `GET https://apiv2.nobitex.ir/v2/options` (مستند عمومی) | ارز، شبکه، کارمزد برداشت، حداقل، فعال/غیرفعال — با خواندن تحمل‌پذیر | نام فیلدها با پاسخ واقعی در این محیط دیده نشده؛ کارمزد معامله در این نقطه پایانی نیست | «دستیار کارمزد» → صفحه رسمی کارمزد نوبیتکس |
| والکس | **خودکار ندارد** | نقطه پایانی عمومی مستند برای کارمزد پیدا نشد | — | کارمزد برداشت/حداقل/شبکه از API عمومی | «دستیار کارمزد» → صفحه رسمی والکس |
| بیت‌یونیکس | **خودکار ندارد** | نقاط پایانی عمومی مستند (فهرست جفت‌ارز، آخرین قیمت، عمق) کارمزد ندارند | — | کارمزد برداشت و شبکه | «دستیار کارمزد» → صفحه رسمی بیت‌یونیکس |

- آدرس صفحه رسمی هر صرافی در `AppSettings.fee_pages` است و از تنظیمات قابل تغییر است (`DEFAULT_FEE_PAGES`).
- «خواندن خودکار» یک بار در روز در حلقه پس‌زمینه اجرا می‌شود و با دکمه هم قابل اجراست. ردیف خودکار
  **هرگز روی کارمزد دستیِ تازه‌تر** نوشته نمی‌شود. اگر پاسخ نفهمد یا نرسد، همان پیام فارسی با دلیل
  نمایش داده می‌شود و هیچ عددی ساخته نمی‌شود.
- **هیچ عددی حدس زده نمی‌شود**؛ کارمزد بدون مقدار «نامعلوم» می‌ماند و مسیر را «نامطمئن» می‌کند.
- **بارگذاری تنبل:** فقط ~۱۰ مسیر با بیشترین اختلاف خام (`fee_candidate_limit`) بررسی می‌شوند و خانه
  می‌گوید «برای این N ارز کارمزد لازم است» با یک کلیک به صفحه کارمزدها.
- **دستیار کارمزد** (`app/fee_text.py`): چسباندن متن صفحه رسمی یا CSV (`coin,network,fee,minimum`).
  ارقام فارسی/عربی، `٫`/`٬`، خطوط تک‌فاصله‌ای، شبکه‌های TRC20/BEP20/ERC20/BTC/SOL/TON/…، نام‌های
  فارسی ارز و شبکه، ردیف تکراری، حداقل کوچک‌تر از کارمزد (جابه‌جایی) و خطاهای هر خط جداگانه مدیریت
  می‌شود؛ پیش‌نمایش قبل از ذخیره. ردیف‌های خراب هرگز ذخیره نمی‌شوند.
- **زمان تقریبی انتقال** هر شبکه ویرایش‌پذیر است (`transfer_minutes`، پیش‌فرض‌های ~۵/۵/۱۰/۶۰ دقیقه) و در
  رابط «تقریبی» برچسب می‌خورد.
- **هزینه‌های دیگر** (`other_costs_toman`، پیش‌فرض ۰) یک خط جدا در رسید است و از سود کم می‌شود.

#### ۱۴.۵ گیج بازار
`app/gauge.py` سود بهترین مسیر همین لحظه را با تاریخچه ثبت‌شده (پیش‌فرض ۷ روز، `gauge_days`) مقایسه
می‌کند: «بهتر از X٪ از زمان‌های همین بازه» + محدوده معمول (چارک‌ها)، بهترین، بدترین و عدد فعلی. تا
۲۴ ساعت داده جمع نشود، می‌نویسد «برای این بخش حداقل ۲۴ ساعت داده لازم است» و هیچ عددی نمی‌سازد.
این متن صریحاً می‌گوید **تاریخچه است، نه پیش‌بینی**. تاریخچه هر اسکن در جدول `best_history` ذخیره می‌شود.

#### ۱۴.۶ وضعیت شما و راه‌اندازی
«وضعیت شما» صرافی‌ها، محل پول (تومان در ایران / تتر / موجودی در هر دو طرف) و سرمایه را نشان می‌دهد؛
موجودی در هر دو طرف یعنی حالت **پیش‌تأمین** و حذف هزینه انتقال. راه‌اندازی سه مرحله دارد (صرافی‌ها و محل
پول؛ سرمایه؛ پیام/بازه به‌روزرسانی) و «۵۰ میلیون» را هم می‌فهمد. مسیرهایی که صرافی‌شان را ندارید از
فهرست حذف می‌شوند و دلیلش نوشته می‌شود (`app/setup.py`).

#### ۱۴.۷ دسترس‌پذیری و متن‌ها
RTL کامل، پایه ۱۷px (و ۱۶px در موبایل)، روشن/تیره/هم‌رنگ سیستم، فونت وزیرمتن همراه برنامه، بدون CDN،
`[hidden]{display:none!important}` به‌عنوان محافظ، متن ساده با اصطلاح فنی فقط در توضیح، و پاورقی دائمی:
«تخمینی، تضمینی نیست، مشاوره مالی نیست، قیمت در زمان انتقال تغییر می‌کند، قواعد/قانونی/مالیاتی را خودتان
بررسی کنید، اول با مبلغ کم آزمایش کنید.» عبارت «سود تضمینی» هیچ‌جا استفاده نمی‌شود.

#### ۱۴.۸ APIهای جدید
`GET /api/home`، `GET /api/decide?key=`، `GET /api/receipt?key=`، `GET /api/receipt.csv?key=`،
`GET /api/gauge`، `GET|PUT /api/setup`، `GET /api/fees`، `POST /api/fees/parse`، `POST /api/fees/save`،
`POST /api/fees/refresh`، `GET /api/fees/needed`. دیالوگ‌های قبلی و همه APIهای قبلی دست‌نخورده‌اند.

#### ۱۴.۹ تست‌های این مرحله
```sh
.venv/bin/python -m pytest -q                       # ۳۱۸ تست
NODE_PATH=/tmp/jsdom-env/node_modules node tests/ui_home_smoke.cjs
NODE_PATH=/tmp/jsdom-env/node_modules node tests/ui_fees_smoke.cjs
```
- `tests/test_decision.py`: هر چهار تصمیم + همه شاخه‌های چک‌لیست (تخمینی، قدیمی، عمق، عمر، هزینه دیگر).
- `tests/test_receipt_engine.py`: تطابق با موتور، پیوستگی مانده، `capital+profit=final`، برچسب کارمزد هر
  مرحله، خط جدا هزینه‌های دیگر، خروجی متن/CSV و مسیر بدون کارمزد.
- `tests/test_fee_confidence.py` و `tests/test_fee_text_parser.py`: برچسب‌ها، عمر/کهنگی، کارمزد معامله،
  متن صفحه و CSV (درست، شلوغ، خراب، تکراری، رقم فارسی، صفر).
- `tests/test_home_api.py`: خانه/تصمیم/رسید/گیج/کارمزد/راه‌اندازی + بارگذاری تنبل + بازار خالی + بازار منفی.
- `tests/test_setup.py`، `tests/test_gauge.py`، `tests/test_agent_headers.py` (هدر User-Agent هر صرافی).
- `tests/ui_home_smoke.cjs` (jsdom): هیچ دیالوگ بازی در بارگذاری، ناوبری، کارت نتیجه، رسید، گیج، گزینه‌های
  دیگر، نوار، توقف، ویزارد سه‌مرحله‌ای (ذخیره یک‌بار)، حالت خالی، پوسته و خطای API.
- `tests/ui_fees_smoke.cjs` (jsdom): جدول کارمزد و برچسب‌ها، کارمزد معامله، جدول منابع، دستیار (پیش‌نمایش →
  ذخیره) و پیام خواندن خودکار.

#### ۱۴.۱۰ چیزهایی که در این مرحله هنوز تأیید نشده است
- **هیچ‌کدام از نقاط پایانی کارمزد با پاسخ واقعی امروز صرافی‌ها آزموده نشده**؛ در `fee_sources.SOURCES`
  وضعیت هر سه صرافی `unconfirmed` است و فقط نوبیتکس نقطه پایانی مستند دارد.
- **کارمزد معامله خودکار خوانده نمی‌شود** (هیچ نقطه پایانی عمومی مستند برای آن پیدا نشد)؛ پیش‌فرض‌های
  همراه برنامه «تخمینی» برچسب می‌خورند و مانع تصمیم «برو» می‌شوند تا خودتان تأیید کنید.
- **زمان‌های انتقال تقریبی و دستی‌اند**؛ اندازه‌گیری زنده نداریم.
- **ظاهر واقعی (فونت، اعداد فارسی، RTL) فقط در jsdom بررسی شده**؛ در مرورگر واقعی روی لپ‌تاپ ببینید.
- **«پیام وقتی فرصت پیدا شد»** فعلاً فقط یک تنظیم ذخیره‌شده است؛ نوتیفیکیشن مرورگر همان مسیر قبلی
  (دکمه اعلان در داشبورد پیشرفته) است و در این صفحه ساخته نشده.

### ۱۵. رفع اشکال «دکمه را باید دو بار بزنم» (فارسی)

شکایت این بود: در حین کار کردن برنامه، بعضی دکمه‌ها با یک کلیک کار نمی‌کنند و باید یک یا دو بار
دیگر زده شوند. علت واقعی پیدا و رفع شد؛ خلاصه‌اش یک قاعده مرورگر است: مرورگر رویداد `click` را روی
**نزدیک‌ترین جد مشترک** هدفِ `mousedown` و `mouseup` می‌فرستد. اگر بین این دو لحظه، یک رندر دوره‌ای
گره‌ای را که رویش کلیک کرده‌اید از صفحه بردارد، کلیک به یک گره جدا‌شده می‌رسد و هیچ کد شما اجرا نمی‌شود.
کاربر «هیچ اتفاقی نیفتاد» می‌بیند و دوباره کلیک می‌کند.

#### ۱۵.۱ علت‌ها، جای دقیق، و تست پوشش‌دهنده

| # | علت | کجا | چرا «دو کلیک» می‌شد | رفع | تست |
|---|-----|-----|----------------------|-----|-----|
| ۱ | هر به‌روزرسانی، کل بدنه جدول را از نو می‌ساخت؛ دقیقاً وقتی اشاره‌گر روی جدول بود (`isHovering()` همان شاخه را انتخاب می‌کرد) | `ui.js: renderTable` و `animateTo` | `tbody.innerHTML=…` و بعد `innerHTML` هر ردیف + جدا و دوباره چسباندن همه ردیف‌ها؛ ستاره پین و ردیف زیر انگشت نابود می‌شد | ردیف‌ها با کلید نگه داشته می‌شوند و سلول‌به‌سلول وصله می‌شوند؛ مرتب‌سازی تا بیرون رفتن اشاره‌گر صبر می‌کند؛ یک شنونده واگذارشده روی `#rows` | `tests/ui_click_test.cjs` (ردیف، ستاره پین) |
| ۲ | چیپ‌های صرافی و شش دکمه «مبلغ سریع سرمایه» هر ۳ تا ۱۰ ثانیه از نو ساخته می‌شدند | `ui.js: renderSummary` / `renderChips` / `renderCapital` | `innerHTML=''` روی ظرف چیپ‌ها و پریست‌ها در هر poll | ظرف یک‌بار ساخته می‌شود؛ چیپ‌ها با کلید و متن فقط وقتی عوض شده باشد | `ui_click_test` (چیپ بالا، چیپ کارت خلاصه، پریست سرمایه) |
| ۳ | نوار «راه‌اندازی کامل نشده» در هر poll دو `onclick` را دوباره می‌نوشت | `ui.js: renderWizardBanner` | نوشتن دوباره شنونده و متن در هر poll | یک‌بار سیم‌کشی می‌شود و نوار فقط وقتی وضعیتش عوض شود لمس می‌شود | `ui_click_test` (بستن نوار) |
| ۴ | هر کلید در جعبه فیلترها کل جدول را از نو می‌ساخت | `ui.js: filters.oninput` | `renderTable(false)` با `innerHTML` در هر ورودی | وصله‌کردن درجا + یکی‌شدن در یک فریم (`requestAnimationFrame`) | `ui_click_test` (چیپ فیلتر) |
| ۵ | در صفحه «خانه»، کارت‌های «گزینه دیگر»، آیتم‌های نوار بالای صفحه و رسید درون‌صفحه هر ۵ تا ۱۵ ثانیه از نو ساخته می‌شدند | `home.js: renderOthers` / `renderBanner` / `renderReceiptInline` | `textContent=''` روی ظرف و ساخت دوباره دکمه‌ها/لینک‌ها | کارت‌ها با کلید و متن وصله می‌شوند؛ هر بخش امضای خودش را دارد و بدون تغییر لمس نمی‌شود | `tests/ui_home_click_test.cjs` (کارت گزینه دیگر، نوار، کلیک روی لینک) |
| ۶ | یک poll خطادار کارت نتیجه را `hidden` می‌کرد | `home.js: load()` | دکمه‌های «رسید» و «معامله آزمایشی» زیر انگشت ناپدید می‌شدند | رندر در حین فشردن/فوکوس/باز بودن دیالوگ عقب می‌افتد و با داده تازه اعمال می‌شود | `ui_home_click_test` (نگه‌داشتن و اعمال بعد از بستن) |
| ۷ | پیام شناور (toast) با `position:fixed; z-index:30` حدود ۳٫۲ ثانیه روی دکمه‌ها می‌نشست و کلیک را می‌خورد؛ حباب راهنمای «؟» هم روی سرستون جدول بود | `home.css: .toast`، `ui.css: .help-pop` | عنصر شفاف/نیمه‌شفاف روی دکمه، هدف کلیک را می‌گرفت | `pointer-events: none` روی هر دو (هیچ‌کدام کنترلی ندارند) | `ui_home_click_test` (قاعده CSS) |
| ۸ | دکمه در حین درخواست `disabled` می‌شد و بعضی درخواست‌ها هیچ timeout نداشتند (`home.js`, `fees.js`) | `home.js: api()`، `fees.js: api()` | با شبکه کند یا درخواست گیرکرده، دکمه تا بازخوانی صفحه مرده می‌ماند | timeout ۱۵ ثانیه‌ای با `AbortController`، فعال‌سازی در `finally`، بازخورد فوری روی دکمه | `ui_home_click_test` (به‌روزرسانی الان) |
| ۹ | درخواست‌های هم‌پوشان و پاسخ کهنه | `ui.js: load()`، `home.js: load()` | هر کلیک روی پین/سرمایه/تب یک `load` تازه راه می‌انداخت؛ چند رندر هم‌زمان، احتمال برخورد با کلیک را چند برابر می‌کرد | فقط یک درخواست در جریان، شماره ترتیب و دور ریختن پاسخ کهنه، poll بعدی همیشه زمان‌بندی می‌شود | `ui_click_test` (۲۰ رندر پشت‌سرهم) |
| ۱۰ | پاسخ دیرِ جزئیات، دراور را بعد از بستن دوباره باز می‌کرد | `drawer.js: openDrawer/closeDrawer` | stale response؛ کاربر فکر می‌کرد کلیکش کار نکرد و دوباره می‌زد | شماره ترتیب دراور؛ پاسخ کهنه نادیده گرفته می‌شود | `ui_controls_smoke` (باز/بسته دراور) |
| ۱۱ | رندر سنگین روی رشته اصلی (۴۰۰ ردیف × ۱۲ سلول با HTML رشته‌ای) و جابه‌جایی ردیف‌ها با انیمیشن زیر اشاره‌گر | `ui.js: renderTable/animateTo`، `home.css` (بالا پریدن ۱ پیکسلی دکمه‌ها در hover) | کلیک‌هایی که در پنجره رندر می‌افتند به گره تازه می‌رسند یا هدف جابه‌جا می‌شود | صفحه ۲۰۰ ردیفی با «نمایش بیشتر»، پرش کامل رندر وقتی داده تغییر نکرده، حذف `translateY(-1px)` از hover دکمه‌ها | `ui_click_test` (بودجه زمان و «نمایش بیشتر») |

#### ۱۵.۲ قاعده‌ای که حالا رعایت می‌شود
هیچ رندری گره‌ای را که در حال فشرده‌شدن، هاور یا فوکوس است جایگزین نمی‌کند. اگر داده تازه برسد در
حالی که pointer پایین است، ورودی/انتخابگر فوکوس دارد یا دیالوگ/دراور باز است، رندر عقب می‌افتد و
**بعد** از رها شدن (یا بسته شدن دیالوگ) با تازه‌ترین داده اعمال می‌شود؛ اسکرول و فوکوس دست نمی‌خورند.
شمارنده «به‌روزرسانی بعدی» همچنان هر ثانیه فقط یک گره متنی را می‌نویسد.

#### ۱۵.۳ تست‌های این مرحله
```sh
.venv/bin/python -m pytest -q                                   # ۳۱۸ تست سبز (بدون تغییر)
NODE_PATH=/tmp/jsdom-env/node_modules node tests/ui_click_test.cjs        # ۲۸ بررسی
NODE_PATH=/tmp/jsdom-env/node_modules node tests/ui_home_click_test.cjs   # ۱۸ بررسی
NODE_PATH=/tmp/jsdom-env/node_modules node tests/ui_smoke.cjs             # و بقیه smokeها
```
- `tests/ui_click_test.cjs`: همان قاعده کلیک مرورگر را شبیه‌سازی می‌کند (`mousedown` → یک رندر → آیا
  همان گره هنوز در صفحه است؟) و برای ۱۹ کنترل داشبورد اجرا می‌شود؛ سپس ۲۰ رندر پشت‌سرهم و شمارش
  «یک کلیک = یک اقدام»، نگه‌داشتن فوکوس/هویت گره، عقب‌انداختن رندر در حین فشردن و هاور، بودجه زمان
  با ۴۰۰ ردیف، «بدون تغییر داده، هیچ گره‌ای ساخته نمی‌شود» (MutationObserver) و خواندن شماره رتبه با
  ترتیب دیده‌شده در حین هاور.
  روی کد قبلی ۱۰ از ۲۸ بررسی شکست می‌خورد (۱۸/۲۸ سبز).
- `tests/ui_home_click_test.cjs`: ۱۸ بررسی برای صفحه خانه؛ روی کد قبلی ۱۳ بررسی شکست می‌خورد.
- **ابزار:** فقط jsdom ۲۶ در این محیط هست (Playwright/Chromium نصب نیست). jsdom نه چیدمان دارد نه
  hit-testing، پس «هدف کلیک» را با هویت گره شبیه‌سازی می‌کنیم و زمان واقعی کلیک، جابه‌جایی چیدمان،
  بالاپریدن hover و رویدادهای لمسی تأیید نشده‌اند؛ این‌ها را باید روی لپ‌تاپ دید.

#### ۱۵.۴ چیزهایی که باید روی لپ‌تاپ (کروم) با به‌روزرسانی روشن بررسی شود
1. داشبورد `/dashboard` با فاصله ۵ ثانیه: پشت‌سرهم روی ردیف‌ها کلیک کنید تا دراور باز شود، ستاره پین
   را بزنید، «قفل ترتیب» و «ساده/پیشرفته» و چیپ‌های صرافی را چند بار بزنید — هر کلیک باید همان بار اول
   کار کند.
2. صفحه خانه `/`: دکمه «به‌روزرسانی الان»، کارت‌های «گزینه دیگر»، «ورود دستی»/«توقف»، دیالوگ رسید و
   ویزارد را در حین کار کردن poll بزنید. بعد از هر toast (پیام پایین صفحه) بلافاصله دکمه‌ای زیر آن را
   بزنید؛ باید کار کند.
3. با شبکه کند/فیلترشکن: «به‌روزرسانی الان» را بزنید و ببینید دکمه فوراً غیرفعال و بعد از پاسخ (یا
   حداکثر ۲۰ ثانیه) دوباره فعال می‌شود.
4. حالت «پیشرفته» با بازار پرردیف: «نمایش بیشتر» باید ردیف‌های بعدی را اضافه کند و اسکرول بپرد.
