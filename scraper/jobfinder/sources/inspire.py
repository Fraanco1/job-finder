"""INSPIRE-HEP job listings (https://inspirehep.net/jobs).

The community job board for high-energy, nuclear, astro- and theoretical
physics: postdocs, PhD and master positions, faculty and staff jobs worldwide.
Everything comes from the public JSON API. Institutions are resolved to their
INSPIRE records (city, country, coordinates) once and cached.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from ..dates import parse_date, parse_timestamp
from ..geocode import geocode, norm
from ..models import Location, Opportunity
from .base import DetailCache, Source, html_to_text

API = "https://inspirehep.net/api"
SITE = "https://inspirehep.net"

# INSPIRE ranks -> our kinds, most specific first.
RANK_KIND = [
    ("POSTDOC", "postdoc"),
    ("PHD", "phd"),
    ("MASTER", "masters"),
    ("UNDERGRADUATE", "internship"),
    ("JUNIOR", "job"),
    ("SENIOR", "job"),
    ("STAFF", "job"),
    ("VISITOR", "job"),
]
RANK_LABEL = {
    "SENIOR": "Senior (permanent)", "JUNIOR": "Junior (tenure track)", "STAFF": "Staff",
    "VISITOR": "Visiting scientist", "POSTDOC": "Postdoc", "PHD": "PhD", "MASTER": "Master",
    "UNDERGRADUATE": "Undergraduate",
}

# arXiv categories -> (discipline, subfield, human label for source_fields)
ARXIV = {
    "astro-ph": ("physics", "astrophysics", "Astrophysics"),
    "gr-qc": ("physics", "astrophysics", "Relativity"),
    "hep-ex": ("physics", "particle-physics", "Particle physics (experiment)"),
    "hep-ph": ("physics", "particle-physics", "Particle physics (phenomenology)"),
    "hep-th": ("physics", "theoretical-physics", "Theoretical physics"),
    "hep-lat": ("physics", "theoretical-physics", "Lattice QCD"),
    "nucl-ex": ("physics", "particle-physics", "Nuclear physics"),
    "nucl-th": ("physics", "particle-physics", "Nuclear physics"),
    "quant-ph": ("physics", "quantum-computing", "Quantum physics"),
    "cond-mat": ("physics", "condensed-matter", "Condensed matter"),
    "physics.acc-ph": ("physics", "particle-physics", "Accelerator physics"),
    "physics.ins-det": ("physics", "instrumentation", "Instrumentation and detectors"),
    "physics": ("physics", None, "Physics"),
    "math-ph": ("physics", "theoretical-physics", "Mathematical physics"),
    "nlin": ("physics", None, "Nonlinear sciences"),
    "math": ("mathematics", None, "Mathematics"),
    "stat": ("mathematics", "probability-statistics", "Statistics"),
    "cs": ("computer-science", None, "Computer science"),
    "eess": ("electrical-engineering", None, "Electrical engineering"),
    "q-bio": ("life-sciences", None, "Biology"),
    "q-fin": ("mathematics", "financial-math", "Quantitative finance"),
}


def kind_from_ranks(ranks: list[str]) -> str | None:
    ranks = [r.upper() for r in ranks or []]
    for rank, kind in RANK_KIND:
        if rank in ranks:
            return kind
    return None


def categories_to_fields(cats: list[str]) -> tuple[list[str], list[str], list[str]]:
    """arXiv categories -> (disciplines, subfields, labels).

    Non-physics categories (cs, math, stat...) only become disciplines when the
    job lists no physics category: on INSPIRE they are usually secondary tags.
    """
    discs: list[str] = []
    subs: list[str] = []
    labels: list[str] = []
    entries = [ARXIV[c] for c in cats or [] if c in ARXIV]
    has_physics = any(d == "physics" for d, _s, _l in entries)
    for d, s, label in entries:
        if label not in labels:
            labels.append(label)
        if has_physics and d != "physics":
            continue
        if d not in discs:
            discs.append(d)
        if s and s not in subs:
            subs.append(s)
    return discs, subs, labels


def parse_institution(meta: dict) -> dict:
    """INSPIRE institution record -> compact location dict."""
    addr = (meta.get("addresses") or [{}])[0]
    hier = meta.get("institution_hierarchy") or []
    return {
        "name": (hier[0].get("name") if hier else None) or meta.get("legacy_ICN"),
        "city": (addr.get("cities") or [None])[0],
        "state": addr.get("state"),
        "country": addr.get("country"),
        "cc": addr.get("country_code"),
        "lat": addr.get("latitude"),
        "lon": addr.get("longitude"),
    }


def institution_location(info: dict) -> Location | None:
    if not info:
        return None
    country = info.get("country") or info.get("cc")
    city = info.get("city")
    g = geocode(", ".join(x for x in (city, info.get("state")) if x) or None, country_hint=country)
    if g.precision != "city" and city:
        for cand in (geocode(city, country_hint=country), geocode(city)):
            if cand.precision == "city":
                g = cand
                break
            # City-states recorded as "Hong Kong, China" / "Singapore, Singapore".
            if cand.lat is not None and cand.country and norm(cand.country) == norm(city):
                g = cand
                break
    if (g.lat is None or g.precision != "city") and info.get("lat") is not None and city:
        # Not in the gazetteer (small town / lab site): trust INSPIRE's coordinates.
        g = Location(city=city, region=info.get("state"), country=g.country or info.get("country"),
                     country_code=g.country_code or info.get("cc"),
                     lat=round(float(info["lat"]), 4), lon=round(float(info["lon"]), 4), precision="city")
    return g if g.lat is not None else None


def name_location(name: str | None) -> Location | None:
    """Last resort: a place named inside the institution string ("Sun Yat-Sen U., Zhuhai")."""
    if not name:
        return None
    parts = [p.strip() for p in name.split(",") if p.strip()]
    cands = [", ".join(parts[i:]) for i in range(1, len(parts))]
    cands += [w for w in re.findall(r"[A-Z][\w'-]{3,}", name) if w not in ("University", "Institute", "National")]
    fallback = None
    for cand in cands:
        g = geocode(cand)
        if g.precision == "city":
            return g
        fallback = fallback or (g if g.lat is not None else None)
    return fallback


class Inspire(Source):
    id = "inspire"
    name = "INSPIRE-HEP Jobs"
    homepage = SITE + "/jobs"
    min_interval = 0.5
    page_size = 250

    def fetch(self):
        hits = []
        page = 1
        while True:
            size = min(self.page_size, self.limit) if self.limit else self.page_size
            data = self.http.get_json(
                f"{API}/jobs", params={"q": "status:open", "sort": "mostrecent", "size": size, "page": page},
                headers={"Accept": "application/json"})
            batch = data.get("hits", {}).get("hits", [])
            hits.extend(batch)
            total = data.get("hits", {}).get("total", 0)
            self.log.info("page %d: %d jobs (total %d)", page, len(batch), total)
            if not batch or len(hits) >= total or (self.limit and len(hits) >= self.limit):
                break
            page += 1
        if self.limit:
            hits = hits[: self.limit]

        cache = DetailCache("inspire_institutions", ttl_days=365)
        try:
            for h in hits:
                opp = self.to_opportunity(h.get("metadata") or {}, cache)
                if opp:
                    yield opp
        finally:
            cache.save()

    # ------------------------------------------------------------ institutions

    def resolve_institution(self, inst: dict, cache: DetailCache) -> dict:
        ref = (inst.get("record") or {}).get("$ref", "")
        rid = ref.rstrip("/").rsplit("/", 1)[-1] if ref else None
        key = f"id:{rid}" if rid else f"name:{inst.get('value')}"
        hit = cache.get(key)
        if hit is not None:
            return hit
        info: dict = {}
        try:
            if rid:
                data = self.http.get_json(f"{API}/institutions/{rid}", headers={"Accept": "application/json"})
                info = parse_institution(data.get("metadata") or {})
            elif inst.get("value"):
                q = f'legacy_ICN:"{inst["value"]}"'
                data = self.http.get_json(f"{API}/institutions?q={quote(q)}&size=1",
                                          headers={"Accept": "application/json"})
                found = data.get("hits", {}).get("hits", [])
                if not found:  # not an exact ICN: free-text search, best hit
                    data = self.http.get_json(f"{API}/institutions?q={quote(inst['value'])}&size=1",
                                              headers={"Accept": "application/json"})
                    found = data.get("hits", {}).get("hits", [])
                if found:
                    info = parse_institution(found[0].get("metadata") or {})
        except Exception as e:  # noqa: BLE001
            self.log.warning("institution %s failed: %s", key, e)
            return {}
        cache.set(key, info)
        return info

    # ------------------------------------------------------------ mapping

    def to_opportunity(self, m: dict, cache: DetailCache) -> Opportunity | None:
        cn = m.get("control_number")
        title = (m.get("position") or "").strip()
        if not cn or not title:
            return None

        orgs, locations = [], []
        for inst in m.get("institutions") or []:
            info = self.resolve_institution(inst, cache) if inst.get("value") else {}
            orgs.append(info.get("name") or inst.get("value"))
            loc = institution_location(info) or name_location(inst.get("value"))
            if loc and all((loc.lat, loc.lon) != (x.lat, x.lon) for x in locations):
                locations.append(loc)

        discs, subs, labels = categories_to_fields(m.get("arxiv_categories") or [])
        experiments = [e.get("name") for e in m.get("accelerator_experiments") or [] if e.get("name")]
        ranks = m.get("ranks") or []
        description = html_to_text(m.get("description"))
        extra = []
        if experiments:
            extra.append("Experiments: " + ", ".join(experiments))
        if labels:
            extra.append("Fields: " + ", ".join(labels))
        if extra:
            description = description + "\n" + "\n".join(extra)

        acq = m.get("acquisition_source") or {}
        opp = Opportunity(
            source=self.id,
            source_id=str(cn),
            url=f"{SITE}/jobs/{cn}",
            title=title,
            organization="; ".join(o for o in orgs if o) or None,
            kind=kind_from_ranks(ranks) or "job",
            description=description,
            locations=locations,
            posted=parse_timestamp(acq.get("datetime")),
            deadline=parse_date(m.get("deadline_date")),
            source_fields=labels,
            tags=[RANK_LABEL.get(r, r.title()) for r in ranks if r != "OTHER"]
            + experiments,
        )
        opp.disciplines = discs or ["physics"]
        opp.subfields = subs
        return opp
