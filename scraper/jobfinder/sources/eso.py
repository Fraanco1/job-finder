"""ESO (European Southern Observatory) recruitment portal.

Staff, fellowships (postdoc), studentships (PhD), summer students and
internships at ESO Headquarters (Garching, Germany) and the observatories in
Chile (incl. ALMA). An RSS feed lists the openings; each job page (fetched
once, cached) carries location, deadline and full text.
"""

from __future__ import annotations

import re

from lxml import etree

from ..dates import parse_date
from ..geocode import geocode
from ..models import Opportunity
from .base import DetailCache, Source, html_to_text, soup

BASE = "https://recruitment.eso.org"

CHILE_SITES = {
    "santiago": "Santiago", "vitacura": "Vitacura", "la serena": "La Serena",
    "antofagasta": "Antofagasta", "paranal": "Antofagasta", "armazones": "Antofagasta",
    "elt": "Antofagasta", "la silla": "La Serena", "chajnantor": "Calama", "apex": "Calama",
    "san pedro": "Calama", "sequitor": "Calama", "chile": None,
}


# ESO's standard "about us" paragraph mentions astronomy several times; it
# would make every admin job look like astrophysics to the classifier.
BOILERPLATE = re.compile(
    r"foremost intergovernmental astronomy organisation|European Organisation for Astronomical Research"
    r"|international astronomy facility operated through|ALMA is funded by|ALMA operations are led by",
    re.I)
NON_RESEARCH = re.compile(r"design|media|communication|outreach|procurement|finance|legal|human resources|"
                          r"administrat|education", re.I)


def kind_hint(title: str) -> str | None:
    t = title.lower()
    if re.search(r"summer student|intern", t):
        return "internship"
    if "studentship" in t:
        return "phd"
    if "fellow" in t:
        return "postdoc"
    return None


def parse_rss(xml: bytes) -> list[dict]:
    root = etree.fromstring(xml, parser=etree.XMLParser(recover=True))
    out = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        m = re.search(r"/jobs/([\w-]+)", link)
        if not m:
            continue
        out.append({
            "id": m.group(1),
            "title": (item.findtext("title") or "").strip(),
            "posted": (item.findtext("pubDate") or "").strip(),
            "url": link,
        })
    return out


def parse_detail(html: str) -> dict:
    s = soup(html)
    head = s.select_one(".jobad-header")
    title = location = deadline = None
    if head:
        h1 = head.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else None
        ps = [p.get_text(" ", strip=True) for p in head.find_all("p")]
        location = next((p for p in ps if p and "deadline" not in p.lower()), None)
        dl = next((p for p in ps if "deadline" in p.lower()), "")
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", dl)
        deadline = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else (dl or None)
    parts = []
    main = s.select_one(".jobad-maintext")
    if main:
        parts.append(html_to_text(str(main)))
    text = "\n".join(p for p in parts if p)
    text = "\n".join(line for line in text.split("\n") if not BOILERPLATE.search(line))
    return {"title": title, "location": location, "deadline": deadline, "description": text[:12000]}


def eso_location(text: str | None, title: str = ""):
    t = (text or "").lower()
    if not any(k in t for k in CHILE_SITES) and "garching" not in t:
        t = "santiago" if "chile" in title.lower() else "garching"
    for key, city in CHILE_SITES.items():
        if key in t:
            return geocode(city, country_hint="Chile") if city else geocode(None, country_hint="Chile")
    return geocode("Garching bei München", country_hint="Germany")


class Eso(Source):
    id = "eso"
    name = "ESO Recruitment"
    homepage = BASE + "/"
    min_interval = 1.0

    def fetch(self):
        r = self.http.get(BASE + "/jobs.rss")
        r.raise_for_status()
        items = parse_rss(r.content)
        if self.limit:
            items = items[: self.limit]
        cache = DetailCache(self.id)
        for it in items:
            if cache.get(it["id"]) is None:
                try:
                    resp = self.http.get(f"{BASE}/jobs/{it['id']}")
                    if resp.status_code == 200:
                        cache.set(it["id"], parse_detail(resp.text))
                except Exception as e:  # noqa: BLE001
                    self.log.warning("job %s failed: %s", it["id"], e)
        cache.save()
        for it in items:
            d = cache.get(it["id"]) or {}
            title = d.get("title") or it["title"]
            loc = eso_location(d.get("location"), title)
            org = "ALMA / ESO" if "alma" in title.lower() else "European Southern Observatory (ESO)"
            yield Opportunity(
                source=self.id,
                source_id=it["id"],
                url=f"{BASE}/jobs/{it['id']}",
                title=title,
                organization=org,
                kind=kind_hint(title) or "job",
                description=d.get("description") or "",
                locations=[loc] if loc.lat is not None else [],
                posted=parse_date(it.get("posted")),
                deadline=parse_date(d.get("deadline")),
                # Fellowships/studentships are astronomy research; staff jobs
                # (engineering, admin) are left to the keyword classifier.
                source_fields=["Astronomy"] if kind_hint(title) and not NON_RESEARCH.search(title) else [],
                tags=[t for t in [d.get("location")] if t],
            )
