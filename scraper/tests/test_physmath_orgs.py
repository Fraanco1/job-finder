"""Parsers for CERN, ESO, Max Planck and FAPESP sources (no network)."""

import os
from datetime import date

import pytest

from jobfinder.sources import cern, eso, fapesp, mpg

needs_geo = pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")


# ------------------------------------------------------------------ CERN

CERN_POSTING = {
    "id": "744000154429914",
    "name": "Technical Studentship - Applied Physics 2027-1",
    "releasedDate": "2026-10-08T12:48:22.590Z",
    "location": {"city": "Geneva", "country": "ch"},
    "department": {"label": "TE"},
    "function": {"label": "Engineering"},
    "typeOfEmployment": {"label": "Full-time"},
    "experienceLevel": {"id": "entry_level"},
    "customField": [{"fieldLabel": "Programme", "valueLabel": "Technical Students"}],
}
CERN_DETAIL = {
    "postingUrl": "https://jobs.smartrecruiters.com/CERN/744000154429914-x",
    "jobAd": {"sections": {
        "jobDescription": {"text": "<p>Join the cryogenics group.</p><p>Job closing date: 29 .10.2026 at 23:59 CEST.</p>"},
        "qualifications": {"text": "<p>Application Deadline: 16/10/26 at 23:59 (Geneva time) "
                                   "Employment Conditions: Ideal Start Date: 01/04/2027</p>"},
    }},
}


def test_cern_dates():
    assert cern.find_cern_deadline("Job closing date: 29 .10.2026 at 23:59") == date(2026, 10, 29)
    assert cern.find_cern_deadline("Application Deadline: 16/10/26 at 23:59") == date(2026, 10, 16)
    assert cern.find_cern_deadline("Closing date: 3 November 2026") == date(2026, 11, 3)
    assert cern.find_cern_start("Ideal Start Date: 01/04/2027") == date(2027, 4, 1)


def test_cern_job_ad_and_programme():
    d = cern.parse_job_ad(CERN_DETAIL)
    assert d["deadline"] == date(2026, 10, 29)  # first cue in the text wins
    assert d["start"] == date(2027, 4, 1)
    assert "cryogenics" in d["description"]
    assert cern.programme(CERN_POSTING) == "Technical Students"


@needs_geo
def test_cern_to_opportunity():
    d = cern.parse_job_ad(CERN_DETAIL)
    d = {**d, "deadline": d["deadline"].isoformat(), "start": d["start"].isoformat()}
    opp = cern.Cern().to_opportunity(CERN_POSTING, d)
    assert opp.kind == "internship"
    assert opp.organization == "CERN"
    assert opp.locations[0].city == "Geneva" and opp.locations[0].country_code == "CH"
    assert opp.posted == date(2026, 10, 8)
    assert "Technical Students" in opp.tags


# ------------------------------------------------------------------ ESO

ESO_RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>ALMA Postdoctoral Fellows</title><pubDate>Sun, 27 Sep 2026 22:00:00 +0000</pubDate>
<link>https://recruitment.eso.org/jobs/2026_0061</link></item></channel></rss>"""

ESO_DETAIL = """<html><body><div id='col3_content'>
<blockquote><p>ALMA operations are led by NAOJ, NRAO and ESO.</p></blockquote>
<div class='hero-unit jobad-header'><h1>ALMA Postdoctoral Fellows</h1><p>Santiago</p>
<p><small>Deadline 30/10/2026</small></p></div>
<div class='jobad-maintext'><p>The JAO is offering a postdoctoral fellowship in submillimeter astronomy.</p>
<p>The European Organisation for Astronomical Research in the Southern Hemisphere (ESO) is the foremost
intergovernmental astronomy organisation in Europe.</p></div></div></body></html>"""


