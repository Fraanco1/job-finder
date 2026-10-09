"""SmartRecruiters public postings API (api.smartrecruiters.com/v1/companies/{id}/postings).

The listing has titles, locations and the posting's job *function*, but no
description, so we filter on title/function first and fetch the detail record
only for technical postings (cached, so each posting is fetched once).
Big employers (Bosch, Continental) have thousands of postings; ``max`` in
companies.json caps how many technical postings per company we keep.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ..dates import parse_timestamp
from ..models import Opportunity
from ._ats import ATSSource, clip, geocode_all, kind_hint, norm_contract
from .base import DetailCache, html_to_text

API = "https://api.smartrecruiters.com/v1/companies/{token}/postings"
PAGE = 100

# SmartRecruiters job-function ids that are technical. Anything else
# (sales, finance, hr, marketing, legal, administrative, ...) is skipped.
TECH_FUNCTIONS = {
    "engineering", "information_technology", "research", "science", "manufacturing",
    "quality_assurance", "production", "design", "analyst", "other", "",
}


class SmartRecruiters(ATSSource):
    id = "smartrecruiters"
    name = "SmartRecruiters (company boards)"
    homepage = "https://www.smartrecruiters.com/"
    ats = "smartrecruiters"
    workers = 2       # boards in parallel
    detail_workers = 4
    default_max = 400

    def __init__(self, limit: int | None = None):
        super().__init__(limit)
        self.cache = DetailCache(self.id, ttl_days=60)

    def list_postings(self, company: dict, cap: int) -> list[dict]:
        rows, offset = [], 0
        while True:
            # English-language ads only: the classifier's vocabulary is English,
            # and Bosch/Continental post thousands of local-language shop-floor ads.
            data = self.http.get_json(API.format(token=company["token"]),
                                      params={"limit": PAGE, "offset": offset, "language": "en"})
            content = data.get("content") or []
            for p in content:
                fn = ((p.get("function") or {}).get("id") or "").lower()
                if fn in TECH_FUNCTIONS and self.keep(p.get("name") or ""):
                    rows.append(p)
            offset += PAGE
            if len(rows) >= cap or not content or offset >= data.get("totalFound", 0):
                return rows[:cap]

    def detail(self, company: dict, pid: str) -> dict | None:
        key = f"{company['token']}:{pid}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        try:
            d = self.http.get_json(f"{API.format(token=company['token'])}/{pid}")
        except Exception as e:  # noqa: BLE001
            self.log.debug("detail %s failed: %s", key, e)
            return None
        sections = ((d.get("jobAd") or {}).get("sections") or {})
        text = "\n".join(
            html_to_text((sections.get(k) or {}).get("text"))
            for k in ("jobDescription", "qualifications", "additionalInformation", "companyDescription"))
        slim = {"description": clip(text), "url": d.get("postingUrl")}
        self.cache.set(key, slim)
        return slim

    def fetch_board(self, company: dict) -> list[Opportunity]:
        cap = self.per_board_cap() or int(company.get("max", self.default_max))
        rows = self.list_postings(company, cap)
        with ThreadPoolExecutor(self.detail_workers) as ex:
            details = list(ex.map(lambda p: self.detail(company, p["id"]), rows))
        self.cache.save()
        return [self.to_opportunity(p, d or {}, company) for p, d in zip(rows, details)]

    def to_opportunity(self, p: dict, d: dict, company: dict) -> Opportunity:
        loc = p.get("location") or {}
        city = ", ".join(x for x in (loc.get("city"), loc.get("region")) if x and len(x) > 3) or loc.get("city")
        places = [(city, (loc.get("country") or "").upper() or None)]
        employment = (p.get("typeOfEmployment") or {}).get("label")
        level = (p.get("experienceLevel") or {}).get("label")
        fn = (p.get("function") or {}).get("label")
        title = p.get("name", "").strip()
        return Opportunity(
            source=self.id,
            source_id=f"{company['token']}:{p['id']}",
            url=d.get("url") or f"https://jobs.smartrecruiters.com/{company['token']}/{p['id']}",
            title=title,
            organization=company["name"],
            kind=kind_hint(title, employment, level) or "job",
            description=d.get("description") or "",
            locations=geocode_all(places, remote=bool(loc.get("remote"))),
            posted=parse_timestamp(p.get("releasedDate")),
            contract=norm_contract(employment),
            tags=[t for t in [company.get("sector"), level if level and level != "Not Applicable" else None] if t],
            source_fields=[x for x in [fn] if x],
        )
