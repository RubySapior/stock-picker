# Stock Picker — HyperGrowth Sharpe Barbell

A simulated managed-portfolio dashboard. A small Python backend fetches prices
and news, runs take-profit / stop-loss checks, and emits a static JS "data
file". A plain HTML/CSS/JS page renders it. No framework, no build step — the
dashboard works by double-clicking `index.html`.

## Files at a glance

| File | Role | Edit? |
|------|------|-------|
| `portfolio.json` | Source of truth: meta, account/cash, positions, theories, events. | **YES** — hand-edit to rebalance / add / remove positions |
| `update.py` | Daily updater: fetch prices → check exits → deploy cash → snapshot → write `dashboard.js`. | **YES** — all data-mutating logic |
| `news.py` | Fetch Yahoo RSS headlines for held tickers, tag theories, score sentiment (VADER). | **YES** |
| `fears.py` | Market Fear Gauge: scores F1-F8 crash scenarios 1-5 (structural/episodic), complacency index, recommendation-only hedge sizing. | **YES** |
| `vader/` | Vendored MIT-licensed VADER sentiment engine (`vader.py` + `vader_lexicon.txt` + `emoji_utf8_lexicon.txt` + `LICENSE`). Third-party code, kept verbatim; `news.py` maps its `compound` score to pos/neg/neutral. | **NO** — upstream dependency |
| `dashboard.js` | **AUTO-GENERATED** output consumed by the browser (`window.DASH = {...}`). | **NO** — overwritten on every `update.py` run; edit `update.py`/`portfolio.json` instead |
| `app.js` | Renders `window.DASH` into every section of `index.html`. | **YES** — UI only |
| `index.html` | Page skeleton; the sections `app.js` fills. | **YES** — UI only |
| `theories.html` + `theories.js` | Theory Archive page: every theory (incl. abandoned) as a flash-card wheel with drag/swipe/wheel navigation, 3D flip to evidence log, plus a plain-table toggle for copy-paste; status/tier filters + free-text search. Reads the same `dashboard.js`. | **YES** — UI only |
| `styles.css` | All styling (dark theme, panels, pills, charts). | **YES** |
| `serve.py` | Optional local server. Exposes `POST /refresh` (runs `update.py`) used by the Update button. | **YES** |
| `run.bat` | Double-click shortcut that runs `python update.py`. | **YES** |

## Data flow

```
portfolio.json  (source of truth)
      │
      │  update.py: fetch Yahoo prices, TP/SL exits, park cash in SGOV,
      │             append today's snapshot to account.history, build metrics
      ▼
dashboard.js  (window.DASH = <json>)   ← AUTO-GENERATED
      │
      │  index.html loads app.js → app.js loads dashboard.js (cache-busted)
      ▼
browser render (cards, charts, tables, news)
```

1. `update.py` reads `portfolio.json`, fetches live prices for every open
   position from Yahoo Finance, closes any position whose take-profit or
   stop-loss triggered (realizing P&L into cash), parks idle cash into SGOV
   ("no idle cash" policy), appends today's value snapshot to
   `account.history`, then writes `dashboard.js`.
2. `app.js` injects `dashboard.js?t=<timestamp>` (cache-busted), reads
   `window.DASH`, and calls one render function per UI section.
3. `serve.py` only serves the folder and exposes `POST /refresh`, which runs
   `update.py` and lets the page's Update button reload fresh data.

## Run / verify

```
python update.py     # fetch prices + news, regenerate dashboard.js, print summary
python serve.py      # serve at http://localhost:8000 (Update button works here)
open index.html      # also works directly via file:// double-click
```

## Conventions & guardrails (important for AI agents)

- **Never edit `dashboard.js` by hand** — it is regenerated on every
  `update.py` run. Change `write_dashboard()` in `update.py` or
  `portfolio.json` instead.
- `portfolio.json` is the source of truth for holdings. A position's `id` and
  `ticker` are the same string (legacy duplicate key); `id` is not otherwise
  used.
- **Effective exposure** = `current_value × leverage`, where leverage comes
  from `meta.limits.position_exposure.<TICKER>.leverage`. Sector caps
  (`meta.limits.sector_limits`) are checked on **effective** exposure, and
  `leverage_factor` in `dashboard.js` is book-wide effective ÷ market value.
- **No idle cash policy**: `update.py` auto-buys SGOV with any cash above
  `CASH_BUFFER` so dry powder never sits idle.
- Returns are anchored to `meta.start_value` (100000) / `meta.start_date`;
  the SPY benchmark is normalized to the same start and aligned to portfolio
  dates.
- Yahoo price endpoint:
  `query1.finance.yahoo.com/v8/finance/chart/<TICKER>?range=1d&interval=1d`.
  The SPY benchmark uses a 2y range.
- **Market-hours behavior**: if the market is closed on a fresh calendar day,
  `update.py` keeps the last trading day's snapshot so its day-change stays
  visible until the next open (`market_is_open()` handles DST manually).
- `app.js`: `render()` delegates to one named function per UI section
  (`renderCards`, `renderPositions`, `renderSectors`, `renderComparison`,
  `renderTheories`, `renderEvents`, `renderSleeves`, `renderNews`,
  `initValueChart`, `initDonut`). Each reads only from `window.DASH` plus the
  `stockpicker.seen.v1` localStorage key (new-since-last-load badges).
