# Changelog

All notable changes to the Stock Picker project (dashboard UI + strategy engine).

Two independent versions, both shown in small text in the dashboard header and
tracked in `portfolio.json` -> `meta.version`:

- **UI** (JSON key `site`) — the website/UI (`app.js`, `index.html`, archive pages, `styles.css`)
- **Engine** (JSON key `algo`) — the strategy engine (`update.py`, `news.py`, `fears.py`, `portfolio.json` data rules)

## Roadmap & version policy

The versions mean something — they track how close each side is to its v1:

- **UI v1.0** = accounts: sign-in, and every user gets a personalized AI tuned
  to their risk tolerance and what they want the AI to focus on.
- **Engine v1.0** = the AI makes **100% of the trades** from real-time
  sentiment with AI analysis, rebalancing weekly across different hedges /
  leading sectors (today AI, next week something else).

Version bumps by side:
- **UI** bumps on any UI change, as today.
- **Engine stays 0.5.x and bumps RARELY** — only on real autonomy/AI
  milestones (new AI decision layers, sentiment-driven trade logic, weekly
  rebalance engine). UI-adjacent tweaks and data-rule adjustments do NOT
  bump the engine. Approaching 1.0 is gated on the roadmap goals above.

Convention: bump `meta.version.site` on any UI change, `meta.version.algo` on
the (rare) engine milestones described above, and add an entry below. Both
stay below 1.0.0 — this project is not v1-ready yet.

**Per-prompt rule:** every prompt's change set (however small) counts as one
version bump — `site` for UI-only changes, `algo` only for genuine engine
milestones (or both if a prompt touches both sides), each with its own entry below.

## Path to v1 — business & legal staging (2026-08-14)

Source: product/business planning session. The v1 goal is a **paid
subscription service for OTHER users** — the tool is the product, not
us trading to make money. No licensing blocks building Phase 1.

