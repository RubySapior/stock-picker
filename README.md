# AI Port-picker — Stock Picker

A self-updating, AI-assisted portfolio dashboard built on the **HyperGrowth Sharpe Barbell** strategy. `update.py` fetches live prices, runs the take-profit / stop-loss engine, parks idle cash, executes human-approved market orders from the AI verdict, and regenerates a static `dashboard.js` that `index.html` renders. Prices and news refresh automatically every hour via GitHub Actions.

Live site: **https://rubysapior.github.io/stock-picker/** (GitHub Pages, served from `main`).

## What it is

A conviction-first, leveraged growth book hedged with crisis-alpha sleeves, tracked against SPY. The **AI Sentiment Decision Layer** (Gemini via OpenRouter) reads Tier A market data each market open, scores theories and fears, and emits proposals — which a human approves into market orders that execute deterministically at the live price. The AI never trades on its own: deterministic rules (TP/SL, sector caps, vol-halt) always override it.

Strategy notes live in `portfolio.json` → `meta` (each position's sleeve, sector, and leverage is defined there too).

## Where this is going (roadmap)

The end goal is a **paid subscription service for other users** — the tool is the product, not us trading to make money. The AI ships universal signals the user operates (one-tap approval in their own Alpaca account); a tool everyone runs the same way needs no RIA registration to launch.

- **UI v1.0** — accounts: sign-in, and every user gets a personalized AI tuned to their risk tolerance and focus.
- **Engine v1.0** — the AI makes **100% of the trades** from real-time sentiment with AI analysis, rebalancing weekly across hedges / leading sectors.
- **Business staging** — Phase 1: universal signals + paper trading + user-authorized live execution via **Alpaca**. Phase 2 (~6 months before launch): RIA registration (Form ADV, compliance program). Phase 3 (registered): AI may auto-execute per-subscriber.
- **Trust is the moat** — public track record, paper-trading history, transparent methodology, no miracle claims.

Full design notes: `CHANGELOG.md` → "Path to v1 — business & legal staging" and "AI Sentiment Decision Layer".

## Files

| File | Purpose |
| --- | --- |
| `portfolio.json` | **Source of truth.** Positions, account, theories, events, limits, sector caps, orders. Hand-edited. |
| `update.py` | Daily updater: fetch prices → check TP/SL exits → execute approved market orders → deploy cash to SGOV → re-entry protocol → snapshot history → write `dashboard.js`. |
| `news.py` | Fetches Yahoo Finance RSS for held tickers; sentiment-scored, theory-tagged stories for the dashboard. |
| `fears.py` | Market Fear Gauge: F1–F8 crash scenarios, complacency regime, hedge-sizing recommendations. |
| `ai_sentiment.py` | AI Sentiment Decision Layer (algo 0.6.0): Gemini verdict call via OpenRouter, fact-delta ledger, theories/fears/bullish translators. Read-only — proposals only. |
| `dashboard.js` | **AUTO-GENERATED** `window.DASH` payload. Never hand-edit (regenerate with `update.py`). |
| `index.html` | Dashboard skeleton (all sections filled by `app.js`). |
| `app.js` | Renders every section of the dashboard from `window.DASH`. |
| `help.html` / `theories.html` / `trades.html` | Help site, Theory Archive (flash-card wheel), Trade Archive. |
| `serve.py` | Optional local server: serves the page and exposes `POST /refresh` so the Update button runs `update.py`. |
| `run.bat` | Windows shortcut: runs `python update.py`. |
| `.github/workflows/update.yml` | GitHub Actions: runs `update.py` every hour (every 6 min during US market hours), commits any data changes. |

## Data flow

```
portfolio.json (source of truth)
      │  update.py  (fetch prices, TP/SL exits, market orders, SGOV park, re-entry, snapshot)
      ▼
dashboard.js (window.DASH)  ← AUTO-GENERATED, never hand-edit
      │
      ▼
index.html + app.js  (renders the dashboard)
```

## Run it

```sh
python update.py     # fetch prices + news, regenerate dashboard.js
python serve.py      # optional: http://localhost:8000 (Update button posts /refresh)
```

Or just open `index.html` via file:// double-click — it works with the last-generated `dashboard.js`.

## Strategy mechanics (in `update.py`)

- **No idle cash** — spare cash is auto-parked in **SGOV** (0–3 month T-bills) so dry powder never sits idle.
- **Index-referenced stops** — leveraged funds (3x/2x) stop against their 1x underlying (e.g. TQQQ→QQQ −8%), so a violent leveraged day or decay drift can't whipsaw the stop. The wrapper-level `stop_loss_pct` is only a wide gap-through backstop. Take-profits check on the wrapper.
- **Re-entry protocol** — a stop is a *vol-halt*, not a death. Linked theories are PAUSED; if the 1x underlying reclaims its level for 2 consecutive sessions the theory is re-affirmed and the position re-entered; no reclaim in 60 days → theory formally ABANDONED.
- **Market orders (algo 0.6.0)** — a successful AI verdict refreshes the human-approved `orders` list in `portfolio.json`; pending orders execute at the live price on the next market-open run. Buys redeem SGOV, sells realize into cash (re-parked in SGOV).
- **Passive rebalance audit** — once per calendar quarter, any sector whose *effective* (leverage-adjusted) exposure drifts from its limit — no tolerance band, however small — produces a flag. It never trades; it asks for a conviction review. SGOV (Short-Term Bonds) is exempt so dry powder grows freely.

## GitHub Actions

`.github/workflows/update.yml` runs `update.py` on a schedule (hourly; every 6 minutes during US market hours to catch intraday moves) and commits any changes to `dashboard.js` / `portfolio.json`. Manual runs via **workflow_dispatch**.

> Note: `dashboard.js` is generated output — pull the latest before hand-editing `portfolio.json`, and push both together.