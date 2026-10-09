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
        retry = Retry(total=3, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET", "POST"), respect_retry_after_header=True)
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

    def get(self, url: str, **kw) -> requests.Response:
        self._throttle(url)
        kw.setdefault("timeout", self.timeout)
        r = self.session.get(url, **kw)
        log.debug("GET %s -> %s", url, r.status_code)
        return r

    def post(self, url: str, **kw) -> requests.Response:
        self._throttle(url)
        kw.setdefault("timeout", self.timeout)
        return self.session.post(url, **kw)

    def get_json(self, url: str, **kw):
        r = self.get(url, **kw)
        r.raise_for_status()
        return r.json()
