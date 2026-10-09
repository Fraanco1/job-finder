"""INSPIRE-HEP jobs: rank/category mapping and record conversion (no network)."""

import os
from datetime import date

import pytest

from jobfinder.sources.inspire import (
    Inspire,
    categories_to_fields,
    kind_from_ranks,
    parse_institution,
)

RECORD = {
    "control_number": 3212700,
    "position": "Postdoc in theoretical physics",
    "ranks": ["POSTDOC"],
    "regions": ["North America"],
    "deadline_date": "2027-01-04",
    "arxiv_categories": ["hep-ph", "astro-ph", "cs"],
    "institutions": [{"value": "Carleton U. (main)",
                      "record": {"$ref": "https://inspirehep.net/api/institutions/1276764"}}],
    "acquisition_source": {"datetime": "2026-10-08T18:02:50.684409"},
    "description": "<div>The <strong>particle theory group</strong> invites applications.</div>",
}

INSTITUTION = {
    "addresses": [{"cities": ["Ottawa"], "state": "Ontario", "country": "Canada",
                   "country_code": "CA", "latitude": 45.388, "longitude": -75.698}],
    "institution_hierarchy": [{"name": "Carleton University"}],
    "legacy_ICN": "Carleton U. (main)",
}


@pytest.mark.parametrize("ranks,kind", [
    (["POSTDOC"], "postdoc"),
    (["PHD", "MASTER"], "phd"),
    (["MASTER"], "masters"),
    (["UNDERGRADUATE"], "internship"),
    (["SENIOR", "JUNIOR"], "job"),
    (["OTHER"], None),
    ([], None),
])
def test_kind_from_ranks(ranks, kind):
    assert kind_from_ranks(ranks) == kind


def test_categories_physics_first_secondary_cs_ignored():
    discs, subs, labels = categories_to_fields(["hep-ex", "cs", "physics.ins-det"])
    assert discs == ["physics"]
    assert subs == ["particle-physics", "instrumentation"]
    assert "Computer science" in labels


def test_categories_math_only():
    discs, subs, _ = categories_to_fields(["math", "stat"])
    assert discs == ["mathematics"]
    assert subs == ["probability-statistics"]


def test_parse_institution():
    info = parse_institution(INSTITUTION)
    assert info["name"] == "Carleton University"
    assert (info["city"], info["cc"]) == ("Ottawa", "CA")


class _FakeCache:
    def __init__(self, data):
        self.data = data

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


@pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")
def test_to_opportunity_uses_cached_institution():
    src = Inspire()
    cache = _FakeCache({"id:1276764": parse_institution(INSTITUTION)})
    opp = src.to_opportunity(RECORD, cache)
    assert opp.url == "https://inspirehep.net/jobs/3212700"
    assert opp.organization == "Carleton University"
    assert opp.kind == "postdoc"
    assert opp.deadline == date(2027, 1, 4)
    assert opp.posted == date(2026, 10, 8)
    assert opp.disciplines == ["physics"]
    assert "particle-physics" in opp.subfields
    assert "particle theory group" in opp.description
    loc = opp.locations[0]
    assert (loc.city, loc.country_code) == ("Ottawa", "CA")
    assert loc.lat is not None


@pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")
def test_location_fallbacks():
    from jobfinder.sources.inspire import institution_location, name_location
    assert name_location("Sun Yat-Sen U., Zhuhai").city == "Zhuhai"
    # INSPIRE files Hong Kong under China: keep it in Hong Kong, not Beijing
    assert institution_location({"city": "Hong Kong", "country": "China", "cc": "CN"}).country_code == "HK"
    # small lab towns missing from the gazetteer use INSPIRE's own coordinates
    loc = institution_location({"city": "Tinytown", "country": "Germany", "cc": "DE", "lat": 50.1, "lon": 8.2})
    assert (loc.city, loc.precision, loc.lat) == ("Tinytown", "city", 50.1)
