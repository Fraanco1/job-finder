"""Company ATS boards (Greenhouse, Lever, Ashby, Workable, Personio, Teamtailor,
SmartRecruiters): parsing and the non-technical title filter. No network."""

import json
import os
from datetime import date

import pytest

from jobfinder.models import Location
from jobfinder.sources import _ats
from jobfinder.sources._ats import (
    fmt_salary,
    is_technical,
    kind_hint,
    load_companies,
    merge_duplicates,
    norm_contract,
    split_locations,
)
from jobfinder.sources.ashby import Ashby
from jobfinder.sources.greenhouse import Greenhouse
from jobfinder.sources.lever import Lever
from jobfinder.sources.personio import Personio
from jobfinder.sources.smartrecruiters import SmartRecruiters
from jobfinder.sources.teamtailor import Teamtailor
from jobfinder.sources.workable import Workable

# A tiny fake gazetteer so parsing tests do not need the GeoNames files.
_FAKE = {
    "bothell": ("Bothell", "US", 47.76, -122.2),
    "boulder": ("Boulder", "US", 40.01, -105.27),
    "broomfield": ("Broomfield", "US", 39.92, -105.08),
    "berkeley": ("Berkeley", "US", 37.87, -122.27),
    "fremont": ("Fremont", "US", 37.55, -121.98),
    "london": ("London", "GB", 51.5, -0.12),
    "berlin": ("Berlin", "DE", 52.52, 13.4),
    "munich": ("Munich", "DE", 48.14, 11.58),
    "münchen": ("Munich", "DE", 48.14, 11.58),
    "espoo": ("Espoo", "FI", 60.2, 24.65),
    "massy": ("Massy", "FR", 48.73, 2.27),
    "sunnyvale": ("Sunnyvale", "US", 37.37, -122.04),
    "toronto": ("Toronto", "CA", 43.7, -79.4),
    "linz": ("Linz", "AT", 48.3, 14.29),
}
_COUNTRIES = {"us": ("US", 38.9, -77.0), "united states": ("US", 38.9, -77.0), "germany": ("DE", 52.52, 13.4)}


def _fake_geocode(text, country_hint=None, city_hint=None):
    t = (text or "").lower()
    remote = "remote" in t
    for key, (city, cc, lat, lon) in _FAKE.items():
        if key in t:
            return Location(city=city, country_code=cc, lat=lat, lon=lon, remote=remote, precision="city")
    for key in (t.split(",")[-1].strip(" -"), (country_hint or "").lower(), t.replace("remote", "").strip(" -")):
        if key in _COUNTRIES:
            cc, lat, lon = _COUNTRIES[key]
            return Location(country_code=cc, lat=lat, lon=lon, remote=remote, precision="country")
    return Location(remote=remote)


@pytest.fixture(autouse=True)
def fake_geocoder(monkeypatch):
    monkeypatch.setattr(_ats, "geocode", _fake_geocode)


CO = {"token": "acme", "name": "Acme Quantum", "sector": "Quantum"}


# ---------------------------------------------------------------- title filter

@pytest.mark.parametrize("title", [
    "Software Engineer, Sales Platform",
    "Data Scientist, Marketing",
    "Quantitative Researcher",
    "Quantitative Trader",
    "Engineering Manager",
    "Physicist - Laser Systems",
    "Research Associate",
    "Additive Manufacturing Technician",
    "Electrical Engineering Intern",
    "Linux Kernel Driver Developer",
    "Flight Controls Engineer",
    "Senior PCB Designer",
    "Applications Scientist",
    "Member of Technical Staff",
    "Werkstudent Softwareentwicklung (m/w/d)",
    "Ingénieur R&D Photonique",
    "Lead Machinist",
    "Cryogenics Engineer",
])
def test_technical_titles_kept(title):
    assert is_technical(title)


@pytest.mark.parametrize("title", [
    "Technical Recruiter",
    "Sales Engineer",
    "Enterprise Account Executive",
    "Customer Success Engineer",
    "Marketing Intern",
    "Head of Legal",
    "Associate General Counsel, Product",
    "VP, Finance",
    "Senior Financial Analyst - FP&A",
    "Accounts Payable Specialist",
    "Executive Assistant to the CEO",
    "Office Manager",
    "HR Business Partner",
    "Asset Lifecycle Coordinator",
    "Chief of Staff",
    "Business Development Manager, Federal",
    "Product Designer",
    "Class A CDL Driver",
    "Cook",
    "Buyer",
    "Acheteur Projet Senior – Électronique & RF",
    "General Application",
    "Talent Community",
    "Technology Talk - University of Oxford (20th of October)",
])
def test_non_technical_titles_dropped(title):
    assert not is_technical(title)


