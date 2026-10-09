"""Shared engine for the Duke "MathPrograms" job boards.

AcademicJobsOnline.org and MathJobs.org run the same software. Both offer:

* an RSS 1.0 feed of recently posted ads with rich ``ads:*`` fields (city,
  state, ISO country, disciplines, deadline, full description);
* an "all jobs" listing page grouped by employer (id, title, deadline);
* one detail page per ad with a small key/value grid.

We read the feed and the listing (two requests), then fetch detail pages only
for listed ads that are not in the feed and not cached yet. ``robots.txt``
asks for ``Crawl-delay: 5``, so detail fetching is slow the first time and
almost free afterwards.
"""

from __future__ import annotations

import re
from datetime import date

from lxml import etree

from ..dates import parse_date
from ..geocode import geocode
from ..models import Location, Opportunity
from ._physmath_util import country_name, ymd
from .base import DetailCache, Source, html_to_text, soup

# Position types used by the detail-page "Position Type" field.
_TYPE_RULES = [
    ("postdoc", re.compile(r"post-?doc", re.I)),
    ("phd", re.compile(r"\b(ph\.?d|doctoral student|graduate student|graduate fellowship)", re.I)),
    ("masters", re.compile(r"\bmaster", re.I)),
    ("internship", re.compile(r"\b(undergraduate|intern|interns|internships?|summer student|student assistant)\b", re.I)),
]

# Departments/titles that are clearly outside STEM: skip fetching their detail
# pages (the classifier would drop them anyway).
NON_STEM = re.compile(
    r"\b(law|legal|philosoph\w*|histor\w*|sociolog\w*|anthropolog\w*|econom\w*|english|"
    r"literature|music|arts?|theolog\w*|religio\w*|divinity|political|politics|government|"
    r"psycholog\w*|business|management|marketing|accounting|education|languages?|linguistics|"
    r"romance|german\w*|french|spanish|italian|classics|gender|african|asian|american studies|"
    r"journalism|communication studies|nursing|surgery|psychiatry|dentistry|law school|"
    r"humanities|social work|public policy|international affairs|film|theat\w*|dance)\b",
    re.I,
)
STEM_HINT = re.compile(
    r"(physic|astro|cosmo|math|statist|quantum|comput|engineer|chemi|data|scien|biolog|"
    r"geo|climat|energy|nuclear|particle|optic|material|robot|lab|institute)", re.I)


# Raw subject labels -> (discipline, subfield) used as a classification baseline.
LABEL_RULES: list[tuple[re.Pattern, str, str | None]] = [
    (re.compile(r"astro|cosmolog|galax|exoplanet|gravitational|planetary", re.I), "physics", "astrophysics"),
    (re.compile(r"high[- ]energy|particle|hep-|nuclear|neutrino|accelerator|collider|hadron", re.I),
     "physics", "particle-physics"),
    (re.compile(r"quantum (info|comput|tech|science)|\bqis\b|quant-ph", re.I), "physics", "quantum-computing"),
    (re.compile(r"condensed matter|cond-mat|solid state|quantum materials", re.I), "physics", "condensed-matter"),
    (re.compile(r"\bamo\b|atomic|quantum optics|\boptics|photonic", re.I), "physics", "optics-photonics"),
    (re.compile(r"plasma|fusion", re.I), "physics", "plasma-fusion"),
    (re.compile(r"biophysic|soft matter", re.I), "physics", "biophysics"),
    (re.compile(r"theoretical physics|mathematical physics|string theory|quantum field|quantum gravity|"
                r"particle theory|statistical physics|gr-qc|math-ph", re.I), "physics", "theoretical-physics"),
    (re.compile(r"physic", re.I), "physics", None),
    (re.compile(r"statist|probabil|stochastic", re.I), "mathematics", "probability-statistics"),
    (re.compile(r"applied math|\bnumerical|computational math|scientific computing", re.I),
     "mathematics", "applied-math"),
    (re.compile(r"\b(algebra\w*|geometry|topology|number theory|combinator\w*|logic|pure math\w*)\b", re.I),
     "mathematics", "pure-math"),
    (re.compile(r"\b(mathematical analysis|real analysis|complex analysis|functional analysis|harmonic analysis|"
                r"pdes?|partial differential|dynamical systems)\b", re.I), "mathematics", "analysis-pde"),
    (re.compile(r"operations research|optimization", re.I), "mathematics", "operations-research"),
    (re.compile(r"math", re.I), "mathematics", None),
]


