"""store.py - locked JSON persistence (site 0.5.5.44).

Single write-path for the JSON files the site mutates (portfolio.json today;
community/ + per-user stores when the NAS backend lands). serve.py's
ThreadingHTTPServer can hit /book, /mode, /bias, /park concurrently - every
read-modify-write goes through update_json() so two requests can never
interleave (one read, then the other's read+write in between -> lost update).

Threading locks cover same-process concurrency (the serve.py thread pool). A
best-effort cross-process file lock (msvcrt on Windows, fcntl on POSIX) covers
the serve.py <-> update.py subprocess case; platforms with neither degrade to
thread-only locking. Writes are tmp-file + atomic rename so a crash never
leaves a half-written JSON.

Full transactional semantics (proper DB, per-user stores) arrive with the NAS
hosting step (api.py + SQLite) - see CHANGELOG roadmap, step 2.
"""

import collections
import json
import os
import re
import threading

try:
    import msvcrt  # Windows
except ImportError:
    msvcrt = None
try:
    import fcntl  # POSIX
except ImportError:
    fcntl = None

BASE = os.path.dirname(os.path.abspath(__file__))
# DATA_DIR allows hosting for thousands: when set (e.g. /data), all mutable
# JSON lives under DATA_DIR instead of the code folder. Supports folder moves
# without breaking BASE-relative assumptions. Falls back to BASE for
# single-tenant / file:// double-click mode.
DATA_ROOT = os.environ.get("DATA_DIR") or os.environ.get("STOCKPICKER_DATA") or BASE
DATA_ROOT = os.path.abspath(DATA_ROOT)
PORTFOLIO = os.path.join(DATA_ROOT, "portfolio.json")
USERS_ROOT = os.path.join(DATA_ROOT, "users")

# Bounded LRU for per-path threading locks — hosting 1000s of users means
# 1000s of per-user JSON files; an unbounded dict would leak locks for every
# distinct path ever touched. LRU caps memory while keeping hot paths locked.
MAX_LOCKS = int(os.environ.get("STORE_MAX_LOCKS", "2048"))
_LOCKS = collections.OrderedDict()
_LOCKS_GUARD = threading.Lock()


def _path_lock(path):
    # Normalized absolute path as key so "./portfolio.json" and
    # "/abs/portfolio.json" don't create two locks for the same file.
    norm = os.path.abspath(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(norm)
        if lock is not None:
            # LRU touch
            _LOCKS.move_to_end(norm)
            return lock
        lock = threading.Lock()
        _LOCKS[norm] = lock
        # Evict oldest if over capacity
        while len(_LOCKS) > MAX_LOCKS:
            _LOCKS.popitem(last=False)
        return lock


def _sanitize_user_id(uid):
    """Filesystem-safe user id (a-z,0-9,_,-); host must validate auth separately."""
    s = re.sub(r"[^a-zA-Z0-9._-]", "_", str(uid or "").strip())
    s = s.strip("._")[:64]
    return s or "default"


def user_portfolio_path(user_id=None):
    """Per-user portfolio path; None/empty -> global singleton (backwards compat)."""
    if not user_id:
        return PORTFOLIO
    safe = _sanitize_user_id(user_id)
    return os.path.join(USERS_ROOT, safe, "portfolio.json")


def portfolio_path_for_request(handler=None, user_id=None):
    """Resolve portfolio path from an HTTP handler or explicit user_id.

    Checks in order: explicit arg > X-User-Id header > ?user= query param >
    portfolio.json singleton. Always returns an absolute path.
    """
    if user_id:
        return user_portfolio_path(user_id)
    if handler is not None:
        # Header wins (hosted API), query param fallback for file:// compat
        hid = None
        try:
            hid = handler.headers.get("X-User-Id") or handler.headers.get("X-User-ID")
        except Exception:
            hid = None
        if hid:
            return user_portfolio_path(hid)
        try:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(handler.path).query)
            quser = (qs.get("user") or qs.get("user_id") or [None])[0]
            if quser:
                return user_portfolio_path(quser)
        except Exception:
            pass
    return PORTFOLIO


