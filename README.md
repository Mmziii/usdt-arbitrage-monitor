# USDT arbitrage monitor
Local, read-only Wallex ↔ Nobitex monitor. No API keys, account access, orders or withdrawals. Persian RTL dashboard with bundled Vazirmatn (OFL license in `app/static/OFL.txt`). Requires Python 3.10+.

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
- Depth on demand: `GET https://api.wallex.ir/v1/depth?symbol=...` and `GET https://apiv2.nobitex.ir/v3/orderbook/...` ([docs](https://apidocs.nobitex.ir/market_data/دریافت-دفتر-سفارشات-نسخه-۳)). At most two positive-gross-spread markets are automatically checked per cycle, rotating through candidates; opening a detail view also fetches depth. Until depth is available, the overview does not claim a net result. Liquidity filtering uses the smaller of the total source ask and destination bid quote values in the fetched depth, an approximation, not a fill guarantee.

Discovery is cached in memory for six hours and can be refreshed manually. Overview defaults to 30 seconds. The scanner allows at most two concurrent requests per exchange and 18 requests per exchange per rolling minute (including retries), with exponential backoff on 429/5xx and network timeouts. The original dashboard's separate USDT depth poll is not included in this scanner budget. Requests time out after eight seconds. Tickers use local receipt time because the bulk fields used have no exchange timestamp; Nobitex depth uses `lastUpdate`, Wallex depth uses local receipt time. Quotes or depth older than 120 seconds are not used for profit. Bulk failure is shown globally; missing/invalid individual tickers are shown per market. The data and endpoints must be checked against live responses on your laptop.

Symbols are case-normalized and matched exactly; known collision/migration tickers and numeric-prefix tokens are excluded for review. No multiplier or renamed-token equivalence is guessed. Exact ticker equality alone cannot prove contract identity: always independently check the asset and network on both exchanges. The conservative rules may exclude valid assets and do not detect every possible ticker collision. A review list is displayed in the overview.

### Network fee table
The new table starts **empty**, including for USDT; the original dashboard's legacy USDT withdrawal defaults are not applied to the new scanner. We did not find a documented public endpoint providing a complete, reliable per-network fee and support table for both exchanges; no account APIs are used. Verify and enter the current information manually. Add one row for each exchange for the same uppercase coin and exact network identifier, set supported on both sides, and enter the source withdrawal fee and minimum in **coin units**. Unknown fee or minimum stays blank/null and blocks that direction's net profit; an unknown minimum is reported separately from an unknown withdrawal fee; do not enter zero unless it is actually zero. No matching supported network blocks profit. The network selector chooses among configured common networks. Information entered here is not automatically updated for suspended withdrawals/deposits. JSON/CSV import replaces the whole table only when saved, and export downloads the currently edited table. SQLite persists the settings and fee table. Example JSON (illustrative values only, not exchange fees):

```json
[
  {"exchange":"wallex","coin":"BTC","network":"BTC","withdrawal":null,"minimum":null,"supported":true},
  {"exchange":"nobitex","coin":"BTC","network":"BTC","withdrawal":null,"minimum":null,"supported":true}
]
```

CSV columns are `exchange,coin,network,withdrawal,minimum,supported`; leave unknown numbers empty, use `true` or `false` for support. Search and exchange filters do not delete hidden rows. The missing-withdrawal-fee filter lists discovered coins even if they have no rows: a coin is included if at least one selected exchange has no supported row with a known withdrawal fee. An exchange filter restricts that check to the selected exchange; this filter does not establish that a common network exists.

For quick entry, paste one line per fee as `TRX, TRC20, wallex, 1` (or `TRX, TRC20, wallex, 1, 10` with minimum as the fifth column). The preview reports line errors and duplicates; nothing is saved by preview. After resolving all errors, apply to the table, verify it, then save the table. Updates preserve existing support and an existing minimum when the fifth column is omitted. Newly added rows have **support unchecked** and minimum unknown, never guessed; confirm both exchanges' network support and minimum withdrawal manually. Import and paste modify only the editor until Save.

Global maker/taker trading fees are shared by all coins of each exchange/quote pair; change all four pairs in the overview or the original dashboard settings. Existing saved toman rates are preserved on upgrade; new USDT rates start at the stated defaults. Legacy per-coin trading overrides are ignored and removed on the next scanner-settings save. No result uses a missing withdrawal fee or unknown minimum. Without a confirmed common network or known withdrawal fee, the overview labels the available ticker spread **gross only**, not net profit. The minimum withdrawal is checked against the post-buy-fee coin amount before subtracting the withdrawal fee. Maker uses the same immediate depth and is hypothetical.

The detail view includes top book levels, calculation steps, network selection, spread history and per-market CSV. All-market CSV is also available. Samples and original history are pruned periodically, including during overview fetch failures, according to the configurable retention period (default 30 days). CSV is limited to the latest million rows. Browser alerts are opt-in, trigger only when a watched coin's taker net result crosses the threshold, and run only while the overview is open. The original dashboard retains its own alert behavior. Liquidity, deposit minimums, memo/tag requirements, network confirmations, suspensions, delistings, and price changes during transfer remain risks to verify manually.
