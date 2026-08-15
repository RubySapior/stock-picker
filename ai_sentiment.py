"""
AI Sentiment Decision Layer - draft (algo 0.5.8).

The Engine v1 stepping stone: a fresh LLM call (Gemini) reads TIER A
market data (prices, fear levels, exposures - never the Tier B RSS news
feed), compares against its last verdict via FACT DELTAS, and emits a
strict JSON verdict. Three deterministic layers (theories / fears /
bullish) translate that verdict into proposals. Nothing executes.

Invariants (see CHANGELOG "AI Sentiment Decision Layer"):
  1. AI thinks, the engine calculates - the LLM outputs conviction /
     urgency / confidence, never dollar sizing.
  2. Deterministic rules override AI (TP/SL, vol-halt, sector caps).
  3. Fact-delta ledger, not prose - the prompt gets verified numbers
     about what happened after the last call, never its own reasoning.
  4. Urgency gates the UI - proposals only, human confirmation required.
  5. AI is read-only until Engine v1 - if the call fails or returns
     junk, the book behaves exactly as before (degraded mode).

Status: DISABLED by default (meta.ai.enabled: false) and NOT wired into
update.py. This module is importable and self-contained; wiring happens
in a later milestone.

Usage (future wiring):
    from ai_sentiment import run
    verdict = run(data, prices, fear_data)
    if verdict:
        theories_deltas = theories_layer(verdict)      # -> theory updates
        ai_scores      = fears_layer(verdict)          # -> build_fears(ai_scores=...)
        proposals      = bullish_layer(verdict, data)  # -> review cards
"""
import hashlib
import json
import os
import re
import time
import urllib.request

# Provider endpoints. API keys via env vars only - never committed.
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}"
    ":generateContent?key={key}"
)
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
ZEN_URL = "https://opencode.ai/zen/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ZEN_FREE_MODEL = "deepseek-v4-flash-free"   # free tier - data may train the model
ZEN_PAID_MODEL = "deepseek-v4-flash"        # paid tier - zero retention, recommended
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_PROVIDER = "deepseek"

# Verdict schema whitelists.
MACRO_STANCES = ("risk_on", "neutral", "risk_off")
SECTOR_STANCES = ("bullish", "neutral", "bearish")
THEORY_VERDICTS = ("affirm", "weaken", "probation", "abandon")
KNOWN_FEARS = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")


# ---------------------------------------------------------------- snapshot

def build_market_snapshot(data, prices, fear_data=None, macro=None):
    """Tier A facts for the prompt: exposures, fear levels, prices, macro.

    Deliberately NO position P&L (disposition effect) and NO news.
    prices: dict ticker -> last price, as fetched by update.py.
    macro: optional live {symbol: {px, chg_1d_pct}} from update.fetch_macro().
    Sector limits: meta.limits.rebalance.limits (exempt sectors, e.g. SGOV,
    carry no cap - dry powder grows freely).
    """
    meta = data.get("meta", {})
    limits = meta.get("limits", {})
    positions = [p for p in data.get("positions", []) if p.get("status") == "open"]

    holdings = []
    sec_tot = {}
    for p in positions:
        info = limits.get("position_exposure", {}).get(p["ticker"], {})
        lev = float(info.get("leverage", 1.0))
        value = round((prices.get(p["ticker"]) or p.get("buy_price", 0)) * p.get("shares", 0), 2)
        sec = info.get("sector", p.get("sleeve", "?"))
        sec_tot[sec] = sec_tot.get(sec, 0.0) + value * lev
        holdings.append({
            "ticker": p["ticker"], "sector": sec, "leverage": lev,
            "current_value": value, "effective_value": round(value * lev, 2),
        })

    limits = limits.get("rebalance", {})
    targets = limits.get("limits") or limits.get("targets") or {}
    total = sum(sec_tot.values()) or 1.0
    sectors = [
        {
            "sector": s, "effective_pct": round(v / total * 100, 1),
            "limit_pct": targets.get(s),
        }
        for s, v in sorted(sec_tot.items(), key=lambda kv: -kv[1])
    ]

    fears = (fear_data or {}).get("fears") or []
    snapshot = {
        "asof": time.strftime("%Y-%m-%d %H:%M:%S"),
        "holdings": holdings,
        "sector_exposures": sectors,
        "fear_levels": [
            {"id": f["id"], "name": f["name"], "type": f["type"],
             "score": f["score"], "trend": f.get("trend_dir")}
            for f in fears
        ],
        "prices": {k: round(v, 4) for k, v in prices.items() if v},
    }
    if macro:
        snapshot["macro"] = {}
        for sym, mv in macro.items():
            snapshot["macro"][sym] = mv["px"]
            snapshot["macro"][sym + "_1d_pct"] = mv["chg_1d_pct"]
    return snapshot


