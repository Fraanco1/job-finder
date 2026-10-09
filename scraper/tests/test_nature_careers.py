"""Nature Careers source: category listing, advert metadata, premium filtering (no network)."""

import json
import os
from datetime import date

import pytest

from jobfinder.sources.nature_careers import NatureCareers, locate

needs_geo = pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")

LISTING_HTML = """
<ul>
<li class="lister__item cf lister__item--premium-job" id="item-1">
  <h3 class="lister__header"><a href=" /naturecareers/job/1/ceo/?LinkSource=PremiumListing ">Chief Executive Officer</a></h3>
  <ul class="lister__meta"><li class="lister__meta-item lister__meta-item--location">Gloucester (US)</li></ul>
</li>
<li class="lister__item cf" id="item-2">
  <h3 class="lister__header"><a href="/naturecareers/job/2/phd-student-dna/">PhD Student – DNA Break Signature</a></h3>
  <ul class="lister__meta">
    <li class="lister__meta-item lister__meta-item--location">Heidelberg, Baden-Württemberg (DE)</li>
    <li class="lister__meta-item lister__meta-item--salary">Doctoral salary</li>
    <li class="lister__meta-item lister__meta-item--recruiter">DKFZ</li>
  </ul>
  <p class="lister__description">Cancer genomics PhD.</p>
</li>
</ul>
"""

LD = {"@type": "JobPosting", "title": "PhD Student – DNA Break Signature",
      "description": "<p>Computational biology of DNA breaks.</p>",
      "datePosted": "2026-10-07T12:42:00.000Z", "validThrough": "2026-10-28T23:59:00.000Z",
      "hiringOrganization": {"name": "German Cancer Research Center (DKFZ)"}}
DETAIL_HTML = f"""
<script type="application/ld+json">{json.dumps(LD)}</script>
<dl><dt>Location</dt><dd>Heidelberg, Baden-Württemberg (DE)</dd>
<dt>Closing date</dt><dd>28 Oct 2026</dd></dl>
<dl><dt>Discipline</dt><dd><a>Biomedicine</a>, <a>Computing</a></dd>
<dt>Job Type</dt><dd><a>PhD Position</a></dd><dt>Qualification</dt><dd><a>Masters</a></dd></dl>
"""


def test_parse_listing_marks_premium():
    rows = NatureCareers.parse_listing(LISTING_HTML)
    assert [(r["id"], r["premium"]) for r in rows] == [("1", True), ("2", False)]
    assert rows[1]["path"] == "/naturecareers/job/2/phd-student-dna/"
    assert rows[1]["org"] == "DKFZ"


def test_parse_detail_metadata():
    d = NatureCareers.parse_detail(DETAIL_HTML)
    assert d["meta"]["Discipline"] == "Biomedicine | Computing"
    assert d["meta"]["Job Type"] == "PhD Position"
    assert d["deadline"].startswith("2026-10-28")


@needs_geo
def test_locate_country_code_suffix():
    loc = locate("Heidelberg, Baden-Württemberg (DE)")
    assert (loc.city, loc.country_code) == ("Heidelberg", "DE")


@needs_geo
def test_to_opportunity_and_premium_filter():
    src = NatureCareers()
    premium, regular = NatureCareers.parse_listing(LISTING_HTML)
    # premium adverts must say PhD in the title even if tagged "PhD Position"
    assert src.to_opportunity(premium, {"meta": {"Job Type": "PhD Position"}}) is None
    opp = src.to_opportunity(regular, NatureCareers.parse_detail(DETAIL_HTML))
    assert opp.kind == "phd"
    assert opp.deadline == date(2026, 10, 28)
    assert opp.source_fields == ["Biomedicine", "Computing"]
    assert opp.organization == "German Cancer Research Center (DKFZ)"
