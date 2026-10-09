"""DAAD International Programmes database (study in Germany).

Master's, PhD and graduate-school programmes taught (mostly) in English. The
search page is backed by a public JSON endpoint; we query it filtered to the
STEM subject groups and the master/PhD/graduate-school degree types, then
fetch each programme's detail page once (cached) for the description, the
admission requirements and the application periods per semester.

A programme is not a single position, so each one becomes an Opportunity
with ``deadline`` = next application deadline and ``start_date`` = start of
the semester that deadline belongs to (winter semester -> 1 October, summer
semester -> 1 April).
"""

from __future__ import annotations

import html as htmllib
import re
from datetime import date

from ..dates import parse_date
from ..geocode import geocode
from ..models import Opportunity
from .base import DetailCache, Source, html_to_text, soup

BASE = "https://www2.daad.de"
APP = BASE + "/deutschland/studienangebote/international-programmes"
SEARCH = APP + "/api/solr/en/search.json"

# Degree facet ids -> our kind.
DEGREES = {2: "masters", 3: "phd", 4: "phd"}  # master / PhD-doctorate / graduate school
DEGREE_LABELS = {2: "Master's degree", 3: "PhD / Doctorate", 4: "Graduate school"}
# Subject-group facet ids.
SUBJECT_GROUPS = {56: "Engineering Sciences", 193: "Mathematics, Natural Sciences"}

PAGE_SIZE = 500

_MONTHS = ("january|february|march|april|may|june|july|august|september|october|"
           "november|december")
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})\.?\s+({_MONTHS})\b(?:\s+(\d{{4}}))?", re.I)
_EXPLICIT_DATE = re.compile(rf"\b\d{{1,2}}\.?\s+(?:{_MONTHS})\s+\d{{4}}\b|\b\d{{4}}-\d{{2}}-\d{{2}}\b", re.I)


def semester_start(semester: str, after: date) -> date:
    """First day of the given semester strictly after ``after``.

    German winter semesters start on 1 October, summer semesters on 1 April.
    """
    month = 10 if semester == "winter" else 4
    d = date(after.year, month, 1)
    return d if d > after else date(after.year + 1, month, 1)


def next_occurrence(day: int, month: int, today: date) -> date | None:
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d >= today:
            return d
    return None


def parse_periods(text: str, today: date | None = None) -> list[tuple[str | None, date]]:
    """Parse the "Application periods" block into (semester, next deadline) pairs.

    Blocks look like ``For the winter semester: until 30 April`` (one block per
    applicant group / semester). The deadline is the last date in the block
    (the end of the period); missing years resolve to the next occurrence.
    """
    today = today or date.today()
    out: list[tuple[str | None, date]] = []
    for block in re.split(r"\n\s*-{3,}\s*\n|<hr\s*/?>", text):
        low = block.lower()
        sem = "winter" if "winter semester" in low else "summer" if "summer semester" in low else None
        dates = list(_DAY_MONTH.finditer(block))
        if not dates:
            continue
        m = dates[-1]
        day, mon = int(m.group(1)), parse_date(f"1 {m.group(2)} 2000").month
        if m.group(3):
            try:
                d = date(int(m.group(3)), mon, day)
            except ValueError:
                continue
            if d < today:
                continue
        else:
            d = next_occurrence(day, mon, today)
            if d is None:
                continue
        out.append((sem, d))
    return out


def locate(city: str | None):
    """Geocode a DAAD course location ("Garching b. München", "Lambaréné (Gabon)")."""
    if not city:
        return geocode(None, country_hint="Germany")
    country = "Germany"
    m = re.match(r"(.*?)\s*\(([^)]+)\)\s*$", city)
    if m:
        city, country = m.group(1), m.group(2)
    short = re.split(r"\s+(?:b\.|bei|im|in der|an der|am|ob der)\s+", city)[0]
    for text, hint in ((city, country), (short, country), (city, None)):
        g = geocode(text, country_hint=hint)
        if g.precision == "city" or (hint is None and g.lat is not None):
            return g
    return geocode(None, country_hint=country)


def first_explicit_date(text: str | None) -> date | None:
    if not text:
        return None
    m = _EXPLICIT_DATE.search(text)
    return parse_date(m.group(0)) if m else None


