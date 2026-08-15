"""
Market Fear Gauge engine (v1 - market-only).

Computes a 1-5 "fear score" for a fixed catalog of macro crash scenarios
(F1-F8) from free Yahoo daily history, using the design converged in the
issue-#6/#7 brainstorm:

  - structural fears (F1/F4/F6/F8): 0.7 x level + 0.3 x slow trend (50d)
  - episodic fears  (F2/F3/F5/F7): 0.7 x velocity (5d) + 0.3 x level
  - every signal is percentile-ranked against its own trailing ~1y window
    (self-relative, so levels mean nothing absolute - only regime matters)
  - market can reach 5.0 unilaterally; a future news layer (VADER keyword
    density) may add at most market+1.5 and only gets a +0.5 boost when both
    market and news are >= 3.0 (two independent witnesses, clamped at 5.0)
  - hedge sizing is RECOMMENDATION-ONLY: per-instrument max demand across
    confirmed active fears (score >= 4.0 sustained for confirm_days), scaled
    to the Hedge Stack headroom (45% cap minus current share). Never trades.

Consumed by update.py (write_dashboard) and rendered by app.js.
"""
import concurrent.futures
import json
import time
import urllib.request

USER_AGENT = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
RNG = "2y"          # history window (percentile bases need 1y + 50/200d warmup)
WINDOW = 260        # trailing trading days used for percentile windows

# Sizing deltas (pp of book) requested when a fear is ACTIVE (>= 4.0 + confirmed).
SIZING_DELTAS = {
    "F1": {"QFLR": 2, "BTAL": 2},
    "F2": {"FXY": 3, "DBMF": 2},
    "F3": {"GLD": 2, "DBMF": 2},
    "F4": {"GLD": 3, "SGOV": 2},
    "F5": {"GLD": 2, "DBMF": 2},
    "F6": {"SGOV": 4},
    "F7": {"BTAL": 3, "DBMF": 2},
    "F8": {"ZROZ": 3, "BTAL": 2},
}
HEDGE_CAP = 0.45     # Hedge Stack sector cap (book-wide, effective exposure)
ACTIVE_THRESHOLD = 4.0
CONFIRM_DAYS = {"structural": 3, "episodic": 2}

