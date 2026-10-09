"""AcademicTransfer source: Nuxt payload decoding, slug filter, mapping (no network)."""

import json
import os
from datetime import date

import pytest

from jobfinder.sources.academictransfer import SLUG_FILTER, AcademicTransfer, extract_vacancy, nuxt_value

needs_geo = pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")

# Nuxt 3 flattens the state: every value is an index into the top-level array.
PAYLOAD = [
    ["ShallowReactive", 1],
    {"data": 2},
    ["ShallowReactive", 3],
    {"vacancy": 4},
    {"id": 5, "external_id": 6, "title": 7, "end_date": 8, "city": 9, "country_code": 10,
     "function_types": 11, "scientific_fields": 13, "research_fields": 15, "education_level": 18,
     "organisation_name": 19, "description": 20, "min_salary": 21, "max_salary": 22,
     "created_datetime": 23, "absolute_url": 24},
    96283, 364611, "PhD Candidate in Quantum Optics", "2026-11-07T23:59:59+01:00", "Leiden", "NL",
    [12], 9,
    [14], 2,
    [16, 17], "32.0", "32.4",
    2, "Universiteit Leiden", "<p>Build a quantum network.</p>", 3204, 4051,
    "2026-10-09T07:06:12+02:00", "https://www.academictransfer.com/en/jobs/364611/phd-candidate/",
]
HTML = ('<html><script type="application/json" data-nuxt-data="nuxt-app" id="__NUXT_DATA__">'
        + json.dumps(PAYLOAD) + "</script></html>")


def test_nuxt_value_resolves_refs():
    assert nuxt_value(PAYLOAD, 0) == {"data": {"vacancy": nuxt_value(PAYLOAD, 4)}}


def test_extract_vacancy():
    v = extract_vacancy(HTML)
    assert v["title"] == "PhD Candidate in Quantum Optics"
    assert v["function_types"] == [9] and v["research_fields"] == ["32.0", "32.4"]
    assert extract_vacancy("<html>no payload</html>") is None


@pytest.mark.parametrize("slug,keep", [
    ("phd position in formal methods", True),
    ("master thesis perovskite nano resonators", True),
    ("promovendus governance en data", True),
    ("postdoc position on wafer bonding", True),
    ("senior financial controller", False),
    ("medewerker technische dienst", False),
])
def test_slug_filter(slug, keep):
    assert bool(SLUG_FILTER.search(slug)) is keep


@needs_geo
def test_to_opportunity():
    v = extract_vacancy(HTML)
    v["description"] = "Build a quantum network."
    opp = AcademicTransfer().to_opportunity({"id": "364611", "url": "x"}, v)
    assert opp.kind == "phd"
    assert opp.deadline == date(2026, 11, 7) and opp.posted == date(2026, 10, 9)
    assert opp.source_fields == ["Physics", "Natural sciences"]
    assert opp.education_level == "masters"
    assert opp.salary == "€3204–€4051 per month"
    assert opp.locations[0].city == "Leiden"
