"""Fraunhofer source and the German field-label helper (no network)."""

import os
from datetime import date

import pytest

from jobfinder.sources._de_fields import german_fields
from jobfinder.sources.fraunhofer import GENERIC, STUDENT_TITLE, Fraunhofer
from jobfinder.taxonomy import EURAXESS_FIELD_MAP

needs_geo = pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")

LISTING_HTML = """
<table><tr class="data-row">
  <td class="colTitle"><span class="jobTitle hidden-phone">
    <a class="jobTitle-link" href="/job/Aachen-Masterarbeit-Laser-52074/1435740733/">Masterarbeit: Laserstrukturierung von Glas</a>
  </span></td>
  <td class="colShifttype"><span class="jobShifttype">Aachen</span></td>
  <td class="colFacility"><span class="jobFacility">ILT - Lasertechnik</span></td>
</tr></table>
"""

DETAIL_HTML = """
<span data-careersite-propertyid="title">Masterarbeit: Laserstrukturierung von Glas</span>
<span data-careersite-propertyid="city">Aachen</span>
<span data-careersite-propertyid="date">09.10.2026</span>
<span itemprop="streetAddress">Aachen, DE, 52074</span>
<span itemprop="industry">Laser, Optics, Engineering</span>
<span class="jobdescription"><p>Du studierst Physik oder Maschinenbau. Wir bieten spannende Forschung.</p></span>
"""


@pytest.mark.parametrize("title,keep", [
    ("Studentische Hilfskraft (m/w/d): Energietechnik", True),
    ("Masterarbeit »Wiedergewinnung eines Amins mittels Elektrodialyse«", True),
    ("Doktorand*in »Interferometrie-basierte Spektroskopie«", True),
    ("Pflichtpraktikum im Bereich Fertigungstechnologien", True),
    ("Controller*in Projektcontrolling", False),
])
def test_student_title_filter(title, keep):
    assert bool(STUDENT_TITLE.search(title)) is keep


def test_generic_applications_excluded():
    assert GENERIC.search("SPECULATIVE APPLICATION: INTERNSHIP")
    assert GENERIC.search("Initiativbewerbung Standort Aachen")


def test_german_fields_are_known_labels():
    labels = german_fields("Masterarbeit Maschinenbau", "Du studierst Elektrotechnik oder Informatik")
    assert labels == ["computer science", "electrical engineering", "mechanical engineering"]
    assert all(label in EURAXESS_FIELD_MAP for label in labels)
    assert german_fields("Controller*in Projektcontrolling") == []


def test_parse_listing_and_detail():
    rows = Fraunhofer.parse_listing(LISTING_HTML)
    assert rows[0]["id"] == "1435740733" and rows[0]["institute"] == "ILT - Lasertechnik"
    d = Fraunhofer.parse_detail(DETAIL_HTML)
    assert d["skills"] == "Laser, Optics, Engineering" and d["posted"] == "09.10.2026"


@needs_geo
def test_to_opportunity():
    row = Fraunhofer.parse_listing(LISTING_HTML)[0]
    opp = Fraunhofer().to_opportunity(row, Fraunhofer.parse_detail(DETAIL_HTML))
    assert opp.kind == "masters" and opp.organization == "Fraunhofer ILT"
    assert opp.posted == date(2026, 10, 9)
    assert opp.locations[0].city == "Aachen"
    assert opp.source_fields == ["mechanical engineering", "physics"]
