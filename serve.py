"""
Local server for the stock-picker dashboard.

Why: the site is a static pair of pages (index.html landing + dashboard.html
+ dashboard.js), and the
browser can't run update.py by itself. This server:
  1. Serves the folder so you can open http://localhost:8000
  2. Provides POST /refresh -> runs update.py (fresh prices + news),
     then the page's Update button reloads the data.
  3. POST /mode -> toggles meta.ai.mode (recommend | execute) - how the
     AI verdict turns into orders.
4. POST /mode -> toggles meta.ai.mode (recommend | execute) - how the
      AI verdict turns into orders.
   5. POST /book -> human approval per proposal / rotation: the dashboard's
      "Submit this Order" buttons write ONE pending market order (or a
      rotation's two legs) from the latest AI verdict into portfolio.json
      (recommend mode). {ticker, action} or {sell, buy}. Amounts are
      conviction-scaled (order_size x |conviction|).
   6. POST /execute_all -> "Submit all Orders": the whole queue at once.
   7. POST /bias -> sets meta.ai.user_bias (-5..+5 sentiment slider).
   8. POST /park -> sets meta.park_mode ("sgov"|"cash" dry-powder toggle).

Usage:  python serve.py
Then open http://localhost:8000 in your browser.
"""
import collections
import http.server
import json
import os
import socket
import subprocess
import sys
import threading

import store

BASE = os.path.dirname(os.path.abspath(__file__))
try:
    PORT = int(os.environ.get("PORT", "8000"))
except ValueError:
    print(f"WARN: invalid PORT={os.environ.get('PORT')!r} - falling back to 8000")
    PORT = 8000

# Per-resource single-flight guard for the update.py subprocess (issue #35
# + hosting for thousands): the old global _UPDATE_LOCK blocked *all* users
# while one user's 10-minute updater ran (409 storm). Now each portfolio
# path (global or users/<id>/portfolio.json) gets its own lock, bounded LRU
# so 1000s of users don't leak locks. Same endpoint on the same portfolio
# still gets 409; different users run concurrently.
_UPDATE_LOCKS = collections.OrderedDict()
_UPDATE_LOCKS_GUARD = threading.Lock()
MAX_UPDATE_LOCKS = int(os.environ.get("SERVE_MAX_LOCKS", "2048"))


def _update_lock(key):
    norm = os.path.abspath(key) if key else "__global__"
    with _UPDATE_LOCKS_GUARD:
        lk = _UPDATE_LOCKS.get(norm)
        if lk is not None:
            _UPDATE_LOCKS.move_to_end(norm)
            return lk
        lk = threading.Lock()
        _UPDATE_LOCKS[norm] = lk
        while len(_UPDATE_LOCKS) > MAX_UPDATE_LOCKS:
            _UPDATE_LOCKS.popitem(last=False)
        return lk


def _portfolio_key(handler):
    """Absolute portfolio path for this request's user (header X-User-Id or ?user=)."""
    try:
        return store.portfolio_path_for_request(handler)
    except Exception:
        return store.PORTFOLIO


def _user_id_for(handler):
    """Return sanitized user_id or None for global singleton."""
    p = _portfolio_key(handler)
    # If it equals global, no user
    if os.path.abspath(p) == os.path.abspath(store.PORTFOLIO):
        return None
    # Extract user id from p = .../users/<id>/portfolio.json
    try:
        parts = os.path.normpath(p).split(os.sep)
        if "users" in parts:
            idx = parts.index("users")
            if idx + 1 < len(parts):
                return parts[idx + 1]
    except Exception:
        pass
    return None


def _set_meta(data, keys, value):
    """Mutator for store.update_portfolio: set meta.<keys...> = value."""
    meta = data.setdefault("meta", {})
    target = meta
    for k in keys[:-1]:
        target = target.setdefault(k, {})
    target[keys[-1]] = value
    return data


