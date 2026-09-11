"""Risk-parity sizing engine — Phase 1 SHADOW MODE (site 0.5.6.17).

Signed spec (multi-review consensus): the deterministic engine owns sizing,
the LLM owns regime/thesis conviction. This module computes target weights,
heat, and would-be tickets WITHOUT trading anything: `shadow_pass` is
strictly read-only (no store calls, mutates nothing) and appends one JSON
line per run to logs/shadow_execution.log (*.log is gitignored and not
served by serve.py's static allowlist).

Conventions (locked):
  - Product-level ATR% everywhere. `L` (leverage) is used ONLY to convert
    market dollars <-> effective dollars at the sector-cap boundary.
  - Underlying-cache bars (QQQ for TQQQ) are converted to product-level by
    xL (documented approximation; daily-reset compounding is second-order
    for a 14/21-day mean).
  - Target is a FOOTPRINT (total desired dollars), never a ticket.
    Ticket = target - current.
  - Block-with-WARN: nothing is scaled to fit; misfits wait.

Phase-2 (live) will consume: `target_dollars`, `evaluate_buy`,
`evaluate_rotation`, `rebalance_drift`. Phase 1 only logs them.
"""

import json
import os
import time
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
OHLC_CACHE = os.path.join(_HERE, "ohlc_cache.json")
LOG_DIR = os.path.join(_HERE, "logs")

RISK_DEFAULTS = {
    "target_risk_bps": 0.005,
    "max_heat_pct_initial": 0.035,
    "max_heat_pct_target": 0.025,
    "rebalance_band_rel": 0.20,
    "rebalance_band_abs": 0.015,
    "max_trim_per_run": 0.20,
    "conviction_deadband": 0.20,
    "min_ticket_usd": 250.0,
    # NOTE (deviation log): the live no-idle-cash sweep still uses
    # update.py CASH_BUFFER (25.0). This 500.0 activates with Phase 2
    # funding; shadow only reports against it.
    "cash_buffer_usd": 500.0,
    "shadow_mode": True,
}


def risk_config(data):
    """Read meta.risk (no writes)."""
    return ((data.get("meta") or {}).get("risk") or {})


def ensure_risk_config(data):
    """Write path (call explicitly from update main, pre-persist): fill
    missing meta.risk keys with defaults, never overwrite set values."""
    meta = data.setdefault("meta", {})
    cfg = meta.setdefault("risk", {})
    for k, v in RISK_DEFAULTS.items():
        cfg.setdefault(k, v)
    return cfg


def ensure_acted_state(data):
    """Write path: init meta.ai_state.acted_conviction registry."""
    state = data.setdefault("meta", {}).setdefault("ai_state", {})
    return state.setdefault("acted_conviction", {})


# ---------------------------------------------------------------- OHLC/vol


def _fetch_bars(ticker, months="3mo"):
    """Product-level daily (h,l,c) bars from Yahoo. No persistence (shadow);
    Phase 2 should extend ohlc_cache coverage instead."""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
           "?range=%s&interval=1d" % (ticker, months))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.load(r)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    bars = [(h, l, c) for h, l, c in
            zip(q["high"], q["low"], q["close"])
            if h is not None and l is not None and c]
    if len(bars) < 2:
        raise ValueError("too few bars")
    return bars


def ema21_atr_pct(bars):
    """EMA21 of the Wilder-ATR14% series. Returns (atr_pct, method).

    method: 'ema21' (> =21 ATR points), 'ema-short' (15-35 bars),
    'rough' (<15 bars, gap-free mean TR%), None (<2 bars).
    """
    n = len(bars)
    if n < 2:
        return None, "insufficient-bars"
    if n < 15:
        m = sum(max(h - l, 0.0) for h, l, c in bars) / n
        return m / bars[-1][2] * 100.0, "rough<%d-bars" % n
    trs = []
    for i, (h, l, c) in enumerate(bars):
        pc = bars[i - 1][2] if i > 0 else c
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    closes = [c for _, _, c in bars]
    a = sum(trs[:14]) / 14.0
    series = [a / closes[13] * 100.0]
    for i in range(14, n):
        a = (a * 13.0 + trs[i]) / 14.0
        series.append(a / closes[i] * 100.0)
    if len(series) >= 21:
        e = sum(series[:21]) / 21.0
        for x in series[21:]:
            e = x * (2.0 / 22.0) + e * (1.0 - 2.0 / 22.0)
        return e, "ema21"
    e = series[0]
    for x in series[1:]:
        e = x * (2.0 / 22.0) + e * (1.0 - 2.0 / 22.0)
    return e, "ema-short(%d)" % len(series)


