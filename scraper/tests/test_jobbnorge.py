"""Jobbnorge source: kind detection, advert components, locations (no network)."""

import os
from datetime import date

import pytest

from jobfinder.sources.jobbnorge import Jobbnorge, components_text, job_kind, job_locations

needs_geo = pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")

JOB = {
    "id": 309744, "title": "PhD position in Aluminium Extrusion",
    "employer": "NTNU - Norwegian University of Science and Technology",
    "department": "Department of Mechanical and Industrial Engineering",
    "deadline": "01.11.2026", "publicationDate": "07.10.2026",
    "jobScope": "Fulltime", "jobDuration": "Temporary",
    "jobType": {"id": 406, "name": "1017 Stipendiat"},
    "link": "https://www.jobbnorge.no/ledige-stillinger/stilling/309744",
    "locations": [{"area": "Trondheim", "municipality": "Trondheim", "county": "Trøndelag",
                   "isDomestic": True, "isPrimary": True}],
}


@pytest.mark.parametrize("title,jobtype,kind", [
    ("PhD position in Aluminium Extrusion", None, "phd"),
    ("Stipendiat i matematikk", None, "phd"),
    ("Postdoctoral Research Fellow in ICT", None, "postdoc"),
    ("Researcher", "1352 Postdoktor ", "postdoc"),
    ("Research position", "1017 Stipendiat", "phd"),
    ("Summer student in marine biology", None, "internship"),
    ("Kantineleder", None, None),
])
def test_job_kind(title, jobtype, kind):
    assert job_kind({"title": title, "jobType": {"name": jobtype} if jobtype else {}}) == kind


def test_components_text_skips_media_and_boilerplate():
    comps = [
        {"heading": "PhD position", "text": "We are looking for.../The Department of xxx has a vacancy for a",
         "typeId": 0, "orderId": 0},
        {"heading": "This is NTNU", "text": "<p>Video</p>", "typeId": 6, "orderId": 1},
        {"heading": "About the position", "text": "<p>Aluminium extrusion research.</p>", "typeId": 4, "orderId": 2},
        {"heading": "Diversity", "text": "<p>We value diversity.</p>", "typeId": 4, "orderId": 3},
    ]
    text = components_text(comps)
    assert text == "About the position\nAluminium extrusion research."


@needs_geo
def test_locations_and_opportunity():
    locs = job_locations(JOB)
    assert locs[0].city == "Trondheim" and locs[0].country_code == "NO"
    opp = Jobbnorge().to_opportunity(JOB, {"text": "About the position\nAluminium extrusion."})
    assert opp.kind == "phd"
    assert opp.deadline == date(2026, 11, 1) and opp.posted == date(2026, 10, 7)
    assert opp.tags[0] == "1017 Stipendiat"
