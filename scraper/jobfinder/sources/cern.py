"""CERN careers (https://careers.cern).

CERN publishes every opening (staff, graduates, fellows, doctoral and
technical students, summer students, trainees) on SmartRecruiters, which has
a public, documented posting API. We list postings and fetch each posting's
job ad once (cached) for the description, deadline and start date.
"""

from __future__ import annotations

import re
from datetime import date

from ..dates import parse_date, parse_timestamp
from ..geocode import geocode
from ..models import Opportunity
from ._physmath_util import country_name
from .base import DetailCache, Source, html_to_text

API = "https://api.smartrecruiters.com/v1/companies/CERN/postings"

# CERN "Programme" custom field -> kind.
PROGRAMME_KIND = {
    "doctoral students": "phd",
    "technical students": "internship",
    "administrative students": "internship",
    "summer students": "internship",
    "openlab summer students": "internship",
    "trainees": "internship",
    "research fellows": "postdoc",
    "senior fellows": "postdoc",
}

_DATE_NUM = r"(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{2,4})"
_DEADLINE = re.compile(
    r"(?:closing date|application deadline|deadline for applications?)\s*:?\s*(?:is\s+)?" + _DATE_NUM, re.I)
_DEADLINE_WORDS = re.compile(
    r"(?:closing date|application deadline|deadline for applications?)\s*:?\s*(?:is\s+)?"
    r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I)
_START = re.compile(r"(?:ideal |earliest )?start(?:ing)? date\s*:?\s*" + _DATE_NUM, re.I)


def _num_date(d: str, m: str, y: str) -> date | None:
    year = int(y)
    if year < 100:
        year += 2000
    try:
        return date(year, int(m), int(d))
    except ValueError:
        return None


def find_cern_deadline(text: str) -> date | None:
    m = _DEADLINE.search(text)
    if m:
        return _num_date(*m.groups())
    m = _DEADLINE_WORDS.search(text)
    return parse_date(m.group(1)) if m else None


def find_cern_start(text: str) -> date | None:
    m = _START.search(text)
    return _num_date(*m.groups()) if m else None


def programme(posting: dict) -> str | None:
    for f in posting.get("customField") or []:
        if f.get("fieldLabel") == "Programme":
            return f.get("valueLabel")
    return None


def parse_job_ad(detail: dict) -> dict:
    sections = ((detail.get("jobAd") or {}).get("sections")) or {}
    parts = []
    for key in ("jobDescription", "qualifications", "additionalInformation", "companyDescription"):
        sec = sections.get(key) or {}
        text = html_to_text(sec.get("text"))
        if text:
            parts.append(text)
    text = "\n".join(parts)
    return {
        "description": text[:12000],
        "deadline": (find_cern_deadline(text) or None),
        "start": (find_cern_start(text) or None),
        "url": detail.get("postingUrl"),
    }


class Cern(Source):
    id = "cern"
    name = "CERN Careers"
    homepage = "https://careers.cern/"
    min_interval = 0.5

    def fetch(self):
        postings: list[dict] = []
        offset = 0
        while True:
            data = self.http.get_json(API, params={"limit": 100, "offset": offset})
            batch = data.get("content") or []
            postings.extend(batch)
            offset += len(batch)
            if not batch or offset >= data.get("totalFound", 0):
                break
        self.log.info("%d postings", len(postings))
        if self.limit:
            postings = postings[: self.limit]

        cache = DetailCache(self.id)
        for p in postings:
            pid = str(p["id"])
            if cache.get(pid) is None:
                try:
                    d = parse_job_ad(self.http.get_json(f"{API}/{pid}"))
                    d["deadline"] = d["deadline"].isoformat() if d["deadline"] else None
                    d["start"] = d["start"].isoformat() if d["start"] else None
                    cache.set(pid, d)
                except Exception as e:  # noqa: BLE001
                    self.log.warning("posting %s failed: %s", pid, e)
        cache.save()

        for p in postings:
            yield self.to_opportunity(p, cache.get(str(p["id"])) or {})

    def to_opportunity(self, p: dict, d: dict) -> Opportunity:
        loc = p.get("location") or {}
        g = geocode(loc.get("city"), country_hint=country_name(loc.get("country") or "CH"))
        prog = programme(p)
        kind = PROGRAMME_KIND.get((prog or "").lower())
        if kind is None and (p.get("experienceLevel") or {}).get("id") == "internship":
            kind = "internship"
        title = re.sub(r"\s+", " ", p.get("name") or "").strip()
        dept = (p.get("department") or {}).get("label")
        func = (p.get("function") or {}).get("label")
        start = parse_date(d.get("start"))
        return Opportunity(
            source=self.id,
            source_id=str(p["id"]),
            url=d.get("url") or f"https://jobs.smartrecruiters.com/CERN/{p['id']}",
            title=title,
            organization="CERN",
            kind=kind or "job",
            description=d.get("description") or "",
            locations=[g] if g.lat is not None else [],
            posted=parse_timestamp(p.get("releasedDate")),
            deadline=parse_date(d.get("deadline")),
            start_date=start,
            contract=(p.get("typeOfEmployment") or {}).get("label"),
            source_fields=[x for x in (func,) if x and x.lower() not in ("research", "other")],
            tags=[t for t in (prog, f"Department {dept}" if dept else None) if t],
        )

