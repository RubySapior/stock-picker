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

## [Unreleased]

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