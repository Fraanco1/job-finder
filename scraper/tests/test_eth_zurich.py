"""ETH Zurich job portal source (no network)."""

import os
from datetime import date

import pytest

from jobfinder.sources.eth_zurich import EthZurich

needs_geo = pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")

LISTING_HTML = """
<ul class="job-ad__wrapper">
<div data-key="12198"><li class="job-ad__item__wrapper">
  <a class="job-ad__item__link" href="/job/view/JOPG_ethz_uXPVmZM0iJ2XgWYNvF">
    <h3 class="job-ad__item__title">Doctoral Researcher in Pulse Electron Paramagnetic Resonance</h3>
    <div class="job-ad__item__details">100%, Zurich, fixed-term</div>
    <div class="job-ad__item__company">08.10.2026 | Institute for Molecular Physical Science (IMPS)</div>
  </a></li></div>
<div data-key="12204"><li class="job-ad__item__wrapper">
  <a class="job-ad__item__link" href="/job/view/12204">
    <h3 class="job-ad__item__title">Studentische Mitarbeiter:innen DevOps (m/w/d)</h3>
    <div class="job-ad__item__details">30%, Basel, unbefristet</div>
    <div class="job-ad__item__company">07.10.2026 | Informatikdienste</div>
  </a></li></div>
</ul>
"""

DETAIL_HTML = """
<section class="description">
  <h1 class="description__title" id="job-title">Doctoral Researcher in Pulse Electron Paramagnetic Resonance</h1>
  <h4>100%, Zurich, fixed-term</h4>
  <div class="paragraph description__paragraph"><p>EPR spectroscopy and spin dynamics.</p></div>
  <h2 id="diversity">We value diversity and sustainability</h2>
  <div class="paragraph description__paragraph"><p>Boilerplate.</p></div>
</section>
<section class="application"><div class="paragraph description__paragraph">
  <p>Apply by 31 October 2026.</p></div></section>
"""


def test_parse_listing():
    rows = EthZurich.parse_listing(LISTING_HTML)
    assert [r["id"] for r in rows] == ["JOPG_ethz_uXPVmZM0iJ2XgWYNvF", "12204"]
    assert rows[0]["posted"] == "08.10.2026"
    assert rows[0]["department"] == "Institute for Molecular Physical Science (IMPS)"


def test_parse_detail_skips_boilerplate():
    d = EthZurich.parse_detail(DETAIL_HTML)
    assert "EPR spectroscopy" in d["description"]
    assert "Boilerplate" not in d["description"]
    assert "31 October 2026" in d["description"]


@needs_geo
def test_to_opportunity():
    src = EthZurich()
    rows = EthZurich.parse_listing(LISTING_HTML)
    opp = src.to_opportunity(rows[0], EthZurich.parse_detail(DETAIL_HTML))
    assert opp.kind == "phd" and opp.organization == "ETH Zurich"
    assert opp.posted == date(2026, 10, 8)
    assert opp.locations[0].city == "Zürich"
    student = src.to_opportunity(rows[1], {})
    assert student.kind == "internship"
    assert student.locations[0].city == "Basel"
