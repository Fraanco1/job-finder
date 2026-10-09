"""jobs.ac.uk source: listing cards, advert pages, intake detection (no network)."""

import json
import os
from datetime import date

import pytest

from jobfinder.sources.jobs_ac_uk import JobsAcUk, find_intake

needs_geo = pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")

LISTING_HTML = """
<div class="j-search-result__result ie-border-left">
  <div class="j-search-result__text">
    <a href="/job/DTE714/fully-funded-phd-studentships-stor-i">Fully Funded PhD Studentships (STOR-i)</a>
    <div class="j-search-result__department">Department of Mathematics</div>
    <div class="j-search-result__employer"><b>Lancaster University</b></div>
    <div>Location: Lancaster</div>
    <div class="j-search-result__info"><strong>Salary:</strong> £30,000</div>
  </div>
</div>
"""

LD = {
    "@context": "https://schema.org", "@type": "JobPosting",
    "title": "Fully Funded PhD Studentships (STOR-i)",
    "description": "<p>Join STOR-i to start in October 2027. Statistics and operational research.</p>",
    "datePosted": "2026-10-08T00:00:00+00:00",
    "validThrough": "2027-07-31T00:00:00+00:00",
    "hiringOrganization": {"@type": "Organization", "name": "Lancaster University"},
    "jobLocation": [{"@type": "Place", "address": {"addressLocality": "Lancaster",
                                                   "addressRegion": "England",
                                                   "addressCountry": "United Kingdom"}}],
}

DETAIL_HTML = f"""
<html><head><script type="application/ld+json">{json.dumps(LD)}</script></head><body>
<div class="j-advert-details__container"><table>
  <tr><th>Qualification Type:</th><td>PhD</td></tr>
  <tr><th>Funding for:</th><td>UK Students, International Students</td></tr>
  <tr><th>Funding amount:</th><td>£30,000</td></tr>
  <tr><th>Placed On:</th><td>8th October 2026</td></tr>
  <tr><th>Closes:</th><td>31st July 2027</td></tr>
</table></div>
<p><b>Subject Area(s):</b></p>
<form method="GET" action="/search/"><input type="submit" value="Mathematics &amp; Statistics"></form>
<form method="GET" action="/search/"><input type="submit" value="Statistics"></form>
</body></html>
"""


def test_parse_listing():
    rows = JobsAcUk.parse_listing(LISTING_HTML)
    assert rows == [{
        "id": "DTE714", "path": "/job/DTE714/fully-funded-phd-studentships-stor-i",
        "title": "Fully Funded PhD Studentships (STOR-i)", "org": "Lancaster University",
        "department": "Department of Mathematics", "location": "Lancaster",
    }]


def test_parse_detail():
    d = JobsAcUk.parse_detail(DETAIL_HTML)
    assert d["table"]["Qualification Type"] == "PhD"
    assert d["subjects"] == ["Mathematics & Statistics", "Statistics"]
    assert d["org"] == "Lancaster University"
    assert "October 2027" in d["description"]


@pytest.mark.parametrize("text,expected", [
    ("for an October 2027 start", (date(2027, 10, 1), "October 2027")),
    ("The project will start in January 2027.", (date(2027, 1, 1), "January 2027")),
    ("Starting date 1st October 2027", (date(2027, 10, 1), "October 2027")),
    ("no intake mentioned", (None, None)),
])
def test_find_intake(text, expected):
    assert find_intake(text) == expected


@needs_geo
def test_to_opportunity():
    src = JobsAcUk()
    card = JobsAcUk.parse_listing(LISTING_HTML)[0]
    opp = src.to_opportunity(card, JobsAcUk.parse_detail(DETAIL_HTML))
    assert opp.kind == "phd"
    assert opp.deadline == date(2027, 7, 31) and opp.posted == date(2026, 10, 8)
    assert opp.start_date == date(2027, 10, 1)
    assert opp.locations[0].city == "Lancaster" and opp.locations[0].country_code == "GB"
    assert "Statistics" in opp.source_fields
    assert opp.url == "https://www.jobs.ac.uk/job/DTE714/fully-funded-phd-studentships-stor-i"
