"""Leaderboards (site 0.5.5.33, community feature).

Computes per-strategy window returns (weekly / monthly / quarterly / yearly /
all-time) and writes the Top-10 leaderboard to leaderboards.js.

Sources (deduplicated by strategy_id):
  - community/strategies/<id>/stats.json  (published + version-snapshot books)
  - benchmark strategies (SPY, QQQ, TQQQ, TQQQ60/TMF40 ...) fetched from
    Yahoo daily closes over a 2y range and normalized to 100000 at the first
    close; window returns are trailing over the full history (real TQQQ
    returns, not anchored to the book's start date)
  - the local book (portfolio.json account.history)

Benchmark closes are cached in benchmark_cache.json and refreshed once per
calendar day (site 0.5.5.44); a failed refresh keeps the cached closes so
the leaderboard never loses a benchmark row to a transient Yahoo error.

Return math: (last_value / first_value - 1) * 100, where first_value is the
snapshot N sessions back (or the earliest available / meta.start_value for
all-time, matching the dashboard's total_return_pct anchor).

Run standalone (`python leaderboards.py`) or via update.py (build_leaderboards
is called after every run, so the committed leaderboard stays fresh on the
GitHub Actions cadence).
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request

from community import list_strategies
import store

BASE = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO = os.path.join(BASE, "portfolio.json")
LEADERBOARD = os.path.join(BASE, "leaderboards.js")
BENCH_CACHE = os.path.join(BASE, "benchmark_cache.json")

TOP_N = 10

WINDOWS = [
    ("weekly", 5, "Last 5 trading sessions"),
    ("monthly", 21, "Last 21 trading sessions"),
    ("quarterly", 63, "Last 63 trading sessions"),
    ("yearly", 252, "Last 252 trading sessions"),
    ("all_time", None, "Since inception (start_value anchored)"),
]

USER_AGENT = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
CHART_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
             "?range=2y&interval=1d")


def _load_portfolio():
    return store.read_portfolio()


def _local_strategy(data=None):
    """The local book as one strategy entry."""
    if data is None:
        data = _load_portfolio()
    meta = data.get("meta", {})
    return {
        "strategy_id": meta.get("strategy_id", "hypergrowth-sharpe-barbell"),
        "name": meta.get("name"),
        "author": meta.get("author", "unknown"),
        "start_value": meta.get("start_value", 100000),
        "history": data.get("account", {}).get("history", []),
    }


def _fetch_closes(symbol):
    """Daily closes keyed by date (YYYY-MM-DD) from Yahoo, oldest first."""
    req = urllib.request.Request(
        CHART_URL.format(sym=urllib.parse.quote(symbol)), headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=25) as r:
        js = json.loads(r.read().decode("utf-8"))
    res = js["chart"]["result"][0]
    ts = res.get("timestamp") or []
    closes = (res.get("indicators") or {}).get("quote", [{}])[0].get("close") or []
    out = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        out[time.strftime("%Y-%m-%d", time.gmtime(t))] = float(c)
    return out


def _update_bench_closes(today):
    """update.py's daily 2y closes from ohlc_cache.json "bench" (a list of
    {date, px} per symbol) as a {sym: {date: close}} dict - but only for
    symbols update.py actually refreshed TODAY, else {} so the caller falls
    back to its own fetch. SPY/QQQ/TQQQ are fetched by BOTH modules; reusing
    update's (adjusted) closes here avoids a second Yahoo fetch per symbol
    per day and keeps the leaderboard consistent with the dashboard chart.
    """
    try:
        cache = store.read_json(os.path.join(BASE, "ohlc_cache.json"), {})
        fetched = cache.get("bench_fetched") or {}
        bench = cache.get("bench") or {}
        return {
            sym: {p["date"]: p["px"] for p in rows}
            for sym, rows in bench.items()
            if fetched.get(sym) == today and isinstance(rows, list)
        }
    except Exception:
        return {}


def _ensure_bench_closes(symbols, cache):
    """Per-symbol 2y closes, refreshed once per calendar day. A failed fetch
    keeps the cached closes (stale fallback) so the leaderboard never loses
    a benchmark row to a transient Yahoo error. Symbols that update.py already
    fetched today (ohlc_cache.json "bench") are reused instead of fetched
    again. Returns changed (bool)."""
    today = time.strftime("%Y-%m-%d")
    fetched = cache.setdefault("fetched", {})
    closes = cache.setdefault("closes", {})
    changed = False
    update_bench = _update_bench_closes(today)
    for sym in symbols:
        if sym in update_bench:
            closes[sym] = update_bench[sym]
            fetched[sym] = today
            continue
        if fetched.get(sym) == today and sym in closes:
            continue
        try:
            closes[sym] = _fetch_closes(sym)
            fetched[sym] = today
            changed = True
        except Exception as exc:
            if sym in closes:
                print(f"  WARN: benchmark refresh failed for {sym} - "
                      f"using cached closes: {exc}")
            else:
                print(f"  WARN: benchmark fetch failed for {sym}: {exc}")
    return changed


def _split_benchmark(spec):
    """'TQQQ60/TMF40' -> [('TQQQ', 0.6), ('TMF', 0.4)]; 'SPY' -> [('SPY', 1.0)]."""
    parts = []
    for chunk in spec.split("/"):
        m = re.match(r"^([A-Z0-9.\-^=]+?)(\d+)?$", chunk.strip())
        if not m:
            continue
        ticker, pct = m.group(1), m.group(2)
        parts.append((ticker, int(pct) / 100.0 if pct else 1.0))
    if not parts:
        parts = [(spec, 1.0)]
    total = sum(w for _, w in parts) or 1.0
    return [(t, w / total) for t, w in parts]


def _benchmark_history(spec, closes_cache):
    """Daily-rebalanced history for a benchmark spec over the FULL fetched range.

    Normalized to start at `anchor` so values are comparable across windows;
    window returns (weekly/monthly/...) are trailing over the full history,
    and all-time = the whole 2y fetch (real return, not anchored to the
    book's start date). Closes come from the shared benchmark cache
    (benchmark_cache.json, refreshed once per calendar day).
    """
    legs = _split_benchmark(spec)
    series = {}
    for t, _w in legs:
        series[t] = closes_cache.get(t) or {}
    dates = sorted({d for s in series.values() for d in s})
    if not dates:
        return []
    anchor = 100000.0
    value = anchor
    prev = {}
    history = []
    for d in dates:
        ret = 0.0
        for t, w in legs:
            closes = series[t]
            p = prev.get(t)
            c = closes.get(d)
            if p is not None and c is not None:
                ret += w * (c / p - 1.0)
            if c is not None:
                prev[t] = c
        value *= 1.0 + ret
        history.append({"date": d, "total_value": round(value, 2)})
    return history


def _benchmark_strategies(benchmarks, closes_cache):
    out = []
    for spec in benchmarks or []:
        try:
            hist = _benchmark_history(spec, closes_cache)
        except Exception:
            hist = []
        if not hist:
            continue
        sid = "benchmark-" + re.sub(r"[^a-z0-9]+", "-", spec.lower()).strip("-")
        out.append({
            "strategy_id": sid,
            "name": spec,
            "author": "Benchmark",
            "kind": "benchmark",
            "start_value": hist[0]["total_value"],
            "start_date": hist[0]["date"],
            "history": hist,
        })
    return out


def _window_return(entry, n_sessions):
    """Return % over the last n_sessions snapshots (earliest available if shorter)."""
    history = entry.get("history") or []
    if not history:
        return None
    last = history[-1].get("total_value")
    if last is None:
        return None
    if n_sessions is None:
        start = entry.get("start_value") or history[0].get("total_value")
    else:
        idx = len(history) - 1 - n_sessions
        start = history[0].get("total_value") if idx < 0 else history[idx].get("total_value")
    if not start:
        return None
    return round((last / start - 1) * 100, 2)


def _max_drawdown(history):
    """Max drawdown % (negative or 0), same convention as update.py."""
    peak = 0.0
    mdd = 0.0
    for h in history:
        v = h["total_value"]
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, (v - peak) / peak)
    return round(mdd * 100, 2)


def _sharpe(history):
    """Annualized Sharpe from daily snapshots (None if uncomputable).

    Same convention as update.py's compute_sharpe: mean daily return over
    daily std, annualized by sqrt(252).
    """
    vals = [h.get("total_value") for h in history]
    if len(vals) < 3 or any(v is None or v <= 0 for v in vals):
        return None
    rets = [(vals[i] / vals[i - 1]) - 1 for i in range(1, len(vals))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = var ** 0.5
    if std == 0:
        return None
    return round((mean / std) * (252 ** 0.5), 2)


def _window_history(history, n_sessions):
    """Slice history to the trailing window (inclusive).
    
    Mirrors _window_return's start index so drawdown/sharpe use the same
    period. n_sessions=None -> full history (all-time).
    """
    if not history:
        return []
    if n_sessions is None:
        return history
    idx = len(history) - 1 - n_sessions
    if idx < 0:
        idx = 0
    return history[idx:]


def _ranked(strategies, n_sessions):
    rows = []
    for s in strategies:
        ret = _window_return(s, n_sessions)
        if ret is None:
            continue
        wh = _window_history(s.get("history") or [], n_sessions)
        rows.append({
            "strategy_id": s["strategy_id"],
            "name": s.get("name"),
            "author": s.get("author"),
            "kind": s.get("kind"),
            "return_pct": ret,
            "max_drawdown_pct": _max_drawdown(wh),
            "sharpe": _sharpe(wh),
        })
    rows.sort(key=lambda r: -r["return_pct"])
    return rows[:TOP_N]


def build_leaderboards(data=None):
    """Compute all windows; returns the leaderboards dict (also written by caller)."""
    if data is None:
        data = _load_portfolio()
    meta = data.get("meta", {})
    benchmarks = (meta.get("community") or {}).get("benchmarks") or []
    symbols = sorted({t for spec in benchmarks for t, _w in _split_benchmark(spec)})
    cache = store.read_json(BENCH_CACHE, {})
    if _ensure_bench_closes(symbols, cache):
        store.write_json(BENCH_CACHE, cache, indent=1)
    strategies = []
    seen = set()
    for s in list_strategies() + [_local_strategy(data)]:
        if s["strategy_id"] in seen:
            continue
        seen.add(s["strategy_id"])
        strategies.append(s)
    for b in _benchmark_strategies(benchmarks, cache.get("closes") or {}):
        if b["strategy_id"] not in seen:
            seen.add(b["strategy_id"])
            strategies.append(b)
    windows = {}
    for key, n, label in WINDOWS:
        windows[key] = {"label": label, "rows": _ranked(strategies, n)}
    return {
        "asof": time.strftime("%Y-%m-%d %H:%M:%S"),
        "top_n": TOP_N,
        "strategy_count": len(strategies),
        "windows": windows,
    }


def write_leaderboards(payload=None):
    if payload is None:
        payload = build_leaderboards()
    # Script-tag format (window.LEADERBOARDS) — same pattern as dashboard.js,
    # so the page works from file:// double-click as well as over HTTP.
    with open(LEADERBOARD, "w", encoding="utf-8") as f:
        f.write("/* AUTO-GENERATED by leaderboards.py from portfolio.json / community/ - do not edit by hand. */\n")
        f.write("window.LEADERBOARDS = ")
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write(";\n")
    return payload


if __name__ == "__main__":
    payload = write_leaderboards()
    print(f"Leaderboards written to {LEADERBOARD} "
          f"({payload['strategy_count']} strategy(s), top {payload['top_n']} per window)")
    for key, win in payload["windows"].items():
        for r in win["rows"][:3]:
            print(f"  {key:10s} #{win['rows'].index(r) + 1}: {r['name']} "
                  f"{r['return_pct']:+.2f}% ({r['author']})")