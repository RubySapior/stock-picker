"""
Daily portfolio updater for the HyperGrowth Sharpe Barbell.

What it does:
  1. Loads portfolio.json (source of truth).
  2. Fetches live prices for all OPEN positions from Yahoo Finance.
  3. Checks take-profit and stop-loss levels; closes positions that trigger,
     realizes P&L into cash, and appends an event to the trade log.
  4. Appends (or updates, if same date) a daily value snapshot to history.
  5. Writes dashboard.js consumed by index.html (works via file:// double-click).
  6. Prints a compact summary of the day.

Usage:  python update.py [--ai]
  --ai   force the AI sentiment call even when the market is closed
         (pre-open ritual: refreshes pending market orders with the new
         verdict; orders still only EXECUTE on market-open runs).

Engine v0.6.1.00: the AI reads a prior-verdict + fact-delta prompt and
outputs ONLY changes (omission = agreement). Proposals become HUMAN-
APPROVED market orders in portfolio.json ("orders") - recommend mode
(default, Execute All button writes them) or execute mode (meta.ai.mode,
AI refresh replaces pending orders automatically). Rotations become
paired sell+buy orders. AI fear proposals persist into the editable
fear_scenarios.json table (pending review). Execution is always a
deterministic market-order engine at the live price on market-open runs.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import datetime as _dt

from news import build_news
from fears import build_fears, apply_ai_witnesses, apply_fear_proposals
import ai_sentiment

BASE = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO = os.path.join(BASE, "portfolio.json")
DASHBOARD_JS = os.path.join(BASE, "dashboard.js")

USER_AGENT = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# No idle cash policy: spare cash is parked in ultra-short T-bills.
STB_TICKER = "SGOV"
STB_SLEEVE = "Short-Term Bonds (SGOV)"
CASH_BUFFER = 25.0

# Benchmarks for the "Portfolio vs <index>" comparison (normalized to start_value).
SPY_TICKER = "SPY"
SPY_RANGE = "2y"
BENCH_TICKERS = {
    "SPY": "S&P 500 (SPY)",
    "QQQ": "Nasdaq 100 (QQQ)",
    "TQQQ": "Nasdaq 3x (TQQQ)",
    "MUU": "Micron 2x (MUU)",
}


def fetch_price(ticker):
    """Latest regular-market price for one ticker (float) via Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
    req = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    meta = data["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice") or meta.get("previousClose")
    return price