- **Sell the tool, not the advice.** AI output ships as universal
  signals/strategies the user operates (one-tap approval in their own
  Alpaca account). Personalized advice ("based on YOUR risk profile, buy
  X") = RIA territory; a universal tool everyone runs the same way =
  TradingView/freqtrade model, no registration needed.
- **Playbook: Composer / Autopilot.** Both launched as tools, built users +
  public track record, then registered as RIAs. Launch before the license;
  let the license catch up (Composer had paying users pre-registration).
- **Phase 1 — now (unregistered):** signals + paper trading + user-authorized
  live execution via **Alpaca** (Robinhood's official API is discontinued;
  Alpaca is the standard — free API, paper trading, and the legal-safe lane
  keeps a user approval step in the loop).
- **Phase 2 — ~6 months before launch:** RIA registration: Form ADV (Parts
  1 & 2), compliance program + CCO, code of ethics, cybersecurity policy,
  business-continuity + trade-error procedures. Registration is NOT gated on
  AUM — being paid for discretionary management is the trigger; a lean
  state-level RIA with compliance-as-a-service runs ~$5-15k/yr.
- **Phase 3 — registered:** flip the switch — AI may auto-execute
  per-subscriber ("the Composer moment"); marketing may say the real words.
- **On-ramp routes (each legal today, each feeds the next):**
  1. Sell the software / universal signals (do this first — Phase 1 business)
  2. B2B: white-label the engine to licensed RIAs/wealth managers (they are
     the licensed party; we are just their software vendor)
  3. Sell the data/API feed (fear gauge + strategy scores) to fintech
  4. State RIA when revenue + track record justify it — the upgrade path to
     full autonomy
- **Trust is the moat.** "AI trading subscription" is the scam capital of the
  internet; the differentiator is boring, honest, auditable: public track
  record, paper-trading history, transparent methodology, no miracle claims.
  First users come from proof (a 12-month public simulation log), not
  marketing.
- **Rebrand before ship:** "Market Fear Gauge" is one rename away from CNN's
  trademarked "Fear & Greed Index."
- **Budget reality:** finished-product-only = a long zero-revenue runway;
  the survivors in this niche ship a boring, honest, auditable tool.

### v1 launch checklist (todos)

- [ ] Phase 1 legal framing decision: signals-with-approval vs
      configurable-bot (determines the Alpaca integration design)
- [ ] Alpaca integration (paper + live) with user one-tap approval flow
- [ ] Public track record: 12-month public simulation log / leaderboard
- [ ] Rebrand "Market Fear Gauge" away from the CNN trademark
- [ ] Paid subscription tier (journal + simulation framing)
- [ ] Phase 2 kickoff: RIA registration ~6 months before launch
- [ ] Phase 3: autonomous per-subscriber execution behind the license

## AI Sentiment Decision Layer — folded design (2026-08-14)

The Engine v1 stepping stone. A fresh LLM call (Gemini, 1x/day at market
open + circuit-event re-runs) reads Tier A market data, compares against
its last verdict via FACT DELTAS (not its own prose), and emits a strict
JSON verdict that feeds three deterministic layers. Nothing executes.

### Grounding tiers

- **Tier A — decision-grade (always on):** index/position deltas, VIX,
  yields, F1-F8 fear levels, sector exposures vs targets, prior-verdict
  outcomes (the ledger). All built from data `update.py` already fetches.
- **Tier B — untrusted (display-only):** RSS news + VADER sentiment.
  `meta.ai.news_to_sentiment: false` until the news layer is scored
  against outcomes for months. Never enters the prompt.

### The five invariants

1. **AI thinks, the engine calculates.** The LLM outputs conviction
   (-1..1), urgency (0-100), confidence (0-100) — never dollar sizing.
   `bullish_layer` does all math (caps, leverage, vol scalars).
2. **Deterministic rules override AI.** 60-day vol-halt circuit breaker,
   TP/SL, sector caps are hard limits. AI can flag "probation"; it can
   never revive a vol-halted position or move capital past a cap.
3. **Fact-delta ledger, not prose.** The prompt gets verified numbers
   about what happened after the last call ("conviction 0.8 on T17;
   index -4.2% since; F4 2->4") — never its own past reasoning. The
   ledger (meta.ai_last_output + meta.ai_ledger) survives GH Actions
   runs and scores every stance against outcomes; scores feed UI badges.
   Raw prompt hash stored per entry for reproducibility.
4. **Urgency gates the UI.** Minor conviction twitches stay silent;
   high-urgency (>= threshold) produces the review card / notification
   button. Human confirmation required to act — proposals only.
5. **AI is read-only until Engine v1.** It proposes; only deterministic
   code + humans mutate `portfolio.json` positions. If the call fails or
   returns junk, the book behaves EXACTLY like today (price rules +
   market fears only) — degraded mode, zero pipeline disruption.

### Cadence & cost guardrails

- 1x daily call at ~09:35 ET (first market-open run of the day).
- Circuit re-runs capped at `max_daily_calls` (default 3): |dQQQ| > 2.5%
  or VIX spike > 15%; never on weekends/holidays (`market_is_open()`).
- API key from env var only (never committed). 1 call/day default.

### Merged verdict schema (final)

```json
{
  "date": "2026-08-14",
  "macro_stance": "risk_on|neutral|risk_off",
  "sector_bias": [
    { "sector": "Tech / AI Growth", "stance": "bullish", "conviction": 0.85, "driver": "..." }
  ],
  "theories": [
    { "id": "T17", "verdict": "affirm|weaken|probation|abandon", "confidence": 80, "evidence": "..." }
  ],
  "fears": [
    { "id": "F4", "sentiment_score": 3, "delta_reason": "..." }
  ],
  "convictions": [
    { "ticker": "TQQQ", "conviction_score": 0.75, "urgency": 60, "confidence": 70, "rationale": "..." }
  ],
  "summary": "..."
}
```

### The three downstream layers (deterministic calculators)

- **Theories layer:** verdicts -> theory status/evidence candidates
  (affirm = new evidence; weaken/probation = flag; abandon = human
  confirm). Emits events with reason "ai_sentiment".
- **Fears layer:** `fears[].sentiment_score` -> `build_fears(data,
  ai_scores={F1:2, F4:4, ...})` — reuses the existing "two independent
  witnesses" hook (fears.py:440) with the AI as the second witness.
- **Bullish layer:** convictions x sleeve caps x leverage x vol scalar
  -> target book diff -> "Buy TQQQ +$2k" review cards (buttons, never
  execution).

## [site 0.5.6.20] — 2026-08-22

### Added — minimal bear & bull gallery (the style I'm actually good at)

- Previous low-poly bears sucked — acknowledged: hand-sculpting 20 `polygon` points without seeing the shape is not my skill. This gallery leans into what *is*: flat, clean primitives (`circle`/`ellipse`/`rect`+`rx`) that stay sharp at any size and read at `opacity:0.18`.
- New `bear_bull_minimal_preview.html` with **5 bears + 5 bulls** (all `viewBox 0 0 100`, red `#dc2626` / green `#16a34a`):
  - **Bears:** B1 Classic Filled (solid + cream snout, safe default), B2 Outline (stroke-only watermark), B3 Angry Brow (furrowed, bear-market), B4 Geometric (squarish head, design-system), B5 Chibi (big eyes + blush, friendliest).
  - **Bulls:** U1 Classic Horns (curved horns), U2 Outline (matches B2), U3 Angry Snort (flared nostrils + brows), U4 Geometric (flat horns), U5 Cute Bull (blush, pairs with B5).
- Each card previews isolated; pair preview shows bear vs bull as they flank the hero. **Pick bear + Pick bull** stores `stockpicker.minimal.picks` + `stockpicker.{bear,bull}.pick` (SVG with `class="heroBear"/"heroBull"`); the landing hero (`index.html:217` now handles both) swaps both sides for live preview. Tell me `use B# + U#` and I'll write the pair into `index.html`.

## [site 0.5.6.19] — 2026-08-22

### Added — bear preview gallery (5 polygon variants)

- New `bear_preview.html` gallery with 5 distinct low-poly red bears sharing the green bull's polygon language — **V1 Classic** (clean faceted front head, calm), **V2 Aggressive** (bared teeth + furrowed brows, the Wall-Street bear), **V3 Walking Profile** (full-body side view mid-stride, pairs with the bull), **V4 Crystal** (diamond-cut, all triangles from center — most "polygon"), **V5 Chibi** (big head / small body, soft but still faceted, friendlier for onboarding). Each is pure SVG `polygon`+`circle` (`viewBox 0 0 100` / `120`), `aria-hidden` on the landing hero. Gallery lets you click **Use this one** (stores `stockpicker.bear.pick` in localStorage) and **Show SVG** (copy-paste source); the landing hero (`index.html:217` preview hook) swaps its `heroBear` for the stored pick so you can preview on `index.html` before committing. Tell me "use V#" and I will write it into `index.html` permanently.

## [site 0.5.6.18] — 2026-08-22

### Added — theory links in Positions, live SPY hero, bear/bull art, and Fear news layer (issues #10, #31, #30, #24)

- **#10 Positions → theory links** (`app.js` `renderPositions`): each position row now shows its `theory_ids` as clickable `theoryTag` pills under the name/sleeve (e.g. T1, T17 → `#theory-T17`), matching the chips already in the Fear panel and News feed. The archive wheel/table remains the detail view.
- **#31 Live SPY comparison on the landing page** (`landing.js` `initHeroChart`): the hero chart now renders **real** history when `dashboard.js` is present — `history[].total_value` (normalized to `start_value`) vs `benchmark.aligned[].value` (both $100k-anchored, browser-cached). Portfolio draws in blue with a blue fill, SPY draws as a dashed amber line with its own fill; an inline legend, end-dot labels with `+x.x%` and excess `+x.x pp vs SPY` update live. Header switches to "Portfolio vs S&P 500 — live track record" and the caption shows the live date range. Falls back to the illustrative random-walk mock on `file://` before the first `update.py` run.
- **#30 Bear / bull hero decoration** (`index.html` + `styles.css`): a bear on the left (red polygons) and a bull on the right (green polygons) flank the hero title — low-poly SVG pair built from `FEAR_*`-style polygons (green `#22c55e` bull, red `#ef4444` bear), `aria-hidden`, absolute-positioned behind the headline with `opacity:0.18` (hidden below 600 px, dimmed below 900 px).
- **#24 Fear Gauge news layer — VADER keyword density** (`fears.py` + `update.py` `write_dashboard`): the planned `market + news` two-witness hook is now wired instead of AI-only.
  - **Scoring** (`fears.py` `score_fears_from_news`): per-fear keyword sets (`FEAR_NEWS_KEYWORDS` F1-F8, tuned to the scenario table — e.g. F1 *ai/nvidia/semiconductor/magnificent*, F2 *yen/carry/boj*, F3 *china/taiwan/xi*, F4 *inflation/cpi/breakeven*, F5 *war/oil/crude/opec*, F6 *rate/yield/fed/powell/treasury*, F7 *credit/spread/hyg/default*, F8 *recession/slowdown/unemployment/layoff*) scanned over `build_news().feed` titles (case-insensitive substring), weighted by VADER sentiment (`negative 1.0 / neutral 0.55 / positive 0.15`) → `density = weighted_hits / total` → `news_score = 1 + 4·min(1, density/0.25)` (1.0-5.0, `0.25` density saturates at panic).
  - **Combination** (`fears.py` `apply_news_witnesses`): identical to the AI witness rule — `raw = max(market, min(news, market+1.5))`, plus `+0.5` when both witnesses ≥3.0, clamped at 5.0; preserves `market_score` so `hedge_harvester` stays market-only (`news_adjusted` flag mirrors `ai_adjusted`).
  - **Wiring** (`update.py` `write_dashboard`): right after `build_news_cached()` computes `news_scores`, it blends them into `fear_data.fears` and sets `fear_data.news_layer = True` + `news_scores` for the dashboard; degraded (fewer than 3 headlines, missing news, or any exception) silently keeps the gauge market-only and never breaks the run, per the acceptance criterion.

### Changed — cache bust

- `dashboard.html` `styles.css?v=57` `app.js?v=66`; `index.html` `styles.css?v=57` `landing.js?v=25`; archive pages `styles.css?v=57`.

## [site 0.5.6.17] — 2026-08-22

### Added — estimated monthly dividend income at the top (issue #14)

- **Ask:** "see how much div per month at the top of page from the current
  port."
- **Engine** (`update.py` `compute_div_runrate`): forward run-rate from
  CURRENT open positions — `shares x trailing-12m payouts/share / 12`,
  summed over the book. Uses the daily-cached Yahoo div events (~1y window)
  already fetched for the credit engine, so payout frequency (SGOV monthly,
  TQQQ quarterly, ...) is baked into each TTM sum; tickers that never paid
  contribute $0. Exposed as `summary.div_monthly_est` (`null` if the cache
  is unreadable).
- **UI** (`app.js` `renderCards`): new top scorecard card "Div / mo (est.)"
  with lifetime dividends received as the delta line and a tooltip spelling
  out the math; cards grid wraps to a clean second row on narrow screens.

### Changed — cache bust

- `dashboard.html` `app.js?v=64`.

## [site 0.5.6.16] — 2026-08-22

### Changed — risk-adjusted metric: Sharpe → Sortino everywhere (issue #32)

- **Why:** Sharpe divides by total volatility, so a hypergrowth book gets
  penalized for big UP-days too. Sortino divides only by downside deviation
  (`sqrt(sum(min(r,0)^2) / (n-1))`) — upward volatility is free (issue #32:
  "doesn't punish upward volatility").
- **Engine math** (`update.py` `compute_sortino`, `leaderboards.py`
  `_sortino`): same convention as the old Sharpe — mean daily return over
  downside deviation, annualized × √252, ≥3 snapshots, `null` when there are
  no down-days (mirrors the old std=0 guard). Leaderboard windows keep using
  `_window_history`, so weekly/monthly/quarterly/yearly/all-time Sortino is
  computed over each window's own slice.
- **Data contract rename**: `summary.sharpe_annualized` →
  `summary.sortino_annualized`; benchmark summaries likewise;
  leaderboard rows now carry `sortino` instead of `sharpe`.
- **UI**: dashboard chart header stat "Sharpe (ann.)" → "Sortino (ann.)"
  (`app.js`); leaderboard column + click-to-sort header "Sharpe" → "Sortino"
  (`community.js`, `.lbSh` → `.lbSortino` in `styles.css` narrow-screen rule);
  Help site Simple tab blurb + Advanced-tab formula updated.

### Changed — cache bust

- `dashboard.html` `app.js?v=63`, `styles.css?v=56`; all other pages
  `styles.css` bump.

## [site 0.5.6.15] — 2026-08-22

### Added — Dividend tracking + payout policy (issue #13)

- **The leak:** prices are UNADJUSTED Yahoo regular-market quotes, so every
  ex-dividend date silently dropped the book by `shares x payout` with
  nothing credited back — SGOV alone leaks ~$8/month at current size.
- **Fetch** (`update.py` `fetch_dividends`/`ensure_dividends`): the same chart
  endpoint with `events=div`, fetched once per calendar day for all open
  positions (cached in `ohlc_cache.json` under `dividends`/`dividends_fetched`,
  stale-fallback on failure). Verified live: SGOV monthly ~$0.30/sh, TQQQ
  quarterly, growth/hedge tickers mostly never.
- **Credit engine** (`update.py` `process_dividends`, runs after market orders,
  BEFORE the exit engine and SGOV parking): per-position watermark
  `last_div_date` (init = `buy_date`; only ex-dates strictly AFTER it count —
  own before ex-date = entitled) advances to the max credited ex-date so a
  failed fetch or deferred leg retries instead of skipping; fully idempotent.
  Payouts under $1 (`DIV_DUST_FLOOR`) always route to cash. Lifetime income
  accumulates in `account.dividends`.
- **Policy choice** `meta.dividend_policy` (default **`reinvest`**):
  - `reinvest` — DRIP: payout buys shares of the paying ticker at the live
    price; `cost` bumps so avg-cost stays true; realized_pnl untouched.
  - `sgov` — payout buys SGOV dry powder directly (creates the position if
    absent; works even when park_mode="cash").
  - `cash` — payout lands in `account.cash`; the existing no-idle-cash
    policy then applies later in the same run.
- **Toggle UI**: DRIP | SGOV | Cash pill next to the auto-park toggle in the
  deterministic-guardrails panel (`app.js` `divTog`, reuses `.parkTog`
  styles), lifetime dividends total shown beside it;
  `serve.py POST /dividend {mode}` persists via locked RMW (mirrors `/park`).
- **Visibility**: events carry `reason:"dividend"` + explicit `amount`
  (`"DIV $8.41 (0.307/sh x 27.4414) -> ..."`); Trade Events card shows a green
  DIV row, Trade Archive colors income green, mirror.json changes[] includes
  dividends and prefers the event amount when no shares traded
  (`community.py`).

### Changed — cache bust

- `dashboard.html` `app.js?v=62`.

## [site 0.5.6.14] — 2026-08-21

### Fixed — Update vs AI split (token control)

- **Decoupled Update from Gemini** (`update.py:1739` `--skip-ai`): `POST /refresh` (Update button + GH Actions 6m price refresh) now runs `update.py --skip-ai` — price/news/TP-SL/SGOV only, `MACRO: skipped` and `AI SKIPPED` log, zero tokens. Previous 2-call morning (`portfolio.json:228` `calls_today:2` at `10:33`/`10:43`) was two market-open `update.py` runs each hitting `ai_sentiment.py:861` until `max_daily_calls:3`.
- **Dedicated Run AI button** (`dashboard.html:83` `#aiRunBtn` `aiRunBtn`): lives in AI header next to `modeSwitch`/`bias`/`Submit all`. `styles.css:307` blue pill, `app.js:1405` wires `POST /ai` → `serve.py:229` `_run_update(ai=True)` → `update.py --ai` (forced, market-hours gated, `3/day` cap) — the **only** token path. Header `Update` title reworded to price-only, AI section now shows switch even when `DEGRADED` (`app.js:948`), `Update` and `book/bias/park/mode` refreshes all use `--skip-ai`.

### Changed — cache bust

- `dashboard.html` `styles.css?v=55`/`app.js?v=61`.

## [site 0.5.6.13] — 2026-08-21

### Removed — rebalance audit retired

- **Rebalance audit deleted** (`update.py:787` `rebalance_audit()` + `meta.limits.rebalance` + `meta.last_rebalance_quarter`): the quarterly drift banner is gone — sentiment analysis runs daily and is the sole driver. `ai_sentiment.py:95` `build_market_snapshot()` now reads `meta.limits.sector_limits` (hard caps) instead of `rebalance.limits`. Historical `rebalanced`/`rebalance_reason` strings kept as notes; no new `rebalance_recommended` events will be generated.
- **UI cleanup**: `dashboard.html:39` `rebalBanner` + `app.js:167` banner render + `trades.js:31` pill + `styles.css:55` `.rebalBanner` + `help.html:122` rebalance explainer + event-pill `REBAL`/`DRIFT` fallbacks removed.
- **portfolio.json**: `meta.limits.rebalance` block and `meta.last_rebalance_quarter` removed via migration.

### Added — Auto AI mode sliding switch

- **Sliding switch UI** (`dashboard.html:70` `modeSwitch` + `aiModeSwitch` checkbox) in the AI Sentiment header toggles `recommend` (manual Submit buttons) ↔ `Auto AI` (`execute` — daily verdict auto-creates pending market orders, executed at next market open). `styles.css:293` `.modeSwitch`/`.switch`/`.slider` pill switch; active label highlighted. `app.js:1038` `renderAI()` wires `POST /mode` with optimistic label toggle + `serve.py` reload, file:// graceful fallback. Pills and order notes reworded to `AUTO AI MODE` where applicable.

### Changed — cache bust

- `styles.css`/`app.js`/`dashboard.html`/`help.html`/`index.html`/`theories.html`/`trades.html`/`leaderboards.html` `?v=` bumped.

## [site 0.5.6.12] — 2026-08-21

### Fixed — post-0.5.6.11 patches

- **#56 serve hygiene (residual)**: `serve.py` now imports `socket`, `PORT` falls back to 8000 on bad env, `Handler.timeout=60` + `server.daemon_threads=True` complete the hardening.
- **#55 lbpage null guard**: `lbpage.js` `setCard` no longer throws on `return_pct==null`.
- **#54 XSS (residual)**: `app.js` positions/order ticker/sleeve/underlying, events ticker, sleeve chips, news `href` scheme check (`https?` only), `wheel.js` tier/id/status all escaped.
- **#46 hold threshold**: `update.py:compute_calibration` skips `|conviction|<0.05` (was exact `0.0` only).
- **Market Orders UI**: `app.js:renderOrders` shows pending only (executed reflected in positions).
- **#17 landing page**: closed — `index.html` is the landing site since 0.5.5.09.
- **#33 drawdown time-scale**: `leaderboards.py:_ranked` now slices `max_drawdown`/`sharpe` per window via `_window_history` (weekly 5, monthly 21, quarterly 63, yearly 252); weekly TQQQ `−8.65%` (was `−58.04%`) etc.

## [site 0.5.6.11] — 2026-08-20

### Fixed — rework of issues reopened from the 2026-08-20 closing batch (fixes were claimed in 0.5.6.05-0.5.6.10 but never committed; all re-implemented and verified here)

Engine:
- **#41 NYSE holiday calendar**: `nyse_holidays()` / `nyse_early_closes()`
  (fixed-date rules + `_nth_weekday` / `_last_weekday` / `_easter` helpers,
  holiday fallback on weekends) wired into `market_state()` — the book
  stays closed on full-close holidays and opens until 13:00 ET on
  early-close days (e.g. Jul 3) instead of trading on a dead tape.
- **#40 pending-order dedupe**: `execute_pending_orders` drops duplicate
  pending orders (same ticker/action/amount/source/note) before executing,
  so a twice-booked proposal can't double-execute at the next open.
- **#52 running-average cost basis**: new `avg_cost(pos)` (cost/shares,
  fallback `buy_price`) used by `check_exits` realized P&L and by the
  sell path in `execute_pending_orders` (proceeds/realized/cost write-down
  all on the averaged basis, not the stale entry price).
- **#46 hold verdicts excluded from calibration**: `compute_calibration`
  skips 0.0-conviction (HOLD) entries — they are not directional calls and
  are no longer scored as wrong.
- **#51 runner gate wired**: the runner trail arms only after the base trim
  wrapper reaches `RUNNER_GATE_PNL` (+30%) — the gate constant existed but
  was never enforced.
- **#50 SGOV exempt**: `check_exits` returns None for the STB ticker, so
  the cash-parking sleeve can never be reaped by the exit engine.
- **#29 sector caps are hard limits**: new `sector_cap_blocked()` guard
  (ai_sentiment.py) blocks any BUY whose sector EFFECTIVE exposure
  (market value x leverage) would exceed `meta.limits.sector_limits`
  max_pct, enforced at every buy path — `execute_pending_orders` (blocked
  buys stay pending), `refresh_orders_from_ai` execute mode (AI/rotation
  buy legs skipped), and serve.py `/book` + `/execute_all` (human
  approval rejected with the same rule). Sells are never blocked.
- **#48 atomic asset writes**: new `store.write_text_atomic()` (tmp-file +
  rename under the same locks) for `dashboard.js` and `ohlc_cache.json` —
  a kill mid-write can no longer leave a blank dashboard or corrupt cache.

AI sentiment (ai_sentiment.py):
- **#44 Gemini key moved to header**: the API key is sent as
  `x-goog-api-key`, never in the URL query string (leaks via logs/proxies).
- **#45 retries + salvage**: all four providers now go through `_http_json()`
  (2 attempts, 5s/15s backoff); `_extract_json()` gained a brace-depth
  salvage pass that recovers truncated replies (auto-appends closers,
  strips trailing prose) instead of discarding the verdict.
- **#42 full-verdict echo degenerates to no-op**: `_drop_unchanged()` diffs
  convictions/theories/fears/rotations/sector_bias against the prior
  verdict; identical sections are dropped (no re-booked orders, no
  sentiment drift) and an all-unchanged verdict logs a warning and no-ops.