def product_atr_pct(ticker, data, cache_bars):
    """Product-level EMA21 ATR% for a holding.

    Source priority: underlying-cache bars xL (TQQQ->QQQ) > product-cache
    bars > live Yahoo fetch of the product. Returns (atr_pct, method, L).
    """
    pex = ((data.get("meta") or {}).get("limits") or {}).get(
        "position_exposure") or {}
    L = float((pex.get(ticker) or {}).get("leverage", 1.0)) or 1.0
    pos = next((p for p in data.get("positions") or []
                if p.get("ticker") == ticker), None)
    underlying = (pos or {}).get("underlying")
    if underlying and underlying in cache_bars:
        bars = [(b["h"], b["l"], b["c"]) for b in cache_bars[underlying]]
        v, m = ema21_atr_pct(bars)
        return (v * L if v else None), ("cache:%s-xL%d" % (underlying, L)), L
    if ticker in cache_bars:
        bars = [(b["h"], b["l"], b["c"]) for b in cache_bars[ticker]]
        v, m = ema21_atr_pct(bars)
        return v, ("cache:%s" % ticker), L
    bars = _fetch_bars(ticker)
    v, m = ema21_atr_pct(bars)
    return v, ("fetch:%s" % ticker), L


# ---------------------------------------------------------------- book math


def _px(ticker, data, prices):
    if prices and prices.get(ticker):
        return float(prices[ticker])
    pos = next((p for p in data.get("positions") or []
                if p.get("ticker") == ticker), None)
    if pos is None:
        return 0.0
    return float(pos.get("current_price") or pos.get("buy_price") or 0.0)


def book_equity(data, prices):
    eq = float((data.get("account") or {}).get("cash", 0.0))
    for p in data.get("positions") or []:
        if p.get("status") == "open":
            eq += float(p.get("shares", 0.0)) * _px(p["ticker"], data, prices)
    return round(eq, 2)


def sector_headroom_market(ticker, data, prices):
    """Buy headroom in MARKET dollars (effective headroom / L)."""
    limits = ((data.get("meta") or {}).get("limits") or {})
    caps = {s["sector"]: s["max_pct"]
            for s in (limits.get("sector_limits") or [])}
    pex = limits.get("position_exposure") or {}
    if ticker not in pex:
        return float("inf"), None
    sector = pex[ticker]["sector"]
    L = float(pex[ticker].get("leverage", 1.0)) or 1.0
    max_pct = caps.get(sector)
    if max_pct is None:
        return float("inf"), sector
    mv_total, eff = 0.0, 0.0
    for p in data.get("positions") or []:
        if p.get("status") != "open":
            continue
        sec = pex.get(p["ticker"], {}).get("sector", "Other")
        lv = float(pex.get(p["ticker"], {}).get("leverage", 1.0))
        m = float(p.get("shares", 0.0)) * _px(p["ticker"], data, prices)
        mv_total += m
        if sec == sector:
            eff += m * lv
    head_eff = max_pct / 100.0 * (mv_total or 1.0) - eff
    return max(head_eff, 0.0) / L, sector


def target_dollars(equity, risk_bps, atr_pct, headroom_market, conviction):
    """Footprint (total desired dollars), conviction-scaled. atr_pct is
    product-level; headroom already converted to market dollars."""
    if not atr_pct or atr_pct <= 0 or not conviction:
        return 0.0
    risk_ticket = equity * float(risk_bps) / (float(atr_pct) / 100.0)
    head = headroom_market if headroom_market != float("inf") else risk_ticket
    return round(min(risk_ticket, head) * abs(float(conviction)), 2)


# ---------------------------------------------------------------- shadow


def _load_cache_bars():
    try:
        with open(OHLC_CACHE, encoding="utf-8") as f:
            return (json.load(f).get("bars") or {})
    except Exception:
        return {}


