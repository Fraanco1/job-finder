"""EURAXESS incremental listing crawl (no network: fake HTTP, temp cache dir)."""

import pytest

from jobfinder.sources import base, euraxess
from jobfinder.sources.euraxess import Euraxess


def card_html(ids):
    arts = "".join(
        f'<article class="ecl-content-item"><h3><a href="/jobs/{i}">PhD position in quantum physics {i}</a></h3>'
        f'<div class="ecl-content-block__description"><p>Physics</p></div></article>'
        for i in ids
    )
    return f"<html><body><p>Search results ({TOTAL})</p>{arts}</body></html>"


TOTAL = 200  # 20 pages of 10


class FakeResp:
    def __init__(self, text):
        self.text, self.status_code = text, 200

    def raise_for_status(self):
        pass


class FakeHTTP:
    def __init__(self, newest):
        self.newest = newest  # highest id; listing is newest first
        self.calls = 0

    def get(self, url, **kw):
        self.calls += 1
        page = int(url.split("page=")[1]) if "page=" in url else 0
        start = self.newest - page * 10
        ids = [i for i in range(start, start - 10, -1) if i > self.newest - TOTAL]
        return FakeResp(card_html(ids))


@pytest.fixture
def src(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "CACHE_DIR", tmp_path)
    monkeypatch.delenv("EURAXESS_FULL", raising=False)
    s = Euraxess()
    monkeypatch.setattr(s, "full_crawl_due", lambda cache: not cache.data)
    return s


def test_first_run_is_full_then_incremental(src):
    src.http = FakeHTTP(newest=1000)
    first = src.crawl_listing()
    assert len(first) == TOTAL

    # Next day: 15 new postings on top; the crawl stops early but still returns everything.
    src.http = FakeHTTP(newest=1015)
    second = src.crawl_listing()
    assert src.http.calls < 12
    ids = {c["id"] for c in second}
    assert "1015" in ids and "801" in ids
