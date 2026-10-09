"""Workable public job-board widget API (apply.workable.com/api/v1/widget)."""

from __future__ import annotations

from ..dates import parse_timestamp
from ..models import Opportunity
from ._ats import ATSSource, clip, geocode_all, kind_hint, norm_contract
from .base import html_to_text

API = "https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"


class Workable(ATSSource):
    id = "workable"
    name = "Workable (company boards)"
    homepage = "https://www.workable.com/"
    ats = "workable"

    def fetch_board(self, company: dict) -> list[Opportunity]:
        data = self.http.get_json(API.format(token=company["token"]))
        return [o for o in (self.parse_job(j, company) for j in data.get("jobs", [])) if o]

    def parse_job(self, j: dict, company: dict) -> Opportunity | None:
        title = (j.get("title") or "").strip()
        dept = " ".join(x for x in (j.get("department"), j.get("function")) if x)
        if not title or not self.keep(title, dept):
            return None
        places = []
        for loc in j.get("locations") or []:
            if loc.get("hidden"):
                continue
            text = ", ".join(x for x in (loc.get("city"), loc.get("region")) if x)
            places.append((text or None, loc.get("countryCode") or loc.get("country")))
        if not places and (j.get("city") or j.get("country")):
            places.append((", ".join(x for x in (j.get("city"), j.get("state")) if x) or None, j.get("country")))
        employment = j.get("employment_type")
        tags = [t for t in [company.get("sector"), j.get("experience")] if t]
        return Opportunity(
            source=self.id,
            source_id=f"{company['token']}:{j.get('shortcode')}",
            url=j.get("url") or j.get("shortlink"),
            title=title,
            organization=company["name"],
            kind=kind_hint(title, employment) or "job",
            description=clip(html_to_text(j.get("description"))),
            locations=geocode_all(places, remote=bool(j.get("telecommuting"))),
            posted=parse_timestamp(j.get("published_on") or j.get("created_at")),
            contract=norm_contract(employment),
            tags=tags,
            source_fields=[x for x in (j.get("department"), j.get("function"), j.get("industry")) if x],
        )