def shadow_pass(data, prices, today, user_id=None):
    """Read-only evaluation. Returns the report dict and appends one JSON
    line to the shadow log. Mutates NOTHING (no store calls)."""
    t0 = time.time()
    cfg = risk_config(data)
    bps = float(cfg.get("target_risk_bps", 0.005))
    deadband = float(cfg.get("conviction_deadband", 0.20))
    min_ticket = float(cfg.get("min_ticket_usd", 250.0))
    heat_target = float(cfg.get("max_heat_pct_target", 0.025))
    heat_initial = float(cfg.get("max_heat_pct_initial", 0.035))
    band_rel = float(cfg.get("rebalance_band_rel", 0.20))
    band_abs = float(cfg.get("rebalance_band_abs", 0.015))

    equity = book_equity(data, prices)
    cache_bars = _load_cache_bars()
    verdict = (data.get("meta") or {}).get("ai_last_output") or {}
    acted = ((data.get("meta") or {}).get("ai_state") or {}).get(
        "acted_conviction") or {}
    order_size = float(((data.get("meta") or {}).get("ai") or {}).get(
        "order_size", 2500))

    heat_rows, heat_total = [], 0.0
    atrs = {}
    for p in data.get("positions") or []:
        if p.get("status") != "open":
            continue
        t = p["ticker"]
        dollars = round(float(p.get("shares", 0.0)) * _px(t, data, prices), 2)
        try:
            a, method, L = product_atr_pct(t, data, cache_bars)
        except Exception as exc:
            heat_rows.append({"ticker": t, "dollars": dollars,
                              "atr_pct": None, "heat": 0.0,
                              "note": "vol-unavailable: %s" % exc})
            atrs[t] = (None, "unavailable", 1.0)
            continue
        atrs[t] = (a, method, L)
        heat = round(dollars * (a / 100.0), 2) if a else 0.0
        heat_total += heat
        heat_rows.append({"ticker": t, "dollars": dollars,
                          "atr_pct": round(a, 2) if a else None,
                          "heat": heat, "method": method})
    heat_rows.sort(key=lambda r: -r["heat"])
    heat_total = round(heat_total, 2)
    heat_pct = round(heat_total / (equity or 1.0) * 100.0, 2)
    heat_cap_now = round(max(heat_total, equity * heat_target), 2)

    signals = []
    for c in verdict.get("convictions") or []:
        t = str(c.get("ticker") or "").upper()
        C = float(c.get("conviction_score", 0.0))
        side = "SELL" if C < 0 else "BUY"
        key = "%s|%s" % (t, side)
        prev = (acted.get(key) or {}).get("conviction")
        dC = None if prev is None else round(C - float(prev), 4)
        passes = prev is None or abs(C - float(prev)) >= deadband
        a, method, L = atrs.get(t, (None, "no-position", 1.0))
        head, sector = sector_headroom_market(t, data, prices)
        cur = next((r["dollars"] for r in heat_rows if r["ticker"] == t), 0.0)
        if not a:
            tgt, delta, held = 0.0, 0.0, False
        elif C >= 0:
            # Buy side: absolute risk footprint scaled by conviction.
            # Floored at zero: a cap-bound "trim" on a BUY conviction is
            # absurd (caps gate buys, never force sells) - overweight-vs-
            # conviction is the weekly weight band's jurisdiction, flagged
            # here via held_overweight.
            tgt = target_dollars(equity, bps, a, head, abs(C))
            raw = round(tgt - cur, 2)
            if raw >= 0:
                delta, held = raw, False
            else:
                delta, held = 0.0, True
        else:
            # Sell side: trim |C| of CURRENT dollars (can't sell what the
            # book doesn't hold; a full |C|=1 exit is decided live).
            tgt = round(cur * (1.0 - abs(C)), 2)
            delta, held = round(-cur * abs(C), 2), False
        dust = 0.0 < abs(delta) < min_ticket
        w_act = round(cur / (equity or 1.0) * 100.0, 2)
        w_tgt = round(tgt / (equity or 1.0) * 100.0, 2)
        band = max(band_abs * 100.0, band_rel * w_tgt)
        drift_breach = abs(w_act - w_tgt) >= band and tgt > 0
        signals.append({
            "ticker": t, "conviction": C, "acted": prev, "delta_C": dC,
            "deadband_pass": passes, "atr_pct": a, "vol_method": method,
            "target": tgt, "current": cur, "ticket": 0.0 if dust else delta,
            "dust_skip": dust,
            "held_overweight": held,
            "cap_headroom": (round(head, 2)
                             if head != float("inf") else None),
            "sector": sector, "w_actual": w_act, "w_target": w_tgt,
            "drift_band": round(band, 2), "drift_breach": drift_breach,
        })

    rotations = []
    for r in verdict.get("rotations") or []:
        s, b = str(r.get("sell") or "").upper(), str(r.get("buy") or "").upper()
        open_t = {p["ticker"] for p in data.get("positions") or []
                  if p.get("status") == "open"}
        a_b, _, _ = atrs.get(b, (None, None, 1.0))
        a_s, _, _ = atrs.get(s, (None, None, 1.0))
        sell_val = next((x["dollars"] for x in heat_rows if x["ticker"] == s),
                        0.0)
        leg = min(sell_val, order_size)
        net = (round(order_size * (a_b / 100.0) - leg * (a_s / 100.0), 2)
               if a_b and a_s else None)
        head_b, _ = sector_headroom_market(b, data, prices)
        rotations.append({
            "sell": s, "buy": b,
            "legs_open": (s in open_t and b in open_t),
            "buy_headroom": (round(head_b, 2)
                             if head_b != float("inf") else None),
            "net_heat": net,
            "atomic_pass": (s in open_t and b in open_t
                            and head_b >= min_ticket
                            and (net is not None and net <= 0)),
        })

    report = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "date": today,
        "user": user_id,
        "shadow": True,
        "equity": equity,
        "heat": heat_total,
        "heat_pct": heat_pct,
        "heat_cap_now": heat_cap_now,
        "heat_target": round(equity * heat_target, 2),
        "heat_rows": heat_rows,
        "verdict_date": verdict.get("date"),
        "signals": signals,
        "rotations": rotations,
        "elapsed_s": round(time.time() - t0, 2),
    }
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        name = ("shadow_%s.log" % user_id if user_id
                else "shadow_execution.log")
        with open(os.path.join(LOG_DIR, name), "a", encoding="utf-8") as f:
            f.write(json.dumps(report) + "\n")
    except Exception as exc:
        print("  WARN: shadow log write failed: %s" % exc)
    print("  SHADOW: equity $%s heat $%s (%.2f%%) cap-now $%s | "
          "%d signals %d rotations -> %s" % (
              f"{equity:,.0f}", f"{heat_total:,.0f}", heat_pct,
              f"{heat_cap_now:,.0f}", len(signals), len(rotations),
              os.path.join(LOG_DIR, name)))
    return report