def test_eso_parsers():
    [item] = eso.parse_rss(ESO_RSS)
    assert item["id"] == "2026_0061"
    d = eso.parse_detail(ESO_DETAIL)
    assert d["title"] == "ALMA Postdoctoral Fellows"
    assert d["location"] == "Santiago"
    assert d["deadline"] == "2026-10-30"
    assert "submillimeter astronomy" in d["description"]
    assert "foremost" not in d["description"]  # boilerplate removed
    assert eso.kind_hint("ESO Studentship Programme Chile 2026/2027") == "phd"
    assert eso.kind_hint("Summer Students Chile 2027") == "internship"


@needs_geo
def test_eso_location():
    assert eso.eso_location("Paranal").country_code == "CL"
    assert eso.eso_location("Conduct your PhD research", "ESO Studentship Programme Chile").country_code == "CL"
    assert eso.eso_location("Garching").country_code == "DE"


# ------------------------------------------------------------------ Max Planck

MPG_ITEMS = """<li class="teaser teaser-horizontal"><div class="row"><div class="col-sm-12">
<div class="text-box"><div class="meta-information"><h3>
<a href="/27022851/postdoctoral-position-20-2026">Postdoctoral Position(s) (m/f/d) | High-Energy Astrophysics</a>
</h3><div class="data"><span class="date">October 08, 2026</span></div></div>
<div>Max Planck Institute for Extraterrestrial Physics, Garching</div></div></div></div></li>"""

MPG_DETAIL = """<html><body><div class="content"><article class="top-story"><h1>Postdoc</h1>
<div class="data"><span class="type"><span class="subject">Scientist</span></span>
<span class="city">Garching</span></div><div class="tags"><span>Astronomy &amp; Astrophysics</span></div>
<div class="description"><p class="job_code">Job Code: 20/2026</p></div></article>
<p>The High-Energy Astrophysics Group invites applications.</p></div></body></html>"""


def test_mpg_parsers():
    [item] = mpg.parse_items(MPG_ITEMS)
    assert item["id"] == "27022851"
    assert mpg.split_institute(item["institute"]) == ("Max Planck Institute for Extraterrestrial Physics", "Garching")
    d = mpg.parse_detail(MPG_DETAIL)
    assert (d["city"], d["type"], d["tags"]) == ("Garching", "Scientist", ["Astronomy & Astrophysics"])
    assert d["description"].strip().startswith("The High-Energy")


@needs_geo
def test_mpg_locations():
    assert [x.city for x in mpg.mpg_locations("Radolfzell / Constance")] == ["Radolfzell", "Konstanz"]
    assert mpg.mpg_locations("Potsdam-Golm")[0].city == "Potsdam"


# ------------------------------------------------------------------ FAPESP

FAPESP_LIST = """<ul>
<li class="box_col aberta area_16 sao-paulo tipo_1 pt"><a href="/oportunidades/Control/../projeto-x/9842/" class="link_col">
<strong class="title">Bolsa de PD</strong></a></li>
<li class="box_col aberta area_16 sao-paulo tipo_1 en"><a href="/oportunidades/Control/../projeto-x/9842/" class="link_col">
<span class="txt_col left"><strong class="title">Post-Doctoral Fellowship in Quantum Gases</strong><br>
<span class="text-principal"><strong>Instituition:</strong> Instituto de Física, USP<br>
<strong>City:</strong> São Paulo <br><strong>Deadline for submissions:</strong> 2026-10-30<br></span>
<span class="text-resumo"><p>Ultracold atoms experiment.</p></span></span></a></li></ul>"""

FAPESP_DETAIL = """<div class="col_left"><h3 class="detalhe pt">Bolsa de PD</h3>
<h3 class="detalhe en">Post-Doctoral Fellowship in Quantum Gases</h3><div class="wrap_texto">
<p class="linha"><strong>Nº:</strong> 9842</p>
<p class="linha en"><strong>Field of knowledge:   </strong> Physics</p>
<p class="linha en"><strong>Unit/Instituition: </strong> Instituto de Física, USP</p>
<p class="linha en"><strong>Deadline for submissions: </strong> 2026-10-30</p>
<p class="linha en"><strong>Publishing date: </strong> 2026-09-23</p>
<p class="linha en"><strong>Start: </strong> 2027, january</p>
<p class="linha en"><strong>Locale: </strong> São Paulo</p></div>
<ul class="list"><li class="box_col"><a href="#" class="link_col no_hover en"><strong>Activities and context</strong></a>
<div class="resumo pt"><p>Texto em português.</p></div><div class="resumo en"><p>Bose-Einstein condensates.</p></div>
</li></ul></div>"""


