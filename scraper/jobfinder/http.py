"""Polite HTTP client: per-host rate limiting, retries and an identifying UA."""

from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126 Safari/537.36 job-finder/0.1 (+https://github.com/Fraanco1/job-finder)"
)


class PoliteSession:
    """A requests session that waits ``min_interval`` seconds between hits to the same host."""

    def __init__(self, min_interval: float = 0.5, timeout: float = 30.0):
        self.min_interval = min_interval
        self.timeout = timeout
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en"})
        # Connection-level retries only; HTTP status retries are handled in _request so we can
        # back off adaptively (some servers send non-integer Retry-After values urllib3 rejects).
        retry = Retry(total=3, connect=3, read=2, status=0, backoff_factor=1.5,
                      status_forcelist=(), respect_retry_after_header=False, raise_on_status=False)
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        while True:
            with self._lock:
                now = time.monotonic()
                wait = self._last.get(host, 0.0) + self.min_interval - now
                if wait <= 0:
                    self._last[host] = now
                    return
            time.sleep(wait)

    RETRY_STATUS = (429, 500, 502, 503, 504)

    def _request(self, method: str, url: str, attempts: int = 5, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        delay = max(2.0, self.min_interval * 4)
        for attempt in range(attempts):
            self._throttle(url)
            r = self.session.request(method, url, **kw)
            log.debug("%s %s -> %s", method, url, r.status_code)
            if r.status_code not in self.RETRY_STATUS or attempt == attempts - 1:
                return r
            try:
                wait = float(r.headers.get("Retry-After", "0"))
            except ValueError:
                wait = 0.0
            wait = max(wait, delay)
            if r.status_code == 429:
                # Slow down for the rest of the run, not just this request.
                self.min_interval = min(self.min_interval * 1.5, 5.0)
            log.info("%s on %s; retrying in %.1fs", r.status_code, url, wait)
            time.sleep(wait)
            delay *= 2
        return r

    def get(self, url: str, **kw) -> requests.Response:
        return self._request("GET", url, **kw)

    def post(self, url: str, **kw) -> requests.Response:
        return self._request("POST", url, **kw)

    def get_json(self, url: str, **kw):
        r = self.get(url, **kw)
        r.raise_for_status()
        return r.json()