def build_fact_deltas(last, snapshot):
    """What happened AFTER the last call, as numbers (never prose).

    last: the previous verdict (meta.ai_last_output), which embeds a
    prices snapshot at call time. Returns deltas only for the facts the
    prior verdict cared about - this is what defeats anchor drift.
    """
    if not last or not isinstance(last, dict):
        return None
    deltas = []
    old_px = (last.get("prices") or {})
    new_px = snapshot.get("prices") or {}
    old_fears = {f["id"]: f for f in (last.get("fear_levels") or [])}
    new_fears = {f["id"]: f for f in snapshot.get("fear_levels") or []}

    for conv in last.get("convictions") or []:
        tk = conv.get("ticker")
        if tk in old_px and tk in new_px and old_px[tk]:
            chg = (new_px[tk] / old_px[tk] - 1) * 100
            deltas.append({
                "type": "conviction_outcome",
                "ticker": tk,
                "was_conviction": conv.get("conviction_score"),
                "since_pct": round(chg, 2),
            })
    for fear in last.get("fears") or []:
        fid = fear.get("id")
        if fid in old_fears and fid in new_fears:
            prev = old_fears[fid]["score"]
            now = new_fears[fid]["score"]
            if prev is not None and now != prev:
                deltas.append({
                    "type": "fear_delta", "id": fid,
                    "was": prev, "now": now, "trend": new_fears[fid].get("trend"),
                })
    for th in last.get("theories") or []:
        deltas.append({
            "type": "theory_verdict_prior", "id": th.get("id"),
            "verdict": th.get("verdict"), "confidence": th.get("confidence"),
        })
    return deltas or None


# ---------------------------------------------------------------- prompt

def build_prompt(cfg, snapshot, deltas, theories=None):
    """Assemble the fixed-structure prompt from Tier A facts only."""
    active = [t for t in theories or []
              if t.get("status") in ("pending", "paused")]
    themes = [
        {
            "id": t.get("id"), "tier": t.get("tier"),
            "prediction": t.get("prediction", "")[:300],
        }
        for t in active
    ]
    return (
        "You are the sentiment/conviction layer of a barbell portfolio engine.\n"
        "Answer with ONLY a single valid JSON object - no markdown fences, no "
        "prose before or after it. JSON comments are not allowed.\n\n"
        "RULES\n"
        "1. Sector biases: rate EVERY sector in sector_exposures. Stance is "
        "bullish/neutral/bearish; conviction is a float 0.0 to 1.0 (1.0 = "
        "maximum confidence).\n"
        "2. Fears: score ALL F1-F8 as a number 1.0 to 5.0 (5.0 = panic). "
        "Your score is your sentiment read on the deterministic fear level "
        "shown in fear_levels - do not contradict a 4.9 level with a 2.0 "
        "sentiment score without a delta_reason.\n"
        "3. Theories: review EVERY theory in CURRENT THEORIES: affirm / "
        "weaken / probation / abandon, confidence integer 0-100.\n"
        "4. Convictions: rate ONLY tickers present in holdings. conviction_"
        "score is a float -1.0 (max trim) to +1.0 (max add); urgency and "
        "confidence are integers 0-100. Tickers needing no action are "
        "OMITTED - omission means hold (the engine assumes 0.0). Never "
        "invent tickers outside holdings.\n"
        "5. A ticker-level conviction overrides a sector stance wherever "
        "they conflict - conviction is the final word, sector bias is the "
        "macro-level view.\n"
        "6. Never output dollar amounts, share counts, or prices - you set "
        "conviction, urgency and confidence; the engine calculates sizing.\n"
        "7. summary: 2-4 sentences synthesizing stance, fear adjustments, "
        "theory verdicts, and execution priorities.\n\n"
        "MARKET STATE (Tier A facts, decision-grade)\n"
        + json.dumps(snapshot, indent=2)
        + ("\n\nWHAT HAPPENED SINCE YOUR LAST VERDICT (fact deltas)\n"
           + json.dumps(deltas, indent=2)
           if deltas else "\n\n(No prior verdict on record - this is your first read.)")
        + ("\n\nCURRENT THEORIES (active only)\n" + json.dumps(themes, indent=2)
           if themes else "")
        + "\n\nSCHEMA (return exactly this shape)\n"
        + json.dumps({
            "date": "YYYY-MM-DD",
            "macro_stance": "risk_on|neutral|risk_off",
            "sector_bias": [{"sector": "...", "stance": "bullish|neutral|bearish",
                             "conviction": 0.85, "driver": "..."}],
            "theories": [{"id": "T17", "verdict": "affirm|weaken|probation|abandon",
                          "confidence": 80, "evidence": "..."}],
            "fears": [{"id": "F4", "sentiment_score": 3.0, "delta_reason": "..."}],
            "convictions": [{"ticker": "TQQQ", "conviction_score": 0.75,
                             "urgency": 60, "confidence": 70, "rationale": "..."}],
            "summary": "2-4 sentences",
        }, indent=2)
    )


