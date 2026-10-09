"""FAPESP fellowship opportunities (https://fapesp.br/oportunidades/).

The São Paulo Research Foundation publishes every open, FAPESP-funded
postdoc, PhD, direct-doctorate, master's and technical-training fellowship
in Brazil's largest research system (USP, UNICAMP, UNESP, UFABC, INPE, CNPEM,
...). One bilingual listing page holds all open calls; each call's page
(fetched once, cached) has the field of knowledge, start date and full text.
All fields are scraped; the classifier keeps the STEM ones.
"""

from __future__ import annotations

import re

from ..dates import parse_date
from ..geocode import geocode
from ..models import Opportunity
from .base import DetailCache, Source, html_to_text, soup

BASE = "https://fapesp.br/oportunidades/"

TITLE_KIND = [
    (re.compile(r"post-?doc", re.I), "postdoc"),
    (re.compile(r"direct doctorate|doctorate|doctoral|ph\.?d", re.I), "phd"),
    (re.compile(r"master", re.I), "masters"),
    (re.compile(r"technical training|undergraduate|scientific initiation|training", re.I), "internship"),
]

# FAPESP "Field of knowledge" labels that the shared field map does not know.
FIELD_ALIASES = {
    "astronomy": "Astronomy", "physics": "Physics", "mathematics": "Mathematics",
    "probability and statistics": "Statistics", "computer science": "Computer science",
    "chemistry": "Chemistry", "geosciences": "Geosciences", "biophysics": "Biophysics",
    "oceanography": "Earth science", "biochemistry": "Biochemistry",
}


# Fields of knowledge outside STEM: skipped at the source (their descriptions
# often mention "models", "data" or "statistics" and fool the keyword classifier).
NON_STEM_FIELDS = re.compile(
    r"administration|architecture|political|economics|education|psychology|urban and regional|"
    r"sociology|history|law|linguistics|letters|literature|philosophy|communication|anthropology|"
    r"journalism|arts|music|theology|social work|tourism|demography", re.I)


def title_kind(title: str) -> str | None:
    for rx, kind in TITLE_KIND:
        if rx.search(title or ""):
            return kind
    return None


def parse_listing(html: str) -> list[dict]:
    s = soup(html)
    out, seen = [], set()
    for li in s.select("li.box_col.en"):
        if "encerrada" in (li.get("class") or []):
            continue
        a = li.select_one("a.link_col[href]")
        if not a:
            continue
        m = re.search(r"/([^/]+)/(\d+)/?$", a["href"])
        if not m or m.group(2) in seen:
            continue
        seen.add(m.group(2))
        fields = {}
        principal = li.select_one(".text-principal")
        if principal:
            for strong in principal.find_all("strong"):
                key = strong.get_text(" ", strip=True).rstrip(":").strip().lower()
                val = strong.next_sibling
                fields[key] = val.strip() if isinstance(val, str) else ""
        title = li.select_one("strong.title")
        resumo = li.select_one(".text-resumo")
        out.append({
            "id": m.group(2),
            "slug": m.group(1),
            "title": title.get_text(" ", strip=True) if title else None,
            "institution": fields.get("instituition") or fields.get("institution"),
            "city": fields.get("city"),
            "deadline": fields.get("deadline for submissions"),
            "summary": resumo.get_text(" ", strip=True) if resumo else "",
        })
    return out


def parse_detail(html: str) -> dict:
    s = soup(html)
    info: dict[str, str] = {}
    for p in s.select("p.linha.en, p.linha:not(.pt)"):
        strong = p.find("strong")
        if not strong:
            continue
        key = strong.get_text(" ", strip=True).rstrip(":").strip()
        val = p.get_text(" ", strip=True)[len(strong.get_text(" ", strip=True)):].strip()
        info[key] = val
    sections = []
    for box in s.select("ul.list > li.box_col"):
        head = box.select_one("a.link_col.en")
        body = box.select_one("div.resumo.en")
        if body:
            heading = head.get_text(" ", strip=True) if head else ""
            sections.append(f"{heading}\n{html_to_text(str(body))}".strip())
    title = s.select_one("h3.detalhe.en")
    return {
        "title": title.get_text(" ", strip=True) if title else None,
        "field": info.get("Field of knowledge"),
        "working_area": info.get("Working area"),
        "project": info.get("Project title"),
        "institution": info.get("Unit/Instituition") or info.get("Unit/Institution"),
        "deadline": info.get("Deadline for submissions"),
        "posted": info.get("Publishing date"),
        "start": info.get("Start"),
        "locale": info.get("Locale"),
        "value": info.get("Value"),
        "investigator": info.get("Principal investigator"),
        "description": "\n".join(sections)[:12000],
    }


def fapesp_location(city: str | None):
    city = (city or "São Paulo").strip()
    parts = re.split(r"\s+e\s+|\s*,\s*|\s+and\s+", city)
    out = []
    for part in parts:
        g = geocode(part, country_hint="Brazil")
        if g.lat is not None and all((g.lat, g.lon) != (x.lat, x.lon) for x in out):
            out.append(g)
    return out


class Fapesp(Source):
    id = "fapesp"
    name = "FAPESP Fellowship Opportunities"
    homepage = BASE
    min_interval = 1.0

    def fetch(self):
        r = self.http.get(BASE)
        r.raise_for_status()
        rows = parse_listing(r.text)
        self.log.info("%d open opportunities", len(rows))
        if self.limit:
            rows = rows[: self.limit]
        cache = DetailCache(self.id)
        for row in rows:
            if cache.get(row["id"]) is None:
                try:
                    resp = self.http.get(f"{BASE}{row['slug']}/{row['id']}/")
                    if resp.status_code == 200:
                        cache.set(row["id"], parse_detail(resp.text))
                except Exception as e:  # noqa: BLE001
                    self.log.warning("opportunity %s failed: %s", row["id"], e)
        cache.save()
        for row in rows:
            d = cache.get(row["id"]) or {}
            if d.get("field") and NON_STEM_FIELDS.search(d["field"]):
                continue
            yield self.to_opportunity(row, d)

    def to_opportunity(self, row: dict, d: dict) -> Opportunity:
        title = d.get("title") or row.get("title") or ""
        field = d.get("field")
        fields = [FIELD_ALIASES.get(field.lower(), field)] if field else []
        desc_parts = [x for x in (d.get("project") and f"Project: {d['project']}",
                                  d.get("working_area") and f"Working area: {d['working_area']}",
                                  d.get("description") or row.get("summary")) if x]
        start_text = d.get("start")
        start = None
        if start_text:
            m = re.match(r"(\d{4}),?\s+([A-Za-z]+)", start_text)
            start = parse_date(f"1 {m.group(2)} {m.group(1)}") if m else parse_date(start_text)
        return Opportunity(
            source=self.id,
            source_id=row["id"],
            url=f"{BASE}{row['slug']}/{row['id']}/",
            title=title,
            organization=d.get("institution") or row.get("institution"),
            kind=title_kind(title) or "job",
            description="\n".join(desc_parts),
            locations=fapesp_location(d.get("locale") or row.get("city")),
            posted=parse_date(d.get("posted"), dayfirst=False),
            deadline=parse_date(d.get("deadline") or row.get("deadline"), dayfirst=False),
            start_date=start,
            start_text=start_text if not start else None,
            salary=d.get("value").split("(")[0].strip() if d.get("value") else None,
            source_fields=fields,
            tags=["FAPESP fellowship"] + [x for x in [field] if x],
        )
