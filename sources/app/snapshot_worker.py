"""Background thread that polls rclone RC and writes batched history to SQLite.

Batches writes every BATCH_INTERVAL_SEC to avoid SD-card write amplification.
"""
import logging
import threading
import time

logger = logging.getLogger("rclone-dashboard.worker")

BATCH_INTERVAL_SEC = 2.5  # write batch flush cadence


class SnapshotWorker(threading.Thread):
    def __init__(self, rclone_client, history, poll_interval_ms: int) -> None:
        super().__init__(daemon=True, name="snapshot-worker")
        self.client = rclone_client
        self.history = history
        self.poll_interval_s = max(0.5, poll_interval_ms / 1000.0)
        self.latest: dict | None = None
        self._stop = threading.Event()
        self._pending: list[dict] = []
        self._last_flush = time.monotonic()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        logger.info(f"Snapshot worker started, polling every {self.poll_interval_s}s")
        while not self._stop.is_set():
            try:
                snap = self.client.snapshot()
                self.latest = snap
                self._pending.append(snap)
                if time.monotonic() - self._last_flush >= BATCH_INTERVAL_SEC:
                    self._flush()
            except Exception as e:
                logger.error(f"Snapshot poll failed: {e}", exc_info=True)
            self._stop.wait(self.poll_interval_s)
        self._flush()
        logger.info("Snapshot worker stopped")

    def _flush(self) -> None:
        if not self._pending:
            return
        # keep only the latest snapshot per second
        seen = set()
        unique = []
        for s in reversed(self._pending):
            if s["ts"] not in seen:
                seen.add(s["ts"])
                unique.append(s)
        for s in reversed(unique):
            try:
                self.history.insert(s)
            except Exception as e:
                logger.error(f"History insert failed: {e}")
        self._pending.clear()
        self._last_flush = time.monotonic()
