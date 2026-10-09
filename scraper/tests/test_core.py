"""Unit tests for the deterministic core: dates, classification, geocoding, pipeline rules."""

from datetime import date, timedelta

import pytest

from jobfinder.classify import classify_fields, enrich, infer_kind, required_degrees
from jobfinder.dates import find_deadline, find_start, parse_date
from jobfinder.models import Opportunity
from jobfinder.pipeline import normalize


# ---------------------------------------------------------------- dates

@pytest.mark.parametrize("text,expected", [
    ("12 Nov 2026 - 23:59 (Europe/Bucharest)", date(2026, 11, 12)),
    ("2026-12-01", date(2026, 12, 1)),
    ("November 5, 2026", date(2026, 11, 5)),
    ("01.03.2027", date(2027, 3, 1)),
    ("not a date", None),
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_find_deadline_and_start():
    text = ("We offer a fully funded PhD. Application deadline: 30 November 2026. "
            "The position starts in Fall 2027.")
    assert find_deadline(text) == date(2026, 11, 30)
    assert find_start(text) == date(2027, 9, 1)


# ---------------------------------------------------------------- kinds

@pytest.mark.parametrize("title,kind", [
    ("PhD position in quantum optics", "phd"),
    ("Doctoral candidate in surface physics (ESR 7)", "phd"),
    ("Postdoctoral researcher in condensed matter theory", "postdoc"),
    ("Research Fellow in Electrochemistry", "postdoc"),
    ("Summer Internship - RF Engineering", "internship"),
    ("Werkstudent Hardware Engineering (m/w/d)", "internship"),
    ("Master thesis: FPGA readout for MKIDs", "masters"),
    ("Senior Optical Engineer", "job"),
])
def test_infer_kind(title, kind):
    assert infer_kind(title) == kind


def test_postdoc_title_beats_phd_requirement():
    assert infer_kind("Postdoc in astrophysics", "A PhD in physics is required.") == "postdoc"


def test_washington_dc_is_not_a_doctoral_candidate():
    assert infer_kind("Optical Engineer - Washington DC") == "job"


# ---------------------------------------------------------------- fields

def test_classify_quantum_physics():
    disc, subs = classify_fields(
        "PhD position in superconducting qubits",
        "Join our quantum computing lab working on superconducting circuits and quantum error correction.",
    )
    assert disc[0] == "physics"
    assert "quantum-computing" in subs


def test_classify_uses_source_fields():
    disc, subs = classify_fields("Researcher", "", ["Physics » Surface physics"])
    assert disc == ["physics"]
    assert subs == ["surface-physics"]


def test_classify_non_stem_is_empty():
    disc, _ = classify_fields("Postdoc in Political Science", "Transitional justice and survey experiments.")
    assert disc == []


def test_required_degrees():
    body = ("Requirements: a Master's degree in Physics, Electrical Engineering or a related field. "
            "Experience with Python is a plus.")
    req = required_degrees("PhD in detector development", body)
    assert "physics" in req and "electrical-engineering" in req
    assert "chemistry" not in req


def test_physicist_title_counts_as_requirement():
    assert "physics" in required_degrees("Laser Physicist", "Build ultrafast laser systems.")


# ---------------------------------------------------------------- pipeline rules

def _opp(**kw):
    base = dict(source="t", source_id="1", url="https://x", title="PhD in condensed matter physics",
                description="Superconductivity and magnetism in quantum materials.")
    base.update(kw)
    return Opportunity(**base)


def test_normalize_drops_expired_and_non_stem():
    assert normalize(_opp(deadline=date.today() - timedelta(days=1))) is None
    assert normalize(_opp(title="Lecturer in Medieval History", description="Medieval manuscripts.")) is None
    assert normalize(_opp()) is not None


def test_normalize_drops_non_technical_titles():
    assert normalize(_opp(title="Internship in Graphic Design")) is None
    assert normalize(_opp(title="Talent Acquisition Partner, Quantum Hardware")) is None
    assert normalize(_opp(title="RF Communications Engineer")) is not None


def test_normalize_past_start_means_asap():
    o = normalize(_opp(start_date=date.today() - timedelta(days=10)))
    assert o.start_date is None and o.start_text == "As soon as possible"


def test_enrich_sets_kind_and_fields():
    o = enrich(_opp())
    assert o.kind == "phd"
    assert "physics" in o.disciplines and "condensed-matter" in o.subfields


# ---------------------------------------------------------------- industry edge cases

def test_company_boilerplate_phds_do_not_make_a_phd_position():
    body = "Axelera has 60+ PhDs on staff building AI accelerators. You will test silicon."
    assert infer_kind("Test Technician", body) == "job"


def test_industry_research_associate_is_a_job():
    assert infer_kind("Research Associate II, Assay Development") == "job"
    assert infer_kind("Postdoctoral Research Associate in Photonics") == "postdoc"


def test_phd_required_industry_titles_are_jobs():
    assert infer_kind("ML Engineer (PhD, New Grad)") == "job"
    assert infer_kind("Graduate Quantitative Researcher, PhD (2027 Start)") == "job"
    assert infer_kind("PhD Researcher in Quantum Materials") == "phd"


def test_infrastructure_is_not_civil_engineering():
    disc, _ = classify_fields("Site Reliability Engineer, Data Infrastructure", "Kubernetes and cloud infrastructure.")
    assert "civil-engineering" not in disc and "computer-science" in disc


def test_industry_hardware_vocabulary():
    disc, _ = classify_fields("Digital Mixed Signal Verification Engineer", "RTL design verification of mixed-signal chips.")
    assert disc and disc[0] == "electrical-engineering"


def test_employer_boilerplate_does_not_override_the_title():
    boiler = ("IonQ builds quantum computers. Our quantum computers use trapped ions and lasers. "
              "Join the quantum revolution with photonics. ")
    disc, _ = classify_fields("IT Network Engineer II", boiler)
    assert disc == ["computer-science"]
    disc, _ = classify_fields("AI Research Engineer - Foundation Models", "Train foundation models.")
    assert disc == ["computer-science"]
