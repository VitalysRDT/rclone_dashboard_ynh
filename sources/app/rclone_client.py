"""Thin httpx wrapper for the rclone Remote Control API.

Whitelist-only: we explicitly enumerate the read-only endpoints we consume.
Mutation endpoints (sync, operations, mount/unmount, vfs/forget, etc.) are
NOT exposed and never called from this client.
"""
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("rclone-dashboard.client")

ALLOWED_PATHS = {
    "core/stats",
    "core/transferred",
    "core/version",
    "core/memstats",
    "core/bwlimit",
    "vfs/stats",
    "vfs/list",
    "mount/listmounts",
    "options/get",
    "job/list",
    "rc/noop",
}


class RcloneClient:
    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def call(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if path not in ALLOWED_PATHS:
            raise ValueError(f"rclone RC path not in whitelist: {path}")
        url = f"{self.base_url}/{path}"
        try:
            r = self._client.post(url, json=params or {})
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            logger.warning(f"rclone RC call {path} failed: {e}")
            return None
        except ValueError as e:
            logger.error(f"rclone RC bad JSON for {path}: {e}")
            return None

    def health(self) -> bool:
        return self.call("rc/noop") is not None

    def snapshot(self) -> dict[str, Any]:
        """One combined snapshot used by the polling endpoint and history worker."""
        ts = int(time.time())
        stats = self.call("core/stats") or {}
        vfs = self.call("vfs/stats") or {}
        bw = self.call("core/bwlimit") or {}
        jobs = self.call("job/list") or {}
        return {
            "ts": ts,
            "stats": stats,
            "vfs": vfs,
            "bwlimit": bw,
            "jobs": jobs,
        }

    def close(self) -> None:
        self._client.close()