- Main-page scorecard shows **active theories only** (`pending`/`paused`);
  `theories.html` (Theory Archive) lists every theory incl. `abandoned` with
  status/tier filters + free-text search, linked from the scorecard header.

## `window.DASH` data contract

Owned by `write_dashboard()` in `update.py`. `app.js` reads these fields:

- `meta`: `name`, `strategy`, `start_date`, `start_value`, `limits`
- `asof`: last snapshot date
- `summary`: `total_value`, `cash`, `invested_value`, `day_change`,
  `total_return_pct`, `realized_pnl`, `start_value`, `max_drawdown_pct`,
  `sharpe_annualized`, `cagr_annualized`
- `positions[]`: `ticker`, `name`, `sleeve`, `buy_date`, `buy_price`, `shares`,
  `cost`, `current_price`, `current_value`, `pnl_pct`, `take_profit_pct`,
  `stop_loss_pct`, `status` ("open"/"closed"), `exit` (null or
  {reason:"take_profit"|"stop_loss", price, state, note, ...}), `sector`,
  `leverage`, `effective_value`, `theory_ids[]`. Leveraged funds (3x/2x) also
  carry index-referenced stops: `underlying`, `underlying_stop_pct`,
  `underlying_buy_price`. `check_exits()` in `update.py` stops them on the
  **1x underlying** (vol-aware, no whipsaw); `stop_loss_pct` is then only a
  wide wrapper backstop. Stop exits are tagged `state:"vol_halt"` with
  `reclaim_ticker` / `reclaim_level` / `reentry_amount` for the re-entry
  protocol (see `meta.limits.re_entry`). A position may carry a one-shot
  `scheduled_exit` `{reason, note}` tag (e.g. a deliberate rebalance): on the
  FIRST market-open run `execute_scheduled_exits()` sells it at the live open
  price, realizes proceeds into cash, removes the position, and prunes its
  sector from `position_exposure`/`sector_limits`/rebalance targets if it was
  the last holding there.
- `sleeves[]`: `{sleeve, value}`
- `sectors[]`: `sector`, `value`, `effective`, `leverage`, `pct`, `max_pct`,
  `status` ("ok"/"warn"/"over"), `note`
- `leverage_factor`: book-wide effective ÷ market value
- `history[]`: `date`, `total_value`, `cash`, `invested_value`, `day_change`,
  `prices{ticker: px}`
- `events[]`: `date`, `ticker`, `name`, `reason` ("take_profit"/"stop_loss"/
  "deploy_cash"/"re_entry"/"rebalance_recommended"/"rebalance"), `note`
  ("index_stop (TICKER x%)"/"backstop"/"re-affirmed (...)"/drift message/
  scheduled-exit note/null), `state`
  (null/"vol_halt"), `price`, `buy_price`, `shares`, `realized_pnl`
- `theories[]`: `id`, `title`, `prediction`, `tier` (S/A/B/C/D), `tier_reason`,
  `status` ("pending"/"paused"/"right"/"wrong"/"abandoned"), `created`,
  `last_updated`, `evidence[]`. A `paused` theory also carries `paused_date`,
  `pause_reason`, `paused_ticker` (set by the vol-halt re-entry protocol).
- `rebalance`: null or `[{type, sleeve, target_exposure, actual_exposure,
  message}]` — passive drift flags from `rebalance_audit()` (see
  `meta.limits.rebalance.targets` + `tolerance_pct`). Flags never trade; they
  ask the conviction layer to review a risk-budget mismatch.
- `benchmark`: null or `label`, `start_value`, `history[]`, `aligned[]`,
  `summary{total_return_pct, max_drawdown_pct, sharpe_annualized}`
- `news`: `asof`, `big_stories[]`, `feed[]` — items have `title`, `link`, `ts`,
  `when`, `ticker`, `industry`, `theory[]`, `sent` ("positive"/"negative"/
  "neutral")
- `fears`: null or `asof`, `degraded[]`, `news_layer`, `fears[]` — each fear:
  `id` (F1-F8), `name`, `type` ("structural"/"episodic"), `score` (1-5, 5 =
  panic), `level`, `velocity`/`trend` (label/value/pct), `signals[]` (top
  contributors), `theory_ids[]`, `hedge_ticks[]`, `trend_dir`
  ("rising"/"falling"/"flat"), `degraded`. Structural = 0.7×level + 0.3×50d
  trend; episodic = 0.7×5d velocity + 0.3×level; all percentile-ranked on
  each fear's own trailing ~1y window (`fears.py`). `fear_sizing`: null or
  `[{instrument, pct, demand_pct, reasons[]}]` — RECOMMENDATION-ONLY
  per-instrument max demand from fears scoring ≥4.0 sustained `confirm_days`
  (3 structural / 2 episodic), scaled to Hedge Stack headroom (45% cap minus
  current share). Never trades. `complacency`: null or `{index, valuation_
  stretch, fear_term, note}` — index = stretch×(1−(mean(top3)−1)/4); ≥0.5
  warns to keep baseline hedges on. State persists in `meta.fear_state`
  (score/prev_score/days_above/confirmed).
