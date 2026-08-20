"""
AI Sentiment Decision Layer (algo 0.6.1.00).

The Engine v1 stepping stone: a fresh LLM call (Gemini) reads TIER A
market data (prices, fear levels, exposures - never the Tier B RSS news
feed), compares against its last verdict via FACT DELTAS plus the prior
verdict block, and emits a strict JSON verdict of ONLY changes. Three
deterministic layers (theories / fears / bullish) translate that verdict
into proposals. Nothing executes directly.

Engine v0.6.1: change-detect semantics (omission = agreement with the
prior read), paired rotations, AI fear proposals/edits that persist into
the editable fear_scenarios.json table, a crowding sentiment-gauge gate,
and a calibration track record that discounts confidence on repeatedly
wrong tickers.

Invariants (see CHANGELOG "AI Sentiment Decision Layer"):
  1. AI thinks, the engine calculates - the LLM outputs conviction /
     urgency / confidence, never dollar sizing.
  2. Deterministic rules override AI (TP/SL, vol-halt, sector caps).
  3. Fact-delta ledger, not prose - the prompt gets verified numbers
     about what happened after the last call, never its own reasoning.
  4. Urgency gates the UI - proposals only, human confirmation required
     (recommend mode default; execute mode is a human-set override).
  5. AI is read-only - if the call fails or returns junk, the book
     behaves exactly as before (degraded mode).

Usage (wired into update.py):
    from ai_sentiment import run
    verdict = run(data, prices, fear_data, macro, sentiment, calibration)
    if verdict:
        theories_deltas = theories_layer(verdict)      # -> theory updates
        ai_scores      = fears_layer(verdict)          # -> build_fears(ai_scores=...)
        proposals      = bullish_layer(verdict, data)  # -> review cards
        rotations      = rotation_layer(verdict, data) # -> paired orders
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
    ":generateContent"
)
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
ZEN_URL = "https://opencode.ai/zen/v1/chat/completions"


def _http_json(url, body, headers, timeout=90, attempts=2):
    """POST JSON with retries + exponential backoff (5s / 15s) (issue #45).

    Returns the parsed response dict, or None after all attempts fail.
    """
    for attempt in range(attempts):
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            print(f"  WARN: ai_sentiment call failed (attempt {attempt + 1}/{attempts}): {exc}")
            if attempt < attempts - 1:
                time.sleep(5 * (3 ** attempt))
    return None
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

def build_market_snapshot(data, prices, fear_data=None, macro=None, sentiment=None):
    """Tier A facts for the prompt: exposures, fear levels, prices, macro.

    Deliberately NO position P&L (disposition effect) and NO news.
    prices: dict ticker -> last price, as fetched by update.py.
    macro: optional live {symbol: {px, chg_1d_pct}} from update.fetch_macro().
    sentiment: optional {index: 0-100, label} crowding gauge (CNN-style
    Fear & Greed) - the 'don't buy the top' euphoria check.
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
    if sentiment:
        snapshot["sentiment_gauge"] = {
            "index": sentiment.get("index"), "label": sentiment.get("label"),
        }
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

def build_prompt(cfg, snapshot, deltas, theories=None, calibration=None,
                 last=None, user_bias=0):
    """Assemble the fixed-structure prompt from Tier A facts only.

    Engine v0.6.1: this is a CHANGE-DETECT pass. The previous verdict is
    embedded (last) plus the fact deltas since it, and the AI outputs ONLY
    changes - omission means agreement with the previous read (the engine
    merges silently). calibration: {ticker: {wrong, total, last_wrong}}
    outcome track record for conviction discounting.
    """
    active = [t for t in theories or []
              if t.get("status") in ("pending", "paused")]
    themes = [
        {
            "id": t.get("id"), "tier": t.get("tier"),
            "prediction": t.get("prediction", "")[:300],
        }
        for t in active
    ]
    prior = None
    if last and isinstance(last, dict):
        prior = {
            "date": last.get("date"),
            "macro_stance": last.get("macro_stance"),
            "sector_bias": [
                {"sector": s.get("sector"), "stance": s.get("stance"),
                 "conviction": s.get("conviction")}
                for s in last.get("sector_bias") or []
            ],
            "fears": [
                {"id": f.get("id"), "sentiment_score": f.get("sentiment_score")}
                for f in last.get("fears") or []
            ],
            "convictions": [
                {"ticker": c.get("ticker"), "conviction_score": c.get("conviction_score"),
                 "urgency": c.get("urgency")}
                for c in last.get("convictions") or []
            ],
            "summary": last.get("summary"),
        }
    calib = sorted(
        [{"ticker": k, "wrong": v.get("wrong", 0), "total": v.get("total", 0),
          "last_wrong": v.get("last_wrong")}
         for k, v in (calibration or {}).items() if v.get("wrong", 0) > 0],
        key=lambda x: -x["wrong"])
    rules = (
        "RULES\n"
        "0. BARBELL MANDATE: the book is a barbell - hyper-growth core "
        "(leveraged tech/semis/nuclear + A/B-tier convictions) with a "
        "hedge-stack insurance sleeve (ZROZ/FXY/VIXM/QFLR/GLD/GDX/BTAL/"
        "DBMF), no idle cash (dry powder parks in SGOV), deterministic "
        "TP/SL/vol-halt rules. Never chase euphoria: high sentiment alone "
        "is NOT a reason to add; the hedge stack exists to be USED when "
        "fears spike.\n"
        "1. Sector biases: rate EVERY sector in sector_exposures. conviction "
        "is a DIRECTIONAL score -1.0 to +1.0 (-1.0 = maximum bearishness, "
        "+1.0 = maximum bullishness); the sign IS the direction and the "
        "magnitude IS the strength, so a neutral view sits near 0.0 "
        "(e.g. -0.2 to +0.2 means 'no opinion worth acting on'). stance is "
        "only the rounded label of the sign (bullish if positive, bearish if "
        "negative, neutral if near zero) - never contradict it. Output ONLY "
        "sectors whose stance or conviction CHANGED vs YOUR PREVIOUS VERDICT "
        "- an omitted sector keeps its previous read (agreement needs no "
        "output).\n"
        "2. Fears: score EVERY fear in fear_levels where YOUR sentiment read "
        "differs from the deterministic level - omitted fears keep the "
        "deterministic level (you agree). Scores are 1.0 to 5.0 (5.0 = "
        "panic). Do not contradict a 4.9 level with a 2.0 sentiment score "
        "without a delta_reason.\n"
        "3. Theories: review EVERY theory in CURRENT THEORIES: affirm / "
        "weaken / probation / abandon, confidence integer 0-100. Prior "
        "verdicts and outcomes appear in the fact deltas - argue with the "
        "evidence, not the prior opinion.\n"
        "4. Convictions: rate ONLY tickers present in holdings. conviction_"
        "score is a float -1.0 (max trim) to +1.0 (max add); urgency and "
        "confidence are integers 0-100. Tickers needing no action are "
        "OMITTED - omission means hold (the engine assumes 0.0). Never "
        "invent tickers outside holdings.\n"
        "5. Rotations: a paired {sell, buy} conviction change (risk "
        "rotation between holdings - e.g. trim a crowded winner into a "
        "cheaper conviction). Both tickers MUST be in holdings; never "
        "list either rotation leg as a standalone conviction in the same "
        "run. The engine sizes both legs.\n"
        "6. Fear proposals/edits: propose NEW crash scenarios you think the "
        "book is unhedged for (name, type, rationale, watch_signals, "
        "hedge_ticks). The engine stages them PENDING HUMAN REVIEW - they "
        "are scored only after approval. fear_edits tune existing "
        "scenarios' name/hedge_ticks only.\n"
        "7. A ticker-level conviction overrides a sector stance wherever "
        "they conflict - conviction is the final word, sector bias is the "
        "macro-level view.\n"
        "8. Never output dollar amounts, share counts, or prices - you set "
        "conviction, urgency and confidence; the engine calculates sizing.\n"
        "9. summary: 2-4 sentences synthesizing stance, fear adjustments, "
        "theory verdicts, and execution priorities.\n"
    )
    if snapshot.get("sentiment_gauge"):
        g = snapshot["sentiment_gauge"]
        rules += ("\nSENTIMENT GAUGE (crowding check - 0 = extreme fear, "
                  "100 = extreme greed): index %s (%s). At index >= 75 "
                  "additions are CROWDED and need extra justification; at "
                  "index <= 25 panic dips may be opportunities, but the "
                  "barbell mandate always wins.\n" % (g.get("index"), g.get("label")))
    if calib:
        rules += ("\nCALIBRATION (your outcome track record - facts): you "
                  "were directionally WRONG on these tickers in recent "
                  "verdicts: %s. Confidence on a repeatedly-wrong ticker "
                  "starts DISCOUNTED - weigh evidence over ego; a fresh "
                  "correct run restores it.\n"
                  % json.dumps(calib))
    if user_bias:
        rules += ("\nUSER SENTIMENT BIAS (the human operator's lean - your "
                  "override on top of the CNN crowding gauge): %+d on a "
                  "-5..+5 scale (+ = the operator is bullish, - = bearish). "
                  "Tilt your macro_stance and conviction scores accordingly: "
                  "bias >= 2 leans risk_on with slightly more positive "
                  "convictions; bias <= -2 leans risk_off with trimmed "
                  "convictions. A bias skews - it never overrides hard "
                  "facts: do not flip a conviction against the evidence.\n"
                  % user_bias)
    body = (
        "You are the sentiment/conviction layer of a barbell portfolio engine.\n"
        "Answer with ONLY a single valid JSON object - no markdown fences, no "
        "prose before or after it. JSON comments are not allowed.\n\n"
        + rules
        + "\nMARKET STATE (Tier A facts, decision-grade)\n"
        + json.dumps(snapshot, indent=2)
        + (("\n\nYOUR PREVIOUS VERDICT (compare against it - output ONLY "
            "changes; omission means you still agree)\n"
            + json.dumps(prior, indent=2))
           if prior else "\n\n(No prior verdict on record - this is your first read.)")
        + (("\n\nWHAT HAPPENED SINCE YOUR LAST VERDICT (fact deltas)\n"
            + json.dumps(deltas, indent=2))
           if deltas else "")
        + ("\n\nCURRENT THEORIES (active only)\n" + json.dumps(themes, indent=2)
           if themes else "")
        + "\n\nSCHEMA (return exactly this shape)\n"
        + json.dumps({
            "date": "YYYY-MM-DD",
            "macro_stance": "risk_on|neutral|risk_off",
            "sector_bias": [{"sector": "...", "stance": "bullish|neutral|bearish",
                             "conviction": -0.2, "driver": "..."}],
            "theories": [{"id": "T17", "verdict": "affirm|weaken|probation|abandon",
                          "confidence": 80, "evidence": "..."}],
            "fears": [{"id": "F4", "sentiment_score": 3.0, "delta_reason": "..."}],
            "convictions": [{"ticker": "TQQQ", "conviction_score": 0.75,
                             "urgency": 60, "confidence": 70, "rationale": "..."}],
            "rotations": [{"sell": "SOXL", "buy": "NLR", "rationale": "..."}],
            "fear_proposals": [{"name": "...", "type": "structural|episodic",
                                "rationale": "...", "watch_signals": ["..."],
                                "hedge_ticks": ["GLD"]}],
            "fear_edits": [{"id": "F3", "name": "...", "hedge_ticks": ["..."],
                            "note": "..."}],
            "summary": "2-4 sentences",
        }, indent=2)
    )
    return body


# ---------------------------------------------------------------- API call

def _call_gemini(cfg, prompt):
    """POST the prompt to Gemini. Returns raw text or None (degraded).

    Issue #44: the key goes in the `x-goog-api-key` header, never in the
    URL query string (query strings leak into logs / proxies / referrers).
    """
    model = cfg.get("model") or "gemini-2.0-flash"
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        print("  WARN: ai_sentiment: no GEMINI_API_KEY env var - AI offline")
        return None
    url = GEMINI_URL.format(model=model)
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": int(cfg.get("max_output_chars", 4000)),
        },
    }).encode("utf-8")
    raw = _http_json(url, body, {"x-goog-api-key": key})
    try:
        parts = raw["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except Exception as exc:
        print(f"  WARN: ai_sentiment: gemini response shape unexpected: {exc}")
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
    raw = _http_json(DEEPSEEK_URL, body, {"Authorization": "Bearer " + key})
    try:
        return raw["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"  WARN: ai_sentiment: deepseek response shape unexpected: {exc}")
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
    raw = _http_json(ZEN_URL, body, {"Authorization": "Bearer " + key})
    try:
        return raw["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"  WARN: ai_sentiment: zen response shape unexpected: {exc}")
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
    raw = _http_json(OPENROUTER_URL, json.dumps(body).encode("utf-8"),
                     {"Authorization": "Bearer " + key}, timeout=120)
    try:
        return raw["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"  WARN: ai_sentiment: openrouter response shape unexpected: {exc}")
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
    """Pull the JSON object out of the model reply (strip fences/prose).

    Salvage pass (issue #45): if the strict parse fails, a brace/array-depth
    walk recovers truncated replies (auto-appends missing closers) and
    strips stray trailing prose instead of discarding the whole verdict.
    """
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
        pass

    # Salvage: walk the object, count depth, cut prose, rebalance closers.
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    cut = None
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                cut = i + 1
                break
    if cut is None:
        return None
    tail = text[start:cut]
    # Rebalance unclosed arrays/objects from the right.
    stack = []
    for ch in tail:
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            if (ch == "}" and stack[-1] == "{") or (ch == "]" and stack[-1] == "["):
                stack.pop()
    close = {"]": "[", "}": "{"}
    for ch in reversed(stack):
        tail += "]" if close[ch] == "[" else "}"
    try:
        return json.loads(tail)
    except Exception:
        return None


def _drop_unchanged(verdict, last):
    """Diff the verdict against the prior one (issue #42).

    A full-verdict echo (same convictions/theories/fears/rotations/
    sector_bias) is logged as a warning and degenerates into a no-op:
    no new orders, no sentiment_index drift. Partial deltas pass through.
    Returns the filtered verdict, or None when nothing changed at all.
    """
    if not last:
        return verdict
    sections = ("convictions", "theories", "fears", "rotations", "sector_bias")
    changed = False
    for key in sections:
        cur = verdict.get(key)
        prev = last.get(key)
        if not cur:
            continue
        if prev is None:
            changed = True
            continue
        try:
            cur_norm = json.dumps(cur, sort_keys=True)
            prev_norm = json.dumps(prev, sort_keys=True)
        except Exception:
            changed = True
            continue
        if cur_norm == prev_norm:
            print(f"  WARN: ai_sentiment: {key} unchanged vs prior verdict - dropping echo")
            del verdict[key]
        else:
            changed = True
    if not any(verdict.get(k) for k in sections):
        print("  WARN: ai_sentiment: full-verdict echo - degenerating to no-op")
        return None
    return verdict


def _clamp(v, lo, hi, default=0.0):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _validate_verdict(obj, allowed_fears=None):
    """Whitelist + clamp every field. Malformed = None (degraded).

    allowed_fears: valid fear ids (from the editable fear_scenarios.json
    table, e.g. F1-F9+). Defaults to the F1-F8 legacy set.
    """
    if not isinstance(obj, dict):
        return None
    fear_ids = set(allowed_fears) if allowed_fears else set(KNOWN_FEARS)
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
        if fid not in fear_ids:
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
    v["rotations"] = []
    for r in obj.get("rotations") or []:
        if not isinstance(r, dict):
            continue
        sell = str(r.get("sell") or "").strip().upper()
        buy = str(r.get("buy") or "").strip().upper()
        if not sell or not buy or sell == buy:
            continue
        v["rotations"].append({
            "sell": sell, "buy": buy,
            "rationale": str(r.get("rationale") or "")[:400],
        })
    v["fear_proposals"] = []
    for p in obj.get("fear_proposals") or []:
        if not isinstance(p, dict) or not str(p.get("name") or "").strip():
            continue
        v["fear_proposals"].append({
            "name": str(p["name"]).strip()[:80],
            "type": p.get("type") if p.get("type") in ("structural", "episodic") else "structural",
            "rationale": str(p.get("rationale") or "")[:400],
            "watch_signals": [str(s)[:80] for s in (p.get("watch_signals") or [])][:6],
            "hedge_ticks": [str(t).upper() for t in (p.get("hedge_ticks") or [])][:8],
        })
    v["fear_edits"] = []
    for e in obj.get("fear_edits") or []:
        if not isinstance(e, dict) or not str(e.get("id") or "").strip():
            continue
        v["fear_edits"].append({
            "id": str(e["id"]).strip().upper()[:8],
            "name": str(e.get("name") or "").strip()[:80] or None,
            "hedge_ticks": [str(t).upper() for t in (e.get("hedge_ticks") or [])][:8] or None,
            "note": str(e.get("note") or "")[:200] or None,
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
    conviction 0.0).

    Sizing (UI v0.5.4): amount = meta.ai.order_size x |conviction_score| -
    the conviction scales the dollar size (conv 0.65 -> $1,625 of a $2,500
    order_size); direction comes from the sign. The UI displays the
    port-weight impact from this amount; booking uses the same number.
    """
    whitelist = {p["ticker"] for p in data.get("positions") or []
                 if p.get("status") == "open"}
    size = float(((data.get("meta") or {}).get("ai") or {}).get("order_size", 2500))
    proposals = []
    for c in verdict.get("convictions") or []:
        if whitelist and c["ticker"] not in whitelist:
            print(f"  WARN: AI conviction for {c['ticker']} not in holdings - discarded")
            continue
        p = dict(c)
        p["amount"] = int(round(size * abs(float(p.get("conviction_score", 0)))))
        if p["conviction_score"] > 0:
            p["action"] = "add" if p["conviction_score"] >= 0.5 else "buy"
        else:
            p["action"] = "trim" if p["conviction_score"] <= -0.5 else "sell"
        proposals.append(p)
    return sorted(proposals, key=lambda x: -x["urgency"])


def sector_cap_blocked(ticker, amount, data, positions=None):
    """True if a BUY of `amount` of `ticker` would push its sector's
    EFFECTIVE exposure (market value x leverage) over the hard cap in
    meta.limits.sector_limits (issue #29). Sells are never blocked.

    Enforced at every buy path: execute_pending_orders (blocked buys stay
    pending until the sector drops under its cap), refresh_orders_from_ai
    (execute mode skips AI/rotation buy legs), and serve.py /book +
    /execute_all (human approval is rejected the same way). The projected
    exposure is measured against the CURRENT invested value, matching the
    basis the dashboard renders.
    """
    if not ticker or amount is None or amount <= 0:
        return False
    limits_cfg = ((data.get("meta") or {}).get("limits") or {})
    caps = {s["sector"]: s["max_pct"] for s in (limits_cfg.get("sector_limits") or [])}
    pex = limits_cfg.get("position_exposure") or {}
    if not caps or ticker not in pex:
        return False
    sector = pex[ticker]["sector"]
    lev = float(pex[ticker].get("leverage", 1.0))
    max_pct = caps.get(sector)
    if max_pct is None:
        return False
    positions = positions if positions is not None else (data.get("positions") or [])
    mv, eff = {}, {}
    for p in positions:
        if p.get("status") != "open":
            continue
        sec = pex.get(p["ticker"], {}).get("sector", "Other")
        lv = float(pex.get(p["ticker"], {}).get("leverage", 1.0))
        px = p.get("current_price") or p.get("buy_price") or 0.0
        m = px * p.get("shares", 0)
        mv[sec] = mv.get(sec, 0.0) + m
        eff[sec] = eff.get(sec, 0.0) + m * lv
    proj_eff = eff.get(sector, 0.0) + float(amount) * lev
    total_inv = sum(mv.values()) or 1.0
    blocked = (proj_eff / total_inv * 100.0) > max_pct
    if blocked:
        print(f"  WARN: sector cap - BUY {ticker} {amount:,.0f} would push "
              f"{sector} effective exposure over {max_pct:.0f}% - blocked")
    return blocked


def rotation_layer(verdict, data):
    """Rotations -> paired {sell, buy} proposals (engine sizes both legs).

    Engine v0.6.1: a rotation is a paired conviction change between two
    holdings. Both legs must be OPEN positions - anything else is dropped
    with a warning (the AI is told this, but validation never trusts it).
    """
    whitelist = {p["ticker"] for p in data.get("positions") or []
                 if p.get("status") == "open"}
    conviction_ticks = {c.get("ticker") for c in (verdict.get("convictions") or [])}
    out = []
    for r in verdict.get("rotations") or []:
        sell, buy = r.get("sell"), r.get("buy")
        if sell not in whitelist or buy not in whitelist:
            print(f"  WARN: AI rotation {sell}->{buy} outside holdings - discarded")
            continue
        # Issue #43: a leg that also appears as a conviction in the SAME
        # verdict is dropped - the conviction is the explicit sized read
        # and must win; booking both would double-queue the ticker.
        if sell in conviction_ticks or buy in conviction_ticks:
            print(f"  WARN: AI rotation {sell}->{buy} overlaps a conviction - "
                  f"conviction wins, rotation leg dropped")
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------- entry

def run(data, prices, fear_data=None, macro=None, sentiment=None,
        calibration=None):
    """Full layer run. Returns the validated verdict or None (degraded).

    Never raises. The caller (update.py, future wiring) decides whether
    to persist it into meta.ai_last_output + meta.ai_ledger.
    macro: optional live {symbol: {px, chg_1d_pct}} from update.fetch_macro().
    sentiment: optional {index, label} crowding gauge (CNN-style).
    calibration: optional {ticker: {wrong, total, last_wrong}} track record.
    """
    cfg = (data.get("meta") or {}).get("ai") or {}
    if not cfg.get("enabled"):
        return None
    snapshot = build_market_snapshot(data, prices, fear_data, macro, sentiment)
    last = (data.get("meta") or {}).get("ai_last_output")
    deltas = build_fact_deltas(last, snapshot)
    allowed_fears = set(KNOWN_FEARS)
    try:
        import fears as _fears_mod
        allowed_fears = {f["id"] for f in _fears_mod.load_scenarios()}
    except Exception:
        pass
    prompt = build_prompt(cfg, snapshot, deltas,
                          theories=data.get("theories"),
                          calibration=calibration, last=last,
                          user_bias=int(cfg.get("user_bias") or 0))
    raw = call_ai(cfg, prompt)
    obj = _extract_json(raw)
    verdict = _validate_verdict(obj, allowed_fears=allowed_fears)
    if not verdict:
        print("  WARN: ai_sentiment: verdict invalid/missing - AI offline")
        return None
    verdict = _drop_unchanged(verdict, last)
    if not verdict:
        return None
    verdict["prompt_hash"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    verdict["prices"] = snapshot["prices"]
    verdict["fear_levels"] = snapshot["fear_levels"]
    print(f"  AI SENTIMENT: {verdict['macro_stance']} | "
          f"{len(verdict['theories'])} theories | "
          f"{len(verdict['convictions'])} convictions | "
          f"{len(verdict['rotations'])} rotations")
    return verdict


if __name__ == "__main__":
    # Smoke test with no live data: prints what a degraded run looks like.
    print("ai_sentiment: module (algo 0.6.1.00) - providers: zen / deepseek / gemini")
    print("run(data, prices, fear_data, macro, sentiment, calibration) "
          "-> verdict dict or None (degraded)")