def fetch_chart_history(symbol, rng=SPY_RANGE, interval="1d"):
    """Daily adjusted-close history: [{'date','px'}, ...] oldest first."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval={interval}"
    req = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    quote = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose", quote["close"])
    out = []
    for i in range(len(ts)):
        if ts[i] is None or adj[i] is None:
            continue
        out.append({"date": time.strftime("%Y-%m-%d", time.gmtime(ts[i])), "px": round(adj[i], 4)})
    return out


# Macro indicators for the AI prompt (Tier A facts). Same Yahoo chart endpoint
# as fetch_price; ^TNX is normalized to percent (Yahoo chart API returns the
# yield x10, e.g. 41.80 = 4.18%).
MACRO_SYMBOLS = ("SPY", "QQQ", "^VIX", "^TNX", "JPY=X", "HYG")


def fetch_macro():
    """Live macro snapshot: {symbol: {px, chg_1d_pct}}. Never raises.

    Failures degrade per-symbol (skipped); a total failure returns {}.
    'chg_1d_pct' is the regular-market 1-day % change (float percent).
    """
    out = {}
    for sym in MACRO_SYMBOLS:
        try:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                   "?range=1d&interval=1d")
            req = urllib.request.Request(url, headers=USER_AGENT)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            meta = data["chart"]["result"][0]["meta"]
            px = meta.get("regularMarketPrice") or meta.get("previousClose")
            prev = meta.get("previousClose") or px
            if px is None:
                continue
            if sym == "^TNX" and abs(px) > 20:
                px = px / 10.0
                prev = (prev / 10.0) if prev else px
            chg = (px / prev - 1) * 100 if prev else 0.0
            out[sym] = {"px": round(px, 4), "chg_1d_pct": round(chg, 2)}
        except Exception as exc:
            print(f"  WARN: macro fetch failed for {sym}: {exc}")
        time.sleep(0.4)
    return out


# Crowding gate for the AI prompt: CNN-style Fear & Greed (0 = extreme fear,
# 100 = extreme greed). Free endpoint, no key. Never allowed to break a run.
FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"


def fetch_fear_greed():
    """Live crowding gauge: {'index': 0-100, 'label': '...'} or None.

    The 'don't buy the top' check: at >=75 additions are crowded and the
    AI must justify them extra; <=25 panic dips become opportunity. Never
    raises - any failure returns None (the prompt just omits the gate).
    """
    try:
        req = urllib.request.Request(FEAR_GREED_URL, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/125.0.0.0 Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.cnn.com/markets/fear-and-greed",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        fg = data["fear_and_greed"]
        idx = int(round(float(fg["score"])))
        return {"index": max(0, min(100, idx)),
                "label": str(fg.get("rating") or "Neutral").title()}
    except Exception as exc:
        print(f"  WARN: fear & greed fetch failed: {exc}")
        return None


def compute_calibration(data, prices, today):
    """Outcome scoring: mark the AI wrong where its conviction sign lost.

    Engine v0.6.1: compares each conviction in the LAST verdict against
    the price move since it was written. |move| < 0.5% counts as noise
    (no call). Wrong = the sign of the move contradicts the conviction
    sign. Accumulates into meta.ai_calibration {ticker: {wrong, total,
    last_wrong}} - fed to the next prompt so confidence on a repeatedly
    wrong ticker starts discounted. Never raises.
    """
    meta = data.setdefault("meta", {})
    last = meta.get("ai_last_output")
    if not isinstance(last, dict):
        return {}
    old_px = last.get("prices") or {}
    rec = meta.setdefault("ai_calibration", {})
    for conv in last.get("convictions") or []:
        tk = conv.get("ticker")
        old = old_px.get(tk)
        new = prices.get(tk)
        if not old or not new:
            continue
        chg = (new / old - 1) * 100
        if abs(chg) < 0.5:
            continue
        r = rec.setdefault(tk, {"wrong": 0, "total": 0, "last_wrong": None})
        r["total"] = r.get("total", 0) + 1
        wrong = (conv["conviction_score"] > 0) != (chg > 0)
        if wrong:
            r["wrong"] = r.get("wrong", 0) + 1
            r["last_wrong"] = today
            print(f"  CALIBRATION: {tk} - AI was WRONG (conv {conv['conviction_score']:+.2f}, "
                  f"moved {chg:+.2f}%) -> {r['wrong']}/{r['total']} wrong")
    return rec


def deploy_cash_to_bonds(data, prices, today):
    """Park idle cash in SGOV so dry powder never sits as cash."""
    cash = data["account"]["cash"]
    if cash <= CASH_BUFFER + 5:
        return
    px = prices.get(STB_TICKER)
    if not px:
        print("  WARN: could not park cash in SGOV (no price)")
        return
    spend = round(cash - CASH_BUFFER, 2)
    shares = round(spend / px, 6)
    deployed = round(shares * px, 2)
    if deployed < 5:
        return
    pos = next((p for p in data["positions"]
                if p["ticker"] == STB_TICKER and p["status"] == "open"), None)
    if pos is None:
        pos = {
            "ticker": STB_TICKER,
            "name": "iShares 0-3 Month Treasury Bond ETF",
            "sleeve": STB_SLEEVE,
            "buy_date": today,
            "buy_price": round(px, 4),
            "shares": 0.0,
            "cost": 0.0,
            "take_profit_pct": None,
            "stop_loss_pct": None,
            "status": "open",
            "thesis": "Dry powder: idle cash parked in ultra-short T-bills (no cash drag).",
        }
        data["positions"].append(pos)
    pos["shares"] = round(pos["shares"] + shares, 6)
    pos["cost"] = round(pos["cost"] + deployed, 2)
    data["account"]["cash"] = round(cash - deployed, 2)
    data["events"].append({
        "date": today,
        "ts": time.strftime("%H:%M:%S"),
        "ticker": STB_TICKER,
        "name": pos["name"],
        "reason": "deploy_cash",
        "price": round(px, 4),
        "buy_price": round(px, 4),
        "shares": round(shares, 4),
        "realized_pnl": 0,
    })
    print(f"  CASH->BONDS: parked ${deployed:,.2f} in {STB_TICKER}")


def _sell_sgov(data, amount, px, today):
    """Redeem SGOV shares to free up `amount` of raw cash (re-entry funding)."""
    pos = next((p for p in data["positions"]
                if p["ticker"] == STB_TICKER and p["status"] == "open"), None)
    if pos is None:
        return 0.0
    need = round(amount - data["account"]["cash"], 2)
    if need <= 0:
        return round(amount, 2)
    px = px or pos["buy_price"]
    shares = round(need / px, 6)
    pos["shares"] = round(pos["shares"] - shares, 6)
    pos["cost"] = round(pos["cost"] - shares * px, 2)
    if pos["shares"] <= 0.01:
        pos["status"] = "closed"
    data["account"]["cash"] = round(data["account"]["cash"] + shares * px, 2)
    return round(amount, 2)


def re_entry_protocol(data, prices, today):
    """Research-integrity protocol (v5.2): a stop is a VOL-HALT, not a death.

    Prevents the silent-SGOV trap from corrupting multi-month theory testing:
      1. When a position exits via index_stop/backstop, its linked theories are
         marked PAUSED (only when no open position still tests that theory).
      2. Daily re-validation: if the 1x underlying (or wrapper, for backstops)
         closes back above the stop level for `confirm_bars` consecutive
         sessions, the theory is RE-AFFIRMED and the position is re-entered
         with the recovered capital.
      3. If no reclaim within `max_pause_days`, the theory is formally marked
         ABANDONED (falsified) and the capital stays reallocated.

    Returns the number of resolutions (re-entries + abandonments) this run.
    """
    cfg = (data["meta"].get("limits") or {}).get("re_entry") or {}
    confirm = int(cfg.get("confirm_bars", 2))
    max_days = int(cfg.get("max_pause_days", 60))
    resolved = 0
    closed_positions = [p for p in data["positions"] if p["status"] == "closed"]

    # 1) Pause linked theories for newly vol-halted positions.
    for pos in closed_positions:
        ex = pos.get("exit") or {}
        if ex.get("state") != "vol_halt":
            continue
        for t in pos.get("theory_ids", []):
            theo = next((x for x in data["theories"] if x["id"] == t), None)
            if not theo or theo.get("status") != "pending":
                continue
            still_tested = any(
                p["status"] == "open" and p is not pos and t in p.get("theory_ids", [])
                for p in data["positions"]
            )
            if still_tested:
                continue
            theo["status"] = "paused"
            theo["paused_date"] = today
            theo["pause_reason"] = ex.get("note")
            theo["paused_ticker"] = pos["ticker"]
            theo["last_updated"] = today
            theo.setdefault("evidence", []).append(
                f"{today}: PAUSED - {pos['ticker']} stopped ({ex.get('note')}). "
                f"Test suspended pending re-validation, not failed."
            )
            print(f"  THEORY {t}: PAUSED (vol-halt on {pos['ticker']})")

    # 2+3) Daily re-validation: reclaim -> re-affirm + re-enter; expiry -> abandon.
    from datetime import date
    for pos in closed_positions:
        ex = pos.get("exit") or {}
        if ex.get("state") != "vol_halt" or ex.get("reentry_resolved"):
            continue
        rt = ex.get("reclaim_ticker")
        level = ex.get("reclaim_level")
        ex_date = ex.get("date")
        try:
            elapsed = (date.fromisoformat(today) - date.fromisoformat(ex_date)).days
        except Exception:
            elapsed = 0

        if elapsed >= max_days:
            for t in pos.get("theory_ids", []):
                theo = next((x for x in data["theories"]
                             if x["id"] == t and x.get("status") == "paused"
                             and x.get("paused_ticker") == pos["ticker"]), None)
                if theo:
                    theo["status"] = "abandoned"
                    theo["last_updated"] = today
                    theo.setdefault("evidence", []).append(
                        f"{today}: ABANDONED - {pos['ticker']} failed to reclaim "
                        f"{rt} >= {level} within {max_days} days of vol-halt. "
                        f"Test resolved (falsified); capital stays reallocated."
                    )
            ex["reentry_resolved"] = True
            print(f"  RE-VALIDATE {pos['ticker']}: no reclaim in {max_days}d -> theory ABANDONED")
            resolved += 1
            continue

        # Reclaim check: trailing consecutive closes >= the stop level.
        hist = fetch_chart_history(rt, rng="1mo") if rt else []
        back = 0
        for h in reversed(hist):
            if h["px"] >= level:
                back += 1
            else:
                break
        if back < confirm:
            continue

        wrapper_px = prices.get(pos["ticker"])
        if not wrapper_px:
            continue
        amt = ex.get("reentry_amount")
        if not amt:
            continue
        if data["account"]["cash"] < amt - 5:
            _sell_sgov(data, amt, prices.get(STB_TICKER), today)
        buys = round(min(amt, data["account"]["cash"]), 2)
        if buys >= 100:
            data["positions"].append({
                "ticker": pos["ticker"],
                "name": pos["name"],
                "sleeve": pos["sleeve"],
                "buy_date": today,
                "buy_price": round(wrapper_px, 4),
                "shares": round(buys / wrapper_px, 6),
                "cost": buys,
                "take_profit_pct": pos.get("take_profit_pct"),
                "stop_loss_pct": pos.get("stop_loss_pct"),
                "underlying": pos.get("underlying"),
                "underlying_stop_pct": pos.get("underlying_stop_pct"),
                "underlying_buy_price": round(prices.get(pos.get("underlying")) or 0, 4)
                                         or pos.get("underlying_buy_price"),
                "theory_ids": pos.get("theory_ids", []),
                "status": "open",
                "thesis": f"{pos.get('thesis', '')} [RE-ENTRY on {today}: theory re-affirmed after {rt} reclaimed {level}]",
                "entry_note": "Vol-halt re-entry: index reclaim confirmed the test continues.",
            })
            data["account"]["cash"] = round(data["account"]["cash"] - buys, 2)
            data["events"].append({
                "date": today,
                "ts": time.strftime("%H:%M:%S"),
                "ticker": pos["ticker"],
                "name": pos["name"],
                "reason": "re_entry",
                "note": f"re-affirmed ({rt} reclaimed {level}, {back} close(s))",
                "price": round(wrapper_px, 4),
                "buy_price": round(wrapper_px, 4),
                "shares": round(buys / wrapper_px, 4),
                "realized_pnl": 0,
            })
        for t in pos.get("theory_ids", []):
            theo = next((x for x in data["theories"]
                         if x["id"] == t and x.get("status") == "paused"
                         and x.get("paused_ticker") == pos["ticker"]), None)
            if theo:
                theo["status"] = "pending"
                theo["last_updated"] = today
                theo.setdefault("evidence", []).append(
                    f"{today}: RE-AFFIRMED - {pos['ticker']} reclaimed {rt} >= {level} "
                    f"for {back} session(s); position re-entered, test continues."
                )
        ex["reentry_resolved"] = True
        print(f"  RE-ENTRY {pos['ticker']}: {rt} reclaimed {level} -> re-entered @ {wrapper_px}")
        resolved += 1
    return resolved


def rebalance_audit(data, today):
    """Quarterly exposure audit -> `rebalance_recommended` flags.

    Runs ONCE per calendar quarter (first market-open run of Jan/Apr/Jul/Oct)
    instead of every EOD: no daily pp-drift flagging. On the quarterly check it
    compares each sleeve's EFFECTIVE exposure (market value x leverage, as a %
    of invested value) against the sector LIMITS in
    meta.limits.rebalance.limits, flagging ANY drift from limit - there is
    no tolerance band, every mismatch is flagged no matter how small.

    Exempt sectors (meta.limits.rebalance.exempt_sectors, e.g. Short-Term
    Bonds/SGOV): no cap - dry powder may grow without limit so there is
    always liquidity when an opportunity appears. Exempt sectors are never
    flagged.

    Passive by design - it never trades, it only asks the conviction layer to
    review a risk-budget mismatch. No hidden reallocation, no attribution
    pollution.
    """
    limits = data["meta"].get("limits") or {}
    cfg = limits.get("rebalance") or {}
    targets = cfg.get("limits") or cfg.get("targets") or {}
    exempt = set(cfg.get("exempt_sectors") or [])
    if not targets:
        return []
    year, month, _ = today.split("-")
    quarter = f"{year}Q{(int(month) - 1) // 3 + 1}"
    if data["meta"].get("last_rebalance_quarter") == quarter:
        return []
    data["meta"]["last_rebalance_quarter"] = quarter
    prices = data["account"]["history"][-1].get("prices") or {}
    pex = limits.get("position_exposure", {})
    mv_tot, eff_tot = {}, {}
    for pos in data["positions"]:
        if pos["status"] != "open":
            continue
        px = prices.get(pos["ticker"]) or pos.get("buy_price")
        mv = px * pos["shares"]
        sec = pex.get(pos["ticker"], {}).get("sector", "Other")
        lev = pex.get(pos["ticker"], {}).get("leverage", 1.0)
        mv_tot[sec] = mv_tot.get(sec, 0.0) + mv
        eff_tot[sec] = eff_tot.get(sec, 0.0) + mv * lev
    tot_inv = sum(mv_tot.values()) or 1.0

    flags = []
    for sec, target in targets.items():
        if sec in exempt:
            continue
        actual = eff_tot.get(sec, 0.0) / tot_inv * 100.0
        msg = (f"{sec} effective exposure {actual:.1f}% vs {target:.1f}% limit "
               f"(off by {actual - target:+.1f}pp). "
               f"Quarterly review - manual rebalance or conviction decision required.")
        data["events"].append({
            "date": today,
            "ts": time.strftime("%H:%M:%S"),
            "ticker": sec,
            "name": "Rebalance flag",
            "reason": "rebalance_recommended",
            "note": msg,
            "state": None,
            "price": None,
            "buy_price": None,
            "shares": None,
            "realized_pnl": 0,
        })
        flags.append({
            "type": "rebalance_recommended",
            "sleeve": sec,
            "target_exposure": round(target / 100.0, 3),
            "actual_exposure": round(actual / 100.0, 3),
            "message": msg,
        })
        print(f"  FLAG {sec}: {actual:.1f}% vs {target:.1f}% limit (off by {actual - target:+.1f}pp)")
    return flags


def build_benchmark(data, hist, label):
    """Normalize a benchmark series to start_value, align to portfolio dates, compute metrics."""
    if not hist:
        return None
    start = data["meta"]["start_value"]
    start_date = data["meta"]["start_date"]
    base_px = None
    for h in hist:
        if h["date"] >= start_date:
            base_px = h["px"]
            break
    if base_px is None:
        base_px = hist[-1]["px"]
    norm = [{"date": h["date"], "value": round(start * h["px"] / base_px, 2)}
            for h in hist if h["date"] >= start_date]
    by_date = {h["date"]: h["value"] for h in norm}
    dates = sorted(by_date)

    aligned = []
    for hd in [h["date"] for h in data["account"]["history"]]:
        last = None
        for d in dates:
            if d <= hd:
                last = by_date[d]
            else:
                break
        if last is not None:
            aligned.append({"date": hd, "value": last})

    vals = [{"total_value": by_date[d]} for d in dates]
    return {
        "label": label,
        "start_value": start,
        "history": norm,
        "aligned": aligned,
        "summary": {
            "total_return_pct": round((by_date[dates[-1]] / start - 1) * 100, 2),
            "max_drawdown_pct": compute_drawdown(vals),
            "sharpe_annualized": compute_sharpe(vals),
        },
    }


def fetch_prices(tickers):
    """Fetch {ticker: price} for many tickers; failures become None (logged)."""
    prices = {}
    for t in tickers:
        try:
            prices[t] = fetch_price(t)
        except Exception as exc:
            print(f"  WARN: could not fetch {t}: {exc}")
            prices[t] = None
        time.sleep(0.4)
    return prices


def check_exits(pos, px, today, under_prices=None):
    """Returns (event_or_None).

    Stop discipline (v5.1, index-referenced):
    - Leveraged funds (3x/2x) are stopped against the 1x UNDERLYING index
      (e.g. TQQQ -> QQQ), so a violent leveraged day or daily-decay drift
      cannot whipsaw the hard stop. The stop fires on a genuine correction
      in the actual market exposure.
    - The wrapper-level stop_loss_pct is kept only as a WIDE backstop for
      gap-through / stale-index protection.
    Take-profit stays on the wrapper.
    """
    under_prices = under_prices or {}
    if pos.get("take_profit_pct"):
        tp = pos["buy_price"] * (1 + pos["take_profit_pct"])
        if px is not None and px >= tp:
            return {"date": today, "price": round(px, 2), "reason": "take_profit",
                    "note": "take_profit",
                    "realized_pnl": round((px - pos["buy_price"]) * pos["shares"], 2)}

    underlying = pos.get("underlying")
    if underlying:
        u_px = under_prices.get(underlying)
        u_entry = pos.get("underlying_buy_price")
        u_pct = pos.get("underlying_stop_pct")
        if u_px is not None and u_entry and u_pct and u_px <= u_entry * (1 + u_pct):
            return {"date": today, "price": round(px, 2), "reason": "stop_loss",
                    "note": f"index_stop ({underlying} {round((u_px / u_entry - 1) * 100, 2)}%)",
                    "state": "vol_halt",
                    "reclaim_ticker": underlying,
                    "reclaim_level": round(u_entry * (1 + u_pct), 4),
                    "reentry_amount": round(px * pos["shares"], 2),
                    "realized_pnl": round((px - pos["buy_price"]) * pos["shares"], 2)}

    if pos.get("stop_loss_pct"):
        sl = pos["buy_price"] * (1 + pos["stop_loss_pct"])
        if px is not None and px <= sl:
            return {"date": today, "price": round(px, 2), "reason": "stop_loss",
                    "note": "backstop",
                    "state": "vol_halt",
                    "reclaim_ticker": pos["ticker"],
                    "reclaim_level": round(sl, 4),
                    "reentry_amount": round(px * pos["shares"], 2),
                    "realized_pnl": round((px - pos["buy_price"]) * pos["shares"], 2)}
    return None


def compute_drawdown(history):
    """Max drawdown % from a list of {total_value} snapshots (negative or 0)."""
    peak = 0.0
    mdd = 0.0
    for h in history:
        v = h["total_value"]
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, (v - peak) / peak)
    return round(mdd * 100, 2)


def compute_sharpe(history):
    """Annualized Sharpe from daily {total_value} snapshots; None if too few days."""
    vals = [h["total_value"] for h in history]
    if len(vals) < 3:
        return None
    rets = [(vals[i] / vals[i - 1]) - 1 for i in range(1, len(vals))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = var ** 0.5
    if std == 0:
        return None
    return round((mean / std) * (252 ** 0.5), 2)


def compute_cagr(total, start, start_date):
    """Annualized return % since start_date; None when elapsed time is ~0."""
    from datetime import date
    try:
        days = (date.today() - date.fromisoformat(start_date)).days
    except Exception:
        days = 0
    if days <= 0 or start <= 0 or total <= 0:
        return None
    years = days / 365.25
    return round(((total / start) ** (1 / years) - 1) * 100, 2)


def _nth_sunday(year, month, nth):
    """Date of the nth Sunday of a month (US DST helper)."""
    d = _dt.date(year, month, 1)
    first_sun = d + _dt.timedelta(days=(6 - d.weekday()) % 7)
    return first_sun + _dt.timedelta(days=7 * (nth - 1))


def market_state(now_utc=None):
    """'open' | 'preopen' | 'closed' — NYSE session logic, DST handled manually.

    - open:    Mon-Fri 09:30-16:00 ET
    - preopen: Mon-Fri 09:00-09:30 ET (the 30-min window before the bell)
    - closed:  everything else (nights, pre-9am, post-4pm, weekends)
    """
    now_utc = now_utc or _dt.datetime.utcnow()
    year = now_utc.year
    dst_start = _dt.datetime.combine(_nth_sunday(year, 3, 2), _dt.time(7, 0))    # 2am EST -> 07:00 UTC
    dst_end = _dt.datetime.combine(_nth_sunday(year, 11, 1), _dt.time(6, 0))     # 2am EDT -> 06:00 UTC
    et_offset = -4 if dst_start <= now_utc < dst_end else -5
    et = now_utc + _dt.timedelta(hours=et_offset)
    if et.weekday() >= 5:
        return "closed"
    hm = et.hour * 60 + et.minute
    if 9 * 60 + 30 <= hm <= 16 * 60:
        return "open"
    if 9 * 60 <= hm < 9 * 60 + 30:
        return "preopen"
    return "closed"


def market_is_open(now_utc=None):
    """NYSE session open? Mon-Fri 09:30-16:00 ET, DST handled manually.

    Used so overnight/pre-market runs do NOT start a fresh history day with a
    zero day-change; the last completed trading day keeps showing until the
    next open.
    """
    return market_state(now_utc) == "open"


def execute_scheduled_exits(data, prices, today):
    """Execute deliberate rebalances tagged `scheduled_exit` on positions.

    Used for manual strategy changes (e.g. issue #7: JEPQ removal). A position
    carrying `scheduled_exit` is sold at the live price on the FIRST market-open
    run after the tag was added - never on a stale closed-market quote - then
    removed from the book (proceeds realize into cash, and the no-idle-cash
    policy parks them in SGOV). The tag is deleted on execution.
    """
    if not market_is_open():
        return
    for pos in list(data["positions"]):
        plan = pos.get("scheduled_exit")
        if not plan or pos["status"] != "open":
            continue
        px = prices.get(pos["ticker"])
        if px is None:
            print(f"  WARN: scheduled exit {pos['ticker']} - no price, deferring")
            continue
        realized = round((px - pos["buy_price"]) * pos["shares"], 2)
        proceeds = round(px * pos["shares"], 2)
        data["account"]["cash"] = round(data["account"]["cash"] + proceeds, 2)
        data["account"]["realized_pnl"] = round(data["account"]["realized_pnl"] + realized, 2)
        data["events"].append({
            "date": today,
            "ts": time.strftime("%H:%M:%S"),
            "ticker": pos["ticker"],
            "name": pos["name"],
            "reason": plan.get("reason", "rebalance"),
            "note": plan.get("note"),
            "state": None,
            "price": round(px, 2),
            "buy_price": pos["buy_price"],
            "shares": pos["shares"],
            "realized_pnl": realized,
        })
        # Prune the sector config if this was the last position in its sector
        # (e.g. 'Premium Financing' after JEPQ leaves the book).
        limits = data["meta"].setdefault("limits", {})
        pex = limits.setdefault("position_exposure", {})
        sector = (pex.get(pos["ticker"]) or {}).get("sector")
        pex.pop(pos["ticker"], None)
        if sector:
            still_held = any(
                p["status"] == "open" and p is not pos
                and (pex.get(p["ticker"]) or {}).get("sector") == sector
                for p in data["positions"]
            )
            if not still_held:
                limits["sector_limits"] = [
                    s for s in limits.get("sector_limits", [])
                    if s["sector"] != sector
                ]
                (limits.setdefault("rebalance", {})
                     .setdefault("limits", {}).pop(sector, None))
                (limits.setdefault("rebalance", {})
                     .get("targets", {}) or {}).pop(sector, None)
                print(f"  SECTOR CLEANUP: removed empty sector '{sector}' from limits")
        pos.pop("scheduled_exit", None)
        data["positions"].remove(pos)
        print(f"  SCHEDULED EXIT {pos['ticker']}: sold @ {px:.2f} (pnl {realized:+,.2f})")


def refresh_orders_from_ai(data, verdict, today):
    """Replace PENDING market orders with the latest AI verdict's proposals.

    Engine v0.6.1: mode-aware. meta.ai.mode:
      - "execute"   -> the AI refresh replaces pending orders with the
                       verdict's proposals + rotations (auto mode).
      - "recommend" -> DEFAULT. Pending orders stay untouched; the
                       verdict's proposals are recommendations only and
                       become orders via the dashboard's Execute All
                       button (POST /execute_all), i.e. human approval.
    Each proposal is sized at meta.ai.order_size USD (direction only; the
    engine sizes, the human approved the sizing). Rotation pairs become
    TWO orders (sell leg + buy leg) at the same size. Executed orders
    stay as history; only pending ones are replaced.
    """
    cfg = (data.get("meta") or {}).get("ai") or {}
    if not cfg.get("orders_refresh"):
        return
    mode = str(cfg.get("mode") or "recommend")
    if mode != "execute":
        print("  ORDERS: recommend mode - AI proposals are recommendations; "
              "use Execute All to turn them into pending orders")
        return
    size = float(cfg.get("order_size", 2500))
    proposals = ai_sentiment.bullish_layer(verdict, data)
    rotations = ai_sentiment.rotation_layer(verdict, data)
    keep = [o for o in data.setdefault("orders", [])
            if o.get("status") != "pending"]
    created = []
    for p in proposals:
        action = "buy" if p["conviction_score"] > 0 else "sell"
        created.append({
            "ticker": p["ticker"],
            "action": action,
            "amount": round(size, 2),
            "status": "pending",
            "source": f"ai_{today}",
            "created": today,
            "note": (p.get("rationale") or "")[:160],
        })
    for r in rotations:
        created.append({
            "ticker": r["sell"], "action": "sell", "amount": round(size, 2),
            "status": "pending", "source": f"ai_{today}", "created": today,
            "note": f"rotation {r['sell']}->{r['buy']}: {(r.get('rationale') or '')[:120]}",
        })
        created.append({
            "ticker": r["buy"], "action": "buy", "amount": round(size, 2),
            "status": "pending", "source": f"ai_{today}", "created": today,
            "note": f"rotation {r['sell']}->{r['buy']}: {(r.get('rationale') or '')[:120]}",
        })
    data["orders"] = keep + created
    if created:
        print(f"  ORDERS REFRESHED from AI verdict (execute mode): "
              f"{len(created)} market orders ({size:,.0f} each) - "
              f"pending replaced, {len(keep)} executed kept")


def execute_pending_orders(data, prices, today):
    """Execute pending market orders at the LIVE price (market-open only).

    - buy: funded by redeeming SGOV (no idle cash policy); shares are
      added to the open position at the live price.
    - sell: sells amount worth of shares at the live price; proceeds go
      to cash, then the no-idle-cash policy parks them in SGOV. If the
      order sells the whole position, it closes like a TP/SL exit.
    Orders without a price, without an open position, or beyond SGOV
    availability stay pending (deferred, never dropped).
    """
    if not market_is_open():
        return
    orders = data.setdefault("orders", [])
    for order in list(orders):
        if order.get("status") != "pending":
            continue
        tk = order.get("ticker")
        action = order.get("action")
        amount = float(order.get("amount", 0))
        px = prices.get(tk)
        if not px:
            print(f"  WARN: order {tk} {action} - no live price, deferred")
            continue
        pos = next((p for p in data["positions"]
                    if p["ticker"] == tk and p["status"] == "open"), None)
        if action == "buy":
            if not pos:
                print(f"  WARN: order BUY {tk} - no open position to add to, deferred")
                continue
            sgov = next((p for p in data["positions"]
                         if p["ticker"] == STB_TICKER and p["status"] == "open"), None)
            sgov_px = prices.get(STB_TICKER)
            if not sgov or not sgov_px or sgov["shares"] * sgov_px < amount - 1:
                print(f"  WARN: order BUY {tk} - insufficient SGOV dry powder, deferred")
                continue
            sgov_shares = round(amount / sgov_px, 6)
            sgov["shares"] = round(sgov["shares"] - sgov_shares, 6)
            sgov["cost"] = round(sgov["cost"] - amount, 2)
            buy_shares = round(amount / px, 6)
            pos["shares"] = round(pos["shares"] + buy_shares, 6)
            pos["cost"] = round(pos["cost"] + amount, 2)
            order.update({
                "status": "executed", "exec_date": today,
                "exec_price": round(px, 4),
                "shares": round(buy_shares, 4),
                "realized_pnl": 0.0,
            })
            data["events"].append({
                "date": today,
                "ts": time.strftime("%H:%M:%S"),
                "ticker": tk,
                "name": pos["name"],
                "reason": "market_order",
                "note": f"BUY {amount:,.0f} ({order.get('source')})",
                "state": None,
                "price": round(px, 4),
                "buy_price": round(px, 4),
                "shares": round(buy_shares, 4),
                "realized_pnl": 0,
            })
            print(f"  ORDER BUY {tk}: {amount:,.0f} @ {px:.2f} "
                  f"(from SGOV {sgov_shares:,.2f} shares)")
        elif action == "sell":
            if not pos:
                print(f"  WARN: order SELL {tk} - no open position, deferred")
                continue
            sell_shares = min(pos["shares"], round(amount / px, 6))
            if sell_shares <= 0:
                continue
            proceeds = round(sell_shares * px, 2)
            realized = round((px - pos["buy_price"]) * sell_shares, 2)
            pos["shares"] = round(pos["shares"] - sell_shares, 6)
            pos["cost"] = round(pos["cost"] - round(sell_shares * pos["buy_price"], 2), 2)
            data["account"]["cash"] = round(data["account"]["cash"] + proceeds, 2)
            data["account"]["realized_pnl"] = round(
                data["account"]["realized_pnl"] + realized, 2)
            order.update({
                "status": "executed", "exec_date": today,
                "exec_price": round(px, 4),
                "shares": round(sell_shares, 4),
                "realized_pnl": realized,
            })
            data["events"].append({
                "date": today,
                "ts": time.strftime("%H:%M:%S"),
                "ticker": tk,
                "name": pos["name"],
                "reason": "market_order",
                "note": f"SELL {amount:,.0f} ({order.get('source')})",
                "state": None,
                "price": round(px, 4),
                "buy_price": pos["buy_price"],
                "shares": round(sell_shares, 4),
                "realized_pnl": realized,
            })
            print(f"  ORDER SELL {tk}: {amount:,.0f} @ {px:.2f} "
                  f"(pnl {realized:+,.2f})")
            if pos["shares"] <= 1e-6:
                pos["status"] = "closed"
                pos["exit"] = {
                    "reason": "market_order",
                    "price": round(px, 4),
                    "state": None,
                    "note": f"Market order sold full position ({order.get('source')})",
                    "realized_pnl": realized,
                }
        # keep only the last 15 executed orders
        executed = [o for o in data["orders"] if o.get("status") == "executed"]
        if len(executed) > 15:
            data["orders"] = ([o for o in data["orders"] if o.get("status") != "executed"]
                              + executed[-15:])


def run_ai_layer(data, prices, fear_data, today, macro=None, force=False,
                 sentiment=None, calibration=None):
    """Wire the AI Sentiment Decision Layer (ai_sentiment.py) into the run.

    Invariants (see CHANGELOG 'AI Sentiment Decision Layer'):
      - AI is read-only: it appends theory EVIDENCE, one audit event, and
        blends the DISPLAYED fear scores - it never touches positions,
        theory statuses, or account state. Fear proposals persist to the
        EDITABLE fear_scenarios.json table staged pending_review.
      - Degraded mode: any failure leaves the book exactly as before.
      - Cadence: one call per market-open day (meta.ai_state.last_call_date),
        capped at meta.ai.max_daily_calls. Circuit-event re-runs (|dQQQ|>2.5%,
        VIX +15%) are a later milestone.
      - Engine v0.6.1: in execute mode a successful verdict refreshes
        PENDING market orders (meta.ai.orders_refresh) - execution still
        only happens on market-open runs. Recommend mode (default) leaves
        orders alone; Execute All writes them.

    Returns (ai_verdict, fear_data) - fear_data may carry AI-blended scores.
    macro: optional live {symbol: {px, chg_1d_pct}} from fetch_macro().
    sentiment: optional {index, label} crowding gauge (fetch_fear_greed()).
    calibration: optional {ticker: {wrong, total}} outcome track record.
    force: skip the market-is-open gate (pre-open ritual, python update.py --ai).
    """
    cfg = (data.get("meta") or {}).get("ai") or {}
    if not cfg.get("enabled"):
        return None, fear_data
    try:
        state = data.setdefault("meta", {}).setdefault("ai_state", {})
        if not force and not market_is_open():
            return None, fear_data
        max_calls = int(cfg.get("max_daily_calls", 3))
        if state.get("last_call_date") != today:
            state["calls_today"] = 0
        if state.get("calls_today", 0) >= max_calls:
            return None, fear_data

        verdict = ai_sentiment.run(data, prices, fear_data, macro,
                                   sentiment=sentiment,
                                   calibration=calibration)
        if not verdict:
            return None, fear_data

        state["last_call_date"] = today
        state["calls_today"] = state.get("calls_today", 0) + 1
        state["last_call_ts"] = time.strftime("%H:%M:%S")
        data["meta"]["ai_last_output"] = verdict

        ledger = data["meta"].setdefault("ai_ledger", [])
        ledger.append({
            "date": today,
            "ts": state["last_call_ts"],
            "macro_stance": verdict["macro_stance"],
            "theories": len(verdict["theories"]),
            "convictions": len(verdict["convictions"]),
            "prompt_hash": verdict.get("prompt_hash"),
            "summary": verdict["summary"][:200],
        })
        ledger[:] = ledger[-28:]

        for t in verdict["theories"]:
            theo = next((x for x in data["theories"] if x["id"] == t["id"]), None)
            if theo:
                theo["last_updated"] = today
                theo.setdefault("evidence", []).append(
                    f"{today}: AI verdict {t['verdict'].upper()} (conf {t['confidence']}) "
                    f"- {t['evidence']}"
                )

        ai_scores = ai_sentiment.fears_layer(verdict)
        if ai_scores and fear_data:
            apply_ai_witnesses(fear_data.get("fears") or [], ai_scores)
            fear_data["news_layer"] = True

        pending_fears = apply_fear_proposals(verdict, today)
        if pending_fears:
            data["meta"]["ai_fear_proposals"] = pending_fears

        refresh_orders_from_ai(data, verdict, today)

        data["events"].append({
            "date": today,
            "ts": state["last_call_ts"],
            "ticker": "AI",
            "name": "AI Sentiment",
            "reason": "ai_sentiment",
            "note": (f"{verdict['macro_stance']} - {len(verdict['theories'])} theories, "
                     f"{len(verdict['convictions'])} convictions - {verdict['summary'][:120]}"),
            "state": None,
            "price": None,
            "buy_price": None,
            "shares": None,
            "realized_pnl": 0,
        })
        print(f"  AI SENTIMENT: {verdict['macro_stance']} (call #{state['calls_today']} today)")
        return verdict, fear_data
    except Exception as exc:
        print(f"  WARN: ai_sentiment layer failed (degraded): {exc}")
        return None, fear_data


def main():
    """Fetch prices -> check exits -> deploy cash -> snapshot -> write dashboard.js."""
    parser = argparse.ArgumentParser(description="Stock Picker daily updater")
    parser.add_argument("--ai", action="store_true",
                        help="force the AI sentiment call even when the market is closed")
    parser.add_argument("--preopen", action="store_true",
                        help="GitHub Actions 6-min schedule: skip unless market open or within "
                             "the 30-min pre-open window; forces the AI refresh pre-open so "
                             "Monday's orders are refreshed before the bell")
    args = parser.parse_args()
    if args.preopen and market_state() == "closed":
        print("Outside update window (market closed, not pre-open) - skipping.")
        return
    with open(PORTFOLIO, encoding="utf-8") as f:
        data = json.load(f)

    today = time.strftime("%Y-%m-%d")
    open_positions = [p for p in data["positions"] if p["status"] == "open"]
    tickers = [p["ticker"] for p in open_positions]
    if STB_TICKER not in tickers:
        tickers.append(STB_TICKER)
    # Index-referenced stops: also fetch the 1x underlying of leveraged funds.
    for p in open_positions:
        un = p.get("underlying")
        if un and un not in tickers:
            tickers.append(un)
    # Re-entry protocol: fetch tickers/reclaim indexes of unresolved vol-halts.
    for p in data["positions"]:
        if p.get("status") != "closed":
            continue
        ex = p.get("exit") or {}
        if ex.get("state") == "vol_halt" and not ex.get("reentry_resolved"):
            for tk in (ex.get("reclaim_ticker"), p["ticker"]):
                if tk and tk not in tickers:
                    tickers.append(tk)
    prices = fetch_prices(tickers) if tickers else {}

    # Live macro indicators for the AI layer (SPY/QQQ/VIX/10Y/USDJPY/HYG).
    # Never allowed to break the update - failure degrades to no macro block.
    macro = {}
    try:
        macro = fetch_macro()
        if macro:
            print("  MACRO: " + " | ".join(
                f"{k} {v['px']} ({v['chg_1d_pct']:+.2f}%)" for k, v in macro.items()))
    except Exception as exc:
        print(f"  WARN: macro fetch failed: {exc}")

    # Market Fear Gauge: score F1-F8, persist state, build recommendations.
    # Never allowed to break the update - gauge failure degrades to no section.
    fear_data = None
    try:
        fear_data = build_fears(data)
    except Exception as exc:
        print(f"  WARN: fear gauge failed: {exc}")

    # Crowding gate for the AI layer (CNN-style Fear & Greed). Never breaks
    # the update - failure degrades to no gauge (the prompt omits the gate).
    gauge = None
    try:
        gauge = fetch_fear_greed()
        if gauge:
            print(f"  SENTIMENT GAUGE: {gauge['label']} ({gauge['index']}/100)")
    except Exception as exc:
        print(f"  WARN: fear & greed fetch failed: {exc}")

    # Outcome calibration: mark the AI wrong where its last convictions
    # moved against it. Fed to this run's prompt; persisted to meta.
    try:
        calibration = compute_calibration(data, prices, today)
    except Exception as exc:
        print(f"  WARN: calibration failed: {exc}")
        calibration = {}

    # AI Sentiment Decision Layer (disabled unless meta.ai.enabled). Reads the
    # book + market-only fears, returns a verdict; blends fears, appends theory
    # evidence + one audit event. Degrades silently - never breaks the run.
    # --ai forces the call pre-open (refreshes pending orders); execution of
    # orders is still gated by market_is_open(). --preopen forces the refresh
    # ONLY in the 30-min pre-open window (not during market hours, so the
    # daily AI cadence is untouched mid-session).
    force_ai = args.ai or (args.preopen and market_state() == "preopen")
    ai_verdict, fear_data = run_ai_layer(data, prices, fear_data, today, macro,
                                         force=force_ai, sentiment=gauge,
                                         calibration=calibration)
    # Market-closed / cadence-cap runs produce no live verdict, but the last
    # persisted one (meta.ai_last_output) is still real data - show it.
    if not ai_verdict:
        ai_verdict = (data.get("meta") or {}).get("ai_last_output")

    # Deliberate rebalances (e.g. issue #7 JEPQ removal): sell at the first
    # market-open price, then let the no-idle-cash policy park proceeds in SGOV.
    execute_scheduled_exits(data, prices, today)

    # Engine v0.6.0: execute human-approved market orders at the live price
    # (market-open only). Buys redeem SGOV; sells realize into cash.
    execute_pending_orders(data, prices, today)
    open_positions = [p for p in data["positions"] if p["status"] == "open"]

    # --- stop loss / take profit engine ---
    for pos in list(open_positions):
        px = prices.get(pos["ticker"])
        if px is None:
            continue
        event = check_exits(pos, px, today, prices)
        if event:
            pos["status"] = "closed"
            pos["exit"] = event
            cash_in = pos["shares"] * event["price"]
            data["account"]["cash"] = round(data["account"]["cash"] + cash_in, 2)
            data["account"]["realized_pnl"] = round(data["account"]["realized_pnl"] + event["realized_pnl"], 2)
            data["events"].append({
                "date": today,
                "ts": time.strftime("%H:%M:%S"),
                "ticker": pos["ticker"],
                "name": pos["name"],
                "reason": event["reason"],
                "note": event.get("note"),
                "state": event.get("state"),
                "price": event["price"],
                "buy_price": pos["buy_price"],
                "shares": pos["shares"],
                "realized_pnl": event["realized_pnl"],
            })
            print(f"  EXIT {pos['ticker']}: {event['reason']} @ {event['price']} [{event.get('note')}] (pnl {event['realized_pnl']:+,.2f})")

    # Research-integrity protocol: pause / re-affirm / abandon linked theories.
    re_entry_protocol(data, prices, today)

    # No-idle-cash policy: park any free cash in SGOV.
    deploy_cash_to_bonds(data, prices, today)

    # --- build today's snapshot ---
    invested = 0.0
    pos_snapshot = {}
    for pos in data["positions"]:
        if pos["status"] == "open":
            px = prices.get(pos["ticker"]) or pos["buy_price"]
            mv = px * pos["shares"]
            invested += mv
            pos_snapshot[pos["ticker"]] = round(px, 4)
    cash = data["account"]["cash"]
    total = cash + invested

    # True day change anchors to the last snapshot from a PRIOR day (previous
    # close), not history[-1]: auto-updates every few minutes replace today's
    # own snapshot, so comparing to history[-1] would shrink day_change to
    # "change since last update" instead of the real session-to-date move.
    prev = data["meta"]["start_value"]
    for h in reversed(data["account"]["history"]):
        if h["date"] < today:
            prev = h["total_value"]
            break
    day_change = round(total - prev, 2)

    snapshot = {
        "date": today,
        "total_value": round(total, 2),
        "cash": round(cash, 2),
        "invested_value": round(invested, 2),
        "day_change": day_change,
        "prices": pos_snapshot,
    }

    history = data["account"]["history"]
    if history and history[-1]["date"] == today:
        history[-1] = snapshot
    elif market_is_open():
        history.append(snapshot)
    else:
        # Market closed on a fresh calendar day: don't start a zero-change day.
        # Keep the last completed trading day's snapshot so its day-change stays
        # visible until the next market open.
        print("  Market closed — keeping the last trading day's snapshot (day change stays until next open).")

    # Passive exposure audit -> rebalance_recommended flags (never trades).
    rebalance = rebalance_audit(data, today)

    with open(PORTFOLIO, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    benchmark = None
    benchmarks = {}
    try:
        for tk, label in BENCH_TICKERS.items():
            bm = build_benchmark(data, fetch_chart_history(tk), label)
            if bm:
                benchmarks[tk] = bm
        benchmark = benchmarks.get("SPY")
        if not benchmark and benchmarks:
            benchmark = next(iter(benchmarks.values()))
    except Exception as exc:
        print(f"  WARN: benchmark fetch failed: {exc}")

    write_dashboard(data, benchmark, rebalance, fear_data, benchmarks,
                    ai_verdict, gauge=gauge)
    print_summary(data, today, benchmark)


def build_ai_payload(verdict, data, gauge=None):
    """Serialize the AI verdict for the dashboard (null when offline/disabled)."""
    if not verdict:
        return None
    meta = data.get("meta") or {}
    calib = meta.get("ai_calibration") or {}
    return {
        "asof": verdict["date"],
        "macro_stance": verdict["macro_stance"],
        "sector_bias": verdict["sector_bias"],
        "theories": verdict["theories"],
        "fears": verdict["fears"],
        "convictions": verdict["convictions"],
        "rotations": verdict.get("rotations") or [],
        "fear_proposals": (meta.get("ai_fear_proposals") or [])[:5],
        "proposals": ai_sentiment.bullish_layer(verdict, data),
        "summary": verdict["summary"],
        "ledger": (meta.get("ai_ledger") or [])[-14:],
        "state": meta.get("ai_state") or {},
        "mode": str((meta.get("ai") or {}).get("mode") or "recommend"),
        "gauge": gauge,
        "calibration": {k: v for k, v in calib.items()
                        if v.get("wrong", 0) > 0},
        "enabled": bool((meta.get("ai") or {}).get("enabled")),
    }


def write_dashboard(data, benchmark=None, rebalance=None, fear_data=None,
                    benchmarks=None, ai_verdict=None, gauge=None):
    """Serialize the full dashboard payload to dashboard.js (window.DASH).

    This is the ONLY writer of dashboard.js. The payload shape is the
    "window.DASH data contract" documented in AGENTS.md and app.js.
    """
    start = data["meta"]["start_value"]
    history = data["account"]["history"]
    cash = data["account"]["cash"]
    total = history[-1]["total_value"]
    day_change = history[-1]["day_change"]

    limits = data["meta"].get("limits", {})
    pex = limits.get("position_exposure", {})
    sec_tot = {}

    positions = []
    sleeve_totals = {}
    for pos in data["positions"]:
        if pos["status"] == "open":
            current = history[-1].get("prices", {}).get(pos["ticker"]) or pos["buy_price"]
            value = round(current * pos["shares"], 2)
            pnl_pct = round((current / pos["buy_price"] - 1) * 100, 2)
            exit_info = None
        else:
            current = pos.get("exit", {}).get("price")
            value = round(current * pos["shares"], 2) if current else 0.0
            pnl_pct = round((current / pos["buy_price"] - 1) * 100, 2) if current else None
            exit_info = pos.get("exit")
        sleeve_totals[pos["sleeve"]] = sleeve_totals.get(pos["sleeve"], 0.0) + value

        info = pex.get(pos["ticker"], {"sector": "Other", "leverage": 1.0})
        sec = info.get("sector", "Other")
        lev = info.get("leverage", 1.0)
        if pos["status"] == "open":
            mv, eff = sec_tot.get(sec, (0.0, 0.0))
            sec_tot[sec] = (mv + value, eff + value * lev)

        positions.append({
            "ticker": pos["ticker"],
            "name": pos["name"],
            "sleeve": pos["sleeve"],
            "buy_date": pos["buy_date"],
            "buy_price": pos["buy_price"],
            "shares": pos["shares"],
            "cost": pos["cost"],
            "current_price": current,
            "current_value": value,
            "pnl_pct": pnl_pct,
            "take_profit_pct": pos["take_profit_pct"],
            "stop_loss_pct": pos["stop_loss_pct"],
            "status": pos["status"],
            "exit": exit_info,
            "sector": sec,
            "leverage": lev,
            "effective_value": round(value * lev, 2),
            "underlying": pos.get("underlying"),
            "underlying_stop_pct": pos.get("underlying_stop_pct"),
            "underlying_buy_price": pos.get("underlying_buy_price"),
            "theory_ids": pos.get("theory_ids", []),
            "scheduled_exit": pos.get("scheduled_exit"),
        })

    sleeves = [{"sleeve": k, "value": round(v, 2)} for k, v in sorted(sleeve_totals.items(), key=lambda x: -x[1])]

    total_return = round((total / start - 1) * 100, 2)
    realized = round(data["account"]["realized_pnl"], 2)

    # Leverage-aware sector rollups vs limits.
    tot_mv = sum(v[0] for v in sec_tot.values()) or 1.0
    sectors = []
    for sl in limits.get("sector_limits", []):
        sec = sl["sector"]
        mv, eff = sec_tot.get(sec, (0.0, 0.0))
        eff_pct = round(eff / tot_mv * 100, 1) if eff else 0.0
        cap = sl.get("max_pct", 100)
        status = "over" if eff_pct > cap else ("warn" if eff_pct > cap * 0.9 else "ok")
        sectors.append({
            "sector": sec, "value": round(mv, 2), "effective": round(eff, 2),
            "leverage": round(eff / mv, 2) if mv else 1.0,
            "pct": eff_pct, "max_pct": cap,
            "status": status, "note": sl.get("note", ""),
        })
    for sec, (mv, eff) in sec_tot.items():
        if not any(s["sector"] == sec for s in sectors):
            sectors.append({
                "sector": sec, "value": round(mv, 2), "effective": round(eff, 2),
                "leverage": round(eff / mv, 2) if mv else 1.0,
                "pct": round(eff / tot_mv * 100, 1), "max_pct": 100,
                "status": "ok", "note": "",
            })
    total_eff = sum(v[1] for v in sec_tot.values())

    # Refresh cadence for the dashboard countdown: matches the GitHub Action
    # cron (`*/6 13-21 UTC` weekdays for pre-open + market hours, once daily
    # otherwise — closed market runs once a day, never floods the servers).
    now_utc = time.gmtime()
    refresh_interval = 6 if 13 <= now_utc.tm_hour <= 21 else 1440
    meta = dict(data["meta"])
    meta["asof_ts"] = int(time.time())
    meta["refresh_interval"] = refresh_interval

    payload = {
        "meta": meta,
        "asof": history[-1]["date"],
        "summary": {
            "total_value": total,
            "cash": cash,
            "invested_value": round(history[-1]["invested_value"], 2),
            "day_change": day_change,
            "total_return_pct": total_return,
            "realized_pnl": realized,
            "start_value": start,
            "max_drawdown_pct": compute_drawdown(history),
            "sharpe_annualized": compute_sharpe(history),
            "cagr_annualized": compute_cagr(total, start, data["meta"]["start_date"]),
        },
        "positions": sorted(positions, key=lambda x: -x["current_value"]),
        "sleeves": sleeves,
        "sectors": sectors,
        "leverage_factor": round(total_eff / tot_mv, 2),
        "history": history,
        "events": data["events"],
        "theories": data["theories"],
        "fears": (fear_data or {}).get("fears") or None,
        "fear_greed": gauge,
        "complacency": (fear_data or {}).get("complacency") or None,
        "fear_sizing": (fear_data or {}).get("fear_sizing") or None,
        "benchmark": benchmark,
        "benchmarks": benchmarks,
        "rebalance": rebalance or None,
        "ai": build_ai_payload(ai_verdict, data, gauge=gauge),
        "news": build_news(
            [p for p in data["positions"] if p["status"] == "open"]
        ) if any(p["status"] == "open" for p in data["positions"])
        else {"asof": None, "big_stories": [], "feed": []},
        "orders": (data.get("orders") or [])[-15:],
    }
    with open(DASHBOARD_JS, "w", encoding="utf-8") as f:
        # Banner warns AI agents / humans not to hand-edit this generated file.
        f.write("/* AUTO-GENERATED by update.py from portfolio.json - do not edit by hand. */\n")
        f.write("window.DASH = ")
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write(";\n")


def print_summary(data, today, benchmark=None):
    """Console summary printed after every update.py run."""
    history = data["account"]["history"]
    total = history[-1]["total_value"]
    start = data["meta"]["start_value"]
    ret = (total / start - 1) * 100
    print(f"\n=== {data['meta']['name']} - {today} ===")
    print(f"Total value: ${total:,.2f}   (return {ret:+,.2f}%)")
    print(f"Cash: ${data['account']['cash']:,.2f}  |  Realized P&L: ${data['account']['realized_pnl']:+,.2f}")
    print(f"Max drawdown: {compute_drawdown(history)}%   |   Sharpe (annualized): {compute_sharpe(history)}")
    cagr = compute_cagr(total, start, data["meta"]["start_date"])
    if cagr is not None:
        print(f"Est. CAGR: {cagr:+,.2f}%  (since {data['meta']['start_date']})")
    if benchmark and benchmark.get("summary"):
        b = benchmark["summary"]
        print(f"vs SPY: return {b['total_return_pct']:+,.2f}%  (excess {ret - b['total_return_pct']:+,.2f}pp)  "
              f"| SPY max DD {b['max_drawdown_pct']}%")
    print("Dashboard: open index.html")
    print("=== END ===")


if __name__ == "__main__":
    main()
