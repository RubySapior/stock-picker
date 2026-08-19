"""community.py - community/ strategy registry + copy contracts (site 0.5.5.44).

Extracted from update.py / leaderboards.py so the publish/follow API (NAS
hosting step 2) can build on one importable module without running the whole
daily update:
  - sync_version_snapshots(): freeze the book as a new version strategy
  - build_mirror():         the copy contract (mirror.json) a follower replays
  - list_strategies():      every published/snapshot strategy for leaderboards
"""

import os

import store

BASE = os.path.dirname(os.path.abspath(__file__))
COMMUNITY = os.path.join(BASE, "community")
STRATEGIES_ROOT = os.path.join(COMMUNITY, "strategies")


def strategies_root():
    return STRATEGIES_ROOT


def sync_version_snapshots(data, snapshot, today, exclude_tickers=("SGOV",)):
    """Community experiment (site 0.5.5.33): freeze the book as a new
    version strategy whenever its positions change, so the leaderboard can
    compare branches ("did my change lead to better?"). Gated on
    meta.community.snapshot_versions - normally OFF by design, this is a
    leaderboard-filling experiment, not product behavior. SGOV auto-parking
    is excluded from change detection so daily cash sweeps don't spam
    versions (exclude_tickers). At most one version per day; every run
    appends today's snapshot to all active versions.
    """
    cfg = (data.get("meta") or {}).get("community") or {}
    if not cfg.get("snapshot_versions"):
        return
    root = strategies_root()
    if not os.path.isdir(root):
        os.makedirs(root)
    base_id = (data.get("meta") or {}).get("strategy_id", "hypergrowth-sharpe-barbell")
    prefix = base_id + "-v"

    versions = []
    for sid in sorted(os.listdir(root)):
        if not sid.startswith(prefix):
            continue
        v = store.read_json(os.path.join(root, sid, "stats.json"), None)
        if v is not None:
            versions.append(v)
    versions.sort(key=lambda v: v.get("start_date", ""))

    def save(v):
        d = os.path.join(root, v["strategy_id"])
        if not os.path.isdir(d):
            os.makedirs(d)
        store.write_json(os.path.join(d, "stats.json"), v)

    current_positions = sorted(
        ({"ticker": p["ticker"], "shares": p["shares"], "buy_date": p.get("buy_date")}
         for p in data["positions"]
         if p["status"] == "open" and p["ticker"] not in exclude_tickers),
        key=lambda q: q["ticker"],
    )

    latest = versions[-1] if versions else None
    if latest is None or latest.get("positions") != current_positions:
        v = {
            "strategy_id": prefix + today,
            "name": f"{data['meta']['name']} {today}",
            "author": "Snapshot",
            "kind": "snapshot",
            "parent_id": base_id,
            "start_value": snapshot["total_value"],
            "start_date": today,
            "positions": current_positions,
            "history": [snapshot],
        }
        save(v)
        print(f"  SNAPSHOT: new strategy version {v['strategy_id']} "
              f"({len(current_positions)} positions)")
    else:
        for v in versions:
            hist = v.get("history") or []
            if hist and hist[-1].get("date") == today:
                hist[-1] = snapshot
            else:
                hist.append(snapshot)
            save(v)


def build_mirror(data):
    """Export the book as a copyable mirror (site 0.5.5.29, community copy).

    The mirror is the copy contract: a follower replays `changes` scaled to
    their own capital to reproduce the publisher's book EXACTLY (same
    positions, same allocation percentages, same changes). `positions` is the
    current target allocation; `changes` is the normalized trade log derived
    from events[] (deploys, re-entries, exits, executed orders).
    """
    meta = data.get("meta", {})
    history = data["account"]["history"]
    total = round(history[-1]["total_value"], 2) if history else 0.0
    last_px = history[-1].get("prices", {}) if history else {}

    positions = []
    for pos in data["positions"]:
        if pos["status"] != "open":
            continue
        value = round((last_px.get(pos["ticker"]) or pos["buy_price"]) * pos["shares"], 2)
        positions.append({
            "ticker": pos["ticker"],
            "sleeve": pos["sleeve"],
            "buy_date": pos["buy_date"],
            "shares": pos["shares"],
            "current_value": value,
            "pct_of_book": round(value / total * 100, 2) if total else 0.0,
            "theory_ids": pos.get("theory_ids", []),
        })

    TRADE_REASONS = {"take_profit", "stop_loss", "deploy_cash", "re_entry",
                     "rebalance", "market_order"}
    changes = []
    for ev in data.get("events", []):
        reason = ev.get("reason")
        if reason not in TRADE_REASONS:
            continue
        shares = ev.get("shares") or 0.0
        price = ev.get("price") or 0.0
        changes.append({
            "ts": f"{ev.get('date')} {ev.get('ts', '')}".strip(),
            "type": reason,
            "ticker": ev.get("ticker"),
            # Explicit event direction wins; legacy events fall back to the
            # reason heuristic (market_order / rebalance events can be sells).
            "action": ev.get("action") or (
                "sell" if reason in ("take_profit", "stop_loss") else "buy"),
            "shares": shares,
            "price": price,
            "amount": round(shares * price, 2),
            "reason": ev.get("note"),
        })
    changes.sort(key=lambda c: c["ts"])

    return {
        "asof": history[-1]["date"] if history else None,
        "strategy_id": meta.get("strategy_id", "hypergrowth-sharpe-barbell"),
        "strategy_name": meta.get("name"),
        "author": meta.get("author"),
        "total_value": total,
        "positions": sorted(positions, key=lambda p: -p["pct_of_book"]),
        "changes": changes,
    }


def list_strategies():
    """Published + version-snapshot strategies under community/strategies/."""
    out = []
    if not os.path.isdir(STRATEGIES_ROOT):
        return out
    for sid in sorted(os.listdir(STRATEGIES_ROOT)):
        s = store.read_json(os.path.join(STRATEGIES_ROOT, sid, "stats.json"), None)
        if s is None:
            continue
        out.append({
            "strategy_id": s.get("strategy_id", sid),
            "name": s.get("name", sid),
            "author": s.get("author", "unknown"),
            "kind": s.get("kind"),
            "start_value": s.get("start_value", 0),
            "history": s.get("history", []),
        })
    return out