# Stock Picker

A self-updating portfolio dashboard for the  strategy. `update.py` fetches live prices, runs the take-profit / stop-loss engine, parks idle cash, and regenerates a static `dashboard.js` that `index.html` renders. Prices and news refresh automatically every hour via GitHub Actions.

## What it is

A conviction-first, leveraged growth book hedged with crisis-alpha sleeves, tracked against SPY. Strategy notes live in `portfolio.json` → `meta` (each position's sleeve, sector, and leverage is defined there too).

## Files

| File | Purpose |
| --- | --- |
| `portfolio.json` | **Source of truth.** Positions, account, theories, events, limits, sector caps. Hand-edited. |
| `update.py` | Daily updater: fetch prices → check TP/SL exits → deploy cash to SGOV → re-entry protocol → snapshot history → write `dashboard.js`. |
| `news.py` | Fetches Yahoo Finance RSS for held tickers; sentiment-scored, theory-tagged stories for the dashboard. |
| `ai_sentiment.py` | AI Sentiment Decision Layer (algo 0.5.9): LLM verdict call (Zen default — opencode.ai/zen, paid zero-retention model / DeepSeek / Gemini), fact-delta ledger, theories/fears/bullish translators. Wired into `update.py`, enabled via `meta.ai.enabled`. |
| `dashboard.js` | **AUTO-GENERATED** `window.DASH` payload. Never hand-edit (regenerate with `update.py`). |
| `index.html` | Dashboard skeleton (all sections filled by `app.js`). |
| `app.js` | Renders every section of the dashboard from `window.DASH`. |
| `serve.py` | Optional local server: serves the page and exposes `POST /refresh` so the Update button runs `update.py`. |
| `run.bat` | Windows shortcut: runs `python update.py`. |
| `.github/workflows/update.yml` | GitHub Actions: runs `update.py` every hour (every 6 min during US market hours), commits any data changes. |

## Data flow

```
portfolio.json (source of truth)
      │  update.py  (fetch prices, TP/SL exits, SGOV park, re-entry, snapshot)
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
- **Passive rebalance audit** — if a sector's *effective* (leverage-adjusted) exposure drifts more than ±5pp from its target, a `rebalance_recommended` flag is logged. It never trades; it just asks for a conviction review.

## GitHub Actions

`.github/workflows/update.yml` runs `update.py` on a schedule (hourly; every 6 minutes during US market hours to catch intraday moves) and commits any changes to `dashboard.js` / `portfolio.json`. Manual runs via **workflow_dispatch**.

> Note: `dashboard.js` is generated output — pull the latest before hand-editing `portfolio.json`, and push both together.
