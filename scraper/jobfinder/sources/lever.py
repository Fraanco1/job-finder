"""Lever public postings API (api.lever.co, or api.eu.lever.co for EU-hosted boards)."""

from __future__ import annotations

from ..dates import parse_timestamp
from ..models import Opportunity
from ._ats import ATSSource, clip, fmt_salary, geocode_all, kind_hint, norm_contract, split_locations
from .base import html_to_text

API = {
    "us": "https://api.lever.co/v0/postings/{token}?mode=json",
    "eu": "https://api.eu.lever.co/v0/postings/{token}?mode=json",
}


def _strip_country_prefix(text: str, country: str | None) -> str:
    """Quantinuum-style "US Broomfield, CO" -> "Broomfield, CO"."""
    if country and text.startswith(country + " ") and len(text) > 3:
        return text[len(country) + 1:]
    return text


class Lever(ATSSource):
    id = "lever"
    name = "Lever (company boards)"
    homepage = "https://www.lever.co/"
    ats = "lever"

    def fetch_board(self, company: dict) -> list[Opportunity]:
        url = API[company.get("region", "us")].format(token=company["token"])
        return [o for o in (self.parse_job(j, company) for j in self.http.get_json(url)) if o]

    def parse_job(self, j: dict, company: dict) -> Opportunity | None:
        title = (j.get("text") or "").strip()
        cat = j.get("categories") or {}
        dept = " ".join(x for x in (cat.get("department"), cat.get("team")) if x)
        if not title or not self.keep(title, dept):
            return None
        parts = [j.get("descriptionPlain") or html_to_text(j.get("description"))]
        for lst in j.get("lists") or []:
            parts.append(lst.get("text") or "")
            parts.append(html_to_text(lst.get("content")))
        parts.append(j.get("additionalPlain") or "")
        description = "\n".join(p for p in parts if p)

        country = j.get("country")
        raw = list(cat.get("allLocations") or []) or [cat.get("location") or ""]
        places = [(_strip_country_prefix(p, country), country) for r in raw for p in split_locations(r)]
        if not places and (company.get("hq") or country):
            places = [(company.get("hq"), country)]
        sal = j.get("salaryRange") or {}
        commitment = cat.get("commitment")
        return Opportunity(
            source=self.id,
            source_id=f"{company['token']}:{j['id']}",
            url=j.get("hostedUrl") or j.get("applyUrl"),
            title=title,
            organization=company["name"],
            kind=kind_hint(title, commitment) or "job",
            description=clip(description),
            locations=geocode_all(places, remote=(j.get("workplaceType") == "remote")),
            posted=parse_timestamp(j.get("createdAt")),
            salary=fmt_salary(sal.get("min"), sal.get("max"), sal.get("currency"), sal.get("interval")),
            contract=norm_contract(commitment),
            tags=[t for t in [company.get("sector")] if t],
            source_fields=[x for x in (cat.get("department"), cat.get("team")) if x],
        )