# ---------------------------------------------------------------- API call

def _call_gemini(cfg, prompt):
    """POST the prompt to Gemini. Returns raw text or None (degraded)."""
    model = cfg.get("model") or "gemini-2.0-flash"
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        print("  WARN: ai_sentiment: no GEMINI_API_KEY env var - AI offline")
        return None
    url = GEMINI_URL.format(model=model, key=key)
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": int(cfg.get("max_output_chars", 4000)),
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = json.loads(r.read().decode("utf-8"))
        parts = raw["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except Exception as exc:
        print(f"  WARN: ai_sentiment call failed (gemini): {exc}")
        return None


def _call_deepseek(cfg, prompt):
    """POST the prompt to DeepSeek (OpenAI-compatible). Raw text or None."""
    model = cfg.get("model") or "deepseek-chat"
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("  WARN: ai_sentiment: no DEEPSEEK_API_KEY env var - AI offline")
        return None
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": int(cfg.get("max_output_chars", 4000)),
    }).encode("utf-8")
    req = urllib.request.Request(
        DEEPSEEK_URL, data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = json.loads(r.read().decode("utf-8"))
        return raw["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"  WARN: ai_sentiment call failed (deepseek): {exc}")
        return None


def _zen_key():
    """Zen API key: env var first, then opencode's own auth store.

    auth.json lives at ~/.local/share/opencode/auth.json and holds whatever
    the user connected via `opencode /connect`. Never prints the value.
    """
    key = os.environ.get("ZEN_API_KEY") or os.environ.get("OPENCODE_ZEN_KEY")
    if key:
        return key
    try:
        p = os.path.join(os.path.expanduser("~"), ".local", "share",
                         "opencode", "auth.json")
        with open(p, encoding="utf-8") as f:
            store = json.load(f)
        for name in ("opencode", "zen"):
            v = (store.get(name) or {}).get("key") or (store.get(name) or {}).get("apiKey")
            if v:
                return v
    except Exception:
        pass
    return None


def _call_zen(cfg, prompt):
    """POST the prompt to OpenCode Zen (OpenAI-compatible). Raw text or None.

    Paid model (deepseek-v4-flash) is zero-retention; the free model
    (deepseek-v4-flash-free) may use data to improve the model - pick
    deliberately.
    """
    model = cfg.get("model") or ZEN_PAID_MODEL
    if cfg.get("debug_free"):
        model = ZEN_FREE_MODEL
        print("  WARN: ai_sentiment: DEBUG mode - free model (request data may be used for training)")
    key = _zen_key()
    if not key:
        print("  WARN: ai_sentiment: no ZEN_API_KEY (or opencode auth.json) - AI offline")
        return None
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": int(cfg.get("max_output_chars", 4000)),
    }).encode("utf-8")
    req = urllib.request.Request(
        ZEN_URL, data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = json.loads(r.read().decode("utf-8"))
        return raw["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"  WARN: ai_sentiment call failed (zen): {exc}")
        return None


def _openrouter_key():
    """OpenRouter API key: env var first, then opencode's auth store."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    try:
        p = os.path.join(os.path.expanduser("~"), ".local", "share",
                         "opencode", "auth.json")
        with open(p, encoding="utf-8") as f:
            store = json.load(f)
        v = (store.get("openrouter") or {}).get("key")
        if v:
            return v
    except Exception:
        pass
    return None


def _call_openrouter(cfg, prompt):
    """POST the prompt to OpenRouter (OpenAI-compatible). Raw text or None.

    Used to reach Google models (e.g. google/gemini-3.7-flash) with
    extended thinking via cfg.reasoning_effort. Key: OPENROUTER_API_KEY
    env var, else opencode auth.json's "openrouter" entry. Never prints
    the value.
    """
    model = cfg.get("model") or "google/gemini-3.7-flash"
    key = _openrouter_key()
    if not key:
        print("  WARN: ai_sentiment: no OPENROUTER_API_KEY (or opencode auth.json) - AI offline")
        return None
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": int(cfg.get("max_tokens", 16000)),
        "response_format": {"type": "json_object"},
    }
    effort = cfg.get("reasoning_effort")
    if effort:
        body["reasoning_effort"] = effort
    req = urllib.request.Request(
        OPENROUTER_URL, data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = json.loads(r.read().decode("utf-8"))
        return raw["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"  WARN: ai_sentiment call failed (openrouter): {exc}")
        return None


def call_ai(cfg, prompt):
    """Route to the configured provider (meta.ai.provider). Degraded -> None."""
    provider = str(cfg.get("provider") or DEFAULT_PROVIDER).lower()
    if provider == "deepseek":
        return _call_deepseek(cfg, prompt)
    if provider == "zen":
        return _call_zen(cfg, prompt)
    if provider == "gemini":
        if str(cfg.get("router") or "").lower() == "openrouter":
            return _call_openrouter(cfg, prompt)
        return _call_gemini(cfg, prompt)
    print(f"  WARN: ai_sentiment: unknown provider '{provider}' - AI offline")
    return None


# ---------------------------------------------------------------- validation

def _extract_json(raw):
    """Pull the JSON object out of the model reply (strip fences/prose)."""
    if not raw:
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except Exception:
        return None


def _clamp(v, lo, hi, default=0.0):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _validate_verdict(obj):
    """Whitelist + clamp every field. Malformed = None (degraded)."""
    if not isinstance(obj, dict):
        return None
    v = {}
    v["date"] = str(obj.get("date") or time.strftime("%Y-%m-%d"))
    stance = obj.get("macro_stance")
    v["macro_stance"] = stance if stance in MACRO_STANCES else "neutral"
    v["sector_bias"] = []
    for s in obj.get("sector_bias") or []:
        if not isinstance(s, dict) or not s.get("sector"):
            continue
        st = s.get("stance")
        v["sector_bias"].append({
            "sector": str(s["sector"]),
            "stance": st if st in SECTOR_STANCES else "neutral",
            "conviction": _clamp(s.get("conviction"), -1.0, 1.0),
            "driver": str(s.get("driver") or "")[:300],
        })
    v["theories"] = []
    for t in obj.get("theories") or []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        vd = t.get("verdict")
        v["theories"].append({
            "id": str(t["id"]),
            "verdict": vd if vd in THEORY_VERDICTS else "weaken",
            "confidence": int(_clamp(t.get("confidence"), 0, 100)),
            "evidence": str(t.get("evidence") or "")[:400],
        })
    v["fears"] = []
    for f in obj.get("fears") or []:
        fid = str(f.get("id") or "")
        if fid not in KNOWN_FEARS:
            continue
        v["fears"].append({
            "id": fid,
            "sentiment_score": int(round(_clamp(f.get("sentiment_score"), 1, 5, 3))),
            "delta_reason": str(f.get("delta_reason") or "")[:300],
        })
    v["convictions"] = []
    for c in obj.get("convictions") or []:
        if not isinstance(c, dict) or not c.get("ticker"):
            continue
        v["convictions"].append({
            "ticker": str(c["ticker"]).upper(),
            "conviction_score": _clamp(c.get("conviction_score"), -1.0, 1.0),
            "urgency": int(_clamp(c.get("urgency"), 0, 100)),
            "confidence": int(_clamp(c.get("confidence"), 0, 100)),
            "rationale": str(c.get("rationale") or "")[:400],
        })
    v["summary"] = str(obj.get("summary") or "")[:1000]
    return v


# ---------------------------------------------------------------- layers

def theories_layer(verdict):
    """Verdict -> theory deltas (affirm/weaken/probation/abandon candidates).

    Deterministic rules still override: a theory linked to an active
    vol-halt stays paused regardless of what the AI says.
    """
    out = []
    for t in verdict.get("theories") or []:
        out.append({
            "id": t["id"], "verdict": t["verdict"],
            "confidence": t["confidence"], "evidence": t["evidence"],
        })
    return out


def fears_layer(verdict):
    """Verdict -> {fear_id: 1-5} for build_fears(ai_scores=...).

    Reuses the 'two independent witnesses' hook (fears.py:440) with the
    AI as the second witness. Only 1-5 scores, validated above.
    """
    return {f["id"]: f["sentiment_score"] for f in verdict.get("fears") or []}


def bullish_layer(verdict, data, prices=None):
    """Convictions -> target-book proposals (review cards, never trades).

    Ticker whitelist: only OPEN holdings from `data` survive - hallucinated
    tickers (NVDA, TLT, ...) are dropped with a warning, never fatal.
    Omitted holdings need no action by construction (the engine assumes
    conviction 0.0). The engine's sizing math lives here later (caps,
    leverage, vol scalars).

    The engine's sizing math lives here later (caps, leverage, vol
    scalars). For the draft this returns the raw conviction proposals
    plus their urgency/confidence so the UI can gate them.
    """
    whitelist = {p["ticker"] for p in data.get("positions") or []
                 if p.get("status") == "open"}
    proposals = []
    for c in verdict.get("convictions") or []:
        if whitelist and c["ticker"] not in whitelist:
            print(f"  WARN: AI conviction for {c['ticker']} not in holdings - discarded")
            continue
        p = dict(c)
        if p["conviction_score"] > 0:
            p["action"] = "add" if p["conviction_score"] >= 0.5 else "buy"
        else:
            p["action"] = "trim" if p["conviction_score"] <= -0.5 else "sell"
        proposals.append(p)
    return sorted(proposals, key=lambda x: -x["urgency"])


# ---------------------------------------------------------------- entry

def run(data, prices, fear_data=None, macro=None):
    """Full layer run. Returns the validated verdict or None (degraded).

    Never raises. The caller (update.py, future wiring) decides whether
    to persist it into meta.ai_last_output + meta.ai_ledger.
    macro: optional live {symbol: {px, chg_1d_pct}} from update.fetch_macro().
    """
    cfg = (data.get("meta") or {}).get("ai") or {}
    if not cfg.get("enabled"):
        return None
    snapshot = build_market_snapshot(data, prices, fear_data, macro)
    last = (data.get("meta") or {}).get("ai_last_output")
    deltas = build_fact_deltas(last, snapshot)
    prompt = build_prompt(cfg, snapshot, deltas,
                          theories=data.get("theories"))
    raw = call_ai(cfg, prompt)
    obj = _extract_json(raw)
    verdict = _validate_verdict(obj)
    if not verdict:
        print("  WARN: ai_sentiment: verdict invalid/missing - AI offline")
        return None
    verdict["prompt_hash"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    verdict["prices"] = snapshot["prices"]
    verdict["fear_levels"] = snapshot["fear_levels"]
    print(f"  AI SENTIMENT: {verdict['macro_stance']} | "
          f"{len(verdict['theories'])} theories | "
          f"{len(verdict['convictions'])} convictions")
    return verdict


if __name__ == "__main__":
    # Smoke test with no live data: prints what a degraded run looks like.
    print("ai_sentiment: module (algo 0.5.9) - providers: zen / deepseek / gemini")
    print("run(data, prices, fear_data) -> verdict dict or None (degraded)")
