"""Varbi university boards: listing table, quick-info table, kind hints (no network)."""

from jobfinder.classify import enrich

import os
from datetime import date

import pytest

from jobfinder.sources.varbi import Varbi, parse_varbi_date

needs_geo = pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")

LISTING_HTML = """
<table>
<tr><th>Vacancy</th><th>City</th><th>Department</th><th>Application deadline</th></tr>
<tr>
  <td><a href="https://kth.varbi.com/en/what:job/jobID:976709/">Postdoc in Sustainable Materials</a></td>
  <td>Stockholm</td><td>KTH Royal Institute of Technology, School of Engineering Sciences</td>
  <td>2026-10-16</td>
</tr>
<tr>
  <td><a href="https://kth.varbi.com/en/what:job/jobID:977000/">Doktorand i reglerteknik</a></td>
  <td>Stockholm</td><td>KTH</td><td>2026-11-01</td>
</tr>
</table>
"""

DETAIL_HTML = """
<h1 class="pull-left">Postdoc in Sustainable Materials</h1>
<h2 class="org-desc">KTH Royal Institute of Technology, School of Engineering Sciences</h2>
<div class="job-desc mb"><h3>Job description</h3><p>Electrochemistry and materials science.</p></div>
<table class="table table-condensed quick-info"><tbody>
  <tr class="quick-info-type-of-employment"><th>Type of employment</th><td>Temporary position</td></tr>
  <tr class="quick-info-admission"><th>First day of employment</th><td>2027-01-01</td></tr>
  <tr class="quick-info-town"><th>City</th><td>Stockholm</td></tr>
  <tr><th>Country</th><td>Sweden</td></tr>
  <tr class="quick-info-published"><th>Published</th><td>07.Oct.2026</td></tr>
  <tr class="quick-info-ends"><th>Last application date</th><td>16.Oct.2026</td></tr>
</tbody></table>
"""


def test_parse_listing():
    rows = Varbi.parse_listing(LISTING_HTML, "kth")
    assert [r["id"] for r in rows] == ["kth:976709", "kth:977000"]
    assert rows[0]["deadline"] == "2026-10-16" and rows[0]["city"] == "Stockholm"


def test_parse_detail_quick_info():
    d = Varbi.parse_detail(DETAIL_HTML)
    assert d["info"]["Last application date"] == "16.Oct.2026"
    assert d["info"]["First day of employment"] == "2027-01-01"
    assert "Electrochemistry" in d["description"]


def test_parse_varbi_date():
    assert parse_varbi_date("16.Oct.2026") == date(2026, 10, 16)
    assert parse_varbi_date("2026-10-16") == date(2026, 10, 16)


@needs_geo
def test_to_opportunity():
    src = Varbi()
    rows = Varbi.parse_listing(LISTING_HTML, "kth")
    opp = src.to_opportunity(rows[0], Varbi.parse_detail(DETAIL_HTML))
    assert opp.organization == "KTH Royal Institute of Technology"
    # English titles get their kind from the shared classifier, as in the pipeline.
    assert enrich(opp).kind == "postdoc"
    assert opp.deadline == date(2026, 10, 16) and opp.start_date == date(2027, 1, 1)
    assert opp.locations[0].country_code == "SE"
    # Swedish title, no detail page yet: kind comes from the Swedish word
    assert src.to_opportunity(rows[1], {}).kind == "phd"