def label_disciplines(labels: list[str]) -> tuple[list[str], list[str]]:
    """Map raw subject labels to (disciplines, subfields) for physics/mathematics."""
    discs: list[str] = []
    subs: list[str] = []
    for label in labels:
        for rx, d, s in LABEL_RULES:
            if rx.search(label):
                if d not in discs:
                    discs.append(d)
                if s and s not in subs:
                    subs.append(s)
                break
    return discs, subs


def kind_from_type(text: str | None) -> str | None:
    if not text:
        return None
    for kind, rx in _TYPE_RULES:
        if rx.search(text):
            return kind
    if re.search(r"faculty|professor|lecturer|instructor|staff|research scientist|chair", text, re.I):
        return "job"
    return None


def unwrap(text: str) -> str:
    """Join hard-wrapped feed lines while keeping paragraph breaks."""
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]*\n[ \t]*(?=\S)", "\n", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


# ---------------------------------------------------------------- parsers

def parse_rss(xml: bytes | str) -> list[dict]:
    """Parse the RSS 1.0 feed into plain dicts (one per ad)."""
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    root = etree.fromstring(xml, parser=etree.XMLParser(recover=True, huge_tree=True))
    out = []
    for item in root.iter():
        if not isinstance(item.tag, str) or etree.QName(item).localname != "item":
            continue
        rec: dict = {}
        for child in item:
            if not isinstance(child.tag, str):
                continue
            rec[etree.QName(child).localname] = (child.text or "").strip()
        link = rec.get("link") or item.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about") or ""
        jid = rec.get("ID") or (re.search(r"/(\d+)\?rss", link) or [None, None])[1]
        if not jid or not rec.get("title"):
            continue
        desc = rec.get("description") or ""
        desc = html_to_text(desc) if "<" in desc else unwrap(desc)
        out.append({
            "id": str(jid),
            "title": rec["title"],
            "org": rec.get("Univ") or None,
            "dept": rec.get("Dept") or None,
            "creator": rec.get("creator") or None,
            "city": rec.get("City") or None,
            "state": rec.get("State") or None,
            "country": rec.get("Country") or None,
            "disciplines": [d.strip() for d in re.split(r"[;,]", rec.get("Disciplines") or "") if d.strip()],
            "posted": rec.get("PostDate") or rec.get("date"),
            "deadline": rec.get("Deadline") or None,
            "end": rec.get("EndDate") or None,
            "description": desc[:12000],
        })
    return out


def parse_listing(html: str, job_path: str) -> list[dict]:
    """Parse the employer-grouped "all jobs" page. ``job_path`` is e.g. '/ajo/jobs/'."""
    s = soup(html)
    out, seen = [], set()
    rx = re.compile(re.escape(job_path) + r"(\d+)$")
    for box in s.select("div.clr"):
        h3 = box.find("h3")
        employer = re.sub(r"\s+,", ",", h3.get_text(" ", strip=True)) if h3 else None
        for li in box.select("ol > li"):
            a = next((x for x in li.find_all("a", href=True) if rx.search(x["href"])), None)
            if not a:
                continue
            jid = rx.search(a["href"]).group(1)
            if jid in seen:
                continue
            seen.add(jid)
            span = li.find("span", id=f"j{jid}")
            dl = li.find("span", class_="purplesml")
            out.append({
                "id": jid,
                "title": span.get_text(" ", strip=True) if span else a.get_text(strip=True),
                "employer": employer,
                "deadline": dl.get_text(" ", strip=True) if dl else None,
            })
    return out


