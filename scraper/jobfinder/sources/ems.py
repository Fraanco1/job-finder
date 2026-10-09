"""European Mathematical Society job board (https://euromathsoc.org/jobs).

Mathematics PhD positions, postdoctoral fellowships, tenure-track and
professor jobs submitted by departments (mostly Europe, some worldwide).
The listing page shows the current ads; each ad page (fetched once, cached)
has the full text and the "Apply by" deadline.
"""

from __future__ import annotations

import re

from ..dates import parse_date
from ..geocode import gazetteer, geocode, norm
from ..models import Location, Opportunity
from .base import DetailCache, Source, html_to_text, soup

BASE = "https://euromathsoc.org"

CATEGORY_KIND = {
    "postdoctoral fellowships": "postdoc",
    "graduate student fellowships": "phd",
    "tenure track": "job",
    "professor": "job",
    "lecturer": "job",
}


def parse_listing(html: str) -> list[dict]:
    s = soup(html)
    out, seen = [], set()
    for a in s.select("a.row[href^='/jobs/']"):
        m = re.search(r"-(\d+)$", a["href"])
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        cells = a.find_all("div", recursive=False)
        col = {c.get("data-column"): c.get_text(" ", strip=True) for c in cells if c.get("data-column")}
        plain = [c.get_text(" ", strip=True) for c in cells if not c.get("data-column")]
        out.append({
            "id": m.group(1),
            "path": a["href"],
            "title": plain[0] if plain else None,
            "org": col.get("Organization") or None,
            "location": col.get("Location") or None,
            "category": col.get("Category") or None,
            "posted": plain[-1] if len(plain) > 1 else None,
        })
    return out


def parse_detail(html: str) -> dict:
    s = soup(html)
    desc = s.select_one(".description")
    apply_by = s.select_one(".apply-by")
    website = None
    if apply_by is not None:
        prev = apply_by.find_previous("a", href=re.compile(r"^https?://"))
        website = prev["href"] if prev else None
    updated = None
    text = s.get_text(" ", strip=True)
    m = re.search(r"Last updated:\s*(\d{1,2}\s+\w+\s+\d{4})", text)
    if m:
        updated = m.group(1)
    return {
        "description": html_to_text(str(desc))[:12000] if desc else "",
        "deadline": re.sub(r"^Apply by\s*", "", apply_by.get_text(" ", strip=True)) if apply_by else None,
        "website": website,
        "updated": updated,
    }


EUROPE = set("AD AL AT BA BE BG BY CH CY CZ DE DK EE ES FI FR GB GR HR HU IE IS IT LI LT LU LV MC MD "
              "ME MK MT NL NO PL PT RO RS RU SE SI SK SM TR UA VA XK".split())


def european_city(name: str) -> Location | None:
    """EMS is a European board: for a bare, ambiguous city name prefer the European one."""
    g = gazetteer()
    for c in g.cities.get(norm(name), []):
        if c.cc in EUROPE:
            return geocode(c.name, country_hint=g.countries[c.cc])
    return None


def mentioned_country(text: str) -> str | None:
    """First country name mentioned in ``text`` (used to disambiguate 'Valencia')."""
    best = None
    for name in gazetteer().countries.values():
        m = re.search(rf"\b{re.escape(name)}\b", text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), name)
    return best[1] if best else None


def ems_location(text: str | None, context: str = "", org: str = "") -> list[Location]:
    """'Bilbao - Spain' / 'San Diego, CA' / 'Oxford, OX2 6GG' / '' (+ org, text context) -> location."""
    text = (text or "").replace(" - ", ", ").strip()
    hint = mentioned_country(f"{org} {context[:1500]}")
    candidates = []
    if text:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        candidates = [", ".join(parts[i:]) for i in range(len(parts))]
    # No usable location: try capitalised words of the organisation ("Stockholm University").
    candidates += [w for w in re.findall(r"[A-ZÀ-Ý][\w'-]+", org or "") if len(w) > 3]
    first = None
    for cand in candidates:
        g = geocode(cand)
        if hint and g.country and g.country != hint:
            g2 = geocode(cand, country_hint=hint)
            if g2.precision == "city":
                g = g2
        if g.precision == "city" and "," not in cand and g.country_code not in EUROPE and not hint:
            g = european_city(cand) or g
        if g.precision == "city":
            return [g]
        first = first or (g if g.lat is not None else None)
    if first is None and hint:
        first = geocode(None, country_hint=hint)
    return [first] if first is not None and first.lat is not None else []


class EuroMathSoc(Source):
    id = "ems"
    name = "European Mathematical Society Jobs"
    homepage = BASE + "/jobs"
    min_interval = 1.0

    def fetch(self):
        r = self.http.get(BASE + "/jobs")
        r.raise_for_status()
        rows = parse_listing(r.text)
        self.log.info("%d ads", len(rows))
        if self.limit:
            rows = rows[: self.limit]
        cache = DetailCache(self.id)
        for row in rows:
            if cache.get(row["id"]) is None:
                try:
                    resp = self.http.get(BASE + row["path"])
                    if resp.status_code == 200:
                        cache.set(row["id"], parse_detail(resp.text))
                except Exception as e:  # noqa: BLE001
                    self.log.warning("ad %s failed: %s", row["id"], e)
        cache.save()
        for row in rows:
            yield self.to_opportunity(row, cache.get(row["id"]) or {})

    def to_opportunity(self, row: dict, d: dict) -> Opportunity:
        category = (row.get("category") or "").strip()
        opp = Opportunity(
            source=self.id,
            source_id=row["id"],
            url=BASE + row["path"],
            title=row.get("title") or "",
            organization=row.get("org"),
            kind=CATEGORY_KIND.get(category.lower(), "job"),
            description=d.get("description") or "",
            locations=ems_location(row.get("location"), d.get("description") or "", row.get("org") or ""),
            posted=parse_date(row.get("posted")),
            deadline=parse_date(d.get("deadline")),
            source_fields=["Mathematics"],
            tags=[t for t in [category] if t],
        )
        opp.disciplines = ["mathematics"]
        return opp
