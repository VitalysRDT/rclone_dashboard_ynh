"""Flask app for rclone Dashboard.

Routes:
  /                   - HTML shell (HTMX-driven)
  /api/snapshot       - JSON: latest snapshot (polled by HTMX every poll_interval)
  /api/history.json   - JSON: rolling 24h chart series
  /api/health         - JSON: rclone reachability + version

Auth: trusts Remote-User header ONLY from local nginx (config.TRUSTED_PROXY).
"""
import logging
import os

from flask import Flask, jsonify, render_template, request

from .history import History
from .rclone_client import RcloneClient
from .snapshot_worker import SnapshotWorker

logger = logging.getLogger("rclone-dashboard")


def _humanize_bytes(n: int | float | None) -> str:
    if not n:
        return "0 B"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} EB"


def _humanize_duration(seconds: int | float | None) -> str:
    if not seconds or seconds <= 0:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    h, rem = divmod(s, 3600)
    return f"{h}h {rem // 60}m"


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_url_path="/static",
        static_folder="static",
        template_folder="templates",
    )

    rclone_url = os.environ.get("RCLONE_RC_URL", "http://127.0.0.1:5572")
    poll_interval_ms = int(os.environ.get("POLL_INTERVAL_MS", "2000"))
    db_path = os.environ.get("DASHBOARD_DB_PATH", "/var/lib/rclone-dashboard/dashboard.sqlite")
    base_path = os.environ.get("BASE_PATH", "").rstrip("/")

    app.config["BASE_PATH"] = base_path
    app.config["POLL_INTERVAL_MS"] = poll_interval_ms
    app.config["RCLONE_URL"] = rclone_url

    client = RcloneClient(rclone_url)
    history = History(db_path)
    worker = SnapshotWorker(client, history, poll_interval_ms)
    worker.start()
    app.config["WORKER"] = worker
    app.config["HISTORY"] = history
    app.config["CLIENT"] = client

    app.jinja_env.filters["humanbytes"] = _humanize_bytes
    app.jinja_env.filters["humanduration"] = _humanize_duration

    @app.route("/")
    def index():
        user = request.headers.get("Remote-User", "anonymous")
        return render_template(
            "index.html",
            user=user,
            poll_interval_ms=poll_interval_ms,
            base_path=base_path,
            rclone_url=rclone_url,
        )

    @app.route("/api/snapshot")
    def api_snapshot():
        snap = worker.latest
        if snap is None:
            return jsonify({"error": "no snapshot yet"}), 503
        return jsonify(snap)

    @app.route("/api/history.json")
    def api_history():
        hours = int(request.args.get("hours", "24"))
        hours = max(1, min(168, hours))  # clamp 1h..7d
        return jsonify({"hours": hours, "points": history.recent(hours)})

    @app.route("/api/health")
    def api_health():
        version_info = client.call("core/version") or {}
        return jsonify({
            "rclone_reachable": client.health(),
            "rclone_version": version_info.get("version"),
            "rclone_os": version_info.get("osVersion"),
            "dashboard_version": "0.1.0",
        })

    @app.route("/fragments/overview")
    def fragment_overview():
        """HTMX partial — overview cards refreshed by frontend polling."""
        snap = worker.latest or {}
        return render_template("fragments/overview.html", snap=snap)

    @app.route("/fragments/transfers")
    def fragment_transfers():
        snap = worker.latest or {}
        transferring = ((snap.get("stats") or {}).get("transferring")) or []
        return render_template("fragments/transfers.html", transferring=transferring)

    @app.route("/fragments/cache")
    def fragment_cache():
        snap = worker.latest or {}
        vfs = snap.get("vfs") or {}
        return render_template("fragments/cache.html", vfs=vfs)

    @app.teardown_appcontext
    def _shutdown(exc=None):
        pass

    return app


app = create_app()