def _field(fields: dict[str, str], suffix: str) -> str | None:
    """'Position Title' / 'Fellowship Title' / 'Job Title' -> value (ads use different nouns)."""
    for key, val in fields.items():
        if key == suffix or key.endswith(" " + suffix):
            return val
    return None


def parse_detail(html: str) -> dict:
    s = soup(html)
    fields: dict[str, str] = {}
    lat = lon = None
    for grid in s.select("div.grid2"):
        cells = grid.find_all("div", recursive=False)
        for k, v in zip(cells[0::2], cells[1::2]):
            key = k.get_text(" ", strip=True).rstrip(":").strip()
            if key.endswith("Location"):
                m = v.find("a", href=re.compile(r"maps\?q=")) if v else None
                if m:
                    mm = re.search(r"q=(-?[\d.]+),(-?[\d.]+)", m["href"])
                    if mm:
                        lat, lon = float(mm.group(1)), float(mm.group(2))
            fields.setdefault(key, re.sub(r"\s*\[\s*map\s*\]\s*", " ", v.get_text(" ", strip=True)).strip())
    sec = s.find("section")
    desc = html_to_text(str(sec)) if sec else ""
    desc = re.sub(r"^\w+ Description\s*", "", desc)
    h2 = s.find("h2")
    deadline_raw = _field(fields, "Deadline") or ""
    posted = re.search(r"posted\s+(\d{4}/\d{1,2}/\d{1,2})", deadline_raw)
    deadline = None if deadline_raw.lower().startswith(("none", "open", "(posted")) else deadline_raw
    subjects = list(dict.fromkeys(
        x.strip() for x in re.split(r"[,/;]", _field(fields, "Areas") or "") if x.strip()))
    return {
        "title": _field(fields, "Title"),
        "employer": h2.get_text(" ", strip=True) if h2 else None,
        "type": _field(fields, "Type"),
        "location": _field(fields, "Location"),
        "lat": lat,
        "lon": lon,
        "subjects": subjects,
        "deadline": deadline.split("(")[0].strip() if deadline else None,
        "posted": posted.group(1) if posted else None,
        "description": desc[:12000],
    }


# ---------------------------------------------------------------- source

