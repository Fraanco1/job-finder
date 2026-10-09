"""DAAD International Programmes source: application periods, semesters, mapping (no network)."""

import os
from datetime import date

import pytest

from jobfinder.sources.daad import Daad, first_explicit_date, parse_periods, semester_start

needs_geo = pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")

TODAY = date(2026, 10, 9)

DETAIL_HTML = """
<html><body><dl>
  <dt class="c-description-list__content">Degree</dt>
  <dd class="c-description-list__content">Master of Science</dd>
  <dt class="c-description-list__content">Beginning</dt>
  <dd class="c-description-list__content">Winter and summer semester</dd>
  <dt class="c-description-list__content">Application periods</dt>
  <dd class="c-description-list__content">
    The following is valid for applicants from: non-EU countries<br>
    For the summer semester:<br> until 31 October <hr>
    The following is valid for applicants from: non-EU countries<br>
    For the winter semester:<br> until 30 April
  </dd>
  <dt class="c-description-list__content">Description/content</dt>
  <dd class="c-description-list__content"><p>Financial mathematics, statistics and computational methods.</p></dd>
  <dt class="c-description-list__content">Academic admission requirements</dt>
  <dd class="c-description-list__content">A BSc degree in Mathematics.</dd>
</dl></body></html>
"""

LISTING = {
    "id": 4722,
    "courseName": "Actuarial and Financial Mathematics",
    "academy": "RPTU University Kaiserslautern-Landau",
    "city": "Kaiserslautern",
    "languages": ["English"],
    "beginning": "Winter semester, Summer semester",
    "programmeDuration": "4 semesters",
    "tuitionFees": "No tuition fees",
    "courseType": 2,
    "applicationDeadline": "Register by 31 October 2026 + 1 more",
    "subject": "Applied Mathematics",
    "link": "/deutschland/studienangebote/international-programmes/en/detail/4722/",
}


def test_semester_start():
    assert semester_start("winter", date(2027, 4, 30)) == date(2027, 10, 1)
    assert semester_start("winter", date(2026, 12, 15)) == date(2027, 10, 1)
    assert semester_start("summer", date(2026, 10, 31)) == date(2027, 4, 1)
    assert semester_start("summer", date(2027, 1, 15)) == date(2027, 4, 1)


def test_parse_periods_resolves_years_and_ranges():
    text = ("EU countries\nFor the summer semester:\n 1 December - 15 March\n---\n"
            "non-EU countries\nFor the summer semester:\n 1 December - 15 January\n---\n"
            "all countries\nFor the winter semester:\n 1 April 2027 - 15 July 2027")
    assert parse_periods(text, TODAY) == [
        ("summer", date(2027, 3, 15)),
        ("summer", date(2027, 1, 15)),
        ("winter", date(2027, 7, 15)),
    ]
    # explicit years in the past are dropped
    assert parse_periods("For the winter semester: until 15 July 2026", TODAY) == []


def test_first_explicit_date():
    assert first_explicit_date("Register by 31 October 2026 + 1 more") == date(2026, 10, 31)
    assert first_explicit_date("This programme has no deadline.") is None


def test_parse_detail():
    d = Daad.parse_detail(DETAIL_HTML)
    assert d["degree"] == "Master of Science"
    assert "until 31 October" in d["periods"] and "---" in d["periods"]
    assert d["requirements"] == "A BSc degree in Mathematics."


@needs_geo
def test_to_opportunity_programme_fields():
    opp = Daad().to_opportunity(LISTING, Daad.parse_detail(DETAIL_HTML), TODAY)
    assert opp.kind == "masters"
    assert opp.title == "Actuarial and Financial Mathematics (Master of Science)"
    assert opp.deadline == date(2026, 10, 31)          # earliest upcoming period
    assert opp.start_date == date(2027, 4, 1)          # ... belongs to the summer semester
    assert opp.start_text == "Summer semester 2027"
    assert opp.education_level == "bachelor"
    assert opp.source_fields == ["Applied Mathematics"]
    assert opp.locations[0].city == "Kaiserslautern"
    assert opp.url.endswith("/en/detail/4722/")


@needs_geo
def test_phd_programme_without_deadline():
    listing = dict(LISTING, courseType=3, courseName="Graduate School of Physics",
                   applicationDeadline="This programme has no deadline.", beginning="Any time")
    opp = Daad().to_opportunity(listing, {}, TODAY)
    assert opp.kind == "phd" and opp.deadline is None and opp.start_date is None
    assert opp.start_text == "Any time"
    assert opp.education_level == "masters"
