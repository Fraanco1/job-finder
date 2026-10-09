"""Normalized opportunity record shared by every scraper."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date

# Opportunity kinds understood by the frontend.
KINDS = ("job", "phd", "postdoc", "masters", "internship")

KIND_LABELS = {
    "job": "Job",
    "phd": "PhD",
    "postdoc": "Postdoc",
    "masters": "Master's",
    "internship": "Internship",
}


@dataclass
class Location:
    city: str | None = None
    region: str | None = None
    country: str | None = None       # full English name
    country_code: str | None = None  # ISO 3166-1 alpha-2
    lat: float | None = None
    lon: float | None = None
    remote: bool = False
    # How precise lat/lon is: "city", "country" or None (unknown, not mappable).
    precision: str | None = None


@dataclass
class Opportunity:
    source: str              # scraper id, e.g. "euraxess"
    source_id: str           # id within the source
    url: str
    title: str
    organization: str | None = None
    kind: str = "job"        # one of KINDS
    description: str = ""    # plain text, used for classification; trimmed on export
    locations: list[Location] = field(default_factory=list)
    posted: date | None = None
    deadline: date | None = None
    start_date: date | None = None
    start_text: str | None = None     # free-form start info ("ASAP", "Fall 2027")
    disciplines: list[str] = field(default_factory=list)
    subfields: list[str] = field(default_factory=list)
    required_degrees: list[str] = field(default_factory=list)  # discipline ids explicitly required
    education_level: str | None = None   # "bachelor" | "masters" | "phd" | None
    salary: str | None = None
    contract: str | None = None          # "full-time", "part-time", "temporary", ...
    tags: list[str] = field(default_factory=list)
    # Research fields / departments reported by the source itself (raw labels).
    source_fields: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.source}:{self.source_id}".encode()).hexdigest()[:12]

    def to_public(self, snippet_len: int = 360) -> dict:
        """Compact JSON-ready dict for the frontend."""
        d = asdict(self)
        desc = " ".join(self.description.split())
        if len(desc) > snippet_len:
            desc = desc[:snippet_len].rsplit(" ", 1)[0] + "…"
        out = {
            "id": self.id,
            "source": self.source,
            "url": self.url,
            "title": self.title,
            "org": self.organization,
            "kind": self.kind,
            "summary": desc,
            "locs": [
                {k: v for k, v in loc.items() if v not in (None, False, "")}
                for loc in d["locations"]
            ],
            "posted": _iso(self.posted),
            "deadline": _iso(self.deadline),
            "start": _iso(self.start_date),
            "startText": self.start_text,
            "disc": self.disciplines,
            "sub": self.subfields,
            "req": self.required_degrees,
            "edu": self.education_level,
            "salary": self.salary,
            "contract": self.contract,
            "tags": self.tags,
        }
        return {k: v for k, v in out.items() if v not in (None, [], "")}


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None
