"""jobs.ac.uk: PhD studentships and funded master's in the UK (and some abroad).

The public search is filtered server-side to the PhD / Masters job types and the
STEM academic disciplines. Each advert's page is fetched once (cached): it
carries a schema.org JobPosting block (description, dates, location) plus the
qualification type, funding details and subject areas.
"""

from __future__ import annotations

import json
import re

from ..dates import parse_date, parse_timestamp
from ..geocode import geocode
from ..models import Location, Opportunity
from .base import DetailCache, Source, html_to_text, soup

BASE = "https://www.jobs.ac.uk"

JOB_TYPES = ("phds", "masters")
DISCIPLINES = (
    "biological-sciences",
    "computer-sciences",
    "engineering-and-technology",
    "mathematics-and-statistics",
    "physical-and-environmental-sciences",
)
PAGE_SIZE = 25

QUALIFICATION_KIND = {"phd": "phd", "masters": "masters", "master": "masters",
                      "integrated masters/doctorate": "phd", "mres": "masters", "msc": "masters"}

# jobs.ac.uk subject labels -> labels the classifier's field map knows.
SUBJECT_ALIASES = {
    "physics and astronomy": "Physics",
    "chemistry": "Chemistry",
    "mathematics": "Mathematics",
    "statistics": "Statistics",
    "computer science": "Computer science",
    "artificial intelligence": "Computer science",
    "software engineering": "Programming",
    "information systems": "Information technology",
    "electrical and electronic engineering": "Electrical engineering",
    "mechanical engineering": "Mechanical engineering",
    "aerospace engineering": "Aerospace engineering",
    "civil engineering": "Civil engineering",
    "chemical engineering": "Chemical engineering",
    "materials science": "Materials engineering",
    "biomedical engineering": "Biomedical engineering",
    "earth sciences": "Earth science",
    "geography": "Earth science",
    "environmental sciences": "Environmental science",
    "biology": "Biology",
    "biotechnology": "Biotechnology",
    "biochemistry": "Biochemistry",
    "molecular biology": "Biology",
    "neuroscience": "Neurosciences",
    "ecology": "Ecology",
}


_MONTH = (r"(january|february|march|april|may|june|july|august|september|october|"
          r"november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)")
_INTAKE = [
    re.compile(_MONTH + r"\s+(20\d\d)\s+(?:start|intake|entry|enrol\w*)", re.I),
    re.compile(r"(?:start|starting|commenc\w+|intake|entry|begin\w*)\s+(?:date\s+)?(?:in|on|from|of)?\s*"
               r"(?:\d{1,2}(?:st|nd|rd|th)?\s+)?" + _MONTH + r"\s+(20\d\d)", re.I),
]


def find_intake(text: str):
    """Programme intake like "for an October 2027 start" or "starting in January 2027"."""
    for rx in _INTAKE:
        m = rx.search(text or "")
        if m:
            d = parse_date(f"1 {m.group(1)} {m.group(2)}")
            if d:
                return d, f"{m.group(1).capitalize()} {m.group(2)}"
    return None, None


