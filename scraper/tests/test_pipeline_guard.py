"""Pipeline resilience: shrink guard and committed seed snapshots (no network)."""

import json

import pytest

from jobfinder import pipeline
from jobfinder.models import Opportunity
from jobfinder.sources.base import Source


def make_source(n):
    class Fake(Source):
        id = "fake"
        name = "Fake"
        homepage = "https://example.org"

        def fetch(self):
            for i in range(n):
                yield Opportunity(source="fake", source_id=str(i), url=f"https://x/{i}",
                                  title=f"PhD position in quantum optics {i}",
                                  description="Lasers and photonics.")
    return Fake


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "SNAPSHOT_DIR", tmp_path / "snap")
    monkeypatch.setattr(pipeline, "SEED_DIR", tmp_path / "seed")
    return tmp_path


def run_with(monkeypatch, env, n):
    monkeypatch.setattr(pipeline, "all_sources", lambda: {"fake": make_source(n)})
    return pipeline.run(output=env / "out.json")


def test_collapse_keeps_previous_snapshot(monkeypatch, env):
    assert len(run_with(monkeypatch, env, 40)["items"]) == 40
    payload = run_with(monkeypatch, env, 3)  # site started blocking us
    assert len(payload["items"]) == 40
    st = payload["sources"][0]
    assert st["ok"] is False and st["stale"] is True and "only 3" in st["error"]


def test_seed_used_when_blocked_in_ci(monkeypatch, env):
    seed = [{"id": f"s{i}", "source": "fake", "url": "u", "title": f"Seeded {i}", "kind": "phd",
             "disc": ["physics"]} for i in range(30)]
    (env / "seed").mkdir()
    (env / "seed" / "fake.json").write_text(json.dumps(seed))
    payload = run_with(monkeypatch, env, 0)
    assert len(payload["items"]) == 30


def test_dedupe_across_sources():
    long_t = "Doctoral student in Physics: Topoelectronic Quantum Devices in 2D Materials"
    per_source = {
        "euraxess": [{"title": long_t, "org": "Lund University", "locs": [{"city": "Lund"}]}],
        "varbi": [{"title": long_t, "org": "Lund University via MyNetwork", "locs": [{"city": "Lund"}]},
                  {"title": "Software Engineer", "org": "A", "locs": [{"city": "Lund"}]}],
        "greenhouse": [{"title": "Software Engineer", "org": "B", "locs": [{"city": "Lund"}]}],
    }
    out = pipeline.dedupe(per_source)
    assert [x["title"] for x in out].count(long_t) == 1
    assert len([x for x in out if x["title"] == "Software Engineer"]) == 2
