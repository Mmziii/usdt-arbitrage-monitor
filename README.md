# USDT arbitrage monitor
Local, read-only Wallex ↔ Nobitex monitor. No API keys, account access, orders or withdrawals. Persian RTL dashboard with bundled Vazirmatn (OFL license in `app/static/OFL.txt`). Requires Python 3.10+.

## Install & run (three commands)
Run from this repository directory:
```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Open http://127.0.0.1:8000. On Windows replace `.venv/bin/python` with `.venv\Scripts\python.exe`. Stop with Ctrl+C. Keep the default loopback bind on your laptop: this is a local app, not a multi-user authenticated service.

Optional: copy `.env.example` to `.env` before starting. Refresh defaults to 10 seconds; edit refresh interval, profit threshold and exchange fees in Settings (persisted in SQLite). Default fees: Wallex maker .25%, taker .3%, withdrawal .8 USDT; Nobitex maker/taker .25%, withdrawal .7 USDT. SQLite database path defaults to `history.sqlite3`, relative to the working directory. Back up this file for history/settings; it is ignored by Git. History chart shows latest 1,000 samples; CSV exports up to 1,000,000 latest samples in chronological order with epoch UTC timestamps, toman prices, gross directional spreads and live/manual labels.

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

Tests cover a hand-calculated 105,644 toman return from 100,000 capital, both-side depth walking, insufficient liquidity, withdrawal exhaustion, a profitable window before deeper losses, exchange formats/unit conversion, API failure/manual fallback, settings and CSV. Transfer time, adverse price movement, withdrawal limits/caps and maintaining toman balances on both exchanges remain operational risks, not modeled guarantees.
