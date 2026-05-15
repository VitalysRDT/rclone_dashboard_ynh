# rclone Dashboard for YunoHost

A polished, real-time web dashboard for monitoring your rclone mount. Packaged
as a YunoHost custom app — install in one command.

## What you see

- **Overview**: live throughput, active transfer count, VFS cache gauge, mount metadata
- **Transfers**: per-file progress with speed + ETA + multi-thread chunks
- **Cache**: disk + metadata cache details, cache-mode, write-back, dir-cache TTL
- **Health**: rclone version, error rate, retry state, bandwidth limit, dashboard internals
- **History chart**: rolling 1h / 6h / 24h / 7d throughput + cache size

## Stack (chosen via multi-AI Double Diamond)

- **Backend**: Flask + gunicorn (gthread, 2 workers × 4 threads), httpx async client for rclone RC, SQLite WAL ring buffer
- **Frontend**: HTMX + Alpine.js + Tailwind CSS + daisyUI + Chart.js
- **Auth**: YunoHost SSO via `auth_header=true` (zero-config, no login screen)
- **Refresh**: 2 s polling (sub-second freshness not required for monitoring)
- **Retention**: 7-day ring buffer, hard 500 MB cap, WAL mode + batched writes
- **Theme**: auto-detect (prefers-color-scheme) + persisted override

## Install

When this is published to a git repo with a tagged release:

```bash
yunohost app install https://github.com/vitalys/rclone-dashboard
```

The installer will prompt for:
- Domain + path (default `/rclone`)
- rclone RC URL (default `http://127.0.0.1:5572`)
- Poll interval (default 2000 ms)
- Access permission (default: admins only)

## Requirements

- YunoHost ≥ 12.0
- rclone daemon already running with `--rc --rc-addr 127.0.0.1:5572 --rc-no-auth`
- Python 3.11
- ~100 MB disk, ~256 MB RAM at runtime

## Configuration after install

Settings can be changed via `yunohost app config rclone_dashboard`:
- `rclone_rc_url` — switch RC backend
- `poll_interval_ms` — tune freshness vs load

## Architecture

```
                  ┌──── YunoHost host ──────────────────────────────────┐
                  │                                                     │
user browser ───► │   nginx (TLS + SSO + CSP + header-spoof-defense)    │
                  │      │                                              │
                  │      ├──► /static/    → app/static/* (cached 7d)    │
                  │      │                                              │
                  │      └──► /            → 127.0.0.1:18572            │
                  │                          (Flask gunicorn)           │
                  │                              │                      │
                  │                              ├──► snapshot worker   │
                  │                              │    (thread, 2s tick) │
                  │                              │         │            │
                  │                              │         ▼            │
                  │                              │   $install_dir/data/ │
                  │                              │   dashboard.sqlite   │
                  │                              │   (WAL, 7d ring)     │
                  │                              │                      │
                  │                              ▼                      │
                  │                       127.0.0.1:5572  ◄── rclone RC │
                  │                                       (read-only)   │
                  └─────────────────────────────────────────────────────┘
```

### Read-only by design

The dashboard ONLY calls these rclone RC endpoints (whitelist):

```
core/stats          vfs/stats           job/list
core/transferred    vfs/list            rc/noop
core/version        mount/listmounts    options/get
core/memstats       core/bwlimit
```

It NEVER calls `sync/*`, `operations/*`, `vfs/forget`, `mount/mount`, etc.
v1 is observer-only by design — no buttons that could damage data.

## Security

- nginx strips inbound `Remote-User` / `Ynh-User-*` headers BEFORE SSOwat
  injects them (defense against header spoofing if backend ever exposed)
- Backend binds 127.0.0.1 only
- CSP headers configured (script-src whitelist for CDN deps)
- gunicorn `--max-requests 1000 --max-requests-jitter 100` to recycle workers
  (defense against gradual memory growth)
- systemd `MemoryMax=256M` hard cap (OOM killer kicks app, not the host)
- SQLite ring buffer hard-capped at 500 MB (defense against error-loop spam)

## Performance notes

- 2 s polling = 30 queries/min to rclone RC API on `core/stats` etc.
- rclone RC `core/stats` returns ~1 KB JSON; total bandwidth < 50 KB/min
- SQLite WAL + batched writes every 2.5 s = ~25 disk syncs/min
- 7 days of snapshots at 2s = ~302k rows = ~600 MB raw, ~400 MB after compression
  (still under the 500 MB hard cap; oldest rows pruned proactively)

## Roadmap

- v0.2 — design polish iterations from user feedback, mobile UX tightening
- v0.3 — SSE upgrade path for sub-second freshness on hosts that handle it
- v0.4 — multi-rclone-daemon support (one dashboard, many backends)
- v0.5 — read-only file browser (rclone RC `operations/list`)
- v1.0 — controlled mutation operations (purge cache, pause transfers, etc.)
  with explicit confirmation modals

## License

AGPL-3.0-or-later

## Credits

Built via /octo:plan + /octo:embrace multi-AI workflow. Special thanks to
Codex (architectural pragmatism), Gemini (lateral thinking and the OOM
resiliency warning), and Claude (synthesis and code).