def test_department_breaks_ties():
    assert is_technical("2026 Internship", "Engineering")
    assert not is_technical("2026 Internship", "Sales")
    assert not is_technical("Program Manager", "Marketing")
    # A strong technical title wins over a non-technical department.
    assert is_technical("Data Engineer", "Finance")


# ---------------------------------------------------------------- helpers

def test_split_locations():
    assert split_locations("London, UK; Berlin, Germany") == ["London, UK", "Berlin, Germany"]
    assert split_locations("Berkeley, CA or Fremont, CA") == ["Berkeley, CA", "Fremont, CA"]
    assert split_locations("Boulder, CO | Remote - US") == ["Boulder, CO", "Remote - US"]
    assert split_locations("") == []


def test_kind_hint_and_contract():
    assert kind_hint("Software Engineer", "Intern") == "internship"
    assert kind_hint("Co-op, Propulsion") == "internship"
    assert kind_hint("Werkstudent Robotik") == "internship"
    assert kind_hint("Software Engineer", "FullTime") is None
    assert norm_contract("FullTime") == "full-time"
    assert norm_contract("CDI") == "full-time"
    assert norm_contract("Part-time") == "part-time"
    assert norm_contract(None) is None


def test_fmt_salary():
    assert fmt_salary(240000, 275000, "USD", "per-year-salary") == "USD 240,000–275,000 per year"
    assert fmt_salary(50, None, "EUR", "per-hour-wage") == "EUR 50 per hour"
    assert fmt_salary(None, None) is None


def test_geocode_all_dedupes_and_drops_redundant_country():
    locs = _ats.geocode_all(["Berlin, Germany", "Germany", "Berlin", "Munich"])
    assert [(l.city, l.country_code) for l in locs] == [("Berlin", "DE"), ("Munich", "DE")]
    only_remote = _ats.geocode_all(["Remote"])
    assert len(only_remote) == 1 and only_remote[0].remote and only_remote[0].lat is None
    assert _ats.geocode_all(["Multiple Locations", "Hybrid"]) == []


def test_merge_duplicates_combines_locations():
    g = Greenhouse()
    a = g.parse_job(_gh_job(1, "Avionics Engineer", "Boulder, CO"), CO)
    b = g.parse_job(_gh_job(2, "Avionics Engineer", "London, UK"), CO)
    c = g.parse_job(_gh_job(3, "Optical Engineer", "Berlin, Germany"), CO)
    merged = merge_duplicates([a, b, c])
    assert len(merged) == 2
    assert [l.city for l in merged[0].locations] == ["Boulder", "London"]


def test_companies_file_is_well_formed():
    seen = set()
    for ats in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "personio", "teamtailor"):
        entries = load_companies(ats)
        assert entries, ats
        for e in entries:
            assert e["token"] and e["name"]
            assert (ats, e["token"]) not in seen
            seen.add((ats, e["token"]))
    assert len(seen) >= 120


# ---------------------------------------------------------------- Greenhouse

def _gh_job(jid, title, location, content="&lt;p&gt;Build &lt;b&gt;trapped-ion&lt;/b&gt; quantum computers.&lt;/p&gt;",
            departments=("Hardware Engineering",), metadata=()):
    return {
        "id": jid, "title": title, "absolute_url": f"https://acme.com/job?gh_jid={jid}",
        "location": {"name": location}, "content": content,
        "first_published": "2026-09-29T12:52:33-04:00", "updated_at": "2026-10-05T16:13:58-04:00",
        "departments": [{"id": 1, "name": d} for d in departments],
        "offices": [], "metadata": list(metadata), "company_name": "Acme",
    }


def test_greenhouse_parse_job():
    j = _gh_job(6107289004, "Quantum Hardware Engineer", "Bothell, Washington, United States",
                metadata=[{"name": "Employment Type", "value": "Full-time", "value_type": "single_select"}])
    o = Greenhouse().parse_job(j, CO)
    assert o.source == "greenhouse" and o.source_id == "acme:6107289004"
    assert o.organization == "Acme Quantum"
    assert o.url == "https://acme.com/job?gh_jid=6107289004"
    assert o.description == "Build trapped-ion quantum computers."  # HTML-escaped content decoded
    assert o.posted == date(2026, 9, 29)
    assert o.contract == "full-time"
    assert o.kind == "job"
    assert [(l.city, l.country_code) for l in o.locations] == [("Bothell", "US")]
    assert o.source_fields == ["Hardware Engineering"]