def ensure_user_dir(user_id):
    """Ensure users/<id>/ dir exists; no-op for global."""
    if not user_id:
        return DATA_ROOT
    safe = _sanitize_user_id(user_id)
    d = os.path.join(USERS_ROOT, safe)
    os.makedirs(d, exist_ok=True)
    return d


class _CrossProcessLock:
    """Best-effort exclusive lock on a sibling .lock file; no-op if unsupported."""

    def __init__(self, path):
        self._path = path + ".lock"
        self._fp = None

    def __enter__(self):
        try:
            self._fp = open(self._path, "a+")
            if msvcrt:
                self._fp.seek(0)
                msvcrt.locking(self._fp.fileno(), msvcrt.LK_LOCK, 1)
            elif fcntl:
                fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX)
        except Exception:
            self._fp = None
        return self

    def __exit__(self, *exc):
        fp, self._fp = self._fp, None
        if fp is None:
            return
        try:
            if msvcrt:
                fp.seek(0)
                msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
            elif fcntl:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            fp.close()
        except Exception:
            pass


def _write_locked(path, data, indent):
    """Write under the path's locks, tmp-file + atomic rename."""
    # Ensure parent dir exists (supports users/<id>/ sharding after folder moves)
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
    try:
        os.replace(tmp, path)
    except OSError:
        # Rename can fail if another process holds the destination open
        # (e.g. an antivirus scan) - fall back to a direct write.
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        try:
            os.remove(tmp)
        except OSError:
            pass


def write_text_atomic(path, text):
    """Locked atomic write of a raw text file (tmp-file + rename).

    Used for generated assets like dashboard.js and ohlc_cache.json
    (issue #48): a kill mid-write (e.g. serve.py's subprocess timeout)
    can no longer leave a half-written dashboard.js (blank page) or a
    corrupt OHLC cache (indicator degradation).
    """
    with _path_lock(path), _CrossProcessLock(path):
        parent = os.path.dirname(os.path.abspath(path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            os.replace(tmp, path)
        except OSError:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            try:
                os.remove(tmp)
            except OSError:
                pass
    return text


def read_json(path, default=None):
    """Read one JSON file; `default` on missing/corrupt/any failure.

    Note: unlocked read is fast and safe for atomic-rename writers (POSIX
    atomic replace guarantees old-or-new, not torn). For RMW or torn-write
    fallback safety, use read_json_locked() or update_json().
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def read_json_locked(path, default=None):
    """Locked read (thread + cross-process) — use when you need a
    consistent snapshot that won't race with a concurrent write's
    direct-write fallback. Slightly higher contention but safe for
    hosting 1000s of concurrent readers/writers."""
    with _path_lock(path), _CrossProcessLock(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default


def write_json(path, data, indent=2):
    """Locked write of one JSON file; returns the written data."""
    with _path_lock(path), _CrossProcessLock(path):
        _write_locked(path, data, indent)
    return data


def update_json(path, mutator, default=None):
    """Locked read-modify-write: mutator(data) -> new data; None skips the
    write. Returns the (possibly mutated) data under lock."""
    with _path_lock(path), _CrossProcessLock(path):
        # Direct read under lock to avoid double-lock nesting via read_json()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = default
        new_data = mutator(data)
        if new_data is not None:
            _write_locked(path, new_data, 2)
            data = new_data
    return data


def read_portfolio(user_id=None):
    return read_json(user_portfolio_path(user_id), {})


def read_portfolio_locked(user_id=None):
    return read_json_locked(user_portfolio_path(user_id), {})


def write_portfolio(data, user_id=None):
    return write_json(user_portfolio_path(user_id), data)


def update_portfolio(mutator, user_id=None):
    """Locked read-modify-write on portfolio.json; mutator may return None."""
    return update_json(user_portfolio_path(user_id), mutator, {})
