"""EURAXESS (European Commission) research job portal.

Covers PhD, postdoc, master and research positions across Europe and beyond.
We crawl the public search listing filtered to STEM research fields, then fetch
each posting's detail page once (cached) for start date, position type,
required education and full description.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from ..dates import parse_date
from ..geocode import geocode
from ..models import Location, Opportunity
from ..taxonomy import EURAXESS_FIELD_MAP, EURAXESS_STEM_FIELD_IDS
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
    # EURAXESS rate-limits bursts (HTTP 429); one request every ~1.5 s stays well under it.
    min_interval = 1.5
    workers = 1

    PAGE_CAP = 40  # the search UI never pages past 40 x 10 results; deeper pages wrap to page 0

    @staticmethod
    def search_url(facets: list[tuple[str, int]], page: int = 0) -> str:
        params = [(f"f[{i}]", f"{name}:{val}") for i, (name, val) in enumerate(facets)]
        if page:
            params.append(("page", str(page)))
        return f"{BASE}/jobs/search?{urlencode(params)}"

    @staticmethod
    def result_count(html: str) -> int:
        text = soup(html).get_text(" ", strip=True)
        m = re.search(r"Search results\s*\((\d[\d,]*)\)", text)
        return int(m.group(1).replace(",", "")) if m else 0

    @staticmethod
    def country_ids(html: str) -> list[int]:
        sel = soup(html).find("select", attrs={"name": "job_country[]"})
        return [int(o["value"]) for o in sel.select("option")] if sel else []

    # ------------------------------------------------------------ listing

    def crawl_listing(self) -> list[dict]:
        """Crawl every STEM posting, partitioning queries so none exceeds the page cap."""
        fields = [("job_research_field", f) for f in EURAXESS_STEM_FIELD_IDS]
        first = self.http.get(self.search_url(fields))
        first.raise_for_status()
        total = self.result_count(first.text)
        self.log.info("%d STEM postings advertised", total)

        rows: dict[str, dict] = {}
        partitions: list[list[tuple[str, int]]] = []
        if total <= self.PAGE_CAP * 10:
            partitions.append(fields)
        else:
            for cid in self.country_ids(first.text):
                partitions.append(fields + [("job_country", cid)])

        while partitions:
            facets = partitions.pop(0)
            r = self.http.get(self.search_url(facets))
            if r.status_code != 200:
                self.log.warning("partition %s -> HTTP %s", facets[-1], r.status_code)
                continue
            n = self.result_count(r.text)
            if n == 0:
                continue
            field_facets = [f for f in facets if f[0] == "job_research_field"]
            if n > self.PAGE_CAP * 10 and len(field_facets) > 1:
                # Too big: split this country by research field (overlaps are de-duplicated).
                rest = [f for f in facets if f[0] != "job_research_field"]
                partitions[:0] = [rest + [f] for f in field_facets]
                continue
            pages = min(self.PAGE_CAP, (n + 9) // 10)
            for page in range(pages):
                if page == 0:
                    html = r.text
                else:
                    rp = self.http.get(self.search_url(facets, page))
                    if rp.status_code != 200:
                        self.log.warning("page %d of %s -> HTTP %s", page, facets[-1], rp.status_code)
                        continue
                    html = rp.text
                for c in self.parse_listing(html):
                    rows.setdefault(c["id"], c)
                if self.limit and len(rows) >= self.limit:
                    return list(rows.values())[: self.limit]
            self.log.info("partition %s: %d results, %d unique so far", facets[len(field_facets):] or "all",
                          n, len(rows))
        return list(rows.values())

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

        def work(jid: str):
            try:
                d = self.fetch_detail(jid)
            except Exception as e:  # noqa: BLE001 - one bad page must not stop the crawl
                self.log.warning("detail %s failed: %s", jid, e)
                return
            if d:
                cache.set(jid, d)

        with ThreadPoolExecutor(self.workers) as ex:
            for i, _ in enumerate(ex.map(work, todo)):
                if i and i % 200 == 0:
                    self.log.info("details %d/%d", i, len(todo))
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
