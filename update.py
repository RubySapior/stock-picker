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

Usage:  python update.py
"""
import json
import os
import sys
import time
import urllib.request
import datetime as _dt

from news import build_news
from fears import build_fears

BASE = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO = os.path.join(BASE, "portfolio.json")
DASHBOARD_JS = os.path.join(BASE, "dashboard.js")

USER_AGENT = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# No idle cash policy: spare cash is parked in ultra-short T-bills.
STB_TICKER = "SGOV"
STB_SLEEVE = "Short-Term Bonds (SGOV)"
CASH_BUFFER = 25.0

# Benchmark for the "Portfolio vs SPY" comparison.
SPY_TICKER = "SPY"
SPY_RANGE = "2y"


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
    of invested value) against the target allocations in
    meta.limits.rebalance.targets, flagging any sleeve beyond tolerance_pct.

    Passive by design - it never trades, it only asks the conviction layer to
    review a risk-budget mismatch. No hidden reallocation, no attribution
    pollution.
    """
    limits = data["meta"].get("limits") or {}
    cfg = limits.get("rebalance") or {}
    targets = cfg.get("targets") or {}
    tol = float(cfg.get("tolerance_pct", 5.0))
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
        actual = eff_tot.get(sec, 0.0) / tot_inv * 100.0
        if abs(actual - target) <= tol:
            continue
        msg = (f"{sec} effective exposure {actual:.1f}% vs {target:.1f}% target "
               f"(tolerance +/-{tol:g}%, off by {actual - target:+.1f}pp). "
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
        print(f"  FLAG {sec}: {actual:.1f}% vs {target:.1f}% target (off by {actual - target:+.1f}pp)")
    return flags


def build_benchmark(data, spy_hist):
    """Normalize SPY to start_value, align to portfolio dates, compute metrics."""
    if not spy_hist:
        return None
    start = data["meta"]["start_value"]
    start_date = data["meta"]["start_date"]
    base_px = None
    for h in spy_hist:
        if h["date"] >= start_date:
            base_px = h["px"]
            break
    if base_px is None:
        base_px = spy_hist[-1]["px"]
    norm = [{"date": h["date"], "value": round(start * h["px"] / base_px, 2)}
            for h in spy_hist if h["date"] >= start_date]
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

    spy_vals = [{"total_value": by_date[d]} for d in dates]
    return {
        "label": "S&P 500 (SPY)",
        "start_value": start,
        "history": norm,
        "aligned": aligned,
        "summary": {
            "total_return_pct": round((by_date[dates[-1]] / start - 1) * 100, 2),
            "max_drawdown_pct": compute_drawdown(spy_vals),
            "sharpe_annualized": compute_sharpe(spy_vals),
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


def market_is_open(now_utc=None):
    """NYSE session open? Mon-Fri 09:30-16:00 ET, DST handled manually.

    Used so overnight/pre-market runs do NOT start a fresh history day with a
    zero day-change; the last completed trading day keeps showing until the
    next open.
    """
    now_utc = now_utc or _dt.datetime.utcnow()
    year = now_utc.year
    dst_start = _dt.datetime.combine(_nth_sunday(year, 3, 2), _dt.time(7, 0))    # 2am EST -> 07:00 UTC
    dst_end = _dt.datetime.combine(_nth_sunday(year, 11, 1), _dt.time(6, 0))     # 2am EDT -> 06:00 UTC
    et_offset = -4 if dst_start <= now_utc < dst_end else -5
    et = now_utc + _dt.timedelta(hours=et_offset)
    if et.weekday() >= 5:
        return False
    hm = et.hour * 60 + et.minute
    return 9 * 60 + 30 <= hm <= 16 * 60


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
                     .setdefault("targets", {}).pop(sector, None))
                print(f"  SECTOR CLEANUP: removed empty sector '{sector}' from limits")
        pos.pop("scheduled_exit", None)
        data["positions"].remove(pos)
        print(f"  SCHEDULED EXIT {pos['ticker']}: sold @ {px:.2f} (pnl {realized:+,.2f})")


def main():
    """Fetch prices -> check exits -> deploy cash -> snapshot -> write dashboard.js."""
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

    # Market Fear Gauge: score F1-F8, persist state, build recommendations.
    # Never allowed to break the update - gauge failure degrades to no section.
    fear_data = None
    try:
        fear_data = build_fears(data)
    except Exception as exc:
        print(f"  WARN: fear gauge failed: {exc}")

    # Deliberate rebalances (e.g. issue #7 JEPQ removal): sell at the first
    # market-open price, then let the no-idle-cash policy park proceeds in SGOV.
    execute_scheduled_exits(data, prices, today)
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
    try:
        benchmark = build_benchmark(data, fetch_chart_history(SPY_TICKER))
    except Exception as exc:
        print(f"  WARN: benchmark (SPY) fetch failed: {exc}")

    write_dashboard(data, benchmark, rebalance, fear_data)
    print_summary(data, today, benchmark)


def write_dashboard(data, benchmark=None, rebalance=None, fear_data=None):
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

    payload = {
        "meta": data["meta"],
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
        "complacency": (fear_data or {}).get("complacency") or None,
        "fear_sizing": (fear_data or {}).get("fear_sizing") or None,
        "benchmark": benchmark,
        "rebalance": rebalance or None,
        "news": build_news(
            [p for p in data["positions"] if p["status"] == "open"]
        ) if any(p["status"] == "open" for p in data["positions"])
        else {"asof": None, "big_stories": [], "feed": []},
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
