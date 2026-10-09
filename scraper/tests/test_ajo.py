"""AcademicJobsOnline / MathJobs engine: RSS, listing and detail parsers (no network)."""

import os
from datetime import date

import pytest

from jobfinder.sources._academicjobs import (
    kind_from_type,
    label_disciplines,
    parse_detail,
    parse_listing,
    parse_rss,
)
from jobfinder.sources._physmath_util import ymd
from jobfinder.sources.ajo import AcademicJobsOnline
from jobfinder.sources.mathjobs import MathJobs

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
 xmlns:ads="https://academicjobsonline.org/ajo/ads.rss" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel rdf:about="https://academicjobsonline.org/ajo"><title>AJO</title></channel>
<item rdf:about="https://academicjobsonline.org/ajo/Wake%20Forest%20University/Physics/33007?rss">
<title>Assistant Professor of Physics</title>
<link>https://academicjobsonline.org/ajo/Wake%20Forest%20University/Physics/33007?rss</link>
<description>   WAKE FOREST UNIVERSITY. The Department of Physics invites applications
   for a tenure-track faculty position in biophysics.

   Qualifications: A Ph.D. in Physics is required.</description>
<dc:creator>Wake Forest University, Physics</dc:creator>
<ads:City>Winston-Salem</ads:City>
<ads:Disciplines>Physics; Astrophysics</ads:Disciplines>
<ads:PostDate>Thu, 08 Oct 2026 12:00:00 EDT</ads:PostDate>
<ads:State>North Carolina</ads:State>
<ads:Dept>Physics</ads:Dept>
<ads:ID>33007</ads:ID>
<ads:Country>US</ads:Country>
<ads:Univ>Wake Forest University</ads:Univ>
<ads:Deadline>Sun, 15 Nov 2026 23:59:59 EST</ads:Deadline>
<ads:EndDate>Thu, 08 Apr 2027 12:00:00 EDT</ads:EndDate>
</item>
</rdf:RDF>"""

LISTING = """<html><body>
<div class="clr"><div class="rht gmap"></div><h3 class="x1"><a href="/ajo/AS">Academia Sinica</a> ,
<a href="/ajo/AS/IoP">Institute of Physics</a></h3><ol class="sp5 ldt">
<li>[<a href="/ajo/jobs/32236" id="k32236">IOPF2026</a>] <span id="j32236">Faculty Positions</span>
<span class="purplesml">(deadline 2026/10/01 11:59PM)</span>
<span class="sml"><a href="https://academicjobsonline.org/ajo/jobs/32236/apply">Apply</a></span></li>
<li>[<a href="/ajo/jobs/32878" id="k32878">PDTNPA</a>] <span id="j32878">Postdoctoral position in
Theoretical Nuclear and Particle Astrophysics</span></li>
</ol></div></body></html>"""

DETAIL = """<html><body><main><h2>Academia Sinica, Institute of Physics </h2>
<div class="grid2 nopd">
<div><b>Position ID:</b></div><div>AS-IoP-PDTNPA [#32878]</div>
<div class="nowrap"><b>Position Title:</b>&nbsp;</div><div>Postdoctoral position in Theoretical Astrophysics</div>
<div><b>Position Type:</b></div><div>Postdoctoral</div>
<div><b>Position Location:</b></div><div>Taipei, Taipei 115, Taiwan
[<a href="https://maps.google.com/maps?q=25.0536674,121.5988884">map</a>]</div>
<div class="top"><b>Subject Areas:</b>&nbsp;</div><div><a href="/ajo/physics">Physics</a> /
<a href="#">Astroparticle Physics</a>, <a href="#">Nuclear Physics</a></div>
<div class="top"><b>Appl Deadline:</b></div><div class="ldt">2026/12/31 23:59:59
(posted <span class="zo">2026/09/29</span>, listed until 2027/02/28)</div>
</div>
<section>Position Description The group invites applications for postdoctoral positions in neutrino
astrophysics.</section></main></body></html>"""


def test_parse_rss():
    [rec] = parse_rss(RSS)
    assert rec["id"] == "33007"
    assert rec["org"] == "Wake Forest University"
    assert rec["disciplines"] == ["Physics", "Astrophysics"]
    assert rec["country"] == "US" and rec["city"] == "Winston-Salem"
    # hard-wrapped lines are joined, paragraphs kept
    assert "applications for a tenure-track" in rec["description"]


def test_parse_listing():
    rows = parse_listing(LISTING, "/ajo/jobs/")
    assert [r["id"] for r in rows] == ["32236", "32878"]
    assert rows[0]["employer"] == "Academia Sinica, Institute of Physics"
    assert ymd(rows[0]["deadline"]) == date(2026, 10, 1)
    assert rows[1]["title"].startswith("Postdoctoral position")


def test_parse_detail():
    d = parse_detail(DETAIL)
    assert d["type"] == "Postdoctoral"
    assert d["location"].startswith("Taipei, Taipei 115, Taiwan")
    assert (d["lat"], d["lon"]) == (25.0536674, 121.5988884)
    assert "Nuclear Physics" in d["subjects"]
    assert ymd(d["deadline"]) == date(2026, 12, 31)
    assert ymd(d["posted"]) == date(2026, 9, 29)
    assert d["description"].startswith("The group invites")


@pytest.mark.parametrize("text,kind", [
    ("Postdoctoral", "postdoc"),
    ("Tenured/Tenure-track faculty", "job"),
    ("Graduate Student", "phd"),
    ("Undergraduate Research", "internship"),
    ("Other", None),
])
def test_kind_from_type(text, kind):
    assert kind_from_type(text) == kind


def test_label_disciplines():
    discs, subs = label_disciplines(["High Energy Physics", "Statistics", "Law"])
    assert discs == ["physics", "mathematics"]
    assert subs == ["particle-physics", "probability-statistics"]


@pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")
def test_to_opportunity_from_feed_and_detail():
    [rec] = parse_rss(RSS)
    opp = AcademicJobsOnline().to_opportunity("33007", None, rec, None)
    assert opp.url == "https://academicjobsonline.org/ajo/jobs/33007"
    assert opp.deadline == date(2026, 11, 15)
    assert opp.locations[0].city == "Winston-Salem"
    assert opp.disciplines[0] == "physics"

    det = parse_detail(DETAIL)
    opp = MathJobs().to_opportunity("32878", {"employer": "Academia Sinica, Institute of Physics"}, None, det)
    assert opp.kind == "postdoc"
    assert opp.locations[0].country_code == "TW"
    assert opp.disciplines[:2] == ["mathematics", "physics"]
    assert opp.url == "https://www.mathjobs.org/jobs/list/32878"


@pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")
def test_canadian_iso_code_is_not_california():
    rec = {"id": "1", "title": "Postdoc", "city": "Victoria", "state": "British Columbia", "country": "CA"}
    opp = MathJobs().to_opportunity("1", None, rec, None)
    assert opp.locations[0].country_code == "CA"
