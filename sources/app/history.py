"""SQLite-backed ring buffer for rclone metric history.

Schema is intentionally narrow: one row per snapshot, key columns extracted
for fast aggregation; the full snapshot is preserved as JSON for replay.

Ring buffer enforces BOTH a time horizon (HISTORY_DAYS) and a hard byte cap
(HISTORY_MAX_BYTES) — protects against error-loop spam blowing up the DB.
"""
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

logger = logging.getLogger("rclone-dashboard.history")

HISTORY_DAYS = 7
HISTORY_MAX_BYTES = 500 * 1024 * 1024  # 500 MB hard cap
PRUNE_INTERVAL_SEC = 300  # check size every 5 minutes


class History:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._last_prune = 0.0
        self._init_schema()

    @contextmanager
    def _conn(self):
        # WAL mode = many readers + one writer, no readers blocked on writes
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS snapshots (
                    ts INTEGER PRIMARY KEY,
                    speed_bps REAL,
                    eta_s INTEGER,
                    errors INTEGER,
                    total_bytes INTEGER,
                    cache_used_bytes INTEGER,
                    cache_files INTEGER,
                    uploads_in_progress INTEGER,
                    uploads_queued INTEGER,
                    last_error TEXT,
                    payload TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(ts);
            """)

    def insert(self, snapshot: dict) -> None:
        stats = snapshot.get("stats") or {}
        vfs = (snapshot.get("vfs") or {}).get("diskCache") or {}
        payload = json.dumps(snapshot, separators=(",", ":"))
        row = (
            snapshot.get("ts"),
            stats.get("speed", 0.0),
            stats.get("eta", 0),
            stats.get("errors", 0),
            stats.get("totalBytes", 0),
            vfs.get("bytesUsed", 0),
            vfs.get("files", 0),
            vfs.get("uploadsInProgress", 0),
            vfs.get("uploadsQueued", 0),
            stats.get("lastError", "")[:512],
            payload,
        )
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO snapshots
                   (ts, speed_bps, eta_s, errors, total_bytes,
                    cache_used_bytes, cache_files, uploads_in_progress,
                    uploads_queued, last_error, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                row,
            )
            c.commit()
        self._maybe_prune()

    def _maybe_prune(self) -> None:
        now = time.time()
        if now - self._last_prune < PRUNE_INTERVAL_SEC:
            return
        self._last_prune = now
        self._prune()

    def _prune(self) -> None:
        cutoff_ts = int(time.time()) - HISTORY_DAYS * 86400
        try:
            db_size = os.path.getsize(self.db_path)
        except OSError:
            db_size = 0

        with self._lock, self._conn() as c:
            c.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff_ts,))
            if db_size > HISTORY_MAX_BYTES:
                cur = c.execute("SELECT COUNT(*) FROM snapshots")
                total = cur.fetchone()[0]
                excess = max(int(total * 0.10), 100)
                c.execute(
                    "DELETE FROM snapshots WHERE ts IN "
                    "(SELECT ts FROM snapshots ORDER BY ts ASC LIMIT ?)",
                    (excess,),
                )
                logger.warning(f"History DB exceeded cap ({db_size} > {HISTORY_MAX_BYTES}); pruned {excess} oldest rows")
            c.commit()
            # VACUUM must run OUTSIDE a transaction
            c.isolation_level = None
            c.execute("VACUUM")

    def recent(self, hours: int = 24) -> list[dict]:
        since = int(time.time()) - hours * 3600
        with self._conn() as c:
            cur = c.execute(
                """SELECT ts, speed_bps, errors, total_bytes,
                          cache_used_bytes, uploads_in_progress, uploads_queued
                   FROM snapshots WHERE ts >= ? ORDER BY ts ASC""",
                (since,),
            )
            return [
                {
                    "ts": r[0],
                    "speed_bps": r[1],
                    "errors": r[2],
                    "total_bytes": r[3],
                    "cache_used_bytes": r[4],
                    "uploads_in_progress": r[5],
                    "uploads_queued": r[6],
                }
                for r in cur.fetchall()
            ]
