"""Fraunhofer-Gesellschaft: theses, internships, student-assistant and PhD jobs in Germany.

jobs.fraunhofer.de is a SAP SuccessFactors career site; the HTML search table
(``/search/?startrow=N``, 25 rows per page; robots.txt only blocks the
``/services/`` feeds and apply flows) lists title, city and institute for
all ~750 vacancies. We keep student / early-career roles by title
(Masterarbeit, Abschlussarbeit, Praktikum, Studentische Hilfskraft,
Werkstudent, Promotion, PhD, ...) and fetch each advert once (cached).
Adverts are mostly German, so subject words are translated to field labels
via ``_de_fields``.
"""

from __future__ import annotations

import re

from ..dates import parse_date
from ..geocode import geocode
from ..models import Opportunity
from ._de_fields import german_fields
from .base import DetailCache, Source, html_to_text, soup

BASE = "https://jobs.fraunhofer.de"
PAGE = 25

STUDENT_TITLE = re.compile(
    r"studentisch\w*|hilfskr\w*|hiwi|werkstudent\w*|praktik\w*|abschlussarbeit\w*|masterarbeit\w*|"
    r"bachelorarbeit\w*|thesis|internship|\bintern\b|promotion\w*|doktorand\w*|ph\.?\s?d|promovier\w*|"
    r"studienarbeit\w*|\bstudent\w*|studierende\w*", re.I)
GENERIC = re.compile(r"initiativbewerbung|unsolicited|bewirb dich hier|spontaneous application|"
                     r"speculative application", re.I)

TITLE_KIND = [
    ("phd", re.compile(r"promotion\w*|doktorand\w*|ph\.?\s?d|promovier\w*|doctoral", re.I)),
    ("masters", re.compile(r"masterarbeit\w*|master'?s? thesis|master-?thesis", re.I)),
    ("internship", re.compile(r".", re.I)),  # everything else kept here is a student job
]
# Sentences that name the expected study programme ("Du studierst Maschinenbau ...").
_STUDY_SENTENCE = re.compile(r"[^.!?\n]*(studier|studium|studiengang|fachrichtung|abschluss in|"
                             r"degree in|studying|student of)[^.!?\n]*", re.I)


class Fraunhofer(Source):
    id = "fraunhofer"
    name = "Fraunhofer (theses, internships, student jobs, PhD)"
    homepage = BASE + "/search/?q=&locale=en_US"
    min_interval = 1.0
    max_pages = 60

    @staticmethod
    def parse_listing(html: str) -> list[dict]:
        s = soup(html)
        out = []
        for tr in s.select("tr.data-row"):
            a = tr.select_one("a.jobTitle-link")
            if not a:
                continue
            m = re.search(r"/(\d+)/?$", a["href"])
            if not m:
                continue
            city = tr.select_one("td.colShifttype .jobShifttype") or tr.select_one(".jobShifttype")
            fac = tr.select_one("td.colFacility .jobFacility") or tr.select_one(".jobFacility")
            out.append({
                "id": m.group(1),
                "path": a["href"],
                "title": a.get_text(" ", strip=True),
                "city": city.get_text(" ", strip=True) if city else None,
                "institute": fac.get_text(" ", strip=True) if fac else None,
            })
        return out

    def crawl_listing(self) -> list[dict]:
        rows: list[dict] = []
        seen: set[str] = set()
        for page in range(self.max_pages):
            r = self.http.get(f"{BASE}/search/", params={"q": "", "locale": "en_US", "startrow": page * PAGE})
            r.raise_for_status()
            batch = [x for x in self.parse_listing(r.text) if x["id"] not in seen]
            if not batch:
                break
            seen.update(x["id"] for x in batch)
            rows.extend(x for x in batch if STUDENT_TITLE.search(x["title"]) and not GENERIC.search(x["title"]))
            if self.limit and len(rows) >= self.limit:
                return rows[: self.limit]
        self.log.info("%d listed, %d student/early-career", len(seen), len(rows))
        return rows

    @staticmethod
    def parse_detail(html: str) -> dict:
        s = soup(html)
        props: dict[str, str] = {}
        for e in s.select("[data-careersite-propertyid]"):
            key = e["data-careersite-propertyid"]
            if key != "description":
                props.setdefault(key, e.get_text(" ", strip=True))
        item = {}
        for e in s.select("[itemprop]"):
            val = e.get("content") or e.get_text(" ", strip=True)
            if val:
                item.setdefault(e["itemprop"], val)
        desc = s.select_one("span.jobdescription")
        return {
            "title": props.get("title"),
            "city": props.get("city"),
            "posted": props.get("date"),
            "address": item.get("streetAddress"),
            "skills": item.get("industry"),
            "description": html_to_text(str(desc))[:8000] if desc else "",
        }

    def fetch(self):
        rows = self.crawl_listing()
        cache = DetailCache(self.id)
        todo = [c for c in rows if cache.get(c["id"]) is None]
        self.log.info("%d new detail pages", len(todo))
        for i, c in enumerate(todo):
            try:
                r = self.http.get(BASE + c["path"])
                if r.status_code == 200:
                    cache.set(c["id"], self.parse_detail(r.text))
            except Exception as e:  # noqa: BLE001
                self.log.warning("detail %s failed: %s", c["id"], e)
            if i and i % 50 == 0:
                cache.save()
        cache.save()
        for c in rows:
            yield self.to_opportunity(c, cache.get(c["id"]) or {})

    def to_opportunity(self, c: dict, d: dict) -> Opportunity:
        title = d.get("title") or c["title"]
        kind = next(k for k, rx in TITLE_KIND if rx.search(title))
        institute = c.get("institute") or ""
        code = institute.split(" - ")[0].strip() if institute else ""
        org = f"Fraunhofer {code}" if code and len(code) <= 12 else "Fraunhofer-Gesellschaft"
        city = d.get("city") or c.get("city")
        loc = geocode(city, country_hint="Germany") if city else geocode(None, country_hint="Germany")
        if loc.precision != "city" and d.get("address"):
            loc = geocode(d["address"].split(",")[0], country_hint="Germany")
        desc = d.get("description") or ""
        study = " ".join(m.group(0) for m in _STUDY_SENTENCE.finditer(desc))
        fields = german_fields(title, institute, study)
        header = [x for x in (institute, f"Skills: {d['skills']}" if d.get("skills") else None) if x]
        return Opportunity(
            source=self.id,
            source_id=c["id"],
            url=BASE + c["path"],
            title=title,
            organization=org,
            kind=kind,
            description="\n".join(header + [desc]),
            locations=[loc] if loc.lat is not None else [],
            posted=parse_date(d.get("posted")),
            source_fields=fields,
            tags=[x for x in (institute,) if x],
        )