def test_greenhouse_filters_and_internships():
    g = Greenhouse()
    assert g.parse_job(_gh_job(1, "Senior Technical Recruiter", "Boulder, CO"), CO) is None
    assert g.parse_job(_gh_job(2, "Office Coordinator", "Boulder, CO", departments=("G&A",)), CO) is None
    intern = g.parse_job(_gh_job(3, "Summer Intern, Photonics", "London, UK; Berlin, Germany"), CO)
    assert intern.kind == "internship"
    assert [l.city for l in intern.locations] == ["London", "Berlin"]


def test_greenhouse_fetch_board(monkeypatch):
    g = Greenhouse()
    payload = {"jobs": [_gh_job(1, "Laser Physicist", "Boulder, CO"),
                        _gh_job(2, "Account Executive", "Boulder, CO"),
                        _gh_job(3, "Laser Physicist", "Bothell, WA")]}
    monkeypatch.setattr(g.http, "get_json", lambda url, **kw: payload)
    items = g._safe_board(CO)
    assert [o.title for o in items] == ["Laser Physicist"]
    assert {l.city for l in items[0].locations} == {"Boulder", "Bothell"}


# ---------------------------------------------------------------- Lever

LEVER_JOB = {
    "id": "38071b28-19a4", "text": "Cryogenic Systems Engineer",
    "categories": {"commitment": "Full-time", "department": "QPU", "team": "Hardware Engineering",
                   "location": "Berkeley, CA or Fremont, CA",
                   "allLocations": ["Berkeley, CA or Fremont, CA"]},
    "country": "US", "workplaceType": "onsite", "createdAt": 1783628474915,
    "descriptionPlain": "Design dilution refrigerators for superconducting qubits.",
    "lists": [{"text": "What you'll do", "content": "<li>Build cryostats</li><li>Test RF lines</li>"}],
    "additionalPlain": "Equal opportunity employer.",
    "salaryRange": {"min": 140000, "max": 175000, "currency": "USD", "interval": "per-year-salary"},
    "hostedUrl": "https://jobs.lever.co/acme/38071b28-19a4",
}


def test_lever_parse_job():
    o = Lever().parse_job(LEVER_JOB, CO)
    assert o.source_id == "acme:38071b28-19a4"
    assert o.url == "https://jobs.lever.co/acme/38071b28-19a4"
    assert "superconducting qubits" in o.description and "Build cryostats" in o.description
    assert o.salary == "USD 140,000–175,000 per year"
    assert o.contract == "full-time"
    assert o.posted == date(2026, 7, 9)
    assert [l.city for l in o.locations] == ["Berkeley", "Fremont"]


def test_lever_country_prefix_and_intern():
    j = dict(LEVER_JOB, text="Quantum Software Intern",
             categories={"commitment": "Intern", "location": "US Broomfield, CO",
                         "allLocations": ["US Broomfield, CO"]})
    o = Lever().parse_job(j, CO)
    assert o.kind == "internship" and o.contract == "internship"
    assert [l.city for l in o.locations] == ["Broomfield"]
    assert Lever().parse_job(dict(LEVER_JOB, text="Director of Talent Acquisition"), CO) is None


# ---------------------------------------------------------------- Ashby

ASHBY_JOB = {
    "id": "8fb1615c", "title": "Photonics Test Engineer", "department": "Hardware", "team": "Test",
    "employmentType": "FullTime", "location": "Sunnyvale, CA", "isListed": True, "isRemote": True,
    "workplaceType": "Hybrid",
    "secondaryLocations": [{"location": "Toronto, CAN", "address": {"postalAddress": {
        "addressLocality": "Toronto", "addressRegion": "Ontario", "addressCountry": "Canada"}}}],
    "publishedAt": "2026-03-12T16:38:15.322+00:00",
    "address": {"postalAddress": {"addressLocality": "Sunnyvale", "addressRegion": "California",
                                  "addressCountry": "United States"}},
    "jobUrl": "https://jobs.ashbyhq.com/acme/8fb1615c",
    "descriptionPlain": "Characterize silicon photonics transceivers.",
    "shouldDisplayCompensationOnJobPostings": True,
    "compensation": {"scrapeableCompensationSalarySummary": "$150K - $200K"},
}


