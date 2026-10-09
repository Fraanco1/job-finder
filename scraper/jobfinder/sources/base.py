"""Base class and helpers for scrapers.

To add a source, drop a module in this package that defines a ``Source``
subclass with a unique ``id``. The registry picks it up automatically.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

from ..http import PoliteSession
from ..models import Opportunity

CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache"


class DetailCache:
    """JSON-backed key/value store so detail pages are fetched only once.

    Entries not touched for ``ttl_days`` are dropped on save, which keeps the
    file from growing forever as postings expire.
    """

    def __init__(self, name: str, ttl_days: int = 120):
        self.path = CACHE_DIR / f"{name}.json"
        self.ttl = timedelta(days=ttl_days)
        self._lock = threading.Lock()
        try:
            self.data: dict = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def get(self, key: str):
        with self._lock:
            entry = self.data.get(key)
            if entry is None:
                return None
            entry["_seen"] = date.today().isoformat()
            return entry.get("v")

    def set(self, key: str, value) -> None:
        with self._lock:
            self.data[key] = {"v": value, "_seen": date.today().isoformat()}

    def save(self) -> None:
        cutoff = (date.today() - self.ttl).isoformat()
        with self._lock:
            self.data = {k: v for k, v in self.data.items() if v.get("_seen", "") >= cutoff}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False))
            tmp.replace(self.path)


class Source:
    id: str = ""
    name: str = ""
    homepage: str = ""
    # Seconds between requests to the same host.
    min_interval: float = 0.5

    def __init__(self, limit: int | None = None):
        self.limit = limit  # max items, for quick test runs
        self.log = logging.getLogger(f"jobfinder.{self.id}")
        self.http = PoliteSession(min_interval=self.min_interval)

    def fetch(self) -> Iterable[Opportunity]:
        raise NotImplementedError


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    s = BeautifulSoup(html, "lxml")
    for br in s.find_all(["br", "p", "li", "div", "h1", "h2", "h3", "h4", "tr"]):
        br.insert_before("\n")
    text = s.get_text(" ")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()
