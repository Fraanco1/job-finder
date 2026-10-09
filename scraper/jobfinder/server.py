"""Tiny local server: serves the built site (web/dist) and lets the page trigger a refresh.

    python -m jobfinder serve            # http://127.0.0.1:8000

Endpoints
---------
GET  /api/status   -> {"running": bool, "started": iso|null, "finished": iso|null, "error": str|null}
POST /api/refresh  -> starts a background scrape (all sources); 409 if one is already running
Everything else is served from web/dist, with data/opportunities.json read from
web/public/data so a refresh is visible without rebuilding the site.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .pipeline import OUTPUT, ROOT, run

log = logging.getLogger(__name__)
DIST = ROOT / "web" / "dist"


class _State:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.started: str | None = None
        self.finished: str | None = None
        self.error: str | None = None

    def as_dict(self):
        return {"running": self.running, "started": self.started, "finished": self.finished, "error": self.error}


STATE = _State()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _refresh_worker():
    try:
        run()
        STATE.error = None
    except BaseException as e:  # noqa: BLE001 - report anything, including SystemExit
        log.exception("refresh failed")
        STATE.error = f"{type(e).__name__}: {e}"[:300]
    finally:
        with STATE.lock:
            STATE.running = False
            STATE.finished = _now()


def start_refresh() -> bool:
    with STATE.lock:
        if STATE.running:
            return False
        STATE.running = True
        STATE.started = _now()
    threading.Thread(target=_refresh_worker, daemon=True).start()
    return True


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter than the default stderr spam
        log.debug(fmt, *args)

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.endswith("/api/status"):
            return self._json(200, STATE.as_dict())
        if path.endswith("/data/opportunities.json"):
            if not OUTPUT.exists():
                return self._json(404, {"error": "no data yet; run a refresh"})
            data = OUTPUT.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return None
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0].endswith("/api/refresh"):
            started = start_refresh()
            return self._json(202 if started else 409, STATE.as_dict())
        return self._json(404, {"error": "not found"})


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    root = DIST if (DIST / "index.html").exists() else None
    if root is None:
        raise SystemExit("web/dist not found. Build the site first: cd web && npm install && npm run build")
    httpd = ThreadingHTTPServer((host, port), partial(Handler, directory=str(Path(root))))
    print(f"Serving {root} on http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