- **#43 rotation vs conviction cross-check**: `rotation_layer()` drops a
  rotation leg that also appears as a conviction in the SAME verdict —
  the explicit sized read wins, no double-queuing.

Fears:
- **#38 per-scenario isolation**: `build_fears` wraps each scenario in
  try/except — one malformed scenario is skipped (and reported), never
  takes down the whole gauge.
- **#39 `days_above` counts calendar days**: gated on `last_above_date`
  instead of every 6-min run — a single hot day can no longer fast-track
  a fear to confirmed.
- **#47 market witness preserved**: `apply_ai_witnesses` stores the raw
  market score on `market_score` before blending, and `hedge_harvester`
  decides on `market_score` — one AI sentiment spike can no longer unpark
  hedges mid-panic.

Server (serve.py):
- **#56 `_read_body` hardening**: bad/negative Content-Length -> 400 (was
  an `int()` crash), bodies > 64KB -> 413, stalled reads -> 400 after a
  60s socket timeout, malformed JSON -> 400 (was silent `{}`).
- **#29 sector caps** enforced on `/book` and `/execute_all` buy paths.

UI:
- **#15 positions table**: dropped the Buy/Current columns, added P&L $
  (unrealized `current_value - cost`, realized for closed) with sorting.
- **#53 theories search debounced** (200ms) — fast typing no longer
  re-renders the deck per keystroke.
- **#54 XSS sweep**: sector names/notes, theory tier badges, stance pill,
  trade ticker/reason and theories table tier text are escaped (app.js,
  theories.js, trades.js).
- **#55 leaderboard hardening**: community.js no longer double-escapes
  names/authors (textContent), lbpage.js shows the empty state when
  leaderboards.js fails instead of throwing, and `loadDash` surfaces a
  visible hint when dashboard.js fails to load.

## [site 0.5.6.04] — 2026-08-18

### Fixed — calibration over-counting, frontend listener leaks, quarterly audit gating

Engine (no algo bump — correctness fixes):
- **AI calibration scored every run, not every verdict**: `compute_calibration`
  compared the SAME `meta.ai_last_output` verdict against every 6-min intraday
  run's price, inflating wrong/total (TQQQ had reached 20/25 wrong after ~8
  days of runs). Each verdict is now scored exactly once — on the first run of
  a later day (`meta.ai_calibrated_verdict_date` gate). Pre-fix inflated
  counts are reset once on the first fixed run.
- **Quarterly rebalance audit ran on closed-market days**: `rebalance_audit`
  now waits for a market-open run before flagging (no stale-priced flags or
  early quarter marker on weekends/holidays).
- `compute_cagr` now anchors to the last snapshot date (the asof), not the
  wall-clock today, so closed-day / backdated runs don't skew CAGR.
- `_sell_sgov` writes down SGOV cost basis at `buy_price`, not the current
  redemption price.
- `market_state()` uses tz-aware `datetime.now(timezone.utc)` instead of the
  deprecated naive `utcnow()` (DST math unchanged).

Efficiency (network):
- `fetch_prices` / `fetch_macro` / `ensure_ohlc_bars` now fetch concurrently
  (bounded thread pools, small politeness gap) instead of one-serial-Yahoo-call
  with a sleep each — every cron run's price phase drops from ~N seconds to a
  few waves.
- `fetch_macro` reuses prices already fetched for held/underlying symbols
  (SPY/QQQ) instead of a second fetch per run.
- News is day-cached (`news_cache.json`): RSS feeds refetched once per calendar
  day instead of ~80x/day on the intraday cron (same semantics as the OHLC /
  benchmark / fear caches).
- Leaderboards reuse update.py's daily 2y benchmark closes (`ohlc_cache.json`
  `bench`) for shared symbols (SPY/QQQ/TQQQ), so those aren't fetched twice per
  day; only leaderboard-only symbols (e.g. TMF) still fetch in
  `benchmark_cache.json`.

UI:
- **Positions table sort broke after a soft refresh**: the sort click handler
  was re-attached on every `render()`, so a single click toggled the direction
  twice (no visible change). Handlers are now replaced each render instead of
  accumulated.
- **News feed scroll/wheel + window-resize handlers accumulated on every
  render** (soft refresh / 6-min countdown). They're now wired once and read
  live DOM state.

## [site 0.5.6.03] — 2026-08-18

### Added — `server/` deployment snapshot for TrueNAS SCALE (Docker)

- New self-contained `server/` folder: a frozen copy of the whole project
  (site 0.5.6.03) plus `Dockerfile`, `entrypoint.sh`, `.dockerignore` and a
  TrueNAS deployment README. One container runs the engine + `serve.py` +
  opencode web, so the NAS deployment is isolated from dev changes in the
  parent folder — nothing in the daily dev workflow can break the running
  server; code updates are a deliberate copy + restart.
- `entrypoint.sh` runs three processes: `serve.py` (PORT env, already
  supported by serve.py), an hourly `update.py` loop (interval via
  `UPDATE_INTERVAL`, self-gating market hours), and `opencode web` as the
  persistent front process (basic auth via `OPENCODE_SERVER_PASSWORD`).
- No engine changes: `market_is_open()` already computes NYSE hours from UTC
  with manual DST (update.py), so the container timezone is cosmetic only
  (`TZ=America/New_York` for readable logs).

## [site 0.5.6.02] — 2026-08-18