class Daad(Source):
    id = "daad"
    name = "DAAD International Programmes"
    homepage = APP + "/en/"
    min_interval = 0.6

    # ------------------------------------------------------------ listing

    def search(self, offset: int) -> dict:
        params: list[tuple[str, str | int]] = [("degree[]", d) for d in DEGREES]
        params += [("subjectGroup[]", g) for g in SUBJECT_GROUPS]
        params += [("limit", PAGE_SIZE), ("offset", offset), ("sort", 4), ("display", "list")]
        r = self.http.get(SEARCH, params=params)
        r.raise_for_status()
        return r.json()

    def crawl_listing(self) -> list[dict]:
        rows: list[dict] = []
        seen: set[int] = set()
        offset = 0
        while True:
            data = self.search(offset)
            courses = data.get("courses") or []
            new = [c for c in courses if c.get("id") not in seen]
            if not new:
                break
            for c in new:
                seen.add(c["id"])
            rows.extend(new)
            self.log.info("listing offset %d: %d programmes (of %s)", offset, len(rows), data.get("numResults"))
            if self.limit and len(rows) >= self.limit:
                return rows[: self.limit]
            offset += len(courses)
            if offset >= int(data.get("numResults") or 0):
                break
        return rows

    # ------------------------------------------------------------ detail

    @staticmethod
    def parse_detail(html: str) -> dict:
        s = soup(html)
        fields: dict[str, str] = {}
        for dt in s.select("dt"):
            dd = dt.find_next_sibling("dd")
            if dd is None:
                continue
            key = dt.get_text(" ", strip=True)
            if key in fields:
                continue
            for hr in dd.find_all("hr"):
                hr.replace_with("\n---\n")
            fields[key] = html_to_text(str(dd))
        return {
            "degree": fields.get("Degree"),
            "beginning": fields.get("Beginning"),
            "periods": fields.get("Application periods") or fields.get("Application deadline"),
            "description": fields.get("Description/content"),
            "organisation": fields.get("Course organisation"),
            "requirements": fields.get("Academic admission requirements"),
            "duration": fields.get("Programme duration"),
            "fees": fields.get("Tuition fees per semester"),
            "funding": fields.get("Funding opportunities within the university"),
        }

    def fetch_detail(self, cid: int) -> dict | None:
        r = self.http.get(f"{APP}/en/detail/{cid}/", allow_redirects=True)
        if r.status_code != 200:
            return None
        return self.parse_detail(r.text)

    # ------------------------------------------------------------ main

    def fetch(self):
        rows = self.crawl_listing()
        cache = DetailCache(self.id)
        todo = [c for c in rows if cache.get(str(c["id"])) is None]
        self.log.info("%d programmes, %d new detail pages", len(rows), len(todo))
        for i, c in enumerate(todo):
            try:
                d = self.fetch_detail(c["id"])
            except Exception as e:  # noqa: BLE001
                self.log.warning("detail %s failed: %s", c["id"], e)
                continue
            if d:
                cache.set(str(c["id"]), d)
            if i and i % 100 == 0:
                self.log.info("details %d/%d", i, len(todo))
                cache.save()
        cache.save()
        for c in rows:
            yield self.to_opportunity(c, cache.get(str(c["id"])) or {})

    def to_opportunity(self, c: dict, d: dict, today: date | None = None) -> Opportunity:
        today = today or date.today()
        ctype = int(c.get("courseType") or 2)
        kind = DEGREES.get(ctype, "masters")
        raw_deadline = html_to_text(htmllib.unescape(c.get("applicationDeadline") or ""))

        # --- deadline: the listing states the next one ("Register by 31 October 2026 + 1 more")
        # Periods differ per applicant group (EU / non-EU); the earliest upcoming
        # one is the safe deadline for an international audience.
        periods = parse_periods(d.get("periods") or "", today)
        deadline = min(p[1] for p in periods) if periods else first_explicit_date(raw_deadline)

        # --- start: semester tied to that deadline
        beginning = (d.get("beginning") or c.get("beginning") or "").strip()
        bl = beginning.lower()
        semesters = [s for s in ("winter", "summer") if s in bl]
        sem = None
        if deadline:
            match = [p[0] for p in periods if p[1] == deadline and p[0]]
            if match:
                sem = match[0]
            elif len(semesters) == 1:
                sem = semesters[0]
        elif len(semesters) == 1:
            sem = semesters[0]
        start_date = semester_start(sem, deadline or today) if sem else None
        if start_date:
            y = start_date.year
            start_text = (f"Winter semester {y}/{str(y + 1)[-2:]}" if sem == "winter"
                          else f"Summer semester {y}")
        else:
            start_text = beginning or None

        subject = (c.get("subject") or "").strip()
        degree = d.get("degree") or DEGREE_LABELS.get(ctype)
        parts = []
        if degree:
            parts.append(f"{DEGREE_LABELS.get(ctype, '')}: {degree}.")
        if subject:
            parts.append(f"Subject: {subject}.")
        for key in ("description", "organisation"):
            if d.get(key):
                parts.append(d[key])
        if d.get("requirements"):
            parts.append("Admission requirements: " + d["requirements"])
        if c.get("programmeDuration"):
            parts.append(f"Duration: {c['programmeDuration']}.")
        if c.get("tuitionFees"):
            parts.append(f"Tuition: {c['tuitionFees']}.")
        if raw_deadline and not deadline:
            parts.append(f"Application deadline: {raw_deadline}")
        description = "\n".join(p for p in parts if p)

        title = (c.get("courseName") or "").strip()
        if kind == "masters" and degree and not re.search(r"\bmaster|\bm\.?\s?sc|\bm\.?\s?eng", title, re.I):
            title = f"{title} ({degree})"
        city = c.get("city")
        loc = locate(city)
        tags = [x for x in (DEGREE_LABELS.get(ctype), c.get("tuitionFees"),
                            ", ".join(c.get("languages") or []) or None) if x]
        return Opportunity(
            source=self.id,
            source_id=str(c["id"]),
            url=BASE + (c.get("link") or f"/deutschland/studienangebote/international-programmes/en/detail/{c['id']}/"),
            title=title,
            organization=c.get("academy"),
            kind=kind,
            description=description,
            locations=[loc] if loc.lat is not None else [],
            deadline=deadline,
            start_date=start_date,
            start_text=start_text,
            # required prior degree: a bachelor's for a master's programme, a master's for a PhD
            education_level="masters" if kind == "phd" else "bachelor",
            source_fields=[x for x in [subject] if x],
            tags=tags,
        )
