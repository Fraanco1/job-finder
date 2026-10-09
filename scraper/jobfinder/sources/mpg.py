"""Max Planck Society job board (English, https://www.mpg.de/jobboard).

PhD, postdoc, group-leader and scientist positions at the ~85 Max Planck
Institutes (mostly Germany, a few abroad). We query the board's "load more"
endpoint filtered to the natural-science research subjects, then fetch each
offer page once (cached) for the description, subject tags and position type.
"""

from __future__ import annotations

import json
import re

from ..dates import parse_date
from ..geocode import geocode
from ..models import Location, Opportunity
from .base import DetailCache, Source, html_to_text, soup

BASE = "https://www.mpg.de"
MORE = BASE + "/jobboard/115824/more_items"

# Board subject ids (English board): physics, astronomy, materials, maths,
# complex systems, chemistry, computer science, earth & climate.
SUBJECTS = ["a-ap", "tp-pp-qp", "ff-mw", "ma", "ks", "ch", "it", "gf-kf"]
SUBJECT_FIELDS = {
    "a-ap": "Astrophysics", "tp-pp-qp": "Physics", "ff-mw": "Solid state physics",
    "ma": "Mathematics", "ks": None, "ch": "Chemistry", "it": "Computer science",
    "gf-kf": "Earth science",
}
# Tag labels on offer pages -> source field labels the classifier understands.
TAG_FIELDS = {
    "astronomy & astrophysics": "Astrophysics",
    "particle, plasma and quantum physics": "Physics",
    "solid state research & material sciences": "Solid state physics",
    "mathematics": "Mathematics",
    "chemistry": "Chemistry",
    "computer science": "Computer science",
    "earth sciences and climate research": "Earth science",
}


def parse_items(html: str) -> list[dict]:
    s = soup(html)
    out = []
    for li in s.select("li.teaser"):
        a = li.select_one("h3 a[href]")
        if not a:
            continue
        m = re.match(r"/(\d+)/", a["href"])
        if not m:
            continue
        date_el = li.select_one(".date")
        box = li.select_one(".text-box")
        inst = ""
        if box:
            divs = box.find_all("div", recursive=False)
            inst = divs[-1].get_text(" ", strip=True) if len(divs) > 1 else ""
        out.append({
            "id": m.group(1),
            "path": a["href"],
            "title": a.get_text(" ", strip=True),
            "posted": date_el.get_text(strip=True) if date_el else None,
            "institute": inst,
        })
    return out


def parse_detail(html: str) -> dict:
    s = soup(html)
    art = s.select_one("article.job_offer") or s.select_one("article")
    scope = art if art is not None else s
    city = (scope.select_one(".city") or {}) and scope.select_one(".city").get_text(" ", strip=True)
    typ = (scope.select_one(".subject") or {}) and scope.select_one(".subject").get_text(" ", strip=True)
    tags = [t.get_text(" ", strip=True) for t in scope.select(".tags span")]
    code_text = code.get_text(" ", strip=True) if (code := scope.select_one(".job_code")) else None
    container = art.parent if art is not None else None
    desc = ""
    if container is not None:
        for x in container.select("article, script, style, .social-media-buttons"):
            x.decompose()
        desc = html_to_text(str(container))
    return {
        "city": city or None,
        "type": typ or None,
        "tags": tags,
        "code": code_text,
        "description": desc[:12000],
    }


def split_institute(text: str) -> tuple[str | None, str | None]:
    """'Max Planck Institute for Physics, Garching' -> (org, city)."""
    if not text:
        return None, None
    if "," in text:
        org, city = text.rsplit(",", 1)
        return org.strip(), city.strip()
    return text.strip(), None


def _one_city(city: str) -> Location | None:
    for name in (city, city.split("-")[0], city.split(" an der ")[0]):
        g = geocode(name, country_hint="Germany")
        if g.precision == "city":
            return g
    g2 = geocode(city)  # institutes abroad (Florida, Luxembourg, Rome, ...)
    if g2.precision == "city":
        return g2
    return g if g.lat is not None else None


def mpg_locations(city: str | None) -> list[Location]:
    """'Stuttgart, Hamburg, Halle' / 'Radolfzell / Constance' / 'Potsdam-Golm' -> locations."""
    out: list[Location] = []
    for part in re.split(r"\s*[,/;]\s*|\s+and\s+|\s+&\s+", city or ""):
        if not part.strip():
            continue
        g = _one_city(part.strip())
        if g and all((g.lat, g.lon) != (x.lat, x.lon) for x in out):
            out.append(g)
    return out


class MaxPlanck(Source):
    id = "mpg"
    name = "Max Planck Society"
    homepage = BASE + "/jobboard"
    min_interval = 1.0
    page = 20  # the endpoint caps a page at 20 items

    def list_subject(self, subject: str) -> list[dict]:
        rows, offset = [], 0
        while True:
            r = self.http.get(MORE, params={
                "offset": offset, "limit": self.page, "subject": json.dumps([subject]),
                "region": "", "job_type": ""}, headers={"X-Requested-With": "XMLHttpRequest"})
            if r.status_code == 204:
                break
            r.raise_for_status()
            batch = parse_items(r.text)
            rows.extend(batch)
            if len(batch) < self.page:
                break
            offset += self.page
        return rows

    def fetch(self):
        rows: dict[str, dict] = {}
        for subj in SUBJECTS:
            for row in self.list_subject(subj):
                entry = rows.setdefault(row["id"], {**row, "subjects": []})
                entry["subjects"].append(subj)
        self.log.info("%d offers in natural-science subjects", len(rows))
        items = list(rows.values())
        if self.limit:
            items = items[: self.limit]

        cache = DetailCache(self.id)
        for it in items:
            if cache.get(it["id"]) is None:
                try:
                    r = self.http.get(BASE + it["path"])
                    if r.status_code == 200:
                        cache.set(it["id"], parse_detail(r.text))
                except Exception as e:  # noqa: BLE001
                    self.log.warning("offer %s failed: %s", it["id"], e)
        cache.save()
        for it in items:
            yield self.to_opportunity(it, cache.get(it["id"]) or {})

    def to_opportunity(self, it: dict, d: dict) -> Opportunity:
        org, city = split_institute(it.get("institute") or "")
        locs = mpg_locations(d.get("city") or city)
        fields = [TAG_FIELDS[t.lower()] for t in d.get("tags") or [] if t.lower() in TAG_FIELDS]
        subjects = it.get("subjects") or []
        if not d.get("tags") and len(subjects) <= 2:  # broad calls are cross-listed everywhere
            fields += [SUBJECT_FIELDS[s] for s in subjects if SUBJECT_FIELDS.get(s)]
        fields = list(dict.fromkeys(fields))
        description = d.get("description") or ""
        if org and org.lower() not in description[:400].lower():
            description = f"{org}\n{description}"
        typ = d.get("type")
        return Opportunity(
            source=self.id,
            source_id=it["id"],
            url=BASE + it["path"],
            title=it["title"],
            organization=org or "Max Planck Society",
            kind="phd" if typ and "young researchers" in typ.lower() and
            re.search(r"\bph\.?d|doctoral", it["title"], re.I) else "job",
            description=description,
            locations=locs,
            posted=parse_date(it.get("posted")),
            source_fields=fields,
            tags=[t for t in [typ] + (d.get("tags") or []) if t],
        )
