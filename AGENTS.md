# Stock Picker — HyperGrowth Sharpe Barbell

A simulated managed-portfolio dashboard. A small Python backend fetches prices
and news, runs take-profit / stop-loss checks, and emits a static JS "data
file". A plain HTML/CSS/JS page renders it. No framework, no build step — the
site opens on the landing page (`index.html`); the dashboard is
`dashboard.html`, both work by double-clicking.

## Files at a glance

| File | Role | Edit? |
|------|------|-------|
| `portfolio.json` | Source of truth: meta, account/cash, positions, theories, events. | **YES** — hand-edit to rebalance / add / remove positions |
| `update.py` | Daily updater: fetch prices → check exits → deploy cash → snapshot → write `dashboard.js`. | **YES** — all data-mutating logic |
| `store.py` | Locked JSON persistence (site 0.5.6.00): the single write-path for `portfolio.json` and other mutable JSON. `update_portfolio(mutator)` = locked read-modify-write (threading lock + best-effort cross-process lock, msvcrt/fcntl) so concurrent serve.py requests can't interleave; writes are tmp-file + atomic rename. Full transactional semantics arrive with SQLite in the NAS hosting step. | **YES** — storage layer |
| `community.py` | Community registry + copy contracts (site 0.5.6.00): `sync_version_snapshots()` + `build_mirror()` (moved out of `update.py`) and `list_strategies()` (moved out of `leaderboards.py`) — the publish/follow API (NAS hosting step) builds on this module without running the whole daily update. | **YES** — importable by update.py, leaderboards.py, future server |
| `news.py` | Fetch Yahoo RSS headlines for held tickers, tag theories, score sentiment (VADER). | **YES** |
| `fears.py` | Market Fear Gauge: scores crash scenarios 1-5 (structural/episodic), complacency index, recommendation-only hedge sizing. Reads the EDITABLE scenario table; persists AI fear proposals/edits. | **YES** |
| `fear_scenarios.json` | **EDITABLE fear table** (algo 0.6.1): F1-F8 scenario definitions (name, type, components, velocity/trend, hedge_ticks, theory links, optional `sizing`) + AI-staged proposals flagged `pending_review` (skipped by the scorer until a human clears the flag and writes components). | **YES** — hand-edit to add/tune fears |
| `ai_sentiment.py` | AI Sentiment Decision Layer (algo 0.6.1.00): change-detect LLM verdict call (prior verdict + fact deltas embedded; outputs ONLY changes — omission = agreement). Provider-routed: **gemini** via OpenRouter — `google/gemini-3.7-flash` extended thinking — / zen / deepseek. Tier A market data + CNN Fear&Greed crowding gate + calibration track record. Rotations (paired sell/buy), fear proposals/edits (staged into `fear_scenarios.json`), schema validation, theories/fears/bullish/rotation layer translators. **WIRED into `update.py`, ENABLED** (`meta.ai.enabled: true`, `meta.ai.mode: recommend`). | **YES** — engine layer; must stay read-only (evidence/events/fear-blend/orders-refresh only) |
| `vader/` | Vendored MIT-licensed VADER sentiment engine (`vader.py` + `vader_lexicon.txt` + `emoji_utf8_lexicon.txt` + `LICENSE`). Third-party code, kept verbatim; `news.py` maps its `compound` score to pos/neg/neutral. | **NO** — upstream dependency |
| `dashboard.js` | **AUTO-GENERATED** output consumed by the browser (`window.DASH = {...}`). | **NO** — overwritten on every `update.py` run; edit `update.py`/`portfolio.json` instead |
| `mirror.json` | **AUTO-GENERATED** copy contract (site 0.5.5.29): the book as `positions[{ticker, sleeve, buy_date, shares, current_value, pct_of_book, theory_ids}]` + `changes[]` (normalized trade log: ts/type/ticker/action/shares/price/amount from `events[]`). What a follower replays to mirror the book exactly. | **NO** — written by `build_mirror()` in `community.py` every run |
| `leaderboards.py` | Community Top-10 leaderboard builder (weekly 5d / monthly 21d / quarterly 63d / yearly 252d / all-time since inception). Sources (deduped): `community/strategies/*/stats.json` + benchmark strategies (SPY / QQQ / TQQQ / TQQQ60-TMF40 — 2y Yahoo daily closes normalized to 100000 at their own first close; trailing windows over the full history) + the local book. Benchmark closes are cached in `benchmark_cache.json`, refreshed once per calendar day with stale fallback (site 0.5.6.00). | **YES** |
| `leaderboards.js` | **AUTO-GENERATED** `window.LEADERBOARDS = {...}` — script-tag format like `dashboard.js` so it loads from `file://`. | **NO** — written by `leaderboards.py` every `update.py` run |
| `community.js` | Shared leaderboard renderer (tab switcher + top-10 table) used by the Community section on `index.html` and `dashboard.html`. | **YES** — UI only |
| `leaderboards.html` + `lbpage.js` | Community Leaderboards site: full page (mascot header + nav, hero stat cards, tabbed Top-10 table, copy explainer, footer) reading the same `leaderboards.js` via `community.js`. | **YES** — UI only |
| `community/` | Leaderboard sources (site 0.5.5.33): `strategies/<id>/stats.json` (`{strategy_id, name, author, kind, start_value, start_date, history[]}` — snapshots also carry `parent_id` + `positions[]`). Written by `leaderboards.py` (benchmarks) and `update.py` (version snapshots, gated by `meta.community.snapshot_versions` — an experiment, normally OFF). `users.json` registry + publish/follow API planned. | — |
| `server/` | **Frozen TrueNAS SCALE deployment snapshot** (site 0.5.6.03): self-contained copy of the project + `Dockerfile` / `entrypoint.sh` / `.dockerignore` / `README.md`. One container runs engine + `serve.py` + opencode web; deliberately isolated from dev edits — update it by re-copying files into the NAS dataset + restart, never via dev changes. Gitignored (`server/`). | **YES** — copy-edit only |
| `app.js` | Renders `window.DASH` into every section of `dashboard.html`. | **YES** — UI only |
| `dashboard.html` | Dashboard page skeleton; the sections `app.js` fills. | **YES** — UI only |
| `index.html` + `landing.js` | Landing/marketing page (the site's default page — GitHub Pages, serve.py and double-click all land here): hero with live stats from `dashboard.js`, features, how-it-works, roadmap, and a sign-up preview (localStorage only, no backend — UI rehearsal for v1 accounts). | **YES** — UI only |
| `theories.html` + `theories.js` | Theory Archive page: every theory (incl. abandoned) as a flash-card wheel with drag/swipe/wheel navigation, 3D flip to evidence log, plus a plain-table toggle for copy-paste; status/tier filters + free-text search. Reads the same `dashboard.js`. | **YES** — UI only |
| `trades.html` + `trades.js` | Trade Archive page: every recorded event (exits, re-entries, cash deploys, rebalance flags) in a plain table with per-second timestamps. Reads the same `dashboard.js`. | **YES** — UI only |
| `help.html` + `help.js` | Help site: plain-language notes (Simple tab) + the math and details (Advanced tab). Static explainer, no data. | **YES** — UI only |
| `styles.css` | All styling (dark theme, panels, pills, charts). | **YES** |
| `serve.py` | Optional local server. Exposes `POST /refresh` (Update button), `POST /mode`, `POST /book` (per-proposal order booking). All portfolio.json mutations go through `store.update_portfolio` (locked RMW). | **YES** |
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
      │  dashboard.html loads app.js → app.js loads dashboard.js (cache-busted)
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
python serve.py      # serve at http://localhost:8000 (landing page; dashboard at /dashboard.html, Update button works here)
open index.html      # landing page — also works directly via file:// double-click (dashboard is dashboard.html)
```

## Versioning (per-prompt rule)

The UI version uses four-part notation: **`v0.5.<feature>.<patch>`** (JSON key
`site`). The engine version (JSON key `algo`) is separate and bumps only on
user-deemed milestones.

- **Every prompt's change set counts as one version bump** (site unless it's
  a user-deemed engine milestone).
- **Site notation `v0.5.F.PP`**:
  - `0.5` — the big stage marker; bumped ONLY when the user says so
    ("increment 0.5 -> 6"). Never bump it on your own.
  - `F` (feature) — incremented ONLY BY THE USER (v0.5.4 → v0.5.5).
    Never bump it on your own.
  - `PP` (patch, two digits) — the ONLY part the AI bumps: every prompt's
    UI change set increments it (0.5.4.00 → 0.5.4.01 → 0.5.4.02); it resets
    to 00 when the user bumps the feature digit.
  - Current baseline: **v0.5.6.03**.
- **Engine (algo) bumps RARELY** — the user announces them explicitly. UI
  tweaks and small data-rule edits do NOT bump the engine.
- Roadmap: **UI v1** = accounts/sign-in with a personalized AI per user
  (risk tolerance + focus). **Engine v1** = AI makes 100% of trades
  (real-time sentiment + AI analysis, weekly rebalance). Versions approach
  1.0 only as these goals are hit. See CHANGELOG.md "Roadmap & version
  policy".
- Hosting path (CHANGELOG.md): Tier 0 = GitHub Pages static (current, stays
  working); Tier 1 = i3 NAS backend (step 2 goal: `api.py` + SQLite +
  publish/follow queue + frontend `/api/health` probe with static-file
  fallback); Tier 2 = professional hosting (same `server/` code, SQLite →
  managed DB). Step 1 shipped in site 0.5.6.00 (`store.py` + `community.py`
  + benchmark cache).
- Header displays the versions as "UI v0.5.6.00 · Engine v0.6.1" (JSON keys
  remain `site`/`algo`).
- Each bump gets a `CHANGELOG.md` entry under `[site 0.5.F.PP]` /
  `[algo x.y.z]` sections.
- After editing `app.js` / `styles.css` / `index.html` / `dashboard.html` / archive pages, bump
  the matching `?v=N` cache-bust query strings in the HTML files.
- After bumping `meta.version` in `portfolio.json`, run `python update.py`
  so `dashboard.js` (and the header version line) picks it up. Never hand-
  edit `dashboard.js`.

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
  `CASH_BUFFER` so dry powder never sits idle — unless `meta.park_mode` is
  `"cash"` (the dashboard's dry-powder toggle, `serve.py POST /park`;
  default `"sgov"`).
- **Market orders (algo 0.6.1.00)**: portfolio.json `orders[]` holds
  human-approved market orders `{ticker, action "buy"|"sell", amount,
  status "pending"|"executed", source, created, note, exec_date,
  exec_price, shares, realized_pnl}`. `execute_pending_orders()` runs
  them at the LIVE price on market-open runs only — buys redeem SGOV,
  sells realize into cash (then re-parked in SGOV). **Mode-aware**
  (`meta.ai.mode`, default `recommend`): in **execute** mode a successful
  AI verdict REPLACES pending orders with its proposals + rotations
  (`meta.ai.orders_refresh`, sized at `meta.ai.order_size`); in
  **recommend** mode orders are written one at a time by the dashboard's
  **Submit this Order** buttons (`serve.py POST /book`) or all at once by
  **Submit all Orders** (`POST /execute_all`), human approval per
  proposal / rotation legs. Proposal amounts are conviction-scaled
  (`order_size × |conviction_score|`); rotation legs use the flat
  `order_size`. `meta.ai.user_bias` (-5..+5, `POST /bias`) is the user's
  sentiment lean embedded in the AI prompt.
  Executed history is pruned to the last 15.
- **Sector limits, not targets**: `meta.limits.rebalance.limits` are
  exposure LIMITS compared by the quarterly audit (old key `targets`
  still read as fallback). `rebalance.exempt_sectors` (e.g.
  "Short-Term Bonds"/SGOV) are never capped — dry powder grows freely so
  liquidity is always available for an opportunity.
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
  `renderOrders`, `initValueChart`, `initDonut`). Each reads only from
  `window.DASH` plus the
  `stockpicker.seen.v1` localStorage key (new-since-last-load badges).
- Main-page scorecard shows **active theories only** (`pending`/`paused`);
  `theories.html` (Theory Archive) lists every theory incl. `abandoned` with
  status/tier filters + free-text search, linked from the scorecard header.

## `window.DASH` data contract

Owned by `write_dashboard()` in `update.py`. `app.js` reads these fields:

- `meta`: `name`, `strategy`, `start_date`, `start_value`, `limits`,
  `park_mode` ("sgov"|"cash" dry-powder toggle)
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
  `underlying_buy_price`. **Consensus exit engine (site 0.5.4.05)**:
  leveraged positions stop on the **1x underlying** at a DYNAMIC level
  `-max(|static|, 2.5 x ATR14%)` (widens in high vol, floored; recomputed
  every run, telemetry `dynamic_stop_pct`); `stop_loss_pct` is then only a
  wide wrapper backstop. Take-profit on leveraged positions is the runner
  system: a one-shot **base trim** of 50% of shares at +50% wrapper PnL
  (`base_trimmed`, proceeds to SGOV, arms `runner_active`), then a trailing
  **runner exit** on 2 consecutive completed closes < `underlying_ema20`
  or a single completed close <= EMA20 - 1.5 x ATR14 (`runner_2close` /
  `runner_emergency` notes). 1x positions keep fixed `take_profit_pct`.
  Indicator math (EMA20/ATR14, Wilder RMA with gap-inclusive True Range)
  evaluates COMPLETED daily sessions only (1y OHLC cached once per day in
  `ohlc_cache.json`); only the vol-halt uses the live 6-min price. Stop
  exits are tagged `state:"vol_halt"` with `reclaim_ticker` /
  `reclaim_level` (frozen at halt time) / `reentry_amount` for the re-entry
  protocol (see `meta.limits.re_entry`): re-entry now requires 2+
  consecutive closes above the frozen level **AND** the last close above
  the underlying's EMA20 (trend gate). A position may carry a one-shot
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
- `events[]`: `date`, `ts` (HH:MM:SS local time the event was recorded),
  `ticker`, `name`, `reason` ("take_profit"/"stop_loss"/
  "deploy_cash"/"re_entry"/"rebalance_recommended"/"rebalance"), `note`
  ("index_stop (TICKER x%)"/"backstop"/"re-affirmed (...)"/drift message/
  scheduled-exit note/null), `state`
  (null/"vol_halt"), `price`, `buy_price`, `shares`, `realized_pnl`.
  The dashboard's Trade Events card shows the last 7 days only (min 2
  events); `trades.html` (Trade Archive) lists every event with time.
- `theories[]`: `id`, `title`, `prediction`, `tier` (S/A/B/C/D), `tier_reason`,
  `status` ("pending"/"paused"/"right"/"wrong"/"abandoned"), `created`,
  `last_updated`, `evidence[]`. A `paused` theory also carries `paused_date`,
  `pause_reason`, `paused_ticker` (set by the vol-halt re-entry protocol).
- `rebalance`: null or `[{type, sleeve, target_exposure, actual_exposure,
  message}]` — quarterly drift flags from `rebalance_audit()` (see
  `meta.limits.rebalance.limits`): the audit runs ONCE per calendar quarter
  (tracked in `meta.last_rebalance_quarter`), not daily. There is no
  tolerance band — ANY drift from limit is flagged, however small.
  `rebalance.exempt_sectors` (e.g. "Short-Term Bonds"/SGOV) are never
  flagged — dry powder is uncapped by design.
  Flags never trade; they ask the conviction layer to review a risk-budget
  mismatch.
- `benchmark`: null or `label`, `start_value`, `history[]`, `aligned[]`,
  `summary{total_return_pct, max_drawdown_pct, sharpe_annualized}`
- `news`: `asof`, `big_stories[]`, `feed[]` — items have `title`, `link`, `ts`,
  `when`, `ticker`, `industry`, `theory[]`, `sent` ("positive"/"negative"/
  "neutral")
- `ai`: null (disabled/degraded) or `asof`, `macro_stance`
  ("risk_on"/"neutral"/"risk_off"), `sector_bias[]`, `theories[]` (verdict/
  confidence/evidence), `fears[]` (sentiment_score), `convictions[]`
  (conviction_score -1..1, urgency, confidence, rationale), `proposals[]`
  (action buy/sell/add/trim from `bullish_layer`, urgency-sorted, each
  carrying `amount` = order_size × |conviction_score|, rounded),
  `rotations[]` (`{sell, buy, rationale}` — paired orders, engine sizes
  both legs at flat order_size), `sentiment_index` (mean conviction of the
  last verdict) + `sentiment_delta` (vs previous verdict, from
  `meta.ai_state.last_sentiment_index`), `fear_proposals[]` (staged AI
  scenarios, pending review), `mode` ("recommend"/"execute"),
  `gauge` (null or `{index, label}` CNN-
  style Fear & Greed), `calibration` (`{ticker: {wrong, total,
  last_wrong}}` — wrong-call track record), `summary`, `ledger[]` (last
  14 verdicts), `state` (cadence bookkeeping),
  `enabled`. Recommendations only — the UI must never execute from it.
- `fear_greed`: null or `{index` (0-100), `label`} — CNN-style crowding
  gauge fetched every run, displayed in the Fear panel and fed to the AI
  prompt as the euphoria gate.
- `orders[]`: human-approved market orders — `ticker`, `action`
  ("buy"/"sell"), `amount` (USD), `status` ("pending"/"executed"), `source`
  (e.g. `ai_YYYY-MM-DD` / `book_YYYY-MM-DD`), `created`, `note`, and
  for executed orders `exec_date`, `exec_price`, `shares`, `realized_pnl`.
  Pending orders execute at the live price on market-open runs; in execute
  mode the AI refresh replaces pending orders with the latest verdict
  (meta.ai.orders_refresh) — in recommend mode only Book Order writes them.
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
  current share). Never trades. `hedge_harvest`: null or `{asof,
  items:[{ticker, pct, z, reasons[]}]}` — RECOMMENDATION-ONLY hedge
  monetization (consensus 0.5.4.05): a Crisis Alpha hedge ≥ +2σ above its
  50d mean while a growth vol-halt is ACTIVE, proposing a 50% trim into the
  re-entry pool; never fires for a hedge claimed by a confirmed fear
  scenario (score ≥ 4.0, in its `hedge_ticks`). Never trades.
  `complacency`: null or `{index, valuation_
  stretch, fear_term, divergence, fear_avg, regime, note, pay_check}` —
  index = stretch×(1−(mean(top3)−1)/4), but the reading is a 2D regime
  matrix (equity stretch × top-3 fear avg): fragility (stretch≥0.5 +
  fear≥3.5), stress (<0.5 + ≥3.5), complacency (≥0.5 + <2.5), neutral
  (<0.5 + <2.5), watchful/moderate (middle band). `pay_check` =
  `{fear_id, fear_name, score, checks:[{ticker, ret_pct, paying}]}` —
  10-session returns of the DOMINANT fear's hedge_ticks only (the
  instruments expected to pay in that scenario). State persists in
  `meta.fear_state` (score/prev_score/days_above/confirmed).