def test_ashby_parse_job():
    o = Ashby().parse_job(ASHBY_JOB, CO)
    assert o.source_id == "acme:8fb1615c"
    assert o.url == "https://jobs.ashbyhq.com/acme/8fb1615c"
    assert o.salary == "$150K - $200K"
    assert o.contract == "full-time"
    assert o.posted == date(2026, 3, 12)
    assert [l.city for l in o.locations] == ["Sunnyvale", "Toronto"]
    assert not any(l.remote for l in o.locations)  # hybrid is not remote


def test_ashby_skips_unlisted_and_nontech():
    assert Ashby().parse_job(dict(ASHBY_JOB, isListed=False), CO) is None
    assert Ashby().parse_job(dict(ASHBY_JOB, title="Head of Marketing", department="Marketing"), CO) is None
    intern = Ashby().parse_job(dict(ASHBY_JOB, title="Hardware Engineer", employmentType="Intern"), CO)
    assert intern.kind == "internship"


# ---------------------------------------------------------------- Workable

def test_workable_parse_job():
    j = {"title": "AI scientist for Quantum Computing (Massy)", "shortcode": "F1AC80AB01",
         "employment_type": "Full-time", "telecommuting": False, "department": "Research",
         "url": "https://apply.workable.com/j/F1AC80AB01", "published_on": "2026-08-25",
         "country": "France", "city": "Massy", "state": "Île-de-France", "experience": "Mid-Senior level",
         "locations": [{"country": "France", "countryCode": "FR", "city": "Massy", "region": "Île-de-France",
                        "hidden": False}],
         "description": "<p>Spin-photonic <b>quantum</b> computers.</p>"}
    o = Workable().parse_job(j, CO)
    assert o.source_id == "acme:F1AC80AB01"
    assert o.description == "Spin-photonic quantum computers."
    assert o.posted == date(2026, 8, 25)
    assert [l.city for l in o.locations] == ["Massy"]
    assert Workable().parse_job(dict(j, title="Export Control Officer"), CO) is None


# ---------------------------------------------------------------- Personio

PERSONIO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
<position>
  <id>2791761</id><subcompany>ACME GMBH</subcompany>
  <office>München</office>
  <additionalOffices><office>Hybrid</office></additionalOffices>
  <department>Engineering</department><recruitingCategory>Permanent</recruitingCategory>
  <name>Cryo Engineer (f/m/d)</name>
  <jobDescriptions><jobDescription><name>Your tasks</name>
    <value><![CDATA[<p>Build adiabatic demagnetization refrigerators.</p>]]></value>
  </jobDescription></jobDescriptions>
  <employmentType>permanent</employmentType><schedule>full-time</schedule>
  <occupationCategory>engineering</occupationCategory>
  <createdAt>2026-09-10T11:59:28+00:00</createdAt>
</position>
<position>
  <id>2791762</id><office>München</office><department>Marketing</department>
  <name>Communications &amp; Events Manager</name>
  <occupationCategory>marketing_and_product</occupationCategory>
  <createdAt>2026-09-10T11:59:28+00:00</createdAt>
</position>
<position>
  <id>2791763</id><office>Kiutra GmbH</office><department>R&amp;D</department>
  <name>Werkstudent Physik (m/w/d)</name><schedule>part-time</schedule>
  <createdAt>2026-09-11T11:59:28+00:00</createdAt>
</position>
</workzag-jobs>""".encode()


def test_personio_parse_feed():
    items = Personio().parse_feed(PERSONIO_XML, dict(CO, hq="Munich, Germany"))
    assert [o.title for o in items] == ["Cryo Engineer (f/m/d)", "Werkstudent Physik (m/w/d)"]
    a, b = items
    assert a.url == "https://acme.jobs.personio.com/job/2791761"
    assert "adiabatic demagnetization" in a.description
    assert a.contract == "full-time" and a.posted == date(2026, 9, 10)
    assert [l.city for l in a.locations] == ["Munich"]
    assert b.kind == "internship" and b.contract == "part-time"
    assert [l.city for l in b.locations] == ["Munich"]  # unknown office -> company HQ


# ---------------------------------------------------------------- Teamtailor

TEAMTAILOR_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:tt="https://teamtailor.com/locations"><channel><title>Acme</title>
<item>
  <title>Design Engineer, Microelectronics Packaging</title>
  <description>&lt;p&gt;Package superconducting &lt;b&gt;QPUs&lt;/b&gt;.&lt;/p&gt;</description>
  <pubDate>Fri, 25 Sep 2026 08:54:31 +0300</pubDate>
  <link>https://acme.teamtailor.com/jobs/1-design-engineer</link>
  <remoteStatus>none</remoteStatus><guid>bdabd2d5</guid>
  <tt:locations>
    <tt:location><tt:name>Acme Finland</tt:name><tt:city>Espoo</tt:city><tt:country>Finland</tt:country></tt:location>
    <tt:location><tt:name>Acme Germany</tt:name><tt:city>München</tt:city><tt:country>Germany</tt:country></tt:location>
  </tt:locations>
  <tt:department>Hardware</tt:department>
</item>
<item>
  <title>VP, Sales</title><description>x</description><link>https://acme.teamtailor.com/jobs/2</link>
  <guid>c0ffee</guid><tt:department>Commercial</tt:department>
</item>
</channel></rss>""".encode()


