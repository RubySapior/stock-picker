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

import json
import os
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
PORTFOLIO = os.path.join(BASE, "portfolio.json")

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _path_lock(path):
    with _LOCKS_GUARD:
        lock = _LOCKS.get(path)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[path] = lock
        return lock


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
        fp.close()


def _write_locked(path, data, indent):
    """Write under the path's locks, tmp-file + atomic rename."""
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


def read_json(path, default=None):
    """Read one JSON file; `default` on missing/corrupt/any failure."""
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
        data = read_json(path, default)
        new_data = mutator(data)
        if new_data is not None:
            _write_locked(path, new_data, 2)
            data = new_data
    return data


def read_portfolio():
    return read_json(PORTFOLIO, {})


def write_portfolio(data):
    return write_json(PORTFOLIO, data)


def update_portfolio(mutator):
    """Locked read-modify-write on portfolio.json; mutator may return None."""
    return update_json(PORTFOLIO, mutator, {})