"""EURAXESS (European Commission) research job portal.

Covers PhD, postdoc, master and research positions across Europe and beyond.
We crawl the public search listing filtered to STEM research fields, then fetch
each posting's detail page once (cached) for start date, position type,
required education and full description.
"""

from __future__ import annotations

import re
import os
import time

from ..classify import classify_fields
from ..dates import parse_date
from ..geocode import geocode
from ..models import Location, Opportunity
from ..taxonomy import EURAXESS_FIELD_MAP
from .base import DetailCache, Source, soup

BASE = "https://euraxess.ec.europa.eu"

POSITION_KIND = {
    "phd positions": "phd",
    "postdoc positions": "postdoc",
    "master positions": "masters",
    "bachelor positions": "internship",
    "undergraduate positions": "internship",
    "research support positions": "job",
}

EDU_LEVEL = {
    "phd or equivalent": "phd",
    "master degree or equivalent": "masters",
    "bachelor degree or equivalent": "bachelor",
}


class Euraxess(Source):
    id = "euraxess"
    name = "EURAXESS"
    homepage = BASE + "/jobs/search"
    # EURAXESS rate-limits bursts (HTTP 429); one request every ~2 s stays well under it.
    min_interval = 2.0
    # Detail pages are fetched newest-first within this time budget per run; the rest use
    # listing data until a later run fills the cache. Override with EURAXESS_DETAIL_BUDGET.
    detail_budget_s = 3600

    @staticmethod
    def result_count(html: str) -> int:
        text = soup(html).get_text(" ", strip=True)
        m = re.search(r"Search results\s*\((\d[\d,]*)\)", text)
        return int(m.group(1).replace(",", "")) if m else 0

    @staticmethod
    def is_stem_card(card: dict) -> bool:
        """Cheap pre-filter on listing data, so detail pages are fetched only for STEM postings."""
        for raw in card.get("fields") or []:
            for part in raw.split("»"):
                if EURAXESS_FIELD_MAP.get(part.strip().lower(), (None,))[0]:
                    return True
        disc, _ = classify_fields(card.get("title", ""), card.get("summary", ""), card.get("fields"))
        return bool(disc)

    # ------------------------------------------------------------ listing

    def crawl_listing(self) -> list[dict]:
        """Walk the unfiltered listing (newest first) and keep STEM cards.

        Facet filters in the URL are not reliable (the site sometimes ignores them), so we
        page through everything and filter locally. ~670 pages at the polite rate ≈ 20 min.
        """
        first = self.http.get(f"{BASE}/jobs/search")
        first.raise_for_status()
        total = self.result_count(first.text)
        pages = (total + 9) // 10 if total else 2000
        self.log.info("%d postings advertised (%d pages)", total, pages)

        rows: dict[str, dict] = {}
        seen = 0
        empty_streak = 0
        for page in range(pages + 2):
            if page == 0:
                html = first.text
            else:
                r = self.http.get(f"{BASE}/jobs/search?page={page}")
                if r.status_code != 200:
                    self.log.warning("listing page %d -> HTTP %s", page, r.status_code)
                    continue
                html = r.text
            cards = self.parse_listing(html)
            fresh = [c for c in cards if c["id"] not in rows]
            if not fresh:
                empty_streak += 1
                if empty_streak >= 3:
                    break
                continue
            empty_streak = 0
            seen += len(cards)
            for c in fresh:
                if self.is_stem_card(c):
                    rows[c["id"]] = c
            if page % 50 == 0:
                self.log.info("listing page %d/%d: %d STEM of %d seen", page, pages, len(rows), seen)
            if self.limit and len(rows) >= self.limit:
                break
        out = list(rows.values())
        return out[: self.limit] if self.limit else out

    @staticmethod
    def parse_listing(html: str) -> list[dict]:
        s = soup(html)
        out = []
        for art in s.select("article.ecl-content-item"):
            a = art.select_one("h3 a[href^='/jobs/']")
            if not a:
                continue
            m = re.search(r"/jobs/(\d+)", a["href"])
            if not m:
                continue
            meta = [li.get_text(" ", strip=True) for li in art.select(".ecl-content-block__primary-meta-item")]
            fields = {}
            for d in art.select("div[class^='id-']"):
                key = d["class"][0][3:]
                val = d.select_one(".ecl-text-standard")
                if val:
                    fields[key] = [x.get_text(" ", strip=True) for x in val.find_all(recursive=False)] \
                        or [val.get_text(" ", strip=True)]
            posted = next((x.split(":", 1)[1] for x in meta if x.lower().startswith("posted on")), None)
            out.append({
                "id": m.group(1),
                "title": a.get_text(" ", strip=True),
                "org": meta[0] if meta and not meta[0].lower().startswith("posted") else None,
                "posted": posted.strip() if posted else None,
                "summary": (art.select_one(".ecl-content-block__description") or art).get_text(" ", strip=True)
                if art.select_one(".ecl-content-block__description") else "",
                "locations": fields.get("Work-Locations", []),
                "fields": fields.get("Research-Field", []),
                "profile": " ".join(fields.get("Researcher-Profile", [])),
                "deadline": " ".join(fields.get("Application-Deadline", [])),
            })
        return out

    # ------------------------------------------------------------ detail

    def fetch_detail(self, job_id: str) -> dict | None:
        r = self.http.get(f"{BASE}/jobs/{job_id}", allow_redirects=False)
        if r.status_code != 200:
            return None
        return self.parse_detail(r.text)

    @staticmethod
    def parse_detail(html: str) -> dict:
        s = soup(html)
        sections = {}
        for h in s.select("h2"):
            box = h.find_parent("div")
            if box is not None:
                sections[h.get_text(strip=True)] = box

        def pairs(box) -> list[tuple[str, str]]:
            out = []
            if box is None:
                return out
            for dl in box.select("dl"):
                for dt, dd in zip(dl.select("dt"), dl.select("dd")):
                    out.append((dt.get_text(" ", strip=True), dd.get_text(" ", strip=True)))
            return out

        info = dict(pairs(sections.get("Job Information")))
        req_pairs = pairs(sections.get("Requirements"))
        required_fields, edu = [], []
        for k, v in req_pairs:
            if k == "Research Field":
                required_fields.append(v)
            elif k == "Education Level":
                edu.append(v)
        locs = []
        cur: dict = {}
        for k, v in pairs(sections.get("Work Location(s)")):
            if k == "Company/Institute" and cur:
                locs.append(cur)
                cur = {}
            if k in ("Company/Institute", "Country", "State/Province", "City"):
                cur[k] = v
        if cur:
            locs.append(cur)
        desc_box = sections.get("Offer Description")
        desc = desc_box.get_text("\n", strip=True) if desc_box else ""
        desc = re.sub(r"^Offer Description\s*", "", desc)
        title = (s.select_one("meta[property='og:title']") or {}).get("content")
        return {
            "title": title,
            "org": info.get("Organisation/Company"),
            "fields": info.get("Research Field"),
            "profile": info.get("Researcher Profile"),
            "positions": info.get("Positions"),
            "deadline": info.get("Application Deadline"),
            "country": info.get("Country"),
            "contract": info.get("Type of Contract"),
            "status": info.get("Job Status"),
            "start": info.get("Offer Starting Date"),
            "required_fields": required_fields,
            "education": edu,
            "locations": locs,
            "description": desc[:8000],
        }

    # ------------------------------------------------------------ main

    def fetch(self):
        cards = self.crawl_listing()
        cache = DetailCache(self.id)
        todo = [c["id"] for c in cards if cache.get(c["id"]) is None]
        self.log.info("%d cards, %d new detail pages to fetch", len(cards), len(todo))

        budget = float(os.environ.get("EURAXESS_DETAIL_BUDGET", self.detail_budget_s))
        deadline = time.monotonic() + budget
        done = 0
        for jid in todo:
            if time.monotonic() > deadline:
                self.log.info("detail budget used up; %d pages left for the next run", len(todo) - done)
                break
            try:
                d = self.fetch_detail(jid)
            except Exception as e:  # noqa: BLE001 - one bad page must not stop the crawl
                self.log.warning("detail %s failed: %s", jid, e)
                d = None
            if d:
                cache.set(jid, d)
            done += 1
            if done % 100 == 0:
                self.log.info("details %d/%d", done, len(todo))
                cache.save()
        cache.save()

        for c in cards:
            d = cache.get(c["id"]) or {}
            yield self.to_opportunity(c, d)

    def to_opportunity(self, c: dict, d: dict) -> Opportunity:
        fields = [f for f in (c.get("fields") or [])]
        if d.get("fields"):
            fields += re.split(r"\s{2,}|(?<=[a-z])(?=[A-Z][a-z]+ »)", d["fields"])
        positions = (d.get("positions") or "").lower()
        kind_hint = next((k for label, k in POSITION_KIND.items() if label in positions), None)

        required = []
        for rf in d.get("required_fields") or []:
            for part in reversed([p.strip().lower() for p in rf.split("»")]):
                if EURAXESS_FIELD_MAP.get(part, (None,))[0]:
                    disc = EURAXESS_FIELD_MAP[part][0]
                    if disc not in required:
                        required.append(disc)
                    break
        edu = None
        for e in d.get("education") or []:
            edu = EDU_LEVEL.get(e.strip().lower(), edu)

        locations: list[Location] = []
        for loc in d.get("locations") or []:
            g = geocode(loc.get("City") or loc.get("State/Province"), country_hint=loc.get("Country"))
            if g.lat is not None and all((g.lat, g.lon) != (x.lat, x.lon) for x in locations):
                locations.append(g)
        if not locations:
            for raw in c.get("locations") or []:
                # "Number of offers: 1, Sweden, Göteborgs universitet, Göteborg, 40530, Box 711"
                parts = [p.strip() for p in raw.split(",")]
                parts = [p for p in parts if not p.lower().startswith("number of offers")]
                country = parts[0] if parts else None
                g = geocode(", ".join(reversed(parts[1:])), country_hint=country)
                if g.lat is not None:
                    locations.append(g)
        if not locations and d.get("country"):
            locations.append(geocode(None, country_hint=d["country"]))

        status = d.get("status") or ""
        contract = ", ".join(x for x in (d.get("contract"), status) if x) or None
        description = d.get("description") or c.get("summary") or ""

        return Opportunity(
            source=self.id,
            source_id=c["id"],
            url=f"{BASE}/jobs/{c['id']}",
            title=d.get("title") or c["title"],
            organization=d.get("org") or c.get("org"),
            kind=kind_hint or "job",
            description=description,
            locations=locations,
            posted=parse_date(c.get("posted")),
            deadline=parse_date(d.get("deadline") or c.get("deadline")),
            start_date=parse_date(d.get("start")),
            required_degrees=required,
            education_level=edu,
            contract=contract,
            source_fields=fields,
            tags=[t for t in [c.get("profile") or d.get("profile")] if t],
        )
