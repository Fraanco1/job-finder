"""ETH Zurich job portal: doctoral, postdoc, student-assistant and internship positions.

jobs.ethz.ch renders every open vacancy on one HTML page (title, workload /
place / contract, publication date, department). The job-type filter is a
CSRF-protected POST, so we take the whole list and fetch each advert page
once (cached); the classifier then keeps the STEM ones and assigns the kind.
"""

from __future__ import annotations

import re

from ..dates import parse_date
from ..geocode import geocode
from ..models import Opportunity
from ._de_fields import german_fields
from .base import DetailCache, Source, html_to_text, soup

BASE = "https://jobs.ethz.ch"

PLACES = {"zürich": "Zurich", "zurich": "Zurich", "basel": "Basel", "lugano": "Lugano",
          "singapur": "Singapore", "singapore": "Singapore", "ascona": "Ascona", "genf": "Geneva",
          "geneva": "Geneva", "lausanne": "Lausanne", "locarno": "Locarno", "heilbronn": "Heilbronn",
          "dübendorf": "Dübendorf", "duebendorf": "Dübendorf", "villigen": "Villigen",
          "davos": "Davos", "birmensdorf": "Birmensdorf", "einsiedeln": "Einsiedeln"}
PLACE_COUNTRY = {"Singapore": "Singapore", "Heilbronn": "Germany"}

# German titles the classifier does not know.
_KIND_HINTS = [
    ("phd", re.compile(r"\bdoktorand\w*|\bdoctoral\b|\bph\.?d", re.I)),
    ("postdoc", re.compile(r"\bpostdoktorand\w*", re.I)),
    ("internship", re.compile(r"\bpraktik\w*|\bstudentische\w*|\bhilfsassistent\w*|"
                              r"\bstudent (?:research )?assistant\w*|\bmaster'?s? thesis|\bwerkstudent\w*", re.I)),
]
# Boilerplate sections that would only add noise to the classifier.
_SKIP_SECTIONS = re.compile(r"^(about eth|we value diversity|über die eth|wir schätzen vielfalt)", re.I)


class EthZurich(Source):
    id = "eth_zurich"
    name = "ETH Zurich jobs"
    homepage = BASE + "/"
    min_interval = 0.8

    @staticmethod
    def parse_listing(html: str) -> list[dict]:
        s = soup(html)
        out = []
        for a in s.select("a.job-ad__item__link[href^='/job/view/']"):
            href = a["href"]
            title = a.select_one(".job-ad__item__title")
            details = a.select_one(".job-ad__item__details")
            company = a.select_one(".job-ad__item__company")
            date_txt, dept = None, None
            if company:
                bits = [b.strip() for b in company.get_text(" ", strip=True).split("|")]
                date_txt = bits[0] if bits else None
                dept = bits[1] if len(bits) > 1 else None
            out.append({
                "id": href.rsplit("/", 1)[-1],
                "path": href,
                "title": title.get_text(" ", strip=True) if title else a.get("aria-label", ""),
                "details": details.get_text(" ", strip=True) if details else "",
                "posted": date_txt,
                "department": dept,
            })
        return out

    @staticmethod
    def parse_detail(html: str) -> dict:
        s = soup(html)
        sec = s.select_one("section.description")
        parts: list[str] = []
        if sec:
            for region in sec.find_all("div", class_="description__paragraph"):
                head = region.find_previous(["h2"])
                head_txt = head.get_text(" ", strip=True) if head else ""
                if head_txt and _SKIP_SECTIONS.search(head_txt):
                    continue
                txt = html_to_text(str(region))
                if txt and txt not in parts:
                    parts.append(txt)
        app = s.select_one("section.application .description__paragraph")
        if app:
            parts.append(html_to_text(str(app)))
        wp = s.select_one("iframe[title^='Workplace']")
        h1 = s.select_one("h1#job-title")
        h4 = s.select_one("section.description h4")
        return {
            "title": h1.get_text(" ", strip=True) if h1 else None,
            "details": h4.get_text(" ", strip=True) if h4 else None,
            "workplace": wp["title"].split("-", 1)[-1].strip() if wp else None,
            "description": "\n".join(parts)[:8000],
        }

    def fetch(self):
        r = self.http.get(BASE + "/", headers={"Accept-Language": "en"})
        r.raise_for_status()
        rows = self.parse_listing(r.text)
        self.log.info("%d vacancies", len(rows))
        if self.limit:
            rows = rows[: self.limit]
        cache = DetailCache(self.id)
        for c in rows:
            if cache.get(c["id"]) is not None:
                continue
            try:
                resp = self.http.get(BASE + c["path"])
                if resp.status_code == 200:
                    cache.set(c["id"], self.parse_detail(resp.text))
            except Exception as e:  # noqa: BLE001
                self.log.warning("detail %s failed: %s", c["id"], e)
        cache.save()
        for c in rows:
            yield self.to_opportunity(c, cache.get(c["id"]) or {})

    def to_opportunity(self, c: dict, d: dict) -> Opportunity:
        title = d.get("title") or c["title"]
        kind = next((k for k, rx in _KIND_HINTS if rx.search(title)), "job")
        details = d.get("details") or c.get("details") or ""
        place = None
        for tok in [t.strip() for t in details.split(",")]:
            place = PLACES.get(tok.lower()) or place
        if place is None and d.get("workplace"):
            m = re.search(r"\b\d{4}\s+([A-Za-zÀ-ÿ.\- ]+?)(?:\s+\w+)?$", d["workplace"])
            place = m.group(1) if m else None
        place = place or "Zurich"
        loc = geocode(place, country_hint=PLACE_COUNTRY.get(place, "Switzerland"))
        if loc.lat is None:
            loc = geocode("Zurich", country_hint="Switzerland")
        contract = details.split(",")[-1].strip() if "," in details else None
        description = "\n".join(x for x in (c.get("department"), d.get("description")) if x)
        return Opportunity(
            source=self.id,
            source_id=c["id"],
            url=BASE + c["path"],
            title=title,
            organization="ETH Zurich",
            kind=kind,
            description=description,
            locations=[loc],
            posted=parse_date(c.get("posted")),
            contract=", ".join(x for x in (details.split(",")[0].strip() if details else None, contract)
                               if x) or None,
            source_fields=german_fields(title, c.get("department")),
            tags=[x for x in (c.get("department"),) if x],
        )
