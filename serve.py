"""
Local server for the stock-picker dashboard.

Why: the dashboard is a static page (index.html + dashboard.js), and the
browser can't run update.py by itself. This server:
  1. Serves the folder so you can open http://localhost:8000
  2. Provides POST /refresh -> runs update.py (fresh prices + news),
     then the page's Update button reloads the data.

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


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serves static files, plus POST /refresh -> runs update.py.

    The Update button in index.html POSTs to /refresh; the handler runs
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
        if self.path.rstrip("/") == "/refresh":
            self._refresh()
            return
        self.send_response(404)
        self.end_headers()

    def _refresh(self):
        """Run update.py and return {ok, output} as JSON."""
        try:
            out = subprocess.run(
                [sys.executable, "update.py"],
                cwd=BASE,
                capture_output=True,
                text=True,
                timeout=600,
            )
            body = json.dumps({"ok": out.returncode == 0,
                               "output": out.stdout or out.stderr}).encode("utf-8")
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("", PORT), Handler)
    print(f"Serving dashboard at http://localhost:{PORT}")
    print("Update button runs update.py via POST /refresh.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
