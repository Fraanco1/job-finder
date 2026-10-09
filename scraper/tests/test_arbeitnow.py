"""Arbeitnow source: student/technical filter and mapping (no network)."""

import os
from datetime import date

import pytest

from jobfinder.sources.arbeitnow import Arbeitnow, is_student_tech

needs_geo = pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")


def job(title, tags=(), types=(), **kw):
    return {"slug": "x-1", "title": title, "tags": list(tags), "job_types": list(types),
            "company_name": "ACME", "location": "Munich", "remote": False,
            "description": "<p>Python and robotics.</p>", "created_at": 1791516005,
            "url": "https://www.arbeitnow.com/jobs/companies/acme/x-1", **kw}


@pytest.mark.parametrize("title,tags,types,keep", [
    ("Werkstudent:in AI & Automation (m/w/d)", (), (), True),
    ("Working Student Electronics Engineering (m/f/d)", (), (), True),
    ("Software Engineer (Intern or Recent Graduate)", (), (), True),
    ("Pflichtpraktikum Systemintegration & Deployment - Docker, Linux", (), (), True),
    ("Robotics Engineer", ("Engineering",), ("Intern",), True),
    ("Werkstudent*in Finance Projects & Systems (m/w/d)", (), (), False),   # non-STEM function
    ("Working Student Marketing - Content Creation", (), (), False),
    ("Senior Software Engineer", (), ("Full Time",), False),                # not a student job
    ("Werkstudent Office Management", (), (), False),
])
def test_is_student_tech(title, tags, types, keep):
    assert is_student_tech(job(title, tags, types)) is keep


@needs_geo
def test_to_opportunity():
    opp = Arbeitnow().to_opportunity(job("Werkstudent Maschinenbau (m/w/d)", ("Engineering",),
                                         ("Working student",), remote=True))
    assert opp.kind == "internship" and opp.organization == "ACME"
    assert opp.posted == date(2026, 10, 9)  # 1791516005 = 2026-10-09 03:20 UTC
    assert opp.locations[0].city == "Munich" and opp.locations[0].remote
    assert "mechanical engineering" in opp.source_fields
    assert "Remote" in opp.tags
