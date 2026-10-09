"""Ashby public job-board API (api.ashbyhq.com/posting-api)."""

from __future__ import annotations

from ..dates import parse_timestamp
from ..models import Opportunity
from ._ats import ATSSource, clip, geocode_all, kind_hint, norm_contract, split_locations
from .base import html_to_text

API = "https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"


def _place(loc: str | None, address: dict | None) -> list:
    """Prefer the structured postal address; fall back to the free-text location."""
    pa = (address or {}).get("postalAddress") or {}
    city, region, country = pa.get("addressLocality"), pa.get("addressRegion"), pa.get("addressCountry")
    if city or region:
        return [(", ".join(x for x in (city, region) if x), country)]
    parts = split_locations(loc)
    if parts:
        return [(p, country) for p in parts]
    return [(None, country)] if country else []


class Ashby(ATSSource):
    id = "ashby"
    name = "Ashby (company boards)"
    homepage = "https://www.ashbyhq.com/"
    ats = "ashby"

    def fetch_board(self, company: dict) -> list[Opportunity]:
        data = self.http.get_json(API.format(token=company["token"]))
        return [o for o in (self.parse_job(j, company) for j in data.get("jobs", [])) if o]

    def parse_job(self, j: dict, company: dict) -> Opportunity | None:
        title = (j.get("title") or "").strip()
        dept = " ".join(x for x in (j.get("department"), j.get("team")) if x)
        if not title or j.get("isListed") is False or not self.keep(title, dept):
            return None
        places = _place(j.get("location"), j.get("address"))
        for sec in j.get("secondaryLocations") or []:
            places += _place(sec.get("location"), sec.get("address"))
        comp = j.get("compensation") or {}
        salary = comp.get("scrapeableCompensationSalarySummary") or comp.get("compensationTierSummary")
        employment = j.get("employmentType")
        description = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml"))
        return Opportunity(
            source=self.id,
            source_id=f"{company['token']}:{j['id']}",
            url=j.get("jobUrl") or f"https://jobs.ashbyhq.com/{company['token']}/{j['id']}",
            title=title,
            organization=company["name"],
            kind=kind_hint(title, employment) or "job",
            description=clip(description),
            # ``isRemote`` is also true for hybrid roles; only fully remote ones count.
            locations=geocode_all(places, remote=(j.get("workplaceType") or "").lower() == "remote"),
            posted=parse_timestamp(j.get("publishedAt")),
            salary=salary if j.get("shouldDisplayCompensationOnJobPostings", True) else None,
            contract=norm_contract(employment),
            tags=[t for t in [company.get("sector")] if t],
            source_fields=[x for x in (j.get("department"), j.get("team")) if x],
        )
