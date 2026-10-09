"""Jobbnorge: PhD research fellowships, postdocs and student jobs at Norwegian institutions.

Jobbnorge is where NTNU, the universities of Oslo, Bergen, Tromsø, Stavanger,
Agder, research institutes and colleges publish their vacancies. Its public
search API (``publicapi.jobbnorge.no/v3/jobs``) returns every open vacancy in
one JSON response (title, employer, deadline, location, position code). We
keep early-career research roles (position codes 1017 Stipendiat = PhD
research fellow, 1352 Postdoktor, 1378, plus matching titles) and fetch each
advert's text once (cached) from the JSON endpoint the job page itself uses.
"""

from __future__ import annotations

import re

from ..dates import parse_date
from ..geocode import geocode
from ..models import Location, Opportunity
from .base import DetailCache, Source, html_to_text

LIST_API = "https://publicapi.jobbnorge.no/v3/jobs"
DETAIL_API = "https://id.jobbnorge.no/api/joblisting"
LANG_EN = 2

TYPE_KIND = [
    ("phd", re.compile(r"\b(1017|1378)\b|stipendiat", re.I)),
    ("postdoc", re.compile(r"\b1352\b|postdoktor", re.I)),
]
TITLE_KIND = [
    ("postdoc", re.compile(r"post-?doc\w*|postdoktor\w*|post-doctoral", re.I)),
    ("phd", re.compile(r"\bph\.?\s?d\b|stipendiat\w*|doctoral|doktorgrad\w*|research fellow", re.I)),
    ("internship", re.compile(r"summer (?:student|intern\w*|research)|sommerstudent\w*|sommerjobb|"
                              r"\bintern(?:ship)?\b|trainee\w*|master'?s? thesis|masteroppgave\w*|"
                              r"student assistant|vitenskapelig assistent", re.I)),
]
# Boilerplate sections dropped from the description.
SKIP_HEADINGS = re.compile(r"^(diversity|mangfold|general information|generell informasjon|"
                           r"about the application|om søknaden)", re.I)


def job_kind(job: dict) -> str | None:
    title = job.get("title") or ""
    for kind, rx in TITLE_KIND:
        if rx.search(title):
            return kind
    jt = (job.get("jobType") or {}).get("name") or ""
    for kind, rx in TYPE_KIND:
        if rx.search(jt):
            return kind
    return None


def job_locations(job: dict) -> list[Location]:
    out: list[Location] = []
    locs = sorted(job.get("locations") or [], key=lambda x: not x.get("isPrimary"))
    for loc in locs:
        domestic = loc.get("isDomestic", True)
        area = loc.get("area") or loc.get("municipality")
        if domestic or area:
            text = ", ".join(x for x in (area, loc.get("county")) if x)
            g = geocode(text, country_hint="Norway") if text else geocode(None, country_hint="Norway")
            if g.precision != "city" and loc.get("municipality") and loc.get("municipality") != area:
                g2 = geocode(loc["municipality"], country_hint="Norway")
                g = g2 if g2.precision == "city" else g
        else:
            g = geocode(loc.get("address"))
        if g.lat is not None and all((g.lat, g.lon) != (x.lat, x.lon) for x in out):
            out.append(g)
    return out


def components_text(components: list[dict]) -> str:
    parts = []
    for c in sorted(components or [], key=lambda x: int(x.get("orderId") or 0)):
        if str(c.get("typeId")) not in ("0", "4"):
            continue  # images, videos, employer boxes
        head = (c.get("heading") or "").strip()
        if head and SKIP_HEADINGS.search(head):
            continue
        body = html_to_text(c.get("text") or "")
        if body and not re.fullmatch(r"We are looking for\.\.\./.*", body):
            parts.append(f"{head}\n{body}" if head and str(c.get("typeId")) != "0" else body)
    return "\n".join(parts)


class Jobbnorge(Source):
    id = "jobbnorge"
    name = "Jobbnorge (Norway: PhD & postdoc)"
    homepage = "https://www.jobbnorge.no/search/en"
    min_interval = 0.7

    def fetch(self):
        data = self.http.get_json(LIST_API, params={"language": LANG_EN})
        jobs = [j for j in data.get("jobs") or [] if job_kind(j)]
        self.log.info("%d vacancies, %d early-career research", len(data.get("jobs") or []), len(jobs))
        if self.limit:
            jobs = jobs[: self.limit]
        cache = DetailCache(self.id)
        for j in jobs:
            key = str(j["id"])
            if cache.get(key) is not None:
                continue
            try:
                r = self.http.get(DETAIL_API, params={"jobId": j["id"], "languageId": LANG_EN})
                if r.status_code == 200:
                    d = r.json()
                    langs = d.get("activeLanguages") or []
                    if langs and LANG_EN not in langs:  # Norwegian-only advert
                        r = self.http.get(DETAIL_API, params={"jobId": j["id"], "languageId": langs[0]})
                        d = r.json() if r.status_code == 200 else d
                    cache.set(key, {"text": components_text(d.get("components") or [])[:8000]})
            except Exception as e:  # noqa: BLE001
                self.log.warning("detail %s failed: %s", j["id"], e)
        cache.save()
        for j in jobs:
            yield self.to_opportunity(j, cache.get(str(j["id"])) or {})

    def to_opportunity(self, j: dict, d: dict) -> Opportunity:
        jt = (j.get("jobType") or {}).get("name")
        org = j.get("employer")
        dept = j.get("department")
        description = "\n".join(x for x in (dept, d.get("text") or j.get("summary") or "") if x)
        return Opportunity(
            source=self.id,
            source_id=str(j["id"]),
            url=j.get("link") or f"https://www.jobbnorge.no/ledige-stillinger/stilling/{j['id']}",
            title=(j.get("title") or "").strip(),
            organization=org,
            kind=job_kind(j) or "job",
            description=description,
            locations=job_locations(j),
            posted=parse_date(j.get("publicationDate")),
            deadline=parse_date(j.get("deadline")),
            contract=", ".join(x for x in (j.get("jobScope"), j.get("jobDuration")) if x) or None,
            tags=[x.strip() for x in (jt, dept) if x],
        )
