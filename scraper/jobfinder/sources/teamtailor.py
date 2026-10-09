"""Teamtailor public RSS job feed ({company}.teamtailor.com/jobs.rss), common in Nordic/EU companies."""

from __future__ import annotations

from bs4 import BeautifulSoup

from ..dates import parse_date
from ..models import Opportunity
from ._ats import ATSSource, clip, geocode_all, kind_hint
from .base import html_to_text

FEED = "https://{token}.teamtailor.com/jobs.rss"


def _text(node, name: str) -> str:
    el = node.find(name)
    return el.get_text(" ", strip=True) if el else ""


class Teamtailor(ATSSource):
    id = "teamtailor"
    name = "Teamtailor (company boards)"
    homepage = "https://www.teamtailor.com/"
    ats = "teamtailor"

    def fetch_board(self, company: dict) -> list[Opportunity]:
        r = self.http.get(FEED.format(token=company["token"]))
        r.raise_for_status()
        return self.parse_feed(r.content, company)

    def parse_feed(self, xml: bytes | str, company: dict) -> list[Opportunity]:
        doc = BeautifulSoup(xml, "xml")
        return [o for o in (self.parse_item(it, company) for it in doc.find_all("item")) if o]

    def parse_item(self, it, company: dict) -> Opportunity | None:
        title = _text(it, "title")
        dept = " ".join(x for x in (_text(it, "department"), _text(it, "role")) if x)
        if not title or not self.keep(title, dept):
            return None
        places = []
        for loc in it.find_all("location"):
            city, country = _text(loc, "city"), _text(loc, "country")
            if city or country:
                places.append((city or None, country or None))
        link = _text(it, "link")
        remote = _text(it, "remoteStatus").lower() in ("fully", "remote", "fully_remote")
        return Opportunity(
            source=self.id,
            source_id=f"{company['token']}:{_text(it, 'guid') or link}",
            url=link,
            title=title,
            organization=company["name"],
            kind=kind_hint(title) or "job",
            description=clip(html_to_text(_text(it, "description"))),
            locations=geocode_all(places, remote=remote),
            posted=parse_date(_text(it, "pubDate")),
            tags=[t for t in [company.get("sector")] if t],
            source_fields=[d for d in [_text(it, "department")] if d],
        )