FEARS = [
    {
        "id": "F1", "name": "AI / tech concentration pop", "type": "structural",
        "theory_ids": ["T17"], "hedge_ticks": ["QFLR", "VIXM", "BTAL", "ZROZ"],
        "components": [
            {"kind": "inv_pct_ratio", "a": "QQQ", "b": "RSP", "w": 0.5,
             "label": "QQQ/RSP concentration ratio"},
            {"kind": "drawdown", "a": "QQQ", "w": 0.5,
             "label": "QQQ drawdown from 52w high"},
        ],
        "velocity": {"a": "QQQ", "b": "RSP", "sign": -1, "n": 5},
        "trend": {"a": "QQQ", "b": "RSP", "sign": -1, "n": 50},
    },
    {
        "id": "F2", "name": "Yen-carry unwind", "type": "episodic",
        "theory_ids": ["T18"], "hedge_ticks": ["FXY", "DBMF"],
        "components": [
            {"kind": "pct", "a": "FXY", "w": 1.0, "label": "Yen strength (FXY level)"},
        ],
        "velocity": {"a": "JPY=X", "sign": -1, "n": 5},
    },
    {
        "id": "F3", "name": "China / Taiwan escalation", "type": "episodic",
        "theory_ids": ["T19"], "hedge_ticks": ["GLD", "GDX", "DBMF"],
        "components": [
            {"kind": "drawdown", "a": "EWH", "w": 0.6,
             "label": "HK equities drawdown"},
            {"kind": "pct_rise", "a": "GLD", "n": 3, "w": 0.4,
             "label": "Gold 3d momentum"},
        ],
        "velocity": {"a": "EWH", "sign": -1, "n": 5},
    },
    {
        "id": "F4", "name": "Inflation resurgence", "type": "structural",
        "theory_ids": ["T20"], "hedge_ticks": ["GLD", "GDX", "SGOV"],
        "components": [
            {"kind": "pct_ratio", "a": "TIP", "b": "IEF", "w": 1.0,
             "label": "TIP/IEF (breakevens proxy)"},
        ],
        "velocity": {"a": "TIP", "b": "IEF", "sign": 1, "n": 5},
        "trend": {"a": "TIP", "b": "IEF", "sign": 1, "n": 50},
    },
    {
        "id": "F5", "name": "War / energy shock", "type": "episodic",
        "theory_ids": ["T21"], "hedge_ticks": ["GLD", "GDX", "FXY", "DBMF"],
        "components": [
            {"kind": "pct_rise", "a": "CL=F", "n": 5, "w": 0.7,
             "label": "Crude 5d momentum"},
            {"kind": "pct_rise", "a": "GLD", "n": 1, "w": 0.3,
             "label": "Gold 1d momentum"},
        ],
        "velocity": {"a": "CL=F", "sign": 1, "n": 5},
    },
    {
        "id": "F6", "name": "Rates shock / duration liquidation", "type": "structural",
        "theory_ids": ["T6"], "hedge_ticks": ["SGOV"],
        "components": [
            {"kind": "inv_pct_ratio", "a": "TLT", "b": "SHY", "w": 0.6,
             "label": "TLT/SHY (long-vs-short duration)"},
            {"kind": "pct", "a": "^TNX", "w": 0.4, "label": "10y yield level"},
        ],
        "velocity": {"a": "TLT", "b": "SHY", "sign": -1, "n": 5},
        "trend": {"a": "TLT", "b": "SHY", "sign": -1, "n": 50},
    },
    {
        "id": "F7", "name": "Credit stress / HY spread", "type": "episodic",
        "theory_ids": ["T6"], "hedge_ticks": ["BTAL", "DBMF"],
        "components": [
            {"kind": "inv_pct_ratio", "a": "HYG", "b": "LQD", "w": 1.0,
             "label": "HYG/LQD (credit spread proxy)"},
        ],
        "velocity": {"a": "HYG", "b": "LQD", "sign": -1, "n": 5},
    },
    {
        "id": "F8", "name": "Recession / growth freeze", "type": "structural",
        "theory_ids": ["T6"], "hedge_ticks": ["ZROZ", "BTAL"],
        "components": [
            {"kind": "inv_pct_ratio", "a": "XLY", "b": "XLP", "w": 0.5,
             "label": "XLY/XLP (cyclical vs staples)"},
            {"kind": "ma_dist", "a": "SPY", "w": 0.5,
             "label": "SPY below 200d MA"},
        ],
        "velocity": {"a": "XLY", "b": "XLP", "sign": -1, "n": 5},
        "trend": {"a": "XLY", "b": "XLP", "sign": -1, "n": 50},
    },
]


