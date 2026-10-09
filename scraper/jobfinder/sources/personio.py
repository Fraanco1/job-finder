"""Personio public XML job feed ({company}.jobs.personio.com/xml), common in German/EU start-ups."""

from __future__ import annotations

from bs4 import BeautifulSoup

from ..dates import parse_timestamp
from ..models import Opportunity
from ._ats import ATSSource, clip, geocode_all, kind_hint, norm_contract, split_locations
from .base import html_to_text

FEED = "https://{token}.jobs.personio.com/xml?language=en"
JOB_URL = "https://{token}.jobs.personio.com/job/{id}"

# Personio's own occupation categories that are clearly non-technical.
NONTECH_CATEGORIES = {
    "marketing_and_product", "sales_and_business_development", "finance", "human_resources",
    "administration", "legal", "customer_service", "media_and_communication",
}


def _text(node, name: str) -> str:
    el = node.find(name, recursive=False)
    return el.get_text(" ", strip=True) if el else ""


class Personio(ATSSource):
    id = "personio"
    name = "Personio (company boards)"
    homepage = "https://www.personio.com/"
    ats = "personio"

    def fetch_board(self, company: dict) -> list[Opportunity]:
        r = self.http.get(FEED.format(token=company["token"]))
        r.raise_for_status()
        return self.parse_feed(r.content, company)

    def parse_feed(self, xml: bytes | str, company: dict) -> list[Opportunity]:
        doc = BeautifulSoup(xml, "xml")
        out = []
        for pos in doc.find_all("position"):
            o = self.parse_position(pos, company)
            if o:
                out.append(o)
        return out

    def parse_position(self, pos, company: dict) -> Opportunity | None:
        title = _text(pos, "name")
        dept = _text(pos, "department")
        if not title or not self.keep(title, dept):
            return None
        if _text(pos, "occupationCategory") in NONTECH_CATEGORIES and not self.keep(title):
            return None
        offices = [_text(pos, "office")]
        extra = pos.find("additionalOffices")
        if extra:
            offices += [o.get_text(" ", strip=True) for o in extra.find_all("office")]
        places = [p for o in offices for p in split_locations(o)]
        locations = geocode_all(places)
        if not locations and company.get("hq"):
            locations = geocode_all([company["hq"]])
        parts = []
        descs = pos.find("jobDescriptions")
        if descs:
            for d in descs.find_all("jobDescription"):
                parts.append(_text(d, "name"))
                parts.append(html_to_text(_text(d, "value")))
        schedule, category = _text(pos, "schedule"), _text(pos, "employmentType")
        return Opportunity(
            source=self.id,
            source_id=f"{company['token']}:{_text(pos, 'id')}",
            url=JOB_URL.format(token=company["token"], id=_text(pos, "id")),
            title=title,
            organization=company["name"],
            kind=kind_hint(title, category, _text(pos, "recruitingCategory")) or "job",
            description=clip("\n".join(p for p in parts if p)),
            locations=locations,
            posted=parse_timestamp(_text(pos, "createdAt")),
            contract=norm_contract(schedule) or norm_contract(category),
            tags=[t for t in [company.get("sector"), _text(pos, "seniority")] if t],
            source_fields=[d for d in [dept] if d],
        )
