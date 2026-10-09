"""Shared plumbing for company applicant-tracking-system (ATS) job boards.

Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Personio and Teamtailor
all expose public, unauthenticated feeds meant for embedding a company's job
board on its own site. Each ATS gets its own ``Source`` module; this module
holds what they share:

* the curated company list (``companies.json``),
* the title filter that drops non-technical roles *before* classification
  (company boilerplate such as "we build quantum computers" would otherwise
  make a recruiter or account-executive posting look like physics),
* location splitting/geocoding and the board-level fetch loop.

The module name starts with ``_`` so the source registry does not import it as
a source on its own.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from ..geocode import geocode
from ..models import Location, Opportunity
from .base import Source

COMPANIES_FILE = Path(__file__).with_name("companies.json")
MAX_LOCATIONS = 5
MAX_DESCRIPTION = 8000


@lru_cache(maxsize=1)
def _all_companies() -> dict:
    return json.loads(COMPANIES_FILE.read_text())


def load_companies(ats: str) -> list[dict]:
    """Company entries (``{"token", "name", ...}``) for one ATS."""
    return list(_all_companies().get(ats, []))


# ---------------------------------------------------------------- title filter

def _rx(*parts: str) -> re.Pattern:
    return re.compile(r"(?<![\w])(?:" + "|".join(parts) + r")(?![\w])", re.I)


# Always non-technical, whatever else the title says ("Technical Recruiter",
# "Sales Engineer", "Customer Success Engineer").
HARD_NONTECH = _rx(
    r"recruit\w*", r"talent (?:acquisition|partner|sourcer|sourcing|community|pool)", r"sourcer",
    r"head ?hunter", r"account (?:executive|manager|director|lead)", r"(?:pre-?)?sales (?:engineer\w*|executive|manager|director|lead|representative|associate|specialist|operations|development|consultant)",
    r"(?:inside|field|channel|enterprise|regional|area|territory|technical|global) sales", r"pre-?sales", r"head of sales", r"vp,? sales",
    r"business development", r"bdr", r"sdr", r"(?:sales|business) development representative",
    r"go[- ]to[- ]market", r"gtm", r"revenue (?:operations|manager|lead)", r"attorney", r"paralegal", r"counsel",
    r"general counsel", r"lawyer", r"legal", r"contracts? (?:manager|specialist|administrator)",
    r"accountant", r"accounting", r"accounts (?:payable|receivable)", r"bookkeep\w*", r"payroll",
    r"tax", r"treasury", r"fp&a", r"financial (?:analyst|planning|controller|reporting)",
    r"financial controller", r"comptroller", r"auditor", r"investor relations",
    r"executive assistant", r"administrative assistant", r"admin assistant",
    r"personal assistant", r"receptionist", r"office (?:manager|coordinator|administrator|assistant)",
    r"front desk", r"human resources", r"hr", r"hrbp", r"people (?:partner|operations|ops|business partner|team|experience)",
    r"compensation", r"benefits", r"marketing (?:manager|director|lead|specialist|coordinator|associate|intern|operations|analyst)", r"(?:product|field|content|digital|growth|brand|performance|partner) marketing", r"head of marketing", r"marketer", r"copywriter", r"content (?:writer|creator|strategist|marketing|designer|manager)",
    r"social media", r"public relations", r"pr", r"communications? (?:manager|specialist|lead|director|coordinator|officer)",
    r"brand (?:manager|designer|director|lead|strategist)", r"events? (?:manager|coordinator|specialist|lead)", r"community manager",
    r"customer success", r"customer experience", r"customer service", r"client services",
    r"partnerships? (?:manager|lead|director)", r"head of partnerships", r"alliances", r"channel (?:manager|partner)", r"demand generation",
    r"growth (?:marketing|manager|lead)", r"government (?:affairs|relations)", r"public policy",
    r"policy (?:manager|lead|analyst|advisor)", r"chief of staff", r"chef", r"cook", r"barista",
    r"sous chef", r"dishwasher", r"janitor\w*", r"custodian", r"housekeep\w*",
    r"security guard", r"(?:cdl|truck|delivery|bus|van|forklift) driver", r"workplace (?:experience|coordinator|manager)",
    r"travel (?:coordinator|manager)", r"graphic designer", r"visual designer", r"brand designer",
    r"video (?:editor|producer)", r"videographer", r"photographer", r"storytelling", r"journalist", r"editor",
    r"procurement", r"purchasing", r"buyer", r"(?:global |strategic )?sourcing (?:manager|specialist|lead|director|analyst|agent)",
    r"global sourcing", r"(?:global )?supply manager", r"commodity manager", r"business analyst", r"real estate", r"insurance", r"underwriter", r"claims",
    # German / French / Spanish / Portuguese
    r"acheteu\w*", r"export control\w*", r"trade compliance",
    r"vertrieb\w*", r"verkauf\w*", r"einkauf\w*", r"eink[äa]ufer\w*", r"buchhalt\w*", r"personalreferent\w*",
    r"steuerberat\w*", r"assistenz", r"comptable", r"juriste", r"ventas", r"vendedor\w*",
    r"contador\w*", r"abogad\w*", r"reclutador\w*", r"vendas", r"jur[ií]dico",
    # placeholder postings that are not actual positions
    r"general application", r"open application", r"spontaneous application", r"unsolicited application",
    r"expression of interest", r"register your interest", r"interest form", r"future opportunit\w*",
    r"general interest", r"don'?t see (?:a|the|your)\b.*", r"(?:technology |tech )?talk", r"webinar",
    r"info(?:rmation)? session", r"insight (?:day|days|event|week|programme|program)", r"open day",
    r"coffee chat", r"meet (?:us|the team)", r"virtual event", r"careers? fair", r"initiativbewerbung", r"candidature spontan[ée]e",
)

# Non-technical unless the title also carries a strong technical term
# ("Data Scientist, Finance" stays; "Finance Manager" goes).
SOFT_NONTECH = _rx(
    r"sales", r"marketing", r"brand", r"revenue", r"partnerships?", r"commercial\w*", r"comercial",
    r"controller", r"driver", r"security officer",
    r"finance", r"financial", r"business (?:analyst|operations|partner|manager)", r"operations (?:associate|coordinator|specialist|analyst)",
    r"strategy", r"strategic", r"program coordinator", r"coordinator", r"administrat\w*",
    r"people", r"talent", r"culture", r"learning (?:and|&) development", r"customer", r"support specialist",
    r"help ?desk", r"desktop support", r"it support", r"communications?", r"content", r"designer",
    r"product designer", r"ux", r"ui", r"creative", r"design director", r"compliance",
    r"risk (?:manager|analyst)", r"supply chain (?:manager|analyst|planner|specialist|coordinator)",
    r"logistics", r"warehouse", r"inventory", r"shipping", r"receiving", r"facilities (?:coordinator|manager)",
    r"office", r"assistant", r"associate", r"intern", r"internship", r"trainee", r"apprentice",
    r"manager", r"director", r"head of", r"vp", r"vice president", r"chief", r"officer", r"lead",
    r"specialist", r"representative", r"analyst", r"consultant", r"advisor", r"planner",
    r"operator", r"product manager", r"product management", r"project manager", r"program manager", r"writer",
    r"superintendent", r"supervisor",
)

# Strong technical signal in a title.
TECH = _rx(
    r"engineer\w*", r"ingenieur\w*", r"ing[eé]nieur\w*", r"ingeniero\w*", r"engenheir\w*", r"ingegner\w*",
    r"scien\w+", r"research\w*", r"r&d", r"researcher", r"wissenschaftl\w*", r"chercheur\w*", r"investigador\w*",
    r"physicist", r"physics", r"chemist\w*", r"mathematic\w*", r"statistic\w*", r"quant\w*",
    r"developer", r"entwickl\w*", r"d[ée]veloppeur\w*", r"desarrollador\w*", r"programmer", r"coder",
    r"software", r"hardware", r"firmware", r"embedded", r"fpga", r"asic", r"rtl", r"vlsi", r"silicon",
    r"analog", r"digital design", r"mixed[- ]signal", r"rf", r"microwave", r"antenna\w*", r"photonic\w*",
    r"optic\w*", r"laser\w*", r"electro\w*", r"electrical", r"electronic\w*", r"mechanical", r"mechatronic\w*",
    r"thermal", r"structur\w*", r"propulsion", r"avionics", r"gnc", r"guidance", r"aerodynamic\w*",
    r"robot\w*", r"autonom\w*", r"perception", r"controls?", r"computer vision", r"vision",
    r"machine learning", r"ml", r"ai", r"deep learning", r"llm", r"nlp", r"data", r"algorithm\w*",
    r"computational", r"simulation", r"modell?ing", r"cfd", r"fea", r"hpc", r"compiler\w*", r"kernel",
    r"technician", r"techniker\w*", r"technicien\w*", r"t[eé]cnico\w*", r"machinist", r"welder", r"fabricat\w*",
    r"metrology", r"process", r"materials?", r"metallurg\w*", r"chemical", r"battery", r"cell", r"electrochem\w*",
    r"semiconductor", r"wafer", r"lithograph\w*", r"cleanroom", r"device", r"test", r"validation",
    r"verification", r"qa", r"quality", r"reliability", r"manufacturing", r"assembly",
    r"pcba?", r"piping", r"cad", r"layout", r"drafter", r"draftsman",
    r"integration", r"systems?", r"architect\w*", r"devops", r"sre", r"infrastructure",
    r"security", r"cyber\w*", r"network\w*", r"cloud", r"backend", r"back-end", r"frontend", r"front-end",
    r"full[- ]?stack", r"mobile", r"ios", r"android", r"web", r"technical staff", r"mts", r"cto",
    r"lab\w*", r"laborator\w*", r"biolog\w*", r"bioinformatic\w*", r"genomic\w*", r"assay", r"clinical",
    r"medical physicist", r"nuclear", r"fusion", r"plasma", r"reactor", r"cryogenic\w*", r"vacuum",
    r"qubit\w*", r"satellite", r"spacecraft", r"rocket", r"launch", r"payload", r"flight",
    r"trader", r"trading", r"phd", r"ph\.d\.?", r"postdoc\w*", r"fellow\w*", r"stem",
)

# Department / team names that mark a posting as non-technical (used only
# when the title has no strong technical term).
NONTECH_DEPARTMENT = _rx(
    r"sales", r"marketing", r"finance", r"legal", r"people", r"human resources", r"hr", r"recruiting",
    r"talent", r"g&a", r"general (?:and|&) administrative", r"administration", r"business development",
    r"customer success", r"communications", r"accounting", r"workplace", r"commercial", r"revenue",
    r"go[- ]to[- ]market", r"gtm", r"partnerships", r"brand", r"growth", r"policy",
)


def is_technical(title: str, department: str | None = None) -> bool:
    """True when the posting title looks like an engineering/science/technical role."""
    t = " ".join((title or "").split())
    if not t:
        return False
    if HARD_NONTECH.search(t):
        return False
    tech = bool(TECH.search(t))
    if not tech and department:
        if NONTECH_DEPARTMENT.search(department):
            return False
        # "2026 Internship" in an Engineering department is technical.
        tech = bool(TECH.search(department))
    if SOFT_NONTECH.search(t) and not tech:
        return False
    return tech or not SOFT_NONTECH.search(t)


# ---------------------------------------------------------------- kind / contract

_INTERN_RX = re.compile(
    r"\b(intern|interns|internship|co-?op|werkstudent\w*|working student|praktik\w*|stagiaire|"
    r"pasant[ií]a|est[aá]gi\w*|summer student|thesis|masterarbeit|bachelorarbeit|apprentice\w*)\b", re.I)


def kind_hint(*texts: str | None) -> str | None:
    """``"internship"`` if the ATS employment type / title says so, else None."""
    for t in texts:
        if t and _INTERN_RX.search(t):
            return "internship"
    return None


_CONTRACT = {
    "fulltime": "full-time", "full time": "full-time", "full-time": "full-time", "permanent": "full-time",
    "parttime": "part-time", "part time": "part-time", "part-time": "part-time",
    "contract": "contract", "contractor": "contract", "temporary": "temporary", "temp": "temporary",
    "intern": "internship", "internship": "internship", "working student": "working student",
    "werkstudent": "working student", "trainee": "internship", "freelance": "freelance",
    "cdi": "full-time", "cdd": "temporary", "stage": "internship", "alternance": "apprenticeship",
    "festanstellung": "full-time", "befristet": "temporary", "praktikum": "internship",
}


def norm_contract(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    return _CONTRACT.get(v.lower().replace("_", " "), v.lower() if len(v) < 40 else None)


def fmt_salary(lo, hi, currency: str | None = None, interval: str | None = None) -> str | None:
    if lo is None and hi is None:
        return None

    def n(x):
        try:
            x = float(x)
        except (TypeError, ValueError):
            return str(x)
        return f"{x:,.0f}"

    amount = f"{n(lo)}–{n(hi)}" if lo is not None and hi is not None and lo != hi else n(lo if lo is not None else hi)
    per = ""
    if interval:
        iv = interval.lower()
        per = next((f" per {w}" for w in ("year", "month", "week", "day", "hour") if w in iv), "")
    return f"{currency + ' ' if currency else ''}{amount}{per}".strip()


# ---------------------------------------------------------------- locations

_SPLIT_RX = re.compile(r"\s*(?:;|\|| • |·|\n|\s+or\s+|\s+/\s+|\s+and\s+)\s*", re.I)
_VAGUE_RX = re.compile(
    r"^(multiple|various|several|many|all)\s+(locations?|offices?|sites?|cities)$|^(tbd|n/?a|global|worldwide|"
    r"hybrid|on-?site|onsite|in-?office|flexible|field[- ]based|travel(ing)?)$", re.I)


def split_locations(raw: str | None) -> list[str]:
    """Split "London, UK; Berlin, Germany" / "Berkeley, CA or Fremont, CA" into parts."""
    if not raw:
        return []
    parts = [p.strip(" ,.-") for p in _SPLIT_RX.split(raw)]
    return [p for p in parts if p]


def geocode_all(strings: Iterable[str | tuple[str | None, str | None]],
                remote: bool = False) -> list[Location]:
    """Geocode up to ``MAX_LOCATIONS`` distinct places.

    Items are location strings or ``(text, country_hint)`` pairs. Places that
    cannot be mapped are dropped, but a posting that is only "Remote" keeps a
    single unmapped remote location so the frontend can show it as such.
    """
    out: list[Location] = []
    seen_remote = remote
    for item in strings:
        text, hint = item if isinstance(item, tuple) else (item, None)
        if not text and not hint:
            continue
        if text and _VAGUE_RX.match(text.strip()):
            continue
        g = geocode(text, country_hint=hint)
        if g.remote:
            seen_remote = True
        if g.lat is None:
            continue
        if remote:
            g.remote = True
        if any((g.lat, g.lon) == (x.lat, x.lon) for x in out):
            continue
        out.append(g)
        if len(out) >= MAX_LOCATIONS:
            break
    out = drop_redundant_countries(out)
    if not out and seen_remote:
        out.append(Location(remote=True))
    return out


def drop_redundant_countries(locs: list[Location]) -> list[Location]:
    """Drop a country-level point ("Germany") when a city in that country is listed too."""
    cities = {x.country_code: x for x in locs if x.precision == "city"}
    out = []
    for x in locs:
        if x.precision == "country" and x.country_code in cities:
            if x.remote:
                cities[x.country_code].remote = True
            continue
        out.append(x)
    return out


def clip(text: str | None) -> str:
    text = (text or "").strip()
    return text[:MAX_DESCRIPTION]


# ---------------------------------------------------------------- base class

class ATSSource(Source):
    """Fetch every configured board of one ATS concurrently.

    Subclasses set ``ats`` (key in companies.json) and implement
    ``fetch_board(company) -> list[Opportunity]``; the title filter is applied
    by ``keep()`` inside ``fetch_board`` so detail requests (SmartRecruiters)
    are only made for technical roles.
    """

    ats: str = ""
    min_interval = 0.2
    workers = 6

    def companies(self) -> list[dict]:
        return load_companies(self.ats)

    def fetch_board(self, company: dict) -> list[Opportunity]:
        raise NotImplementedError

    def keep(self, title: str, department: str | None = None) -> bool:
        return is_technical(title, department)

    def per_board_cap(self) -> int | None:
        # Quick test runs sample a few postings from many boards instead of
        # filling the whole limit from the first one.
        return max(3, self.limit // 10) if self.limit else None

    def _safe_board(self, company: dict) -> list[Opportunity]:
        try:
            items = merge_duplicates(self.fetch_board(company))
        except Exception as e:  # noqa: BLE001 - one broken board must not stop the rest
            self.log.warning("%s board %s failed: %s", self.ats, company.get("token"), e)
            return []
        self.log.debug("%s: %d technical postings", company.get("name"), len(items))
        cap = self.per_board_cap()
        return items[:cap] if cap else items

    def fetch(self) -> Iterator[Opportunity]:
        companies = self.companies()
        if self.limit:
            # Spread a test run across boards; ~1 board per 4 requested items.
            companies = companies[: max(2, self.limit // 4)]
        n = 0
        ex = ThreadPoolExecutor(self.workers)
        try:
            for company, items in zip(companies, ex.map(self._safe_board, companies)):
                self.log.info("%-28s %4d kept", company.get("name"), len(items))
                for opp in items:
                    yield opp
                    n += 1
                    if self.limit and n >= self.limit:
                        return
        finally:
            ex.shutdown(wait=False, cancel_futures=True)


def merge_duplicates(items: list[Opportunity]) -> list[Opportunity]:
    """Collapse same-title postings of one company (one per city) into one item."""
    out: dict[str, Opportunity] = {}
    for o in items:
        key = re.sub(r"[^a-z0-9]+", " ", o.title.lower()).strip()
        first = out.get(key)
        if first is None:
            out[key] = o
            continue
        for loc in o.locations:
            if len(first.locations) >= MAX_LOCATIONS:
                break
            if loc.lat is None or any((loc.lat, loc.lon) == (x.lat, x.lon) for x in first.locations):
                continue
            first.locations = [x for x in first.locations if x.lat is not None] + [loc]
        first.locations = drop_redundant_countries(first.locations)
        if o.posted and (first.posted is None or o.posted > first.posted):
            first.posted = o.posted
    return list(out.values())