class JobsAcUk(Source):
    id = "jobs_ac_uk"
    name = "jobs.ac.uk (PhDs & Masters)"
    homepage = BASE + "/phd"
    min_interval = 1.0
    max_pages = 60

    def listing_url(self, start: int) -> str:
        q = [f"jobTypeFacet[]={t}" for t in JOB_TYPES]
        q += [f"academicDisciplineFacet[]={d}" for d in DISCIPLINES]
        q += [f"pageSize={PAGE_SIZE}", f"startIndex={start}", "sortOrder=1"]
        return f"{BASE}/search/?" + "&".join(q)

    # ------------------------------------------------------------ listing

    @staticmethod
    def parse_listing(html: str) -> list[dict]:
        s = soup(html)
        out = []
        for res in s.select(".j-search-result__result"):
            a = res.select_one("a[href^='/job/']")
            if not a:
                continue
            m = re.match(r"/job/([A-Z0-9]+)/", a["href"])
            if not m:
                continue
            emp = res.select_one(".j-search-result__employer")
            dept = res.select_one(".j-search-result__department")
            text = res.get_text(" ", strip=True)
            loc = re.search(r"Location:\s*(.+?)\s*(?:Salary:|Funding|Date Placed|Closes|$)", text)
            out.append({
                "id": m.group(1),
                "path": a["href"].split("?")[0],
                "title": a.get_text(" ", strip=True),
                "org": emp.get_text(" ", strip=True) if emp else None,
                "department": dept.get_text(" ", strip=True) if dept else None,
                "location": loc.group(1).strip() if loc else None,
            })
        return out

    def crawl_listing(self) -> list[dict]:
        rows: list[dict] = []
        seen: set[str] = set()
        for page in range(self.max_pages):
            r = self.http.get(self.listing_url(1 + page * PAGE_SIZE))
            r.raise_for_status()
            new = [c for c in self.parse_listing(r.text) if c["id"] not in seen]
            if not new:
                break
            for c in new:
                seen.add(c["id"])
            rows.extend(new)
            self.log.info("listing page %d: %d (total %d)", page, len(new), len(rows))
            if self.limit and len(rows) >= self.limit:
                return rows[: self.limit]
        return rows

    # ------------------------------------------------------------ detail

    @staticmethod
    def parse_detail(html: str) -> dict:
        s = soup(html)
        ld = {}
        for tag in s.select("script[type='application/ld+json']"):
            try:
                data = json.loads(tag.string or "")
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("@type") == "JobPosting":
                ld = data
                break
        table = {}
        for tr in s.select(".j-advert-details__container tr"):
            th, td = tr.find("th"), tr.find("td")
            if th and td:
                table[th.get_text(" ", strip=True).rstrip(":")] = " ".join(td.get_text(" ", strip=True).split())
        subjects = []
        for inp in s.select("form[action='/search/'] input[type='submit']"):
            v = inp.get("value", "").strip()
            if v and v not in subjects:
                subjects.append(v)
        locs = []
        for jl in ld.get("jobLocation") or []:
            addr = (jl or {}).get("address") or {}
            locs.append({k: addr.get(k) for k in ("addressLocality", "addressRegion", "addressCountry")})
        org = (ld.get("hiringOrganization") or {}).get("name")
        desc = ld.get("description")
        if not desc:
            box = s.select_one("#job-description")
            desc = str(box) if box else ""
        return {
            "title": ld.get("title"),
            "org": org,
            "posted": ld.get("datePosted"),
            "deadline": ld.get("validThrough"),
            "locations": locs,
            "table": table,
            "subjects": subjects,
            "description": html_to_text(desc)[:8000],
        }

    def fetch_detail(self, path: str) -> dict | None:
        r = self.http.get(BASE + path)
        if r.status_code != 200:
            return None
        return self.parse_detail(r.text)

    # ------------------------------------------------------------ main

    def fetch(self):
        rows = self.crawl_listing()
        cache = DetailCache(self.id)
        todo = [c for c in rows if cache.get(c["id"]) is None]
        self.log.info("%d adverts, %d new detail pages", len(rows), len(todo))
        for i, c in enumerate(todo):
            try:
                d = self.fetch_detail(c["path"])
            except Exception as e:  # noqa: BLE001
                self.log.warning("detail %s failed: %s", c["id"], e)
                continue
            if d:
                cache.set(c["id"], d)
            if i and i % 50 == 0:
                cache.save()
        cache.save()
        for c in rows:
            yield self.to_opportunity(c, cache.get(c["id"]) or {})

    def to_opportunity(self, c: dict, d: dict) -> Opportunity:
        table = d.get("table") or {}
        qual = (table.get("Qualification Type") or "").strip().lower()
        kind = QUALIFICATION_KIND.get(qual)
        if kind is None:
            kind = "masters" if "master" in qual else "phd"

        locations: list[Location] = []
        for loc in d.get("locations") or []:
            g = geocode(", ".join(x for x in (loc.get("addressLocality"), loc.get("addressRegion")) if x),
                        country_hint=loc.get("addressCountry") or "United Kingdom")
            if g.lat is not None and all((g.lat, g.lon) != (x.lat, x.lon) for x in locations):
                locations.append(g)
        if any(x.precision == "city" for x in locations):
            locations = [x for x in locations if x.precision == "city"]
        if not locations:
            raw = table.get("Location") or c.get("location")
            if raw:
                g = geocode(raw, country_hint=None)
                if g.precision != "city":
                    g = geocode(raw, country_hint="United Kingdom")
                if g.lat is not None:
                    locations.append(g)

        subjects = d.get("subjects") or []
        fields = []
        for sub in subjects:
            fields.append(sub)
            alias = SUBJECT_ALIASES.get(sub.lower().replace("&", "and"))
            if alias:
                fields.append(alias)

        header = []
        for k in ("Qualification Type", "Funding for", "Funding amount"):
            if table.get(k):
                header.append(f"{k}: {table[k]}")
        if subjects:
            header.append("Subject areas: " + ", ".join(subjects))
        description = "\n".join(header + [d.get("description") or ""])

        funding = table.get("Funding amount")
        start_date, start_text = find_intake(description)
        tags = [x for x in (table.get("Qualification Type"), table.get("Funding for")) if x]
        return Opportunity(
            source=self.id,
            source_id=c["id"],
            url=BASE + c["path"],
            title=d.get("title") or c["title"],
            organization=d.get("org") or c.get("org"),
            kind=kind,
            description=description,
            locations=locations,
            posted=parse_timestamp(d.get("posted")) or parse_date(table.get("Placed On")),
            deadline=parse_timestamp(d.get("deadline")) or parse_date(table.get("Closes")),
            start_date=start_date,
            start_text=start_text,
            salary=funding,
            contract=table.get("Hours"),
            source_fields=fields,
            tags=tags,
        )
