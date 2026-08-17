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
import http.server
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", 8000))
PORTFOLIO = os.path.join(BASE, "portfolio.json")


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serves static files, plus POST endpoints that run update.py.

    The Update button in dashboard.html POSTs to /refresh; the handler runs
    `python update.py` in this folder and returns its stdout as JSON so the
    page can log it before reloading. GET /refresh is also allowed for
    convenience (curl / browser address bar).
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE, **kwargs)

    def log_message(self, fmt, *args):  # quieter console
        pass

    def do_GET(self):
        if self.path.rstrip("/") == "/refresh":
            self._refresh()
            return
        super().do_GET()

    def do_POST(self):
        path = self.path.rstrip("/")
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
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            return {}

    def _json(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _run_update(self):
        """Run update.py; returns (ok, output_text)."""
        try:
            out = subprocess.run(
                [sys.executable, "update.py"],
                cwd=BASE, capture_output=True, text=True, timeout=600,
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
        mode = str(body.get("mode") or "").lower()
        if mode not in ("recommend", "execute"):
            self._json({"ok": False, "error": "mode must be recommend|execute"}, 400)
            return
        try:
            with open(PORTFOLIO, encoding="utf-8") as f:
                data = json.load(f)
            data["meta"].setdefault("ai", {})["mode"] = mode
            with open(PORTFOLIO, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
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
            with open(PORTFOLIO, encoding="utf-8") as f:
                data = json.load(f)
            meta = data["meta"]
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
            orders = data.setdefault("orders", [])
            orders[:] = [o for o in orders if o.get("status") != "pending"] + created
            with open(PORTFOLIO, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
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
            with open(PORTFOLIO, encoding="utf-8") as f:
                data = json.load(f)
            meta = data["meta"]
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
                created.append({
                    "ticker": p["ticker"], "action": action,
                    "amount": round(float(p.get("amount") or size), 2),
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
                created.append({
                    "ticker": r["buy"], "action": "buy", "amount": round(size, 2),
                    "status": "pending", "source": f"execute_all_{verdict['date']}",
                    "created": verdict["date"], "note": note,
                })
            if not created:
                raise ValueError("the current verdict has no proposals or rotations")
            orders = data.setdefault("orders", [])
            orders[:] = [o for o in orders if o.get("status") != "pending"] + created
            with open(PORTFOLIO, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 500)
            return
        ok, output = self._run_update()
        self._json({"ok": ok, "created": len(created), "output": output})

    def _set_bias(self):
        """POST /bias {value: -5..5} -> meta.ai.user_bias (sentiment slider)."""
        body = self._read_body()
        try:
            value = int(body.get("value"))
        except (TypeError, ValueError):
            self._json({"ok": False, "error": "value must be an integer -5..5"}, 400)
            return
        if not -5 <= value <= 5:
            self._json({"ok": False, "error": "value must be an integer -5..5"}, 400)
            return
        try:
            with open(PORTFOLIO, encoding="utf-8") as f:
                data = json.load(f)
            data["meta"].setdefault("ai", {})["user_bias"] = value
            with open(PORTFOLIO, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 500)
            return
        ok, output = self._run_update()
        self._json({"ok": ok, "value": value, "output": output})

    def _set_park(self):
        """POST /park {mode: "sgov"|"cash"} -> meta.park_mode (dry-powder
        toggle; "sgov" parks idle cash in SGOV, "cash" leaves it idle)."""
        body = self._read_body()
        mode = str(body.get("mode") or "").lower()
        if mode not in ("sgov", "cash"):
            self._json({"ok": False, "error": "mode must be 'sgov' or 'cash'"}, 400)
            return
        try:
            with open(PORTFOLIO, encoding="utf-8") as f:
                data = json.load(f)
            data["meta"]["park_mode"] = mode
            with open(PORTFOLIO, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 500)
            return
        ok, output = self._run_update()
        self._json({"ok": ok, "mode": mode, "output": output})


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("", PORT), Handler)
    print(f"Serving site at http://localhost:{PORT} (landing page)")
    print(f"Dashboard: http://localhost:{PORT}/dashboard.html")
    print("Update button runs update.py via POST /refresh.")
    print("Book buttons + sentiment slider run POST /book, /execute_all, /bias, /mode.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
