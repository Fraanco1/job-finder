"""Nature Careers: PhD positions worldwide.

Crawls the public "PhD Position" job-type category (``/naturecareers/jobs/
phd-position/``; the free-text search and the RSS feeds are disallowed by
robots.txt, category pages are not). Each advert's page is fetched once
(cached) for its schema.org JobPosting block and the metadata list
(discipline, job type, qualification, closing date).
"""

from __future__ import annotations

import json
import re

from ..dates import parse_date, parse_timestamp
from ..geocode import gazetteer, geocode
from ..models import Location, Opportunity
from .base import DetailCache, Source, html_to_text, soup

BASE = "https://www.nature.com"
CATEGORIES = ("phd-position",)
_KIND_TITLE = re.compile(r"\b(ph\.?d|doctoral|doctorate|studentship|graduate student|"
                         r"doktorand|promovend|dphil)\w*", re.I)


def locate(text: str | None) -> Location:
    """Geocode Nature Careers locations like "Heidelberg, Baden-Württemberg (DE)"."""
    if not text:
        return Location()
    country = None
    m = re.search(r"\(([A-Z]{2})\)\s*$", text)
    if m:
        country = gazetteer().countries.get(m.group(1))
        text = text[: m.start()].strip(" ,")
    g = geocode(text, country_hint=country)
    if g.lat is None and country:
        g = geocode(None, country_hint=country)
    return g


class NatureCareers(Source):
    id = "nature_careers"
    name = "Nature Careers (PhD positions)"
    homepage = BASE + "/naturecareers/jobs/phd-position/"
    min_interval = 1.0
    max_pages = 40

    # ------------------------------------------------------------ listing

    @staticmethod
    def parse_listing(html: str) -> list[dict]:
        s = soup(html)
        out = []
        for li in s.select("li.lister__item"):
            a = li.select_one("h3 a[href*='/naturecareers/job/']")
            if not a:
                continue
            href = a["href"].strip().split("?")[0]
            m = re.search(r"/naturecareers/job/(\d+)/", href)
            if not m:
                continue

            def meta(cls: str) -> str | None:
                e = li.select_one(f".lister__meta-item--{cls}")
                return e.get_text(" ", strip=True) if e else None

            desc = li.select_one(".lister__description")
            out.append({
                "id": m.group(1),
                "path": href,
                "title": a.get_text(" ", strip=True),
                "location": meta("location"),
                "salary": meta("salary"),
                "org": meta("recruiter"),
                "summary": desc.get_text(" ", strip=True) if desc else "",
                "premium": "premium" in " ".join(li.get("class", [])),
            })
        return out

    def crawl_listing(self) -> list[dict]:
        rows: list[dict] = []
        seen: set[str] = set()
        for cat in CATEGORIES:
            for page in range(1, self.max_pages + 1):
                url = f"{BASE}/naturecareers/jobs/{cat}/" + (f"{page}/" if page > 1 else "")
                r = self.http.get(url)
                if r.status_code == 404:
                    break
                r.raise_for_status()
                cards = self.parse_listing(r.text)
                new = [c for c in cards if c["id"] not in seen]
                # Premium adverts repeat on every page: stop when only those are new.
                if not [c for c in new if not c["premium"]]:
                    rows.extend(new)
                    seen.update(c["id"] for c in new)
                    break
                for c in new:
                    seen.add(c["id"])
                rows.extend(new)
                self.log.info("%s page %d: %d new (total %d)", cat, page, len(new), len(rows))
                if self.limit and len(rows) >= self.limit:
                    return rows[: self.limit]
        return rows

    # ------------------------------------------------------------ detail

    @staticmethod
    def parse_detail(html: str) -> dict:
        s = soup(html)
        ld: dict = {}
        for tag in s.select("script[type='application/ld+json']"):
            try:
                data = json.loads(tag.string or "")
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("@type") == "JobPosting":
                ld = data
                break
        meta: dict[str, str] = {}
        for dl in s.select("dl"):
            for dt in dl.select("dt"):
                dd = dt.find_next_sibling("dd")
                if dd is not None:
                    vals = [x.get_text(" ", strip=True) for x in dd.select("a, span")] or \
                        [dd.get_text(" ", strip=True)]
                    vals = [v for v in vals if v and v != ","]
                    meta[dt.get_text(" ", strip=True)] = " | ".join(dict.fromkeys(vals))
        desc = ld.get("description")
        if not desc:
            box = s.select_one("#job-description")
            desc = str(box) if box else ""
        return {
            "title": ld.get("title"),
            "org": (ld.get("hiringOrganization") or {}).get("name"),
            "posted": ld.get("datePosted"),
            "deadline": ld.get("validThrough"),
            "meta": meta,
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
            opp = self.to_opportunity(c, cache.get(c["id"]) or {})
            if opp is not None:
                yield opp

    def to_opportunity(self, c: dict, d: dict) -> Opportunity | None:
        meta = d.get("meta") or {}
        job_type = meta.get("Job Type") or ""
        title = d.get("title") or c["title"]
        # Premium adverts are shown on every category page whatever their type
        # (and often tag every job type): keep them only when the title says PhD.
        if c.get("premium") and not _KIND_TITLE.search(title):
            return None
        if not c.get("premium") and "phd" not in job_type.lower() and not _KIND_TITLE.search(title):
            return None
        loc = locate(meta.get("Location") or c.get("location"))
        disciplines = [x.strip() for x in (meta.get("Discipline") or "").split("|") if x.strip()]
        header = [f"{k}: {meta[k]}" for k in ("Discipline", "Qualification", "Sector") if meta.get(k)]
        description = "\n".join(header + [d.get("description") or c.get("summary") or ""])
        return Opportunity(
            source=self.id,
            source_id=c["id"],
            url=BASE + c["path"],
            title=title,
            organization=d.get("org") or meta.get("Employer") or c.get("org"),
            kind="phd",
            description=description,
            locations=[loc] if loc.lat is not None else [],
            posted=parse_timestamp(d.get("posted")),
            deadline=parse_timestamp(d.get("deadline")) or parse_date(meta.get("Closing date")),
            salary=meta.get("Salary") or c.get("salary"),
            contract=", ".join(x for x in (meta.get("Employment - Hours"), meta.get("Duration")) if x) or None,
            source_fields=disciplines,
            tags=[x for x in (job_type, meta.get("Sector")) if x],
        )