def test_fapesp_parsers():
    [row] = fapesp.parse_listing(FAPESP_LIST)
    assert row["id"] == "9842" and row["slug"] == "projeto-x"
    assert row["institution"] == "Instituto de Física, USP"
    assert row["deadline"] == "2026-10-30"
    d = fapesp.parse_detail(FAPESP_DETAIL)
    assert d["field"] == "Physics"
    assert d["start"] == "2027, january"
    assert "Bose-Einstein" in d["description"] and "português" not in d["description"]
    assert fapesp.title_kind("Direct Doctorate Fellowship in Physical Chemistry") == "phd"
    assert fapesp.title_kind("Level 4-Technical Training Fellowship in Chemistry") == "internship"


@needs_geo
def test_fapesp_to_opportunity():
    row = fapesp.parse_listing(FAPESP_LIST)[0]
    opp = fapesp.Fapesp().to_opportunity(row, fapesp.parse_detail(FAPESP_DETAIL))
    assert opp.kind == "postdoc"
    assert opp.deadline == date(2026, 10, 30)
    assert opp.start_date == date(2027, 1, 1)
    assert opp.locations[0].country_code == "BR"
    assert opp.source_fields == ["Physics"]


# ------------------------------------------------------------------ EMS

from jobfinder.sources import ems  # noqa: E402

EMS_LIST = """<div class="jobs"><div class="header row"><div class="cell">Title</div></div>
<a class="row" href="/jobs/two-postdoctoral-fellowships-in-inverse-problems-1866">
<div class="cell">Two Postdoctoral Fellowships in Inverse Problems</div>
<div data-column="Organization" class="cell"><span>BCAM</span></div>
<div data-column="Location" class="cell"><span>Bilbao - Spain<!-- --> </span></div>
<div data-column="Category" class="cell"><span>Postdoctoral fellowships</span></div>
<div class="cell">8 October 2026</div></a></div>"""

EMS_DETAIL = """<main><article><p class="classification">Classification: </p>
<div class="description"><p>Two 2-year postdoc positions on inverse problems for PDEs.</p></div>
<div><p><a href="https://bcamath.org">https://bcamath.org</a></p><p class="apply-by">Apply by <!-- -->21 October 2026</p></div>
</article></main>"""


def test_ems_parsers():
    [row] = ems.parse_listing(EMS_LIST)
    assert row["id"] == "1866"
    assert (row["org"], row["location"], row["category"]) == ("BCAM", "Bilbao - Spain", "Postdoctoral fellowships")
    assert row["posted"] == "8 October 2026"
    d = ems.parse_detail(EMS_DETAIL)
    assert d["deadline"] == "21 October 2026"
    assert d["website"] == "https://bcamath.org"
    assert "inverse problems" in d["description"]


@needs_geo
def test_ems_to_opportunity_and_location():
    [row] = ems.parse_listing(EMS_LIST)
    opp = ems.EuroMathSoc().to_opportunity(row, ems.parse_detail(EMS_DETAIL))
    assert opp.kind == "postdoc" and opp.disciplines == ["mathematics"]
    assert opp.deadline == date(2026, 10, 21)
    assert opp.locations[0].country_code == "ES"
    # bare ambiguous names resolve to the European city
    assert ems.ems_location("Valencia", "", "Universitat de Valencia")[0].country_code == "ES"
    assert ems.ems_location("", "", "Stockholm University")[0].city == "Stockholm"