def test_teamtailor_parse_feed():
    items = Teamtailor().parse_feed(TEAMTAILOR_RSS, CO)
    assert len(items) == 1
    o = items[0]
    assert o.source_id == "acme:bdabd2d5"
    assert o.description == "Package superconducting QPUs ."
    assert o.posted == date(2026, 9, 25)
    assert [l.city for l in o.locations] == ["Espoo", "Munich"]


# ---------------------------------------------------------------- SmartRecruiters

SR_LISTING = {"offset": 0, "limit": 100, "totalFound": 3, "content": [
    {"id": "744000154587989", "name": "Senior MES/IT Engineer (w/m/div.)",
     "releasedDate": "2026-10-09T05:17:59.202Z",
     "location": {"city": "Linz", "region": "OÖ", "country": "at", "remote": False},
     "function": {"id": "engineering", "label": "Engineering"},
     "typeOfEmployment": {"id": "permanent", "label": "Full-time"},
     "experienceLevel": {"id": "mid_senior_level", "label": "Mid-Senior Level"}},
    {"id": "744000154587990", "name": "Senior Process associate",
     "location": {"city": "Linz", "country": "at"},
     "function": {"id": "accounting_auditing", "label": "Accounting/Auditing"}},
    {"id": "744000154587991", "name": "Key Account Manager",
     "location": {"city": "Linz", "country": "at"},
     "function": {"id": "engineering", "label": "Engineering"}},
]}
SR_DETAIL = {"postingUrl": "https://jobs.smartrecruiters.com/Acme/744000154587989-senior-mes",
             "jobAd": {"sections": {"jobDescription": {"text": "<p>Run the manufacturing execution system.</p>"},
                                    "qualifications": {"text": "<ul><li>Degree in computer science</li></ul>"}}}}


def test_smartrecruiters_fetch_board(monkeypatch, tmp_path):
    monkeypatch.setattr("jobfinder.sources.base.CACHE_DIR", tmp_path)
    sr = SmartRecruiters()
    calls = []

    def fake_get_json(url, **kw):
        calls.append(url)
        return SR_DETAIL if url.endswith("744000154587989") else SR_LISTING

    monkeypatch.setattr(sr.http, "get_json", fake_get_json)
    items = sr.fetch_board({"token": "Acme", "name": "Acme", "sector": "Industrial R&D", "max": 10})
    assert len(items) == 1
    o = items[0]
    # only the technical posting's detail record is requested
    assert sum(1 for c in calls if c.endswith("/postings/744000154587989")) == 1 and len(calls) == 2
    assert o.url == SR_DETAIL["postingUrl"]
    assert "manufacturing execution system" in o.description and "computer science" in o.description
    assert o.posted == date(2026, 10, 9) and o.contract == "full-time"
    assert [l.city for l in o.locations] == ["Linz"]


# ---------------------------------------------------------------- real geocoder on ATS strings

@pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")
@pytest.mark.parametrize("raw,city,cc", [
    ("Bothell, Washington, United States", "Bothell", "US"),
    ("Hawthorne, CA", "Hawthorne", "US"),
    ("Pune (on-site)", "Pune", "IN"),
    ("Delft", "Delft", "NL"),
])
def test_real_geocoder_on_ats_strings(monkeypatch, raw, city, cc):
    from jobfinder.geocode import geocode
    monkeypatch.setattr(_ats, "geocode", geocode)
    locs = _ats.geocode_all([raw])
    assert (locs[0].city, locs[0].country_code) == (city, cc)


def test_companies_json_parses():
    data = json.loads(_ats.COMPANIES_FILE.read_text())
    assert set(data) >= {"greenhouse", "lever", "ashby"}