### Fixed — three concurrency / write-integrity audit findings (issues #35-37)
1. **`/refresh` single-flight guard (#35)**: serve.py now runs every
   state-changing endpoint (refresh/mode/book/execute_all/bias/park) under
   one non-blocking lock held for the whole handler. A second request while
   an update.py subprocess is in flight gets `409 {"ok": false, "error":
   "update already running"}` instead of spawning a concurrent updater
   (double AI spend, double rate-limit risk, last-writer-wins on
   portfolio.json).
2. **update.py merge-at-write, no more stale clobber (#36)**: main() used
   to read the whole portfolio once, mutate it in memory for minutes, then
   write the stale copy back - a `/book`/`/execute_all`/`/mode`/`/bias`/
   `/park` landing mid-run succeeded via its own locked write and was then
   silently overwritten (a human-approved order could vanish). The final
   write is now `persist_merged()`: a locked atomic re-read -> merge ->
   write that overlays only the sections update.py owns (positions/account/
   events/theories + limits/last_rebalance_quarter/ai_state/ai_last_output/
   ai_ledger/ai_fear_proposals/ai_calibration/fear_state). serve.py's
   park_mode / ai.mode / ai.user_bias and any fresh pending orders (minus
   ones already executed this run, so nothing double-executes) survive.
3. **fear_scenarios.json written locked + atomic (#37)**: apply_fear_proposals
   wrote the one hand-editable table with a plain `open(..., "w")` - a crash
   mid-write could corrupt it and load_scenarios() would silently fall back
   to embedded defaults, destroying human edits and staged AI proposals. It
   now persists through store.update_json (locked read-modify-write,
   tmp-file + atomic rename).

## [site 0.5.6.01] — 2026-08-17

### Fixed — three audit findings (money math + fetch efficiency)
1. **`_sell_sgov` could mint money (re-entry funding)**: the redemption was
   never clamped to the SGOV position's real shares — a re-entry need larger
   than dry powder drove shares negative, removed the position, and credited
   cash for SGOV value that didn't exist (book value inflated by
   `need - sgov_value`). Shares are now clamped, and the function returns the
   cash ACTUALLY available for the caller to size from.
2. **Re-entry consumed without re-entering**: when a reclaim passed but less
   than $100 was available (or SGOV couldn't cover), the theory was still
   re-affirmed, `reentry_resolved` set, and "re-entered @" printed — the
   one-shot re-entry silently died with no position opened. Resolution now
   happens ONLY inside the `buys >= 100` branch; a shortfall keeps the claim
   open and retries on a later run.
3. **Failed price fetch revalued positions at original cost**: a Yahoo
   429/timeout on one ticker priced it at `buy_price` in the daily snapshot,
   fabricating drawdown/day-change/Sharpe (the dashboard itself already used
   last-known prices — the snapshot feed did not). Snapshot now falls back
   to the last snapshot's price before `buy_price`.

### Changed — cut ~30 Yahoo calls per run (6-min cron was doing ~70/run)
1. **fears.py history is now cached once per calendar day**
   (`fear_history_cache.json`, stale fallback on refresh failure) — the
   gauge previously re-downloaded 2y history for ~24 scenario symbols on
   EVERY run.
2. **Benchmark history cached once per day** inside `ohlc_cache.json`
   ("bench" key, same daily semantics as the indicator bars, stale
   fallback) and each benchmark now builds in its own try/except — one
   failing ticker no longer drops all four comparison series.
3. **`fetch_macro` only runs when the AI layer is enabled** (its only
   consumer) — 6 calls saved per run when AI is off.

## [site 0.5.6.00] — 2026-08-17

### Changed — hosting-ready layering (hosting path step 1)
1. **`store.py` (new)**: single locked write-path for the JSON files the
   site mutates. Every serve.py read-modify-write now goes through
   `update_portfolio()` under a per-path threading lock + best-effort
   cross-process file lock (msvcrt on Windows / fcntl on POSIX), so
   concurrent `/book`, `/mode`, `/bias`, `/park` requests can no longer
   interleave and corrupt portfolio.json. Writes are tmp-file + atomic
   rename; a failed rename falls back to a direct write.
2. **`community.py` (new)**: `sync_version_snapshots()` + `build_mirror()`
   moved out of update.py, `list_strategies()` moved out of
   leaderboards.py — the publish/follow API (hosting path step 2) can build
   on one importable module without running the whole daily update.
3. **Benchmark caching**: leaderboards.py no longer re-fetches 2y of Yahoo
   closes for SPY/QQQ/TQQQ/TMF on every run. Closes live in
   `benchmark_cache.json`, refreshed once per calendar day; a failed
   refresh keeps the cached closes (stale fallback) so the leaderboard
   never loses a benchmark row to a transient Yahoo error.
4. **Behavior unchanged**: same data contracts, same outputs (dashboard.js,
   leaderboards.js, mirror.json regenerated identically) — pure refactor.

## [algo 0.6.1] — 2026-08-17

Engine version officially designated **v0.6.1**: the AI Sentiment Decision
Layer milestone (change-detect verdicts, human-approved market orders,
conviction-scaled sizing, rotations, fear proposals) already shipped and
logged under [algo 0.6.1.00] below. `meta.version.algo` now reflects it.

## Hosting path — GH Pages → i3 NAS → professional (2026-08-17)

Deployment tiers, one codebase:
- **Tier 0 — GitHub Pages (testing):** static `*.js` data files only, zero
  backend — today's model, stays working.
- **Tier 1 — i3 NAS (near goal):** a `server/` package: HTTP API + SQLite +
  a publish job queue + scheduler. Writes live; also regenerates the static
  files for the GH Pages sync.
- **Tier 2 — professional (future):** same `server/` package; SQLite →
  Postgres, proper auth + queue workers.

Frontend rule: the page probes `/api/health`; when absent (GH Pages) it
falls back to reading the static JS files — one app.js, two data paths.
Publishing is a queue, not a request — an i3 handles a worker fine, the
same design scales to Celery/Redis later.

**Step 1 (done, site 0.5.6.00):** `store.py` + `community.py` extraction,
serve.py locking, benchmark caching. **Step 2 (goal, tracked as a GitHub
issue):** `api.py` + SQLite store impl + publish/follow endpoints +
frontend health probe. **Step 3:** professional hosting swap (SQLite →
managed DB, auth, queue workers).

## [site 0.5.5.43] — 2026-08-17

### Fixed — mirror copy contract + SGOV lifecycle
1. **mirror.json sells mislabeled as buys**: `build_mirror()` classified an
   event's action purely by reason (`take_profit`/`stop_loss` = sell,
   everything else = buy) — so `market_order` sells and scheduled-exit
   sells were recorded as **buys** in the copy contract, and a follower
   replaying `mirror.json` would have bought on your sells. Events now
   carry an explicit `action` field (sell/buy) at creation (scheduled
   exits, executed order buys and sells); `build_mirror()` reads it first
   and falls back to the reason heuristic only for legacy events.
2. **SGOV ghost position after full drain**: `_sell_sgov()` marked a fully
   drained SGOV position `closed` without an `exit` record, so the next
   run's `deploy_cash_to_bonds()` could not find an open SGOV and spawned a
   **duplicate SGOV position** (fresh buy_date/cost basis) while the $0
   ghost stayed on the dashboard. A fully drained SGOV is now removed from
   the book entirely; the next park recreates it cleanly.

## [site 0.5.5.42] — 2026-08-17

### Fixed — three leaderboard bugs
1. **Blank board on load failure**: `lbpage.js` only injected `community.js`
   inside `leaderboards.js`'s `onload` — if the data file failed to load,
   the table area stayed completely empty. Now `onerror` injects it too, so
   the empty-state message renders.
2. **Double fetch**: on the leaderboards page, `lbpage.js` (hero cards) and
   `community.js` (tables) each fetched `leaderboards.js`. `community.js`
   now reuses `window.LEADERBOARDS` when it's already loaded.
3. **Unvalidated persisted tab**: a stale/corrupt `aipp.lb.v1` value would
   show an empty board with no tab highlighted. The saved window is now
   validated against the known list.

## [site 0.5.5.41] — 2026-08-17

### Fixed — leaderboard sort was ascending (least->greatest) the whole time
- The comparator sign was inverted: `(vb - va) * -1` = `va - vb` = ascending.
  Now `dir = 1` sorts descending: **Return** greatest->least (default after
  every page load), **Max DD** least drawdown first, **Sharpe** largest first.
- Sort choice no longer persists in localStorage — every page reset restores
  the default Return order, greatest to least.

## [site 0.5.5.40] — 2026-08-17

### Added — version + engine line on all main pages
- "UI vX · Engine vY" now renders on **index** (footer), **leaderboards**
  (header sub), **theories**, **trades**, and **help** (header subs) —
  dashboard already had it. Every page reads it live from `dashboard.js`,
  so the header always tells you which build you're actually running.

### Fixed — leaderboard sort served stale JS
- `community.js` was a static include; browsers kept serving the cached
  old version (flip-toggle behavior). It's now injected by `lbpage.js`
  with a timestamp query (`?t=Date.now()`), same cache-bust pattern as
  `leaderboards.js` — every page load gets the current sort logic.

## [site 0.5.5.39] — 2026-08-17

### Fixed — stale community.js cache served the old flip-toggle sort
- The page loaded `community.js?v=1` (never bumped), so browsers kept the
  old version where clicking the active column reversed the order.
  Cache-bust bumped to `?v=2`; fixed-direction sorting now actually ships.

## [site 0.5.5.38] — 2026-08-17

### Changed — fixed per-column leaderboard sort directions
- **Return** (default): highest first, lowest last.
- **Max DD**: least drawdown first (0.00% → deepest) — no flip on re-click.
- **Sharpe**: largest first, smallest last.
- Column choice still persists (`aipp.lb.sort.v2`); directions are fixed so
  the ordering always matches the column's convention.

## [site 0.5.5.37] — 2026-08-17

### Fixed — benchmark windows were truncated to the book's start date
- Benchmark histories now span the FULL 2y Yahoo fetch (normalized to 100000
  at their own first close). Weekly/monthly/quarterly/yearly are true
  trailing windows over that history, and all-time = the real 2y return
  (e.g. TQQQ now shows +8.55% monthly / +61.90% yearly / +124.34% all-time
  instead of +4.05% everywhere). Max DD and Sharpe now also cover the full
  history.

### Changed — sort buttons → clickable column headers
- Sort buttons removed; click the **Return / Max DD / Sharpe** column
  headers to sort (default Return, high-to-low). Clicking the active column
  again flips the direction (▼/▲); choice persists in localStorage.

## [site 0.5.5.36] — 2026-08-16

### Added — leaderboard sort control
- Sort buttons (Return / Max DD / Sharpe) above the table; **Return** is the
  default, matching the server-side ranking. Client-side re-sort with
  re-numbered ranks; choice persists in localStorage (`aipp.lb.sort.v1`).
  Strategies with a missing metric drop to the bottom.

## [site 0.5.5.35] — 2026-08-16

### Changed — risk-adjusted column: Calmar → Sharpe
- The leaderboard's risk-adjusted column now shows the **annualized Sharpe
  ratio** (mean daily return ÷ daily std × √252, same math as the
  dashboard's summary card). Max DD column stays.

## [site 0.5.5.34] — 2026-08-16

### Added — risk columns on the leaderboard
- **Max drawdown** column (peak-to-trough, same sign convention as the
  dashboard summary).
- **Calmar ratio** column (annualized return ÷ |max drawdown|) — the
  risk-adjusted pick for leveraged/hedge-style strategies: it prices the
  worst-case pain directly and doesn't punish upside volatility the way
  Sharpe does. Numbers stabilize as histories grow past a few sessions.

## [site 0.5.5.33] — 2026-08-16

### Added — leaderboard population: benchmarks + version snapshots
- **Benchmark strategies** on the leaderboard: SPY, QQQ, TQQQ, and a
  daily-rebalanced TQQQ 60% / TMF 40% — fetched from Yahoo daily closes by
  `leaderboards.py` and anchored to the book's start date/value so the
  all-time window compares fairly with the live book.
- **Version snapshots** (`meta.community.snapshot_versions`, experiment —
  normally OFF by design): whenever the book's positions change,
  `update.py` freezes the book as a new version strategy named
  `<strategy> <creation date>` (e.g. "HyperGrowth Sharpe Barbell v5 -
  Conviction-First 2026-08-16"), so the leaderboard shows whether a change
  led to better results. SGOV auto-parking is excluded from change
  detection; at most one version per day; every run appends the day's
  snapshot to all active versions.
- **`meta.community` config block** enables both experiments.
- Leaderboard now deduplicates sources: community strategies + benchmarks
  + the local flagship book.

## [site 0.5.5.32] — 2026-08-16

### Changed — leaderboards is its own site, cards removed
- **Removed the embedded Community Leaderboard cards** from the dashboard
  (`dashboard.html`) and the landing page (`index.html`). The leaderboard
  lives only on its own site: `leaderboards.html`.
- **Top-bar links added**: "Leaderboards" in the dashboard header (next to
  Home/Help) and in the landing nav + footer — same prominence as the
  other top-level pages.

## [site 0.5.5.31] — 2026-08-16

### Changed — leaderboards as a full site
- **`leaderboards.html` rebuilt as a first-class site** (same league as
  dashboard/index): mascot + brand header with nav (Home / Live demo /
  Help), hero stat cards (strategies ranked, top weekly / monthly /
  all-time return with the leading strategy's name), the tabbed Top-10
  panel, a "How copying works" three-step section, and the standard
  footer. `lbpage.js` fills the header + hero cards from
  `window.LEADERBOARDS`.

## [site 0.5.5.30] — 2026-08-16

### Added — dedicated leaderboards site
- **`leaderboards.html`** — the community leaderboard now has its own page
  (archive-page pattern like trades.html): header with as-of + strategy
  count, the tabbed Top-10 table, and a footer noting copy semantics.
- **`lbpage.js`** — fills the page header from `window.LEADERBOARDS` (the
  tables themselves stay rendered by the shared `community.js`).
- Linked from the dashboard's Community panel ("All leaderboards"), the
  landing page's Community section + footer, and the Help page nav.

## [site 0.5.5.29] — 2026-08-16

### Added — community foundation: copy + leaderboards
- **Strategy identity** in `portfolio.json` meta: `strategy_id`,
  `author`, `strategy_tags`, `strategy_short`, `is_public`, and a `copy`
  config block (multiplier, min follow value, fee_bps) — inert metadata
  until the copy engine lands.
- **`mirror.json`** — the copy contract, written by `update.py` every run:
  current positions as `pct_of_book` (the exact allocation a follower
  mirrors) + a normalized `changes[]` feed (every deploy, re-entry, exit
  and executed order with ts/ticker/action/shares/price/amount).
- **`leaderboards.py`** — computes per-strategy window returns
  (weekly 5d / monthly 21d / quarterly 63d / yearly 252d / all-time since
  inception) and writes the **Top-10** leaderboard to `leaderboards.js`
  (`window.LEADERBOARDS`, script-tag format like `dashboard.js`).
  Sources: `community/strategies/*/stats.json` when present, else the
  local book. Called from `update.py` at the end of every run.
- **Community section** on the landing page (`index.html`, new nav link)
  and the dashboard (`dashboard.html`): tabbed leaderboard (Weekly /
  Monthly / Quarterly / Yearly / All time) rendered by the new shared
  `community.js` — top-10 table with gold/silver/bronze ranks, author,
  return %, active tab persisted in localStorage. Works from `file://`.
- **GitHub Actions** now commits `mirror.json` + `leaderboards.js` so the
  live site stays in sync.

## [site 0.5.5.28] — 2026-08-16

### Changed
- **Hero chart reveal is now linear**: the drawing animation used cubic
  ease-out (`1-(1-t)^3`), which speeds through the first part and crawls
  over the last ~10% — that was the perceived end-of-chart slowdown. The
  reveal now progresses at a constant rate (ease = t) over the same 2.4s.

## [site 0.5.5.27] — 2026-08-16

### Changed
- **Hero mock chart enlarged**: canvas height increased from 220px to
  300px (the width already filled the panel), so the line, grid, "AI ON"
  marker and endpoint read more clearly.

## [site 0.5.5.26] — 2026-08-16

### Changed
- **Hero mock chart tail lag root-caused and fixed**: the dips in the
  post-AI section dragged the walk ~14% below the target, leaving the
  endpoint dot floating above the line (the "lag"). The last 12 points now
  receive a linear lift so the line rallies smoothly INTO the target —
  final segment ~1%, jagged shape preserved, no stall, no jump, no dip.

## [site 0.5.5.25] — 2026-08-16

### Changed
- **Hero mock chart tail lag finally fixed**: the tail is no longer always
  blended toward the target (which sagged the line whenever the walk ended
  above it). Now the last two points are only adjusted when they sit ABOVE
  the target — mirrored below it so the final segment always rises into
  the endpoint. When the walk naturally ends below the target the line is
  completely untouched.

## [site 0.5.5.24] — 2026-08-16

### Changed
- **Hero mock chart tail no longer lags**: the 4-point blend that pulled
  the last ~10% of the line toward the target (making it stall) is
  replaced with a light 2-point ease — only the final two points nudge
  toward the endpoint, so the line keeps its natural shape all the way to
  the end while still landing cleanly on the target.

## [site 0.5.5.23] — 2026-08-16

### Changed
- **Hero mock chart post-AI a bit more volatile**: jitter raised to ±2.25%
  with slightly bigger/frequent dips and spikes (still calmer than the
  pre-AI section). The final 4 points are now blended up into the target
  so the line ends cleanly at the endpoint instead of on a random dip.

## [site 0.5.5.22] — 2026-08-16

### Changed
- **Hero mock chart post-AI livelier**: pre-AI section untouched (still the
  super-volatile slow drift). After the "AI ON" marker the jitter doubled
  to ±1.5% with more frequent 2–4% dips and occasional spikes — clearly
  jagged, though still calmer and faster-growing than the pre-AI section.
  Still deterministic via the fixed seed.

## [site 0.5.5.21] — 2026-08-16

### Changed
- **"AI ON" marker is back, deterministic**: the first 30% of the chart is
  super volatile (big ±2.5% swings, sharp dips and spikes) while still
  drifting slowly upward, then the green dashed "AI ON" marker appears and
  the line calms down (±0.75% jitter) and climbs faster to the +38..66%
  target. All driven by the fixed-seed PRNG, so the same line renders
  every load.

## [site 0.5.5.20] — 2026-08-16

### Changed
- **Hero mock chart is now deterministic**: the random walk uses a fixed-
  seed PRNG (mulberry32, seed 20260816) instead of `Math.random()`, so the
  exact same line renders on every load/refresh. The chart no longer
  re-randomizes between visits.

## [site 0.5.5.19] — 2026-08-16

### Changed
- **Hero mock chart y-axis snapped to clean numbers**: the auto-scaled axis
  now snaps to a $20k grid (e.g. $80k/$100k/$120k/$140k/$160k) instead of
  odd $89.5k-style labels. The line itself is unchanged.

## [site 0.5.5.18] — 2026-08-16

### Changed
- **Hero mock chart reverted to the original**: the "AI ON" marker, the
  staged pre/post-AI volatility experiments, and the $600k ending are all
  gone. Back to the original smooth random walk from $100,000 to
  +38..66% (gentle dips, auto-scaled axis, 5 grid lines, endpoint dot and
  value/% label, 2.4s eased reveal + 3.5s pulse). Caption restored.

## [site 0.5.5.17] — 2026-08-16

### Changed
- **Hero mock chart realistic + back to original scale**: the $600k ending
  and sine-wave curves are gone. The walk is now jagged and realistic —
  pre-AI (30%) zigzags hard in a $85k–$115k band with sharp dips and
  spikes, post-AI climbs with per-step jitter (±1%) and occasional
  pullbacks to the original +38..66% ending. Y-axis is a fixed
  $0–$200k grid (labels at $0/$50k/$100k/$150k/$200k) — the 5-digit
  portfolio growing into 6 digits, matching the target customer.

## [site 0.5.5.16] — 2026-08-16

### Changed
- **Hero mock chart volatility fixed**: the 0→$700k axis made ±2% noise
  invisible, so the walk was redrawn with scale-aware movement. Pre-AI (30%)
  now swings hard in a $62k–$145k band (±4% steps with −4..9% dips and
  +3..7% spikes); post-AI climbs to **$621k** with multi-frequency sine
  waves (±3.5% + ±2% of value) plus small jitter and occasional 1.5–3%
  pullbacks — visibly wavy, not a straight line.

## [site 0.5.5.15] — 2026-08-16

### Changed
- **Hero mock chart re-staged**: the "AI ON" marker moved to 30%. The first
  30% is high-noise with dips and spikes but no value growth (flat around
  $100k); after the marker the noise drops and the portfolio climbs all the
  way to **$600k** (+500%). Y-axis is now a fixed $0–$700k grid so the
  $100k start and $600k finish read cleanly.

## [site 0.5.5.14] — 2026-08-16

### Changed
- **Hero mock chart back to the original character**: pre-AI (20% of the
  chart) is a flat sideways jitter in a narrow band with small dips (no
  trend), and post-AI is the original smooth constant climb — now slightly
  more volatile (±1.5% noise + pullbacks) and still never leveling off at
  the end. "AI ON" marker unchanged at 20%.

## [site 0.5.5.13] — 2026-08-16

### Changed
- **Hero mock chart retuned**: the "AI ON" marker now sits at 20% of the
  chart. The pre-AI section is volatile but trending up (big swings with
  dips and spikes on a rising drift, no more flat chopping band), and the
  post-AI section keeps a constant slope with visible noise and small
  pullbacks — livelier than before and it never levels off at the end.

## [site 0.5.5.12] — 2026-08-16

### Changed
- **Hero mock chart tells the AI story**: the pre-AI section of the walk is
  now far more volatile (big swings, sharp drops and spikes in a choppy
  band), and a green dashed **"AI ON"** marker (vertical line + dot + chip)
  appears as the animation reaches it — from there the line gets smoother
  and compounds faster toward the target. Caption updated to match.

## [site 0.5.5.11] — 2026-08-16

### Added
- **Hero mock chart animation**: on page load, a canvas chart in the hero
  ("What your portfolio could look like") draws a rising portfolio line from
  $100k over ~2.4s with a gradient fill, grid, and a pulsing endpoint dot
  with the final value and % gain. Each load generates a fresh (but always
  upward) random walk; clearly tagged "illustrative" with a caption that it
  is not a prediction. Honors `prefers-reduced-motion` (static frame).

## [site 0.5.5.10] — 2026-08-16

### Changed
- **Landing page copy re-pitched around the real product**: the hero and
  sections now sell the goals-and-convictions flow — the user picks a
  playbook (FIRE / fat FIRE / get rich / retirement, risk tolerance, bullish
  convictions), the AI tunes its guardrails to that playbook, researches the
  market daily, and manages the portfolio via recommendations the user
  approves (hands-free auto-trade on the roadmap, with an autonomy dial).
  Feature cards reworked ("Built around your goals", "Tell it what you
  believe", "An AI that researches daily", "You approve every call") and the
  how-it-works steps are now Set your playbook → AI researches & manages →
  Approve or go hands-free. No internals leaked; sign-up UI unchanged.

## [site 0.5.5.09] — 2026-08-16

### Changed
- **Landing page is now the site's default page**: `landing.html` became
  `index.html` and the dashboard became `dashboard.html`. GitHub Pages,
  `serve.py` (localhost:8000) and file:// double-click all land on the
  landing page first; the dashboard lives at `dashboard.html` (its Home
  button goes back to `index.html`). All cross-links, docstrings, README and
  AGENTS.md updated.
- **Sign in → Sign up**: the nav button and modal are now worded as sign-up
  (matches "Create your account"). Still UI-only — no backend, per the
  current stage.

## [site 0.5.5.08] — 2026-08-16

### Changed
- **Landing page rewritten as a proper marketing page**: all internal
  details are gone (no "simulated", no Yahoo/Python/VADER/SGOV/T-bills, no
  strategy names like HyperGrowth, no Alpaca/RIA roadmap, no "mock" sign-in
  wording). Copy now pitches the product to outsiders — automated exits, an
  AI daily read, a fear gauge, theories with receipts, no idle cash — and
  the hero's fourth stat is now "vs S&P 500" (excess return) instead of the
  internal strategy name. "Sign up" links open the sign-up modal; the footer
  no longer links to the internal Theory/Trade archives.

## [site 0.5.5.07] — 2026-08-16

### Added
- **Soft refresh**: the 6-minute auto-refresh (and the Update button) no
  longer reload the whole page — they re-fetch `dashboard.js` in place and
  re-render every section from the new data. Chart/donut/scrollbar listeners
  are now wired once (`dataset.wired` guards) so re-renders don't stack
  duplicate handlers; a failed fetch still falls back to a full reload.
  This is client-side only — on GitHub Pages the data is static until you
  push a new `dashboard.js`, so there is nothing new to pick up there either
  way (the countdown then shows "waiting for new data" as before).

## [site 0.5.5.06] — 2026-08-16

### Changed
- **Dashboard section order**: AI Sentiment now sits directly below Portfolio
  Value History (before the Fear Gauge), and the Sector Limits + PortPie grid
  moved down to sit directly above the Positions table.

## [site 0.5.5.05] — 2026-08-16

### Added
- **Landing page** (`landing.html` + `landing.js`): a marketing front door for
  the site — hero with live portfolio stats pulled from `dashboard.js`
  (value, day change, total return, strategy name), feature cards
  (auto exits, AI sentiment layer, fear gauge, theories, no-idle-cash, news),
  a 3-step "how it works" strip, a roadmap section, and a **mock sign-in**
  modal (email/password stored in localStorage only, no backend — a preview
  of the UI v1 accounts roadmap). Guest mode and sign-out included.
- **Home button** in the dashboard header links back to `landing.html`; the
  landing page links to the dashboard, help, theories and trades.

## [site 0.5.5.04] — 2026-08-16

### Fixed
- **Auto-reload loop**: the next-refresh countdown reloaded the page every
  20s forever when `dashboard.js` was older than the refresh interval (e.g.
  local serve without a fresh update.py run) — each reload re-expired the
  same stale timestamp. Auto-reloads are now capped at 2 tries per stale
  data set, then the header shows "waiting for new data" until the Update
  button (or a fresh run) supplies new data.

## [site 0.5.5.03] — 2026-08-16

### Added
- **Submitted Orders submenu animation**: the drawer now slides open with a
  smooth max-height expand + fade, a rotating chevron on the button
  (▶ → ▼), and a per-card cascade (cards drop in one-by-one, 50ms apart).

## [site 0.5.5.02] — 2026-08-16

### Changed
- **Market Orders moved below the news cards** (Big Stories + Live News
  Feed) and above the Positions table on the main page.

## [site 0.5.5.01] — 2026-08-16

### Fixed
- **Submitted Orders submenu toggle**: the "Click to show Submitted Orders"
  button did nothing — its click listener was attached before the rotations
  `innerHTML +=` append, which re-parses the container and destroys the
  element (and its listener). The toggle is now wired after the final
  append.

## [site 0.5.5.00] — 2026-08-16

Feature milestone (user bump 0.5.4 → 0.5.5): the order lifecycle is now a
first-class UI citizen — submitted state, a persistent proposal queue that
survives AI runs, and visible order-versioning when the AI improves a read.

### Added
- **Proposal queue persists across AI verdicts** (`meta.ai_state.proposals`,
  engine-side merge in update.py): proposals are kept until the next AI run
  supersedes them, instead of vanishing with the verdict that produced them.
  The newest verdict **overwrites & improves** an existing entry for the
  same ticker/direction — a changed amount becomes a NEW actionable
  proposal with an `updated_from` badge (old → new size). The multi-read
  note explains the overwrite rule and that an unsubmitted update never
  cancels your last booked order — it still executes at the next market
  open.
- **Submitted Orders submenu**: booked proposals are hidden under a
  "Click to show Submitted Orders (N)" collapsible button inside Actionable
  Proposals; the header count now shows only open (not-yet-submitted)
  proposals. Booked state is derived from the pending order queue on every
  dashboard write (amount-matched, so a modified size re-arms the Submit
  button), so serve.py's /book and /execute_all flows are untouched.
- Snooze/dismiss keys are now ticker|direction (verdict-independent), so
  they survive across AI runs.

## [site 0.5.4.19] — 2026-08-16

### Added
- **Submitted-order state on proposals**: once a proposal (or rotation pair)
  is booked, its "Submit this Order" / "Book both legs" button is grayed out
  and shows "Order Submitted" / "Both legs Submitted" — matched against the
  pending queue in `D.orders`, so the state persists across reloads until the
  order executes.

## [site 0.5.4.18] — 2026-08-16

### Changed
- **Macro & Sector Convictions**: divider lines removed between rows —
  just the slim name/number list.

## [site 0.5.4.17] — 2026-08-16

### Changed
- **Macro & Sector Convictions compacted**: removed the explanatory
  sub-line, tightened row padding (9px → 4px), smaller name/value fonts —
  the card is now a slim list.

## [site 0.5.4.16] — 2026-08-16

### Changed
- **Sector conviction segment bars removed**: Macro & Sector Convictions
  rows are now a clean two-column list — sector name left, directional
  number right (+0.85 green / -0.35 red / 0.00 gray), tooltip on hover.

## [site 0.5.4.15] — 2026-08-15

### Changed
- **Sector conviction rows now mirror the Market Fear Gauge row structure
  exactly**: name on top, 5-block bar below it (two-line rows with
  divider), value right-aligned at 15px bold — identical styling to the
  fear rows, only the fill color encodes direction (green/red/gray).

## [site 0.5.4.14] — 2026-08-15

### Changed
- **Sector conviction bars capped at the fear-gauge width** (260px) so
  both use the identical bar style — previously the sector bars stretched
  across the whole row.

## [site 0.5.4.13] — 2026-08-15

### Fixed
- **Sector conviction segment bars invisible**: `.fearBar` inside a flex
  `.sectRow` collapsed to zero width (flex children with no container
  width). `.sectRow .fearBar` now grows (`flex:1 1 auto`). Diagnosed via
  headless-Chrome screenshot + vision review.

## [site 0.5.4.12] — 2026-08-15

### Changed
- **Sector conviction bars now use the Market Fear Gauge segment style**:
  5-block segments (filled = strength, color = direction: green bullish,
  red bearish, gray neutral) instead of the single green bar.

## [site 0.5.4.11] — 2026-08-15

### Changed
- **Sector convictions are now single directional scores (-1..+1)**: sign
  = direction, magnitude = strength, neutral sits near 0 — one number,
  no stance words. Prompt rule 1 reworded (`ai_sentiment.py`); the panel
  shows `+0.85` / `-0.35` / `0.00` style values (green/red/gray) with a
  hover tooltip. Old confidence-style reads self-heal on the next AI
  verdict (omitted sectors keep the last read until then).

## [site 0.5.4.10] — 2026-08-15

### Changed
- **AI Sentiment layout is now single-column**: Actionable Proposals sits
  as its own full-width group BELOW Macro & Sector Convictions (no more
  side-by-side columns).

## [site 0.5.4.09] — 2026-08-15

### Changed
- **Sector conviction rows fixed**: the number was the AI's CONFIDENCE
  (0-1), but the UI rendered it as a directional -1..+1 score with a `+`
  sign — everything looked bullish. Rows now show full words:
  `BULLISH · 85% confidence` (bar/color driven by stance: green/red/amber).
- **AI Sentiment card order**: Macro & Sector Convictions column now sits
  ABOVE (before) Actionable Proposals — left on desktop, first on mobile.

## [site 0.5.4.08] — 2026-08-15

### Changed
- **Market Fear Gauge shows ONE rating per fear**: the separate "AI read"
  badge is removed — each Top-5 fear row now shows only the single
  deterministic gauge score (0-5, 5 = panic), with the scale explained in
  the panel header. AI sentiment on fears remains visible in the AI
  Sentiment panel's witness table.

## [site 0.5.4.07] — 2026-08-15

### Changed
- **Market Fear Gauge dual-rating clarity**: each Top-5 fear row shows two
  0-5 ratings (deterministic gauge score + AI sentiment read), which
  customers misread as duplicate scores. Added a legend above the list
  ("Score = market-data gauge · AI = AI sentiment read — both 0-5, 5 =
  panic"), relabeled the badge to "AI read", and added tooltips to both
  ratings.

## [site 0.5.4.06] — 2026-08-15

### Changed
- **Quarterly rebalance audit DISABLED** (`meta.limits.rebalance.enabled:
  false`): the AI sentiment layer continuously re-sizes sector weights, so
  a once-per-quarter drift flag is noise, not signal. `rebalance_audit()`
  now honors the flag and returns no flags while disabled; set
  `enabled: true` in `portfolio.json` to re-arm it.

## [site 0.5.4.05] — 2026-08-16

### Consensus exit engine (five-round design review, full build)

The vol-halt / take-profit engine was redesigned in a five-round
argue-agree-improve review (human + AI) and is now fully implemented.
All indicator math runs on COMPLETED daily sessions only; only the
vol-halt uses the live 6-min price. Engine data rules, not an algo
milestone (algo bump at user discretion).

### Added (engine rules)
- **Dynamic vol stops**: leveraged positions stop at
  `-max(|static|, 2.5 x ATR14%)` on the 1x underlying (e.g. TQQQ->QQQ).
  Widens in high vol, floored at the static level; recomputed every run.
  The halt freezes `reclaim_level` at the level in force.
- **Base trim**: leveraged positions harvest **50% of shares** at +50%
  wrapper PnL (one-shot, `base_trimmed`), proceeds to SGOV, arms the
  runner trail (`runner_active`, one-way).
- **Runner trail**: exits the remaining position on **2 consecutive
  completed closes < EMA20(1x)** OR a single completed close
  `<= EMA20 - 1.5 x ATR14` (emergency; intraday wicks never count).
- **Re-entry trend gate**: vol-halted theories re-enter only when the
  underlying posts 2+ consecutive closes above the frozen
  `reclaim_level` AND the last close is above its EMA20 (no dead-cat
  re-entries). The level stays pinned at halt time.
- **Hedge harvester (recommendation-only)**: while a growth vol-halt is
  active, a Crisis Alpha hedge >= +2 sigma above its 50d mean gets a
  recommended 50% trim into the re-entry pool — never an order, and
  never when the hedge is claimed by a confirmed fear scenario
  (score >= 4.0 in its hedge_ticks). Surfaces as `DASH.hedge_harvest`.
- **Leverage mapping guard**: positions with `leverage > 1` and no 1x
  `underlying` now print a loud WARNING each run (wrapper backstop only).

### Added (data / UI)
- 1y daily OHLC for underlyings + hedges, cached in `ohlc_cache.json`
  (fetched once per day, outside the repo payload).
- `positions[]` telemetry: `dynamic_stop_pct`, `underlying_ema20`,
  `underlying_atr14`, `runner_active`, `base_trimmed`. Positions table
  shows the dynamic stop % and an `R` badge for armed runners; the
  calibration panel shows runner count + harvester status.
- Base trims emit partial-exit `take_profit` events with `partial`
  shares; runner exits emit `take_profit` events with
  `runner_2close` / `runner_emergency` notes.

## [site 0.5.4.04] — 2026-08-16

### Changed
- **AI summary paragraph removed from the GUI**: the heartbeat no longer
  shows the verdict's prose summary (`ai.summary` stays in the data for
  the ledger / future use, it just isn't rendered).
- **Booking buttons renamed**: "Book All Proposals &rarr; Orders" is now
  **Submit all Orders** and the per-proposal card button is **Submit this
  Order** (endpoints unchanged: `POST /execute_all` and `POST /book`).

## [site 0.5.4.03] — 2026-08-15

### Fixed
- **Dry-powder toggle actually wired**: the SGOV | Cash toggle was being
  wired before its panel rendered, so clicks did nothing. Wiring now runs
  right after the calibration panel is built. On `file://` (no local
  server) it alerts that `python serve.py` is needed to persist —
  the toggle itself is a server-write to `meta.park_mode` by design.
- **Trade Events fallback colored**: when no trades happened in the
  7-day window, the fallback lines were all-blue with no visible pills.
  Now every line has a color-coded pill and ticker: `DEPLOY` green
  (SGOV parking), `REBAL`/`DRIFT` amber, `AI READ` blue, plus the
  existing green/red + NEW/CLOSED treatment once real trades land.

## [site 0.5.4.02] — 2026-08-15

### Changed
- **Liquidity card relabeled**: "Cash + SGOV" is now **SGOV + Cash**
  (SGOV is always the bigger half); the sub-line shows both parts
  (`$73k SGOV · $25 cash`). Same wording fix in Help.
- **Sentiment delta always visible**: the heartbeat now always shows
  `(Δ+0.00)` style signed delta vs the previous reading (0.00 until the
  second call lands).
- **Dry-powder toggle**: the "No idle cash: SGOV-parked" note is gone,
  replaced by an inline **SGOV | Cash** toggle in the AI panel's
  deterministic-guardrails block. `serve.py POST /park` writes
  `meta.park_mode` (default `"sgov"`); in `"cash"` mode
  `deploy_cash_to_bonds()` leaves surplus cash idle (no SGOV buy, no
  deploy event). Data rule, not an engine milestone.
- **Trade Events (main page)**: tickers are now colored green (position
  grew / buy) or red (shrank / sell), and buys that opened a new position
  get a **NEW** pill / sells that closed one get a **CLOSED** pill
  (matched against `positions[].status` + `buy_date` / closed state).

## [site 0.5.4.01] — 2026-08-15

### Version policy change (user-decreed)
- From now on the AI only bumps the **patch digits**: `site` moves
  `0.5.4.00 &rarr; 0.5.4.01 &rarr; 0.5.4.02 ...`. The user alone bumps the
  feature digit (`0.5.4 &rarr; 0.5.5`) and the stage marker; the engine
  (`algo`) only on user-announced milestones. `AGENTS.md` rewritten to
  match.

### Changed
- **Booking flow restored + relabeled**: the EXECUTE-mode toggle is gone.
  "Execute All" is back as **Book All Proposals &rarr; Orders** (restored
  `serve.py POST /execute_all`, books the whole verdict queue at once) and
  each proposal card's button is now **Book Proposal** (the per-card
  `POST /book`). Recommend mode is the only mode.
- **Conviction-scaled order sizing**: proposal amounts are now
  `order_size &times; |conviction_score|` (e.g. TQQQ 0.65 &rarr; $1,625 of
  the $2,500 size), computed in `ai_sentiment.bullish_layer()` and carried
  on the proposal; `refresh_orders_from_ai`, `/book` and `/execute_all`
  book that amount. Rotation legs stay flat at `order_size`.
- **Port-weight line on proposal cards**: `Port 4.0% &rarr; 4.1% (+$1,625)`
  in green (growing exposure) / red (trimming), computed against the live
  book value.
- **Sentiment slider (BIAS)**: a &minus;5..+5 slider in the AI panel posts
  `serve.py POST /bias` &rarr; `meta.ai.user_bias`, embedded in the Gemini
  prompt as "USER SENTIMENT BIAS" (tilts stance + convictions, never
  overrides the skews). The heartbeat bar now also shows a **Sentiment
  index**: mean conviction score of the last verdict with the &Delta;
  vs the previous verdict.
- **AI subtitle trimmed** to `Last read <asof>` (Tier A/B line removed);
  news disclaimers elsewhere unchanged.
- **CNN Fear &amp; Greed labels**: gauge and heartbeat now read "CNN
  Fear&amp;Greed".
- **Trade Events fallback**: if no trades happened in the 7-day window the
  card now lists the latest non-trade events (deploy cash, rebalance
  flags, AI reads) instead of showing empty.
- `update.py` records `sentiment_index` / `sentiment_delta` in
  `meta.ai_state`; `build_ai_payload()` exposes them; `meta.ai.user_bias`
  added (default 0).

## [site 0.5.4.00] — 2026-08-15

### Changed
- **Booking flow**: the AI panel's "Execute All &rarr; Orders" button is
  gone. Each proposal card now has a **Book Order** button and each
  rotation row a **Book both legs** button &mdash; both write ONE
  human-approved pending order (or the rotation's two legs) via
  `serve.py POST /book` at `meta.ai.order_size` (source `book_<date>`).
  The endpoint validates the order against the current AI verdict so only
  AI-proposed actions can be booked.
- **Trade Events card simplified** (main page): only buys/sells with the
  money changed &mdash; `BUY TQQQ &minus;$2,500` / `SELL ZROZ +$2,498`.
  Full details (price, shares, realized P&amp;L, notes, timestamps) live
  in the Trade Archive, which gained a **Money** column. `market_order`
  events now carry an `amount` field (engine data addition, not a
  milestone).
- **Market Fear Gauge header** dropped "&middot; 1 = calm &middot; 5 =
  panic" &mdash; the bars speak for themselves.
- **Theories Scorecard wheel**: cards raised again (18px &rarr; 24px) so
  the `1 / N` counter is fully clear, plus a more compact counter with a
  higher z-index so it stays readable even in short windows.

## [site 0.5.3.00] — 2026-08-15

### Changed
- **AI witness merged into the Market Fear Gauge** (de-dup): the duplicate
  fear table in the AI panel's right column is gone. Each fear row in the
  classic gauge now carries the AI score (`AI 3.1` chip next to the name),
  the blended tag (`blended·AI-adjusted`) and the trend word next to the
  existing arrow. The AI column is renamed "Macro &amp; Sector
  Convictions" and keeps only the sector bias bars.
- Removed the duplicate "Book leverage factor" line from the
  Calibration &amp; Safety Monitor (already shown in the Sector Limits
  panel header).

## [site 0.5.2.00] — 2026-08-15

### Fixed
- **Theories Scorecard card overlap**: wheel cards were covering the
  card counter (`1 / N`) at the bottom of the stage — cards now sit
  18px higher (`top: calc(50% - 18px)`) with no change to the panel's
  row height.

### Added
- **Mode toggle (Recommend | Execute)** in the AI Sentiment panel header,
  default **RECOMMEND**: proposals stay advice until the new **Execute All
  &rarr; Orders** button converts them (proposals + rotations) into
  human-approved pending market orders. EXECUTE mode makes AI refresh
  auto-replace pending orders (the old algo-0.6.0 behavior). Buttons post
  to `serve.py` (`/mode`, `/execute_all`) and need the local server.
- **Fear &amp; Greed gauge on the page**: CNN-style 0-100 needle bar
  (Extreme Fear &rarr; Extreme Greed zones) in the Market Fear Gauge panel
  header plus a heartbeat item in the AI bar; drives the AI prompt's
  "don't buy the top" crowding gate.
- **Rotations card**: paired sell&rarr;buy proposals render under
  Actionable Proposals.
- **Fear Scenario Proposals box**: AI-proposed crash scenarios staged
  pending review in `fear_scenarios.json`, with watch signals and hedges.
- **Calibration track record**: directionally-wrong conviction badges
  (TQQQ 2/3 wrong) in the Calibration &amp; Safety Monitor.

### Changed
- Orders section note now explains the active mode's semantics.
- Cache-bust `?v` bumped (`app.js?v=32`, `styles.css?v=30`).

## [algo 0.6.1.00] — 2026-08-15

### Added
- **Change-detect prompt** (`ai_sentiment.py`): embeds `YOUR PREVIOUS
  VERDICT` (prior stance, sector biases, fear overrides, convictions,
  summary) plus fact deltas; the AI outputs **ONLY changes** - omission
  means agreement, the engine merges silently. Rules renumbered with the
  explicit **barbell mandate** (hyper-growth core + hedge-stack
  insurance, no idle cash, never chase euphoria).
- **Crowding gate**: `update.fetch_fear_greed()` pulls the CNN-style
  Fear &amp; Greed index (free endpoint, no key, never breaks a run) into
  the snapshot; the prompt warns when additions are crowded (&ge;75) or
  dips may be opportunities (&le;25).
- **Calibration**: `update.compute_calibration()` scores each prior
  conviction against the move since it was written (&lt;0.5% = noise);
  wrong calls accumulate into `meta.ai_calibration` and are fed back to
  the next prompt so confidence on a repeatedly-wrong ticker starts
  discounted. Displayed in the UI.
- **Rotations**: verdict schema gains `rotations[{sell, buy,
  rationale}]`; `rotation_layer()` whitelists both legs to open
  holdings; orders become a matched sell+buy pair at `order_size` each.
- **Editable fear table**: scenarios moved from the hardcoded `FEARS`
  list into **`fear_scenarios.json`** (F1-F8 verbatim). `fears.py`
  loads it (falls back to embedded defaults), and `apply_fear_proposals()`
  persists the AI's `fear_proposals`/`fear_edits` - new scenarios are
  staged `pending_review: true` and skipped by `build_fears()` until a
  human clears the flag and writes components; safe edits (name / hedge
  ticks) apply immediately. Per-scenario `sizing` dicts are honored.
- **Mode-aware orders**: `meta.ai.mode` (default `recommend`). In
  recommend mode `refresh_orders_from_ai()` leaves pending orders
  untouched (Execute All writes them via `serve.py POST /execute_all`);
  in execute mode it replaces pending orders with proposals + rotations
  as before.

### Changed
- `_validate_verdict()` accepts dynamic fear ids from the scenario table
  (F9+ proposals validate after approval).
- Verdict/dashboard payload gains `rotations`, `fear_proposals`,
  `mode`, `gauge`, `calibration`.

## [site 0.5.1.03] — 2026-08-14

### Changed
- **Header mascot image swapped** for the zoomed-in version the user
  supplied (temp-logo.jpg) + `?v=2` cache-bust so stale browser copies
  can't hide it.

## [site 0.5.1.02] — 2026-08-14

### Changed
- **News disclaimer moved to the Live News Feed card**: "display only — news
  is not used by the AI (yet)" now sits with the headlines it describes,
  instead of cluttering the AI heartbeat bar.

## [site 0.5.1.01] — 2026-08-14

### Changed
- **Versioning re-baselined** to the four-part notation **`v0.5.F.PP`** (per
  user rule): feature digit increments on new features (0.5.1 → 0.5.2), the
  two-digit patch increments on bug fixes for a feature (0.5.1.01 → 0.5.1.02),
  and the leading `0.5` only moves (→ 0.6) when the user deems it. Prior
  entries under the old `0.5.2/0.5.3/0.5.4` notation remain as history.
- **Header mascot fixed**: now a plain 54px box (no CSS transform) — the
  largest size that fits the header row, which the title block already sets.
  (The previous scale-transform looked unchanged because the page being
  viewed was a stale cached v0.5.1 build — hard-refresh to see new builds.)

## [site 0.5.4] — 2026-08-14

### Changed
- **Header mascot bigger** via CSS scale (layout box unchanged — row height untouched).
- **GitHub update cadence**: market closed → ONE run/day at 01:00 UTC (was hourly —
  no more server flooding); pre-open window (09:00–09:30 ET) + market hours →
  every 6 min via `python update.py --preopen`, which forces the AI verdict
  refresh right before the bell so orders land fresh pre-execution. Out-of-window
  6-min runs are cheap no-ops (new `market_state()` helper in update.py; DST-aware).
  Dashboard countdown now shows a 24h next-refresh when closed.
- **AI heartbeat "News" label** rewritten: "shown here only · not used by the AI"
  (was "Tier B — display only").
- **Portfolio vs SPY card removed** (the SPY overlay on the history chart stays).
- **Layout**: Portfolio Value History now owns its full-width row; Sector Limits
  and PortPie share the row beneath (two cards side by side).
- **Theory wheel**: side cards sit closer to the front card (smaller gap, less
  shrink) — deck no longer looks spread out.

## [site 0.5.3] — 2026-08-14

### Changed
- **Dismiss on AI proposals now asks first**: clicking Dismiss flips the
  proposal card over (3D flip) to an "Are you sure?" confirm with
  Yes, Dismiss / Keep — no more accidental one-click dismissal.
- **Snoozed proposals auto-restore**: a 10s poller prunes expired snoozes
  from localStorage and re-renders, so cards come back without a reload.

## [site 0.5.2] — 2026-08-14

### Added
- **Help site now documents the end goal**: "Where this is going" panel on the
  Simple tab and an "End goal & roadmap" section on the Advanced tab — paid
  subscription service for other users (sell the tool, not the advice),
  Alpaca Phase 1 integration, RIA Phases 2–3 staging, trust-moat framing.
- **README rewritten** for the new end goal: live GitHub Pages URL, roadmap
  (UI v1 = accounts + personalized AI, Engine v1 = 100% AI trades), market
  orders (algo 0.6.0), quarterly no-tolerance rebalance audit, `fears.py` and
  archive pages in the file table.

### Changed
- GitHub repo About: added description + homepage (GitHub Pages site).

## [site 0.5.1] — 2026-08-14

### Fixed
- **CRITICAL: 0.5.0 shipped with a broken render chain.** `renderOrders()`
  called the `esc` helper, which only exists as a LOCAL const inside
  `renderFears`/`renderNews` — every renderer after it (Positions, Sector
  Limits, Portfolio vs SPY, Theories Scorecard, Trade Events, News,
  Value History chart, donut) threw `ReferenceError` and rendered empty,
  while the summary cards / fears / AI panel (which run first) survived.
  Switched to the render-scoped `escA`. Full render-chain scope audit
  (helpers vs local consts) now passes for all 10 renderers.
- **Key moment logged (2026-08-14)**: the UI v0.5.0 / Engine v0.6.0
  milestone deployed with this breakage; caught on first visual check,
  fixed in 0.5.1. Full pre-milestone backup taken at
  `Stock Picker Backup 2026-08-14 pre-0.5.0-0.6.0\` (sibling of this
  project); git baseline remains commit `9ce0e7e` (site 0.4.10).
- **Lesson**: never reference local-scope helpers (`esc`) from another
  renderer; only the render-scope helpers (`escA`, `fmt$`, `fmtN`,
  `cls`, `sign`) are safe everywhere.

## [algo 0.6.0] — 2026-08-14

**Engine v1 stepping stone: AI proposals become executable market orders.**
The AI still never trades directly — a successful verdict REFRESHES the
human-approved `orders` list in portfolio.json; execution is a
deterministic market-order engine that runs at the LIVE price on
market-open runs only.

### Added
- **`execute_pending_orders()`** (update.py): pending `orders`
  `{ticker, action buy|sell, amount, status, source, created, note}`
  execute at the live price on the next market-open run. Buys redeem
  SGOV (no-idle-cash invariant holds); sells realize P&L into cash,
  which the no-idle-cash policy then re-parks. Full-position sells close
  the position like a TP/SL exit. Missing prices / positions /
  insufficient SGOV defer the order (never dropped). Events logged as
  `reason: "market_order"`. Executed history pruned to last 15.
- **`refresh_orders_from_ai()`** (update.py): when a verdict succeeds and
  `meta.ai.orders_refresh` is true, PENDING orders are replaced with the
  verdict's proposals, each sized at `meta.ai.order_size` (2500) —
  direction from AI, size from the human-approved config. Executed orders
  stay as history.
- **`python update.py --ai`**: forces the AI call even when the market is
  closed (the Monday pre-open ritual) — refreshes pending orders with the
  new verdict; execution still waits for a market-open run.
- Dashboard payload: new `orders` section (pending + executed tail) with
  the UI's new Market Orders panel.
- 7 human-approved market orders seeded from the 2026-08-14 verdict
  (TQQQ/SOXL/DRAM/NLR/BTAL/DBMF buy 2.5k, ZROZ sell 2.5k).

### Changed
- **Sector limits rename**: `meta.limits.rebalance.targets` ->
  `meta.limits.rebalance.limits` (old key still read as fallback).
  Prompt/AI snapshot field `target_pct` -> `limit_pct`; audit messages
  now say "limit".
- **SGOV exempt from sector limits**: `rebalance.exempt_sectors` =
  ["Short-Term Bonds"] — dry powder has NO cap; the quarterly audit
  never flags SGOV, so liquidity is always there when an opportunity
  appears.
- Version: **algo 0.5.9 -> 0.6.0** (sentiment-driven trade logic, the
  first real step toward Engine v1).

## [site 0.5.0] — 2026-08-14

### Added
- **Market Orders panel** on the main page: every order with
  PENDING/EXECUTED status, action pill (BUY/SELL), amount, source, and
  execution detail (price, shares, realized P&L). Empty state hides the
  panel. Renders from the new `DASH.orders` payload.
- Header now reads **UI v0.5.0 · Engine v0.6.0**.

## [site 0.4.15] — 2026-08-14

### Fixed
- **Dashboard showed "AI Sentiment DEGRADED" after a successful call**:
  `build_ai_payload()` only serialized the transient verdict of the
  current run, which `run_ai_layer()` skips when the market is closed
  (or the daily call cap is hit) - so the banner claimed failure even
  with a fresh verdict persisted in `meta.ai_last_output`. `main()` now
  falls back to the persisted verdict, so the AI section always shows
  the latest real read. Proposals re-derive via `bullish_layer` (still
  read-only, whitelisted to holdings).

## [site 0.4.14] — 2026-08-14

### Changed
- **AI prompt hardening (review pass on the Monday-launch prompt):**
  - `update.py` gains `fetch_macro()`: live SPY / QQQ / ^VIX / ^TNX /
    JPY=X / HYG with 1-day % change (Tier A facts). `^TNX` normalized
    from Yahoo's x10 format (41.80 -> 4.18). Failures degrade per-symbol,
    never break the run. Wired through `run_ai_layer(data, ..., macro)`.
  - `build_market_snapshot()` accepts `macro` and injects a flat
    `macro` block (symbol px + `<SYM>_1d_pct`) into MARKET STATE so the
    LLM can actually judge theories T1/T3/T9/T10/T13 (SPY), T17 (VIX),
    T18 (USDJPY), F4/F6 (yields), F7 (HYG).
  - `build_prompt()` now ships **active theories only** (pending/paused;
    abandoned T11/T12 pruned, `status` field stripped) and a numbered
    RULES block: explicit bounds (conviction -1..1 float, urgency/
    confidence 0-100 int, sentiment 1-5), holdings-only ticker universe
    (omission = hold), ticker-conviction-overrides-sector-bias, no
    dollars/shares, JSON-object-only reply. Schema stays pure JSON (no
    comments - the validator's `json.loads` rejects them).
  - `bullish_layer()` whitelists convictions to open holdings - AI
    hallucinated tickers (NVDA, TLT, ...) are discarded with a WARNING,
    never rendered as review cards. Validator clamps were already in
    place (ai_sentiment.py `_validate_verdict`).
  - `_call_openrouter()` sends `response_format: {"type": "json_object"}`
    so Gemini 3.7 Flash cannot wrap the verdict in prose or fences, and
    uses a dedicated token budget (`meta.ai.max_tokens: 16000`) - the
    previous 4000-char cap was exhausted by extended-thinking reasoning
    tokens (finish_reason=length, truncated JSON -> degraded).

## [site 0.4.13] — 2026-08-14

### Changed
- **AI provider switched to Gemini 3.7 via OpenRouter** (`meta.ai`):
  `provider: "gemini"`, `router: "openrouter"`, `model:
  google/gemini-3.7-flash` with **extended thinking**
  (`reasoning_effort: "high"` — reasoning is mandatory on this model).
  `ai_sentiment.py` gains `_call_openrouter()` (key from
  `OPENROUTER_API_KEY` env var or opencode `auth.json` "openrouter"
  entry) and `call_ai()` routes `provider=gemini + router=openrouter`
  through it; direct Gemini (`GEMINI_API_KEY`) stays as fallback when
  `router` is absent. `debug_free` reset to false.

## [algo 0.5.9] — 2026-08-14

### Added
- **AI Sentiment Decision Layer WIRED into update.py** (behind
  `meta.ai.enabled`, still false): `run_ai_layer()` gates cadence (1x per
  market-open day, max_daily_calls cap), persists `meta.ai_last_output` +
  `meta.ai_ledger` (28-day tail), appends theory evidence entries + one
  `ai_sentiment` audit event, and blends AI fear scores into the DISPLAYED
  fear gauge via the two-independent-witnesses formula
  (`fears.apply_ai_witnesses`). `meta.fear_state` stays market-witness.
- Dashboard payload: new `ai` section (verdict, proposals from
  `bullish_layer`, ledger tail, state) — null/absent when disabled or
  degraded. UI render is a later milestone.
- Invariant kept: AI is read-only; any failure degrades to exactly today's
  behavior. Circuit-event re-runs (|dQQQ|>2.5%, VIX +15%) deferred.

## [algo 0.5.8] — 2026-08-14

### Added
- **ai_sentiment.py** (engine milestone, first AI decision-layer draft):
  Tier A market snapshot + Gemini verdict call + schema validation +
  fact-delta ledger + theories/fears/bullish layer translators.
  **DISABLED by default** (`meta.ai.enabled: false`), not yet wired into
  `update.py` — the book behaves exactly as before.
- Roadmap: folded AI Sentiment Decision Layer design (grounding tiers,
  five invariants, cadence guardrails, merged verdict schema).

## [site 0.4.12] — 2026-08-14

### Added
- **AI Sentiment panel** on the main dashboard (renderAI in app.js): status
  badge (ACTIVE/DEGRADED/OFF + degraded slate when the layer is off or
  broken), heartbeat bar (stance, last call, calls today, model, Tier A/B
  grounding), actionable proposal queue with urgency badges (>=75 red,
  50-74 amber, <50 silent) + Review & Copy Order / Snooze 24h / Dismiss
  buttons (persisted in `stockpicker.ai.q1`), macro & fear gauge
  two-witness table (AI score vs blended level), theory evolution ledger
  (AI reads only - statuses never auto-change), and calibration & safety
  monitor (track-record ledger, vol-halt count, leverage factor, guardrail
  status). Reads `window.DASH.ai`; renders the offline slate when null.
- Engine plumbing (no algo bump - not a milestone): ai_sentiment.py now
  routes providers - **deepseek** (default, `DEEPSEEK_API_KEY`,
  OpenAI-compatible endpoint) or gemini (`GEMINI_API_KEY`); config in
  `meta.ai.provider`/`model`.
- Same-day provider change: **zen** is now the default provider
  (`opencode.ai/zen/v1/chat/completions`, OpenAI-compatible; model
  `deepseek-v4-flash` PAID = zero-retention). Key via `ZEN_API_KEY` env var
  or falls back to opencode's `~/.local/share/opencode/auth.json`. The
  free `deepseek-v4-flash-free` tier is deliberately NOT used — its data
  may train the model. `meta.ai.enabled` flipped to true (first call fires
  at the next market open).
- Debug guard: `meta.ai.debug_free: true` routes dev/debug runs to the FREE
  `deepseek-v4-flash-free` model ($0 spend, warning printed that request
  data may be used for training); flip to false for production runs.

## [site 0.4.11] — 2026-08-14

### Added
- Roadmap: v1 business & legal staging (tool-not-advice framing, Alpaca
  integration, RIA phases 1-3, on-ramp routes, trust moat, Fear Gauge
  rebrand note) + a v1 launch checklist.

## [site 0.4.10] — 2026-08-14

### Added
- Temp logo (Gemini-generated `temp-logo.jpg`) used for the header mascot
  until the real logo is ready.

## [site 0.4.9] — 2026-08-14

### Added
- "Next refresh" countdown in the header (closes #11): ticks down to the
  next expected data refresh (6 min during market hours, hourly otherwise,
  matching the GitHub Action cron), then auto-reloads the cache-busted
  dashboard. If the new data isn't deployed yet it shows "waiting for new
  data" and waits rather than reload-looping.

## [site 0.4.8] — 2026-08-14

### Fixed
- Card rotation slowed a touch more: slide and flip transitions 0.7s ->
  0.85s, in-drag catch glide 0.25s -> 0.3s.

## [site 0.4.7] — 2026-08-14

### Fixed
- Restored the wheel stage's soft radial glow background (removed in
  0.4.2), so the theory cards no longer look spread out / floating in
  empty space. The blank-layer fix from 0.4.5 is unaffected.

## [site 0.4.6] — 2026-08-14

### Fixed
- Reverted the 0.4.4 card-face lightening (faces are back to the original
  dark gradients and `--border`); the transparent-card fix from 0.4.5
  remains, which is what actually removed the blank layer.

## [site 0.4.5] — 2026-08-14

### Fixed
- THE blank layer: wheel cards were still matched by the shared
  `.card{background:var(--panel)}` scorecard rule, so every wheel card
  carried an opaque panel rectangle behind its faces — when a card was
  flipped edge-on that slab covered the side cards. `.wheelStage .card`
  now explicitly sets `background:transparent; border:none; padding:0`,
  so a card is only ever its two faces.

## [site 0.4.4] — 2026-08-14

### Fixed
- The "blank card" behind the front card during a flip is gone for good:
  the deck-back pseudo-cards were removed (they read as a hidden blank
  card covering the side cards), and the card faces are now clearly
  lighter than the page background with a stronger border — so the side
  cards behind the flipping card are actually visible through its
  footprint mid-flip, like a real deck.

## [site 0.4.3] — 2026-08-14

### Fixed
- Deck stack behind the front card now sits flush (no offset), so it is
  invisible at rest and only fills the card footprint mid-flip — no more
  "bonus cards" peeking out, no more blank gap when flipping.
- Rotation is calmer overall: card slide and flip both slow to 0.7s (from
  0.55s), in-drag catch glide to 0.25s.

## [site 0.4.2] — 2026-08-14

### Fixed
- Flip no longer reveals a blank slab behind the front card: the wheel
  stage's background was removed and the front card now sits on a small
  fanned stack of card backs, so flipping shows a deck instead of empty
  space.
- Swipe speed dialed down: mouse-wheel/trackpad advance now waits 400ms
  between cards (was 90ms) and a drag can only catch the next card every
  150ms, so a fast flick moves exactly one card instead of chaining
  through several. Card slide is slightly calmer (0.55s) and the in-drag
  catch glides a touch softer (0.2s).

## [site 0.4.1] — 2026-08-14

### Fixed
- Theory-card flip 3D context: removed `will-change`/`preserve-3d` from the
  card so the browser no longer flattens the flip mid-transition (the old
  "book-spread" glitch where both faces rendered). Flip now animates a clean
  single face.
- Mid-drag catch is now a smooth glide (0.15s easing while dragging) instead
  of a hard teleport.
- Wheel dragging on phones: gestures now run on native touch events
  (touchstart/move/end) so the browser can never cancel them; vertical
  swipes still scroll the page, horizontal swipes always drive the wheel.
  A gesture that already caught the next card no longer double-advances on
  release.

## [site 0.4.0] — 2026-08-14

### Fixed
- Issue #16 (real fix this time, verified in a headless-browser test):
  - **Page-width bug**: the Sector Limits rows' fixed min-widths
    (name 130 + value 86 + cap 44 + stat 56 + gaps) totaled ~346px while a
    390px phone leaves only ~342px of content — the page was 4-19px too
    wide, so 1-finger horizontal swipes panned the page instead of the
    cards. Rows now wrap on narrow screens (`@media max-width:520px`) and
    `html` also clips horizontal overflow + `overscroll-behavior-x:contain`
    as an iOS-proof backstop.
  - **Carousel catch**: dragging now brings the next card to the front the
    moment the drag passes ~45% of the card gap — no need to let go. The
    gesture re-anchors and can chain through several cards in one drag.
  - **Flick velocity bug**: release velocity was always computed as ~0
    (`dragPos - lastX` where lastX was the same event), so flicks never
    fired; velocity is now measured per move-pair and a fast swipe always
    advances regardless of distance.

### Changed
- Version jump 0.3.x -> 0.4.0 per user decision.

## [site 0.3.11] — 2026-08-14

### Fixed
- Issue #16 follow-up: the *page* itself could scroll horizontally, so
  horizontal trackpad swipes / shift-wheel over the dashboard panned the
  whole page ("menu moves left/right") instead of rotating cards. Body now
  clips horizontal overflow (`overflow-x:hidden`) and the value/news/
  comparison grids use `minmax(0,1fr)` so nothing can force the page wider
  than the viewport.
- Wheel gestures over the theory cards now rotate the deck on BOTH axes:
  horizontal `deltaX` swipes (trackpad) rotate cards too instead of being
  ignored — claimed with `preventDefault` so the page can never pan
  sideways from the scorecard.

## [site 0.3.10] — 2026-08-14

### Fixed
- Issue #16: theory-card wheel mobile gestures. The stage no longer blocks
  page scroll (`touch-action: pan-y` instead of `none`) — vertical swipes
  starting on the cards now scroll the page, and gestures are
  direction-locked after 8px so a diagonal swipe never drags the cards.
- Fast flicks now advance cards by release velocity even under the old
  28%-gap threshold (previously a quick swipe just snapped back, feeling
  dead); snap-back and advance still animate smoothly.
- Tap-to-flip preserved: click is only suppressed after the gesture commits
  to horizontal, so a clean tap on the front card still flips it.
- Hint text updated to match: "swipe or scroll to browse · tap the front
  card to flip · tap a side card to select".

## [site 0.3.9] — 2026-08-14

### Added
- Portfolio Value History chart: **1W** and **YTD** range buttons.
- Benchmark dropdown replaces the "vs SPY" checkbox: pick **SPY / QQQ /
  TQQQ / MUU** (MUU = Direxion Daily MU Bull 2X). Each is normalized to the
  same $100,000 start and aligned to portfolio dates; choice is remembered.
- Engine side (no algo bump): `update.py` now fetches and emits all four
  benchmarks under `benchmarks` (SPY stays as the legacy `benchmark` key).

## [site 0.3.8] — 2026-08-14

### Changed
- Header version line relabeled professionally: "UI v0.3.7 · Engine v0.5.7"
  (JSON keys `site`/`algo` unchanged).
- Version policy documented: engine stays 0.5.x, bumped only on real
  autonomy milestones; roadmap (UI v1 = accounts + personalized AI, Engine
  v1 = 100% AI trading with weekly rebalancing) now written in this file.

## [algo 0.5.7] — 2026-08-14

### Changed
- Fragility regime note simplified: "Equities expected to crack." (was the
  longer "Hedges carry expected drag until the equity crack").

## [site 0.3.7] — 2026-08-14

### Added
- Header: GitHub button linking to the project's main page
  (github.com/RubySapior/stock-picker), next to Help.

### Changed
- Help page: fragility description matches the new note wording.

## [algo 0.5.6] — 2026-08-14

### Added
- Complacency reading upgraded to a **2D regime matrix**: equity stretch ×
  top-3 fear average. Distinct states: fragility (ATH + macro stress),
  stress (equity drawdown active), complacency (melt-up), neutral, and
  watchful/moderate middle band. Fixes the old 1D trap where "stress
  regime" described both a realized crash and a fragile divergence.
- **Hedge attribution check**: the sub-line judges only the DOMINANT fear's
  `hedge_ticks` (instruments expected to pay in that scenario) over the
  last 10 sessions — a rates shock (F6) checks SGOV, not ZROZ/TIP which
  are expected to bleed. Hedge tickers are now fetched as part of the
  symbol universe.

### Changed
- `complacency` payload now also carries `divergence` (stretch × fear),
  `fear_avg`, `regime`, and `pay_check`.

## [site 0.3.6] — 2026-08-14

### Changed
- Fear Gauge: complacency line renders the new regime note (e.g. "Fragility
  regime - macro divergence...") and a check line with the dominant fear's
  expected payers as sentiment chips (green = paying, red = bleeding).
- Help page: Complacency section rewritten for the 2D regime matrix and the
  attribution check (Simple + Advanced tabs).

## [site 0.3.5] — 2026-08-14

### Changed
- Help page: Complacency section now explains all four bands, including the
  low-end "Stress regime - hedges should be paying" reading; rebalance
  notes (Simple + Advanced tabs) updated to the v5.5 no-tolerance rule.

## [site 0.3.4] — 2026-08-14

### Changed
- Positions table: the SELL SCHEDULED tag now sits on its own line under the
  ticker and wraps to two lines ("SELL / SCHEDULED") with a slightly smaller
  font — fits within the existing row height (no taller rows).

## [algo 0.5.5] — 2026-08-14

### Changed
- Rebalance audit: tolerance band removed — every sleeve that drifts from its
  target is flagged, no matter how small the gap. `tolerance_pct` config
  deleted; the flag message no longer mentions a tolerance. Still quarterly
  and still recommendation-only (never trades).

## [site 0.3.3] — 2026-08-14

### Changed
- Header sub-line: dropped the old "HyperGrowth Sharpe Barbell v5 -
  Conviction-First" strategy name — the line now shows only the site/algo
  version numbers.

## [site 0.3.2] — 2026-08-14

### Added
- Page renamed to **AI Port-picker** (header title + browser tab).
- Mascot placeholder in the header: dashed 46px slot that auto-loads
  `icon.png` from the project folder when you drop it in (placeholder text
  hides itself; drop `icon.png` next to `index.html`).
- Theories Scorecard on the main page now uses the same flash-card wheel as
  the Theory Archive (drag / scroll / arrow-key browsing, click to flip).
  The plain table is one toggle away ("Table view ⇆" button, choice
  remembered across visits); news links that jump to `#theory-T#` still
  switch to the table automatically.
- Shared `wheel.js` module: the wheel logic now lives in one place, used by
  both the archive page and the main scorecard.

### Changed
- Positions table: positions with a scheduled exit (e.g. TIP) show an amber
  **SELL SCHEDULED** tag next to the ticker, with the exit note on hover.

## [site 0.3.1] — 2026-08-14

### Added
- Version line in the dashboard header (site + algo version, small text).
- Trade Archive page (`trades.html`) — every recorded event in a plain table
  with per-second timestamps, linked from the Trade Events card.
- Help site (`help.html`) — Simple tab (plain-language notes) + Advanced tab
  (the math and details), linked from the header next to the Update button.
- Custom news-feed-style scrollbars (fading blue thumb) on the horizontal
  scroll areas (Positions and Theories tables).

### Changed
- Trade Events card: now shows only the last 7 days (minimum 2 events),
  wider first column so the date no longer wraps, timestamps shown.
- Summary cards cleaned up: Realized P&L, Max Drawdown and Sharpe cards
  removed from the top row; the same figures now live in the Portfolio Value
  History header alongside the chart.
- Theories scorecard: long text (prediction / thesis / evidence) is
  truncated with ellipsis — full text on hover; evidence log capped at the
  2 latest entries with a "+N more" hint; Theory column widened, Prediction
  narrowed.
- Help link moved from the Theories Scorecard header to the top of the page
  next to the Update button.

## [algo 0.5.4] — 2026-08-13

### Added
- Event timestamps: every recorded event (exits, re-entries, cash deploys,
  rebalance flags, scheduled exits) now carries `ts` (HH:MM:SS local) when
  it was recorded.

### Changed
- Rebalance audit is now **quarterly only**: the drift check runs once per
  calendar quarter (first market-open run of Jan/Apr/Jul/Oct), tracked in
  `meta.last_rebalance_quarter`. Daily pp-drift flagging and its dedup state
  (`meta.rebalance_flags`) are removed. Still recommendation-only, never trades.

## [site 0.2.x / algo 0.5.1–0.5.3] — earlier iterations (backfilled)

- Flash-card Theory Archive (wheel navigation, 3D flip, plain-table toggle,
  status/tier filters, free-text search).
- Market Fear Gauge panel (F1–F8), complacency index, review-only hedge
  sizing; moved below the chart/SPY comparison.
- News feed matched to Big Stories height with internal scroll + fading
  scrollbar; sentiment chips (VADER).
- Cards rework: Cash + SGOV rename, cash sub-line restored, Realized P&L /
  Max Drawdown / Sharpe removed from the card row.
- Strategy summary moved out of the header into `meta.strategy` /
  `strategy_log` (one-line summary in header).
- Engine (pre-0.5.4): index-referenced stop-losses for leveraged funds,
  vol-halt re-entry protocol (2-bar reclaim / 60-day abandon), scenario-
  specific hedge theories T17–T21, no-idle-cash SGOV parking, benchmark
  normalization vs SPY.