def _append_orders(data, created):
    """Mutator for store.update_portfolio: keep executed history, replace
    the pending queue with the newly approved orders."""
    orders = data.setdefault("orders", [])
    orders[:] = [o for o in orders if o.get("status") != "pending"] + created
    return data


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serves static files, plus POST endpoints that run update.py.

    The Update button in dashboard.html POSTs to /refresh; the handler runs
    `python update.py` in this folder and returns its stdout as JSON so the
    page can log it before reloading. GET /refresh is also allowed for
    convenience (curl / browser address bar).
    """
    timeout = 60  # socket timeout per request (issue #56: stalled client)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE, **kwargs)

    def log_message(self, fmt, *args):  # quieter console
        pass

    def _guard(self, fn, key=None):
        """Run one endpoint under the per-resource single-flight lock; 409 while an
        update.py subprocess for the *same portfolio* is in flight (issue #35, now
        per-user for hosting)."""
        if key is None:
            key = _portfolio_key(self)
        lk = _update_lock(key)
        if not lk.acquire(blocking=False):
            self._json({"ok": False, "error": "update already running"}, 409)
            return
        try:
            fn()
        finally:
            lk.release()

    def do_GET(self):
        if self.path.rstrip("/").split("?")[0] == "/refresh":
            self._guard(self._refresh)
            return
        super().do_GET()

    def do_POST(self):
        self._guard(self._dispatch_post)

    def _dispatch_post(self):
        # Strip query string for routing, but keep user in key
        path = self.path.split("?")[0].rstrip("/")
        if path == "/refresh":
            self._refresh()
            return
        if path == "/mode":
            self._set_mode()
            return
        if path == "/book":
            self._book()
            return
        if path == "/execute_all":
            self._execute_all()
            return
        if path == "/bias":
            self._set_bias()
            return
        if path == "/park":
            self._set_park()
            return
        self.send_response(404)
        self.end_headers()

    def _read_body(self):
        """POST body as dict. Issue #56 hardening:

        - bad/non-numeric Content-Length -> 400 (was a crash via int())
        - bodies over 64KB -> 413 (a 600MB flood can no longer stall the
          server reading it)
        - a stalled/slow sender -> 400 after 60s (socket timeout, no hang)
        - malformed JSON -> 400 (was a silent {})
        """
        raw_len = self.headers.get("Content-Length") or "0"
        try:
            length = int(raw_len)
        except ValueError:
            self._json({"ok": False, "error": "invalid Content-Length"}, 400)
            return None
        if length < 0:
            self._json({"ok": False, "error": "negative Content-Length"}, 400)
            return None
        if length > 65536:
            self._json({"ok": False, "error": "body too large (max 64KB)"}, 413)
            return None
        if length == 0:
            return {}
        try:
            self.connection.settimeout(60)
        except Exception:
            pass
        try:
            body = self.rfile.read(length)
        except socket.timeout:
            self._json({"ok": False, "error": "body read timed out"}, 400)
            return None
        except Exception as exc:
            self._json({"ok": False, "error": f"body read failed: {exc}"}, 400)
            return None
        try:
            parsed = json.loads(body.decode("utf-8") or "{}")
            if not isinstance(parsed, dict):
                raise ValueError("not a JSON object")
            return parsed
        except Exception:
            self._json({"ok": False, "error": "malformed JSON body"}, 400)
            return None

    def _json(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _run_update(self):
        """Run update.py; returns (ok, output_text). Per-user if X-User-Id header present."""
        user_id = _user_id_for(self)
        try:
            cmd = [sys.executable, "update.py"]
            if user_id:
                cmd += ["--user", user_id]
            env = os.environ.copy()
            # Propagate DATA_DIR so update.py resolves same per-user path
            if "DATA_DIR" in os.environ:
                env["DATA_DIR"] = os.environ["DATA_DIR"]
            out = subprocess.run(
                cmd,
                cwd=BASE, capture_output=True, text=True, timeout=600, env=env,
            )
            return out.returncode == 0, out.stdout or out.stderr
        except Exception as exc:
            return False, str(exc)

    def _refresh(self):
        """Run update.py and return {ok, output} as JSON."""
        ok, output = self._run_update()
        self._json({"ok": ok, "output": output})

    def _set_mode(self):
        """POST /mode {mode: 'recommend'|'execute'} -> meta.ai.mode."""
        body = self._read_body()
        if body is None:
            return
        mode = str(body.get("mode") or "").lower()
        if mode not in ("recommend", "execute"):
            self._json({"ok": False, "error": "mode must be recommend|execute"}, 400)
            return
        user_id = _user_id_for(self)
        try:
            store.update_portfolio(lambda data: _set_meta(data, ["ai", "mode"], mode), user_id=user_id)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 500)
            return
        ok, output = self._run_update()
        self._json({"ok": ok, "mode": mode, "output": output})

    def _book(self):
        """POST /book -> ONE human-approved order from the latest verdict.

        Body: {ticker, action: 'buy'|'sell'} for a proposal, or
        {sell, buy} for a rotation's two legs. The order must exist in
        the current AI verdict (ai_last_output) - the human approval gate
        is the dashboard button, the check here is that the AI actually
        proposed it. Written as a pending order at meta.ai.order_size
        (source 'book_<date>'), then update.py runs so the page reflects
        the new pending queue.
        """
        try:
            import ai_sentiment
            body = self._read_body()
            if body is None:
                return
            user_id = _user_id_for(self)
            data = store.read_portfolio(user_id=user_id)
            meta = data.get("meta") or {}
            cfg = meta.get("ai") or {}
            if not cfg.get("enabled"):
                raise ValueError("AI layer is disabled")
            verdict = meta.get("ai_last_output")
            if not verdict:
                raise ValueError("no AI verdict on record - run Update first")
            size = float(cfg.get("order_size", 2500))
            created = []

            def note_for(tk, action, pnl=None):
                return (pnl or f"{action.upper()} {tk}")[:160]

            proposals = ai_sentiment.bullish_layer(verdict, data)
            rotations = ai_sentiment.rotation_layer(verdict, data)

            if body.get("ticker"):
                ticker = str(body["ticker"]).upper()
                action = str(body.get("action") or "").lower()
                if action not in ("buy", "sell"):
                    raise ValueError("action must be buy|sell")
                p = next((x for x in proposals
                          if x["ticker"] == ticker
                          and ((x["conviction_score"] > 0) == (action == "buy"))), None)
                if not p:
                    raise ValueError(f"'{ticker} {action}' is not in the current AI verdict")
                if action == "buy" and ai_sentiment.sector_cap_blocked(
                        ticker, round(float(p.get("amount") or size), 2), data):
                    raise ValueError(f"BUY {ticker} breaches a sector cap - "
                                     f"human approval is capped the same way")
                created.append({
                    "ticker": ticker, "action": action,
                    "amount": round(float(p.get("amount") or size), 2), "status": "pending",
                    "source": f"book_{verdict['date']}",
                    "created": verdict["date"],
                    "note": note_for(ticker, action, p.get("rationale")),
                })
            elif body.get("sell") and body.get("buy"):
                sell = str(body["sell"]).upper()
                buy = str(body["buy"]).upper()
                r = next((x for x in rotations
                          if x["sell"] == sell and x["buy"] == buy), None)
                if not r:
                    raise ValueError(f"rotation {sell}->{buy} is not in the current AI verdict")
                if ai_sentiment.sector_cap_blocked(buy, round(size, 2), data):
                    raise ValueError(f"rotation {sell}->{buy} buy leg breaches a "
                                     f"sector cap - human approval is capped the same way")
                note = f"rotation {sell}->{buy}: {(r.get('rationale') or '')[:120]}"
                created.append({
                    "ticker": sell, "action": "sell", "amount": round(size, 2),
                    "status": "pending", "source": f"book_{verdict['date']}",
                    "created": verdict["date"], "note": note,
                })
                created.append({
                    "ticker": buy, "action": "buy", "amount": round(size, 2),
                    "status": "pending", "source": f"book_{verdict['date']}",
                    "created": verdict["date"], "note": note,
                })
            else:
                raise ValueError("send {ticker, action} or {sell, buy}")
            if not created:
                raise ValueError("nothing to book")
            store.update_portfolio(lambda d: _append_orders(d, created), user_id=user_id)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 500)
            return
        ok, output = self._run_update()
        self._json({"ok": ok, "created": len(created), "output": output})

    def _execute_all(self):
        """POST /execute_all -> ALL of the latest verdict's proposals +
        rotations become pending orders (the "Submit all Orders" button).

        Recommend-mode human approval for the whole queue at once. Amounts
        are conviction-scaled (order_size x |conviction| from
        bullish_layer); rotation legs use the flat order_size.
        """
        try:
            import ai_sentiment
            user_id = _user_id_for(self)
            data = store.read_portfolio(user_id=user_id)
            meta = data.get("meta") or {}
            cfg = meta.get("ai") or {}
            if not cfg.get("enabled"):
                raise ValueError("AI layer is disabled")
            verdict = meta.get("ai_last_output")
            if not verdict:
                raise ValueError("no AI verdict on record - run Update first")
            size = float(cfg.get("order_size", 2500))
            created = []
            for p in ai_sentiment.bullish_layer(verdict, data):
                action = "buy" if p["conviction_score"] > 0 else "sell"
                amt = round(float(p.get("amount") or size), 2)
                if action == "buy" and ai_sentiment.sector_cap_blocked(p["ticker"], amt, data):
                    continue
                created.append({
                    "ticker": p["ticker"], "action": action,
                    "amount": amt,
                    "status": "pending",
                    "source": f"execute_all_{verdict['date']}",
                    "created": verdict["date"],
                    "note": (p.get("rationale") or "")[:160],
                })
            for r in ai_sentiment.rotation_layer(verdict, data):
                note = f"rotation {r['sell']}->{r['buy']}: {(r.get('rationale') or '')[:120]}"
                created.append({
                    "ticker": r["sell"], "action": "sell", "amount": round(size, 2),
                    "status": "pending", "source": f"execute_all_{verdict['date']}",
                    "created": verdict["date"], "note": note,
                })
                if not ai_sentiment.sector_cap_blocked(r["buy"], round(size, 2), data):
                    created.append({
                        "ticker": r["buy"], "action": "buy", "amount": round(size, 2),
                        "status": "pending", "source": f"execute_all_{verdict['date']}",
                        "created": verdict["date"], "note": note,
                    })
            if not created:
                raise ValueError("the current verdict has no proposals or rotations")
            store.update_portfolio(lambda d: _append_orders(d, created), user_id=user_id)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 500)
            return
        ok, output = self._run_update()
        self._json({"ok": ok, "created": len(created), "output": output})

    def _set_bias(self):
        """POST /bias {value: -5..5} -> meta.ai.user_bias (sentiment slider)."""
        body = self._read_body()
        if body is None:
            return
        try:
            value = int(body.get("value"))
        except (TypeError, ValueError):
            self._json({"ok": False, "error": "value must be an integer -5..5"}, 400)
            return
        if not -5 <= value <= 5:
            self._json({"ok": False, "error": "value must be an integer -5..5"}, 400)
            return
        user_id = _user_id_for(self)
        try:
            store.update_portfolio(lambda data: _set_meta(data, ["ai", "user_bias"], value), user_id=user_id)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 500)
            return
        ok, output = self._run_update()
        self._json({"ok": ok, "value": value, "output": output})

    def _set_park(self):
        """POST /park {mode: "sgov"|"cash"} -> meta.park_mode (dry-powder
        toggle; "sgov" parks idle cash in SGOV, "cash" leaves it idle)."""
        body = self._read_body()
        if body is None:
            return
        mode = str(body.get("mode") or "").lower()
        if mode not in ("sgov", "cash"):
            self._json({"ok": False, "error": "mode must be 'sgov' or 'cash'"}, 400)
            return
        user_id = _user_id_for(self)
        try:
            store.update_portfolio(lambda data: _set_meta(data, ["park_mode"], mode), user_id=user_id)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 500)
            return
        ok, output = self._run_update()
        self._json({"ok": ok, "mode": mode, "output": output})


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("", PORT), Handler)
    server.daemon_threads = True  # issue #56: Ctrl+C exits even with stalled requests
    print(f"Serving site at http://localhost:{PORT} (landing page)")
    print(f"Dashboard: http://localhost:{PORT}/dashboard.html")
    print("Update button runs update.py via POST /refresh.")
    print("Book buttons + sentiment slider run POST /book, /execute_all, /bias, /mode.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