class AcademicJobsBoard(Source):
    """Base for AJO-family boards; subclasses set the URLs and defaults."""

    base = ""
    rss_url = ""
    listing_url = ""
    job_path = ""          # path prefix of detail pages in the listing, e.g. "/ajo/jobs/"
    detail_url = ""        # format string with {id}
    public_url = ""        # format string with {id}
    min_interval = 5.0     # robots.txt: Crawl-delay: 5
    base_disciplines: list[str] = []
    skip_non_stem = False

    def fetch(self):
        cache = DetailCache(self.id, ttl_days=200)
        feed: dict[str, dict] = {}
        try:
            r = self.http.get(self.rss_url)
            r.raise_for_status()
            for rec in parse_rss(r.content):
                feed[rec["id"]] = rec
        except Exception as e:  # noqa: BLE001 - the listing alone still works
            self.log.warning("rss failed: %s", e)
        self.log.info("rss: %d ads", len(feed))

        listing: list[dict] = []
        try:
            r = self.http.get(self.listing_url)
            r.raise_for_status()
            listing = parse_listing(r.text, self.job_path)
        except Exception as e:  # noqa: BLE001
            self.log.warning("listing failed: %s", e)
        self.log.info("listing: %d ads", len(listing))
        if not listing and not feed:
            raise RuntimeError("both feed and listing are empty")

        rows = {x["id"]: x for x in listing}
        ids = list(rows) if listing else list(feed)
        # Feed items missing from the listing are kept while their ad is still up.
        today = date.today()
        for jid, rec in feed.items():
            if jid not in rows and (ymd(rec.get("end")) or today) >= today:
                ids.append(jid)
        # Newest first (ids are sequential) so --limit samples recent ads.
        ids.sort(key=lambda x: -int(x))
        if self.limit:
            ids = ids[: self.limit]

        fetched = 0
        for jid in ids:
            if jid in feed or cache.get(f"d:{jid}") is not None:
                continue
            row = rows.get(jid, {})
            if self.skip_non_stem and self._clearly_non_stem(row):
                continue
            try:
                r = self.http.get(self.detail_url.format(id=jid), allow_redirects=False)
                if r.status_code == 200:
                    cache.set(f"d:{jid}", parse_detail(r.text))
                    fetched += 1
            except Exception as e:  # noqa: BLE001
                self.log.warning("detail %s failed: %s", jid, e)
            if fetched and fetched % 25 == 0:
                self.log.info("details fetched: %d", fetched)
                cache.save()
        cache.save()
        self.log.info("%d new detail pages", fetched)

        for jid in ids:
            opp = self.to_opportunity(jid, rows.get(jid), feed.get(jid), cache.get(f"d:{jid}"))
            if opp:
                yield opp

    @staticmethod
    def _clearly_non_stem(row: dict) -> bool:
        text = f"{row.get('employer') or ''} {row.get('title') or ''}"
        return bool(NON_STEM.search(text)) and not STEM_HINT.search(text)

    # -------------------------------------------------------------- mapping

    def to_opportunity(self, jid: str, row: dict | None, rss: dict | None,
                       det: dict | None) -> Opportunity | None:
        row, rss, det = row or {}, rss or {}, det or {}
        if not (rss or det):
            return None
        title = rss.get("title") or det.get("title") or row.get("title")
        if not title:
            return None

        employer = row.get("employer") or det.get("employer") or rss.get("creator")
        org = rss.get("org")
        if not org and employer:
            org = employer.split(",")[0].strip()
        dept = rss.get("dept")
        if not dept and employer and "," in employer:
            dept = employer.split(",", 1)[1].strip()

        locations: list[Location] = []
        if rss.get("city") or rss.get("country"):
            cname = country_name(rss.get("country"))
            text = ", ".join(x for x in (rss.get("city"), rss.get("state")) if x)
            g = geocode(text or None, country_hint=cname)
            if g.lat is None and rss.get("city"):
                g = geocode(rss["city"], country_hint=cname)
            if g.lat is not None:
                locations.append(g)
        elif det.get("location"):
            raw = re.sub(r"\b\d[\d -]*\b", " ", det["location"])  # drop postal codes
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            country = parts[-1] if len(parts) > 1 else None
            g = geocode(", ".join(parts[:-1]) if country else raw, country_hint=country)
            if g.lat is None and det.get("lat") is not None:
                g = Location(city=parts[0] if parts else None, country=country,
                             lat=det["lat"], lon=det["lon"], precision="city")
            if g.lat is not None:
                locations.append(g)

        fields = list(rss.get("disciplines") or []) + list(det.get("subjects") or [])
        description = rss.get("description") or det.get("description") or ""
        header = " · ".join(x for x in (org, dept) if x)
        if header and header.lower() not in description[:300].lower():
            description = f"{header}\n{description}"

        deadline = ymd(det.get("deadline")) if det.get("deadline") else parse_date(rss.get("deadline"))
        if deadline is None and row.get("deadline"):
            deadline = ymd(row["deadline"])
        posted = parse_date(rss.get("posted")) if rss.get("posted") else ymd(det.get("posted"))

        opp = Opportunity(
            source=self.id,
            source_id=jid,
            url=self.public_url.format(id=jid),
            title=title,
            organization=org,
            kind=kind_from_type(det.get("type")) or "job",
            description=description,
            locations=locations,
            posted=posted,
            deadline=deadline,
            source_fields=fields,
            tags=[t for t in [det.get("type"), dept] if t],
        )
        discs, subs = label_disciplines(fields)
        opp.disciplines = list(dict.fromkeys(list(self.base_disciplines) + discs))
        opp.subfields = subs
        return opp