def fetch_history(symbol, rng=RNG):
    """Daily close history [{date, px}, ...] oldest-first (Yahoo chart endpoint)."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?range={rng}&interval=1d")
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
        out.append({"date": time.strftime("%Y-%m-%d", time.gmtime(ts[i])),
                    "px": float(adj[i])})
    return out


SYMBOLS = sorted({s for f in FEARS for c in f["components"]
                  for s in (c.get("a"), c.get("b")) if s} |
                 {s for f in FEARS for s in (f["velocity"].get("a"),
                                             f["velocity"].get("b")) if s} |
                 {s for f in FEARS for s in f.get("hedge_ticks", []) if s} |
                 {"QQQ"})


def _pct_rank(value, series):
    """Empirical percentile rank (0..1) of value within series (None-safe)."""
    s = [x for x in series if x is not None and x == x]
    if not s:
        return None
    return sum(1 for x in s if x <= value) / len(s)


def _mom(series, n):
    """n-day % change at each point of a close series (list of px)."""
    out = [None] * len(series)
    for i in range(n, len(series)):
        prev = series[i - n]
        if prev and prev != 0:
            out[i] = (series[i] - prev) / prev
    return out


def _ratio(ax, bx):
    out = [None] * len(ax)
    for i in range(len(ax)):
        if ax[i] and bx[i]:
            out[i] = ax[i] / bx[i]
    return out


def _series(sym, hist):
    """Close series for symbol (aligned to window tail) + 52w/200d bases."""
    arr = [h["px"] for h in hist]
    win = arr[-WINDOW:] if len(arr) > WINDOW else arr
    return win


def _component_value(c, hist_map, win_map):
    """Compute one 0..1 'high = fear' component value for today."""
    a = hist_map.get(c["a"])
    if a is None:
        return None
    arr = [h["px"] for h in a]
    win = arr[-WINDOW:]
    today = win[-1]
    if c["kind"] == "pct":
        return _pct_rank(today, win)
    if c["kind"] == "drawdown":
        hi = max(win)
        return 1.0 - (today / hi) if hi else None
    if c["kind"] == "ma_dist":
        if len(win) < 200:
            return None
        ma = sum(win[-200:]) / 200.0
        return max(0.0, min(1.0, 1.0 - today / ma)) if ma else None
    if c["kind"] == "pct_rise":
        mom = _mom(win, c.get("n", 5))
        return _pct_rank(mom[-1], mom)
    if c["kind"] in ("pct_ratio", "inv_pct_ratio"):
        b = hist_map.get(c["b"])
        if b is None:
            return None
        bw = [h["px"] for h in b][-WINDOW:]
        r = _ratio(win, bw)
        p = _pct_rank(r[-1], r)
        return p if c["kind"] == "pct_ratio" else (1.0 - p)
    return None


def _proxy_series(cfg, hist_map):
    """Return (today_value, series, changed_series) for a velocity/trend proxy."""
    a = hist_map.get(cfg["a"])
    if a is None:
        return None, None, None
    arr = [h["px"] for h in a]
    win = arr[-WINDOW:]
    b = hist_map.get(cfg.get("b"))
    if b is not None:
        bw = [h["px"] for h in b][-WINDOW:]
        base = _ratio(win, bw)
    else:
        base = win
    n = cfg.get("n", 5)
    chg = _mom(base, n)
    sign = cfg.get("sign", 1)
    today = chg[-1]
    return (sign * today if today is not None else None,
            [sign * x if x is not None else None for x in chg])


def _fear_score(fear, hist_map, today):
    """Compute {score, level, velocity, trend, signals[]} for one fear."""
    comps = []
    used = 0.0
    for c in fear["components"]:
        v = _component_value(c, hist_map, None)
        if v is None:
            continue
        comps.append({"label": c["label"], "value": round(v, 3),
                      "w": c["w"], "contribution": c["w"] * v})
        used += c["w"]
    if not comps:
        return None
    level = sum(x["contribution"] for x in comps) / used if used else None
    if level is None:
        return None
    level = max(0.0, min(1.0, level))

    score_pct = level
    vinfo = {"label": "5d velocity", "value": None, "pct": None}
    tinfo = {"label": "50d trend", "value": None, "pct": None}
    if fear["type"] == "episodic":
        v_today, v_series = _proxy_series(fear["velocity"], hist_map)
        if v_today is not None:
            v_pct = _pct_rank(v_today, v_series)
            score_pct = 0.7 * v_pct + 0.3 * level
            vinfo = {"label": "5d velocity", "value": round(v_today, 4),
                     "pct": round(v_pct, 3)}
    else:
        t_today, t_series = _proxy_series(fear["trend"], hist_map)
        if t_today is not None:
            t_pct = _pct_rank(t_today, t_series)
            score_pct = 0.7 * level + 0.3 * t_pct
            tinfo = {"label": "50d trend", "value": round(t_today, 4),
                     "pct": round(t_pct, 3)}

    score = max(1.0, min(5.0, round(1 + 4 * score_pct, 1)))
    signals = sorted(comps, key=lambda x: -x["contribution"])[:2]
    signals = [{"label": s["label"], "value": s["value"]} for s in signals]
    return {
        "id": fear["id"], "name": fear["name"], "type": fear["type"],
        "score": score, "level": round(level, 3),
        "velocity": vinfo if fear["type"] == "episodic" else None,
        "trend": tinfo if fear["type"] == "structural" else None,
        "signals": signals,
        "theory_ids": fear["theory_ids"],
        "hedge_ticks": fear["hedge_ticks"],
        "asof": today,
    }


def _regime(vs, fear_avg):
    """2D regime matrix: equity stretch (x) x systemic fear (y)."""
    stretch_hi = vs >= 0.5
    if fear_avg >= 3.5:
        return "fragility" if stretch_hi else "stress"
    if fear_avg >= 2.5:
        return "watchful" if stretch_hi else "moderate"
    return "complacency" if stretch_hi else "neutral"


_REGIME_NOTES = {
    "fragility": ("Fragility regime - macro divergence: equities stretched while "
                  "macro fears run high. Equities expected to crack."),
    "stress": ("Stress regime - broad equity drawdown active. Hedges should be "
               "paying."),
    "complacency": ("Complacency regime - melt-up conditions. Keep the baseline "
                    "hedge floor on."),
    "neutral": ("Neutral regime - quiet equilibrium. No hedge change warranted."),
    "watchful": ("Calm but watchful - some macro stress under the surface. Keep "
                 "the hedge stack on."),
    "moderate": ("Moderate stress - hedges have a job to do."),
}

PAY_WINDOW = 10   # sessions used for the dominant-fear hedge attribution check


def _pay_check(hist_map, fears):
    """Attribution check: dominant fear's hedge_ticks vs their recent returns.

    Returns {fear_id, fear_name, checks:[{ticker, ret_pct, paying}]} - only the
    instruments that are SUPPOSED to pay in this scenario are judged, so a
    rates shock (F6) checks SGOV, not ZROZ/TIP which are expected to bleed.
    """
    if not fears:
        return None
    dom = max(fears, key=lambda f: f["score"])
    checks = []
    for tk in dom.get("hedge_ticks", []):
        h = hist_map.get(tk)
        if not h:
            continue
        px = [x["px"] for x in h]
        px = px[-WINDOW:]
        if len(px) < 2 or not px[-1]:
            continue
        base = px[-1 - min(PAY_WINDOW, len(px) - 1)]
        if not base:
            continue
        ret = round((px[-1] / base - 1.0) * 100.0, 2)
        checks.append({"ticker": tk, "ret_pct": ret, "paying": ret >= 0})
    if not checks:
        return None
    return {"fear_id": dom["id"], "fear_name": dom["name"],
            "score": dom["score"], "checks": checks}


def _complacency(hist_map, fears):
    """Complacency = valuation/momentum stretch x (1 - fear level), 0..1.

    The index stays a single number for the header, but the reading is a 2D
    regime matrix (stretch x systemic fear) so the message can distinguish a
    realized equity crash from a fragile divergence (SPY at ATH while bonds/
    credit are stressed) - see _regime() / _REGIME_NOTES. The dominant fear's
    hedge attribution check (_pay_check) judges only the instruments expected
    to pay in that scenario.
    """
    q = hist_map.get("QQQ")
    if not q:
        return None
    arr = [h["px"] for h in q]
    win = arr[-WINDOW:]
    today = win[-1]
    mom20 = _mom(win, 20)
    vs = 0.5 * (_pct_rank(mom20[-1], mom20) if mom20[-1] is not None else 0.0)
    if len(win) >= 200:
        ma_series = []
        for i in range(200, len(win) + 1):
            ma_series.append(sum(win[i-200:i]) / 200.0)
        dist_series = [win[i] / ma_series[i-200]
                       for i in range(200, len(win))]
        vs += 0.5 * _pct_rank(today / ma_series[-1], dist_series)
    scores = sorted((f["score"] for f in fears), reverse=True)[:3]
    mean = sum(scores) / len(scores) if scores else 3.0
    norm_fear = max(0.0, min(1.0, (mean - 1.0) / 4.0))
    ft = 1.0 - norm_fear
    index = round(vs * ft, 3)
    divergence = round(vs * norm_fear, 3)
    fear_avg = round(mean, 2)
    regime = _regime(vs, fear_avg)
    return {"index": index, "valuation_stretch": round(vs, 3),
            "fear_term": round(ft, 3), "divergence": divergence,
            "fear_avg": fear_avg, "regime": regime,
            "note": _REGIME_NOTES[regime],
            "pay_check": _pay_check(hist_map, fears)}


def _sizing(fears, fear_state, hedge_share):
    """Recommendation-only hedge sizing: per-instrument max, headroom-capped."""
    active = []
    for f in fears:
        st = fear_state.get(f["id"], {})
        if f["score"] >= ACTIVE_THRESHOLD and st.get("confirmed"):
            active.append(f)
    demand = {}
    reasons = {}
    for f in active:
        for inst, pp in SIZING_DELTAS.get(f["id"], {}).items():
            if pp > (demand.get(inst) or 0):
                demand[inst] = pp
                reasons[inst] = [f["id"]]
            elif inst in reasons:
                reasons[inst].append(f["id"])
    if not demand:
        return []
    total = sum(demand.values())
    headroom = max(0.0, HEDGE_CAP - hedge_share)
    scale = min(1.0, headroom / total) if total else 0.0
    out = []
    for inst, pp in sorted(demand.items(), key=lambda x: -x[1]):
        final = round(pp * scale, 2)
        if final >= 0.5:
            out.append({"instrument": inst, "pct": final,
                        "demand_pct": pp, "reasons": sorted(set(reasons[inst]))})
    return out


def _hedge_share(data):
    """Current Hedge Stack sector share of total value (effective, 0..1)."""
    pex = (data.get("meta", {}).get("limits", {}) or {}).get("position_exposure", {})
    snap = data["account"]["history"][-1]
    total = snap["total_value"] or 1.0
    hedge = 0.0
    for p in data["positions"]:
        if p.get("status") != "open":
            continue
        info = pex.get(p["ticker"], {})
        if info.get("sector") == "Hedge Stack":
            px = snap.get("prices", {}).get(p["ticker"]) or p.get("buy_price")
            hedge += (px or 0) * p.get("shares", 0) * float(info.get("leverage", 1.0))
    return hedge / total


def build_fears(data, news_scores=None):
    """Fetch market histories, score all fears, persist state, return payload.

    news_scores: optional {fear_id: 1-5} from the future news layer. When
    provided, applies the 'two independent witnesses' combination:
        raw = max(market, min(news, market + 1.5))
        if market >= 3 and news >= 3: raw = min(raw + 0.5, 5)
    """
    today = time.strftime("%Y-%m-%d")
    hist_map = {}
    degraded = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        fut = {ex.submit(fetch_history, s): s for s in SYMBOLS}
        for f in concurrent.futures.as_completed(fut):
            sym = fut[f]
            try:
                hist_map[sym] = f.result()
            except Exception as exc:
                degraded.append(sym)

    fears = []
    for fear in FEARS:
        needed = {c.get("a") for c in fear["components"]} | {fear["velocity"]["a"]}
        if fear.get("trend"):
            needed |= {fear["trend"]["a"]}
        if any(s not in hist_map for s in needed if s):
            continue
        res = _fear_score(fear, hist_map, today)
        if not res:
            continue
        res["degraded"] = bool({c["a"] for c in fear["components"]} &
                               set(degraded))
        fears.append(res)

    state = data.setdefault("meta", {}).setdefault("fear_state", {})
    for f in fears:
        st = state.setdefault(f["id"], {})
        prev = st.get("score")
        st["prev_score"] = prev
        st["score"] = f["score"]
        if f["score"] >= ACTIVE_THRESHOLD:
            st["days_above"] = st.get("days_above", 0) + 1
        else:
            st["days_above"] = 0
        st["confirmed"] = st["days_above"] >= CONFIRM_DAYS[f["type"]]
        f["trend_dir"] = ("rising" if (prev is not None and f["score"] - prev >= 0.15)
                          else "falling" if (prev is not None and prev - f["score"] >= 0.15)
                          else "flat")

    complacency = _complacency(hist_map, fears)
    sizing = _sizing(fears, state, _hedge_share(data))
    return {
        "fears": sorted(fears, key=lambda x: -x["score"]),
        "complacency": complacency,
        "fear_sizing": sizing,
        "asof": today,
        "degraded": degraded,
        "news_layer": news_scores is not None,
    }


def apply_ai_witnesses(fears, ai_scores):
    """Blend AI sentiment scores into fear readings (two independent witnesses).

    Same combination build_fears() would apply if news_scores were passed,
    applied AFTER the market-only run so the AI (second witness) can raise a
    fear the market already sees but cannot manufacture panic on its own:

        raw = max(market, min(news, market + 1.5))
        if market >= 3 and news >= 3: raw = min(raw + 0.5, 5)

    Mutates the fear objects in place (display layer only). meta.fear_state
    persistence keeps tracking the MARKET witness, so days_above/confirmed
    logic stays purely market-driven.
    """
    if not ai_scores:
        return fears
    for f in fears:
        news = ai_scores.get(f["id"])
        if news is None:
            continue
        market = f["score"]
        raw = max(market, min(news, market + 1.5))
        if market >= 3 and news >= 3:
            raw = min(raw + 0.5, 5)
        f["score"] = round(raw, 1)
        f["ai_adjusted"] = True
    return fears