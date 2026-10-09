"""European Space Agency careers (https://jobs.esa.int).

Staff positions, Internal Research Fellowships (postdoc), Graduate Trainee
and student internship programmes at ESTEC (Noordwijk), ESOC (Darmstadt),
ESRIN (Frascati), ESAC (Madrid), EAC (Cologne), ECSAT (Harwell) and more.
The search pages list title, appointment type, closing date and workplace;
each job page (fetched once, cached) adds the full description.
"""

from __future__ import annotations

import re

from ..dates import parse_date
from ..geocode import geocode
from ..models import Location, Opportunity
from ._physmath_util import country_name
from .base import DetailCache, Source, html_to_text, soup

BASE = "https://jobs.esa.int"

APPOINTMENT_KIND = [
    (re.compile(r"research fellow|post-?doc", re.I), "postdoc"),
    (re.compile(r"graduate trainee|trainee|intern|student|young graduate", re.I), "internship"),
    (re.compile(r"ph\.?d|doctoral|co-?sponsored research", re.I), "phd"),
]


def appointment_kind(text: str | None) -> str | None:
    for rx, kind in APPOINTMENT_KIND:
        if text and rx.search(text):
            return kind
    return None


def parse_search(html: str) -> tuple[list[dict], int | None]:
    s = soup(html)
    total = None
    label = s.select_one("#tile-search-results-label")
    if label:
        m = re.search(r"of\s+(\d+)", label.get_text(" ", strip=True))
        total = int(m.group(1)) if m else None
    out = []
    for li in s.select("li.job-tile"):
        url = li.get("data-url") or ""
        m = re.search(r"/(\d+)/?$", url)
        if not m:
            continue
        a = li.select_one("a.jobTitle-link")

        def field(name: str) -> str | None:
            el = li.select_one(f"[id$='desktop-section-{name}-value']")
            return el.get_text(" ", strip=True) if el else None

        out.append({
            "id": m.group(1),
            "path": url,
            "title": a.get_text(" ", strip=True) if a else None,
            "type": field("shifttype"),
            "closing": field("customfield5"),
            "workplace": field("multilocation") or field("location"),
        })
    return out, total


def parse_detail(html: str) -> dict:
    s = soup(html)

    def prop(pid: str) -> str | None:
        el = s.select_one(f"[data-careersite-propertyid='{pid}']")
        return el.get_text(" ", strip=True) if el else None

    desc = s.select_one("span.jobdescription") or s.select_one("[itemprop=description]")
    return {
        "title": prop("title"),
        "posted": prop("adcode"),
        "closing": prop("customfield5"),
        "type": prop("shifttype"),
        "directorate": prop("dept"),
        "location": prop("location"),
        "description": html_to_text(str(desc))[:12000] if desc else "",
    }


def esa_locations(text: str | None) -> list[Location]:
    """'Noordwijk, NL' / 'Harwell, GB Noordwijk, NL' -> locations (codes are ISO alpha-2)."""
    out: list[Location] = []
    pairs = re.findall(r"\s*([^,]+?),\s*([A-Z]{2})(?=\s|,|;|$)", text or "")
    if not pairs and text:
        pairs = [(text, None)]
    for city, cc in pairs:
        city = city.strip(" ,;")
        g = geocode(city, country_hint=country_name(cc) if cc else None)
        if g.precision != "city" and "-" in city:
            g2 = geocode(city.split("-")[0], country_hint=country_name(cc) if cc else None)
            g = g2 if g2.precision == "city" else g
        if g.lat is not None and all((g.lat, g.lon) != (x.lat, x.lon) for x in out):
            out.append(g)
    return out


def clean_description(text: str) -> str:
    """Drop the leading 'Location / ESTEC, Noordwijk...' block (already in locations)."""
    return re.sub(r"^\s*Location\s*\n[^\n]*\n", "", text, count=1)


class Esa(Source):
    id = "esa"
    name = "ESA Careers"
    homepage = BASE + "/"
    min_interval = 1.0
    page = 25

    def fetch(self):
        rows: list[dict] = []
        start = 0
        while True:
            r = self.http.get(f"{BASE}/search/", params={"q": "", "locale": "en_GB", "startrow": start})
            r.raise_for_status()
            batch, total = parse_search(r.text)
            new = [b for b in batch if b["id"] not in {x["id"] for x in rows}]
            rows.extend(new)
            start += self.page
            if not new or (total is not None and start >= total) or (self.limit and len(rows) >= self.limit):
                break
        self.log.info("%d jobs", len(rows))
        if self.limit:
            rows = rows[: self.limit]

        cache = DetailCache(self.id)
        for row in rows:
            if cache.get(row["id"]) is not None:
                continue
            try:
                resp = self.http.get(BASE + row["path"])
                if resp.status_code == 200:
                    cache.set(row["id"], parse_detail(resp.text))
            except Exception as e:  # noqa: BLE001
                self.log.warning("job %s failed: %s", row["id"], e)
        cache.save()

        for row in rows:
            yield self.to_opportunity(row, cache.get(row["id"]) or {})

    def to_opportunity(self, row: dict, d: dict) -> Opportunity:
        typ = d.get("type") or row.get("type")
        directorate = d.get("directorate")
        return Opportunity(
            source=self.id,
            source_id=row["id"],
            url=BASE + row["path"],
            title=d.get("title") or row.get("title") or "",
            organization="European Space Agency (ESA)",
            kind=appointment_kind(typ) or "job",
            description=clean_description(d.get("description") or ""),
            locations=esa_locations(d.get("location") or row.get("workplace")),
            posted=parse_date(d.get("posted")),
            deadline=parse_date(d.get("closing") or row.get("closing")),
            contract=typ,
            tags=[t for t in (typ, directorate) if t],
        )
