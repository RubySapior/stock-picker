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

## [Unreleased]

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