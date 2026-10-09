"""AcademicTransfer: academic vacancies in the Netherlands (PhD, postdoc, master thesis).

The search API (api.academictransfer.com) is disallowed by its robots.txt and
the www listing only server-renders the first 10 results, so we use the
public vacancy sitemap instead. Slugs are pre-filtered to early-career roles
(PhD / postdoc / thesis / internship / trainee ...), and each advert page is
fetched once (cached) with the 10 s crawl-delay the site asks for. The page
embeds the full vacancy record in its Nuxt payload (deadline, city, job
types, research fields, education level, salary).
"""

from __future__ import annotations

import json
import re

from ..dates import parse_timestamp
from ..geocode import gazetteer, geocode
from ..models import Opportunity
from .base import DetailCache, Source, html_to_text

BASE = "https://www.academictransfer.com"
SITEMAP = BASE + "/sitemap-vacancies.xml"

# Early-career roles; matched against the URL slug (title) before fetching.
SLUG_FILTER = re.compile(
    r"\b(phd|ph d|promovend\w*|promotie\w*|doctor\w*|postdoc\w*|post doc\w*|engd|pdeng|candidate|"
    r"kandidaat|student\w*|intern|internship|stage\w*|stagiair\w*|thesis|afstudeer\w*|master\w*|"
    r"trainee\w*|fellow\w*|fellowship|oio|aio|junior researcher|predoc\w*|graduate)\b", re.I)

FUNCTION_TYPES = {
    9: "PhD", 22: "PhD scholarship", 6: "Postdoc", 121: "Lecturer", 122: "Assistant professor",
    123: "Associate professor", 124: "Professor", 18: "Research, development, innovation",
    19: "Education", 2: "Technical and laboratory", 16: "IT",
}
FUNCTION_KIND = {9: "phd", 22: "phd", 6: "postdoc"}
SCIENTIFIC_FIELDS = {1: "Agriculture", 2: "Natural sciences", 3: "Engineering", 4: "Health",
                     5: "Economics", 6: "Law", 7: "Behaviour and society", 8: "Language and culture",
                     9: "Food"}
# Main research-field codes ("16.0"); sub-codes share the integer part.
RESEARCH_FIELDS = {
    1: "Agricultural sciences", 2: "Anthropology", 3: "Architecture", 4: "Arts", 5: "Astronomy",
    6: "Biological sciences", 7: "Chemistry", 8: "Communication sciences", 9: "Computer science",
    10: "Criminology", 11: "Cultural studies", 12: "Demography", 13: "Economics",
    14: "Educational sciences", 15: "Engineering", 16: "Environmental science",
    17: "Ethics in health sciences", 18: "Ethics in natural sciences", 19: "Ethics in physical sciences",
    20: "Ethics in social sciences", 21: "Geography", 22: "History", 23: "Information science",
    24: "Juridical sciences", 25: "Language sciences", 26: "Literature", 27: "Mathematics",
    28: "Medical sciences", 29: "Neurosciences", 30: "Pharmacological sciences", 31: "Philosophy",
    32: "Physics", 33: "Political sciences", 34: "Psychological sciences", 35: "Religious sciences",
    36: "Sociology", 37: "Technology", 38: "Geosciences",
}
EDUCATION_LEVEL = {1: "phd", 2: "masters", 3: "bachelor", 4: "bachelor"}


def parse_nuxt(html: str) -> list | None:
    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S) or \
        re.search(r'<script type="application/json"[^>]*data-nuxt[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def nuxt_value(arr: list, idx: int, depth: int = 0):
    """Resolve Nuxt 3's flattened payload (values reference other indices)."""
    v = arr[idx]
    if depth > 20:
        return None
    if isinstance(v, dict):
        return {k: nuxt_value(arr, x, depth + 1) if isinstance(x, int) else x for k, x in v.items()}
    if isinstance(v, list):
        if v and isinstance(v[0], str) and v[0] in ("Ref", "Reactive", "ShallowReactive", "ShallowRef",
                                                    "EmptyRef", "Set", "Map", "Date"):
            return nuxt_value(arr, v[1], depth + 1) if len(v) > 1 and isinstance(v[1], int) else None
        return [nuxt_value(arr, x, depth + 1) if isinstance(x, int) else x for x in v]
    return v


def extract_vacancy(html: str) -> dict | None:
    arr = parse_nuxt(html)
    if not arr:
        return None
    for i, v in enumerate(arr):
        if isinstance(v, dict) and "external_id" in v and "title" in v and "end_date" in v:
            return nuxt_value(arr, i)
    return None


class AcademicTransfer(Source):
    id = "academictransfer"
    name = "AcademicTransfer (NL)"
    homepage = BASE + "/en/jobs/"
    min_interval = 10.0  # robots.txt Crawl-delay

    def crawl_sitemap(self) -> list[dict]:
        r = self.http.get(SITEMAP)
        r.raise_for_status()
        rows = []
        for url in re.findall(r"<loc>([^<]+)</loc>", r.text):
            m = re.search(r"/jobs/(\d+)/([^/]+)/?$", url)
            if not m:
                continue
            slug = m.group(2).replace("-", " ")
            if SLUG_FILTER.search(slug):
                rows.append({"id": m.group(1), "url": url.replace("/nl/jobs/", "/en/jobs/"), "slug": slug})
        rows.sort(key=lambda x: -int(x["id"]))  # newest first
        self.log.info("sitemap: %d early-career vacancies", len(rows))
        return rows[: self.limit] if self.limit else rows

    def fetch_detail(self, url: str) -> dict | None:
        r = self.http.get(url)
        if r.status_code != 200:
            return None
        v = extract_vacancy(r.text)
        if not v:
            return None
        keep = ("title", "description", "requirements", "contract_terms", "excerpt", "end_date",
                "created_datetime", "city", "country_code", "function_types", "scientific_fields",
                "research_fields", "education_level", "min_salary", "max_salary", "organisation_name",
                "department_name", "contract_type", "language_code", "keywords", "absolute_url",
                "contract_duration", "min_weekly_hours", "max_weekly_hours")
        out = {k: v.get(k) for k in keep}
        for k in ("description", "requirements", "contract_terms"):
            out[k] = html_to_text(out.get(k) or "")[:6000]
        return out

    def fetch(self):
        rows = self.crawl_sitemap()
        cache = DetailCache(self.id)
        todo = [c for c in rows if cache.get(c["id"]) is None]
        self.log.info("%d vacancies, %d new detail pages (%.0f min at the crawl-delay)",
                      len(rows), len(todo), len(todo) * self.min_interval / 60)
        for i, c in enumerate(todo):
            try:
                d = self.fetch_detail(c["url"])
            except Exception as e:  # noqa: BLE001
                self.log.warning("detail %s failed: %s", c["id"], e)
                continue
            cache.set(c["id"], d or {"missing": True})
            if i and i % 20 == 0:
                self.log.info("details %d/%d", i, len(todo))
                cache.save()
        cache.save()
        for c in rows:
            d = cache.get(c["id"]) or {}
            if d.get("title"):
                yield self.to_opportunity(c, d)

    def to_opportunity(self, c: dict, d: dict) -> Opportunity:
        ftypes = [int(x) for x in d.get("function_types") or [] if str(x).isdigit()]
        kind = next((FUNCTION_KIND[f] for f in ftypes if f in FUNCTION_KIND), "job")
        sfields = [SCIENTIFIC_FIELDS[int(x)] for x in d.get("scientific_fields") or []
                   if str(x).isdigit() and int(x) in SCIENTIFIC_FIELDS]
        rfields = []
        for code in d.get("research_fields") or []:
            try:
                main = RESEARCH_FIELDS.get(int(float(code)))
            except (TypeError, ValueError):
                continue
            if main and main not in rfields:
                rfields.append(main)

        city = d.get("city")
        cc = (d.get("country_code") or "NL").upper()
        country = gazetteer().countries.get(cc, "Netherlands")
        loc = geocode(city, country_hint=country) if city else geocode(None, country_hint=country)
        if loc.lat is None:
            loc = geocode(None, country_hint=country)

        parts = [d.get("description") or d.get("excerpt") or ""]
        if d.get("requirements"):
            parts.append("Requirements:\n" + d["requirements"])
        if d.get("contract_terms"):
            parts.append("Conditions:\n" + d["contract_terms"])
        if rfields:
            parts.append("Research fields: " + ", ".join(rfields))

        salary = None
        if d.get("min_salary") or d.get("max_salary"):
            lo, hi = d.get("min_salary"), d.get("max_salary")
            salary = f"€{lo}–€{hi} per month" if lo and hi and lo != hi else f"€{lo or hi} per month"
        org = d.get("organisation_name")
        return Opportunity(
            source=self.id,
            source_id=c["id"],
            url=d.get("absolute_url") or c["url"],
            title=d["title"],
            organization=org,
            kind=kind,
            description="\n".join(p for p in parts if p),
            locations=[loc] if loc.lat is not None else [],
            posted=parse_timestamp(d.get("created_datetime")),
            deadline=parse_timestamp(d.get("end_date")),
            education_level=EDUCATION_LEVEL.get(d.get("education_level")),
            salary=salary,
            contract={1: "permanent", 2: "temporary"}.get(d.get("contract_type")),
            source_fields=rfields + sfields,
            tags=[FUNCTION_TYPES[f] for f in ftypes if f in FUNCTION_TYPES]
            + ([d["department_name"]] if d.get("department_name") else []),
        )
