"""Greenhouse public job-board API (boards-api.greenhouse.io).

One request per company returns every open posting with its full HTML
description (``content=true``). Companies are listed in ``companies.json``.
"""

from __future__ import annotations

import html

from ..dates import parse_timestamp
from ..models import Opportunity
from ._ats import ATSSource, clip, geocode_all, kind_hint, norm_contract, split_locations
from .base import html_to_text

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


class Greenhouse(ATSSource):
    id = "greenhouse"
    name = "Greenhouse (company boards)"
    homepage = "https://www.greenhouse.com/"
    ats = "greenhouse"

    def fetch_board(self, company: dict) -> list[Opportunity]:
        data = self.http.get_json(API.format(token=company["token"]))
        return [o for o in (self.parse_job(j, company) for j in data.get("jobs", [])) if o]

    def parse_job(self, j: dict, company: dict) -> Opportunity | None:
        title = (j.get("title") or "").strip()
        departments = ", ".join(d.get("name") or "" for d in j.get("departments") or [])
        if not title or not self.keep(title, departments):
            return None
        meta = {}
        for m in j.get("metadata") or []:
            v = m.get("value")
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            if isinstance(v, str) and v:
                meta[(m.get("name") or "").lower()] = v
        employment = next((v for k, v in meta.items() if "employment" in k or k in ("job type", "type")), None)

        raw_loc = (j.get("location") or {}).get("name") or ""
        places = split_locations(raw_loc)
        for office in j.get("offices") or []:
            if office.get("location"):
                places.append(office["location"])
        description = html_to_text(html.unescape(j.get("content") or ""))
        return Opportunity(
            source=self.id,
            source_id=f"{company['token']}:{j['id']}",
            url=j.get("absolute_url") or f"https://job-boards.greenhouse.io/{company['token']}/jobs/{j['id']}",
            title=title,
            organization=company["name"],
            kind=kind_hint(title, employment) or "job",
            description=clip(description),
            locations=geocode_all(places or [company.get("hq")]),
            posted=parse_timestamp(j.get("first_published") or j.get("updated_at")),
            contract=norm_contract(employment),
            tags=[t for t in [company.get("sector")] if t],
            source_fields=[d for d in departments.split(", ") if d],
        )
