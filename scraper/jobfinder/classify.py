"""Rule-based classification of opportunities.

Everything here is deterministic keyword/regex matching. No LLM calls, so a
full refresh costs nothing but bandwidth.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .models import Opportunity
from .taxonomy import DISCIPLINES, EURAXESS_FIELD_MAP


def _kw_pattern(keywords) -> re.Pattern:
    parts = []
    for kw in keywords:
        kw = kw.lower()
        if kw.endswith("*"):
            parts.append(re.escape(kw[:-1]) + r"[\w-]*")
        else:
            parts.append(re.escape(kw).replace(r"\?", "?"))
    return re.compile(r"(?<![\w-])(?:" + "|".join(parts) + r")(?![\w-])", re.I)


@lru_cache(maxsize=None)
def _patterns():
    disc = {}
    for d in DISCIPLINES:
        disc[d.id] = (
            _kw_pattern(d.keywords + tuple(s.label for s in d.subfields)),
            _kw_pattern(d.degree_terms),
            {s.id: _kw_pattern(s.keywords) for s in d.subfields},
        )
    return disc


# ---------------------------------------------------------------- kind

_KIND_RULES = [
    ("internship", re.compile(
        r"\b(intern|interns|internship|internships|werkstudent\w*|working student|co-?op|"
        r"summer student|praktikum|stage\s+de\s+fin|trainee(ship)?|apprentice\w*|"
        r"student assistant|student researcher|student worker|thesis student|"
        r"bachelor'?s? thesis|undergraduate research)\b", re.I)),
    ("phd", re.compile(
        r"\b(ph\.?\s?d\.?\s+(student|position|candidate|studentship|scholarship|fellowship|"
        r"opportunit\w+|project|researcher|program\w*|vacanc\w+|offer)|"
        r"phd|doctoral (student|candidate|researcher|position|fellow\w*|program\w*|scholarship\w*|"
        r"school|training)|doctorant\w*|doktorand\w*|promovend\w*|studentship|"
        r"early[- ]stage researcher|esr\d*|dc\d+|doctoral network|"
        r"fully[- ]funded ph\.?d)\b", re.I)),
    ("postdoc", re.compile(
        # Bare "research associate" is left out: in industry (biotech) it is a technician role.
        r"\b(post-?doc\w*|post-?doctoral|postdoctorate|"
        r"research fellow|experienced researcher|marie curie fellow\w*|"
        r"msca postdoctoral)\b", re.I)),
    ("masters", re.compile(
        r"\b(master'?s? (programme|program|scholarship|position|student|thesis|project|degree programme)|"
        r"m\.?sc\.? (programme|program|scholarship|thesis|project)|master thesis|masterarbeit|"
        r"erasmus mundus)\b", re.I)),
]

# Explicit PhD-position phrases; the only PhD evidence trusted outside the title, because
# company boilerplate ("60+ PhDs on our team") would otherwise turn jobs into PhD positions.
_PHD_EXPLICIT = re.compile(
    r"\b(ph\.?\s?d\.?\s+(student|position|candidate|studentship|scholarship|fellowship|project|"
    r"researcher|vacanc\w+)|doctoral (student|candidate|researcher|position)|studentship|"
    r"doktorand\w*|doctorant\w*|promovend\w*)\b", re.I)

# Industry titles that mention a PhD as a requirement ("ML Engineer (PhD, New Grad)").
_INDUSTRY_PHD_TITLE = re.compile(
    r"\b(engineer|scientist|developer|trader|analyst|new grad\w*|graduate|quantitative researcher|"
    r"research scientist|20\d\d start)\b", re.I)


def infer_kind(title: str, description: str = "", hint: str | None = None) -> str:
    """Infer the opportunity kind. ``hint`` is a kind reported by the source."""
    t = title or ""
    for kind, rx in _KIND_RULES:
        if rx.search(t):
            # "Postdoc ... PhD in physics required" -> title "postdoc" wins over "phd";
            # order matters only within the title.
            if kind == "phd" and _KIND_RULES[2][1].search(t):
                return "postdoc"
            if kind == "phd" and _INDUSTRY_PHD_TITLE.search(t) and not _PHD_EXPLICIT.search(t):
                return "job"
            return kind
    if hint:
        return hint
    head = (description or "")[:600]
    for kind, rx in _KIND_RULES:
        if kind == "phd":
            rx = _PHD_EXPLICIT
        if rx.search(head):
            return kind
    return "job"


# ---------------------------------------------------------------- disciplines

@lru_cache(maxsize=None)
def _field_matcher():
    """One alternation over every discipline/subfield keyword, longest first.

    Scanning a posting once with this, then expanding each matched phrase into all the
    keywords it contains (cached), gives the same scores as running every keyword
    pattern separately, at a fraction of the cost.
    """
    singles: list[tuple[re.Pattern, tuple[str, str]]] = []
    alts: list[str] = []
    for d in DISCIPLINES:
        for kw in d.keywords + tuple(sf.label for sf in d.subfields):
            singles.append((_kw_pattern([kw]), ("d", d.id)))
            alts.append(kw)
        for sf in d.subfields:
            for kw in sf.keywords:
                singles.append((_kw_pattern([kw]), ("s", sf.id)))
                alts.append(kw)
    uniq = sorted(set(k.lower() for k in alts), key=len, reverse=True)
    combined = _kw_pattern(uniq)
    return combined, singles


@lru_cache(maxsize=50000)
def _targets(phrase: str) -> tuple[tuple[tuple[str, str], int], ...]:
    _combined, singles = _field_matcher()
    out: dict[tuple[str, str], int] = {}
    for rx, target in singles:
        n = len(rx.findall(phrase))
        if n:
            out[target] = out.get(target, 0) + n
    return tuple(out.items())


def _accumulate(text: str, weight: int, disc: dict[str, int], sub: dict[str, int]) -> None:
    combined, _singles = _field_matcher()
    for m in combined.finditer(text):
        for (kind, tid), n in _targets(m.group(0).lower()):
            bucket = disc if kind == "d" else sub
            bucket[tid] = bucket.get(tid, 0) + weight * n


def classify_fields(title: str, body: str, source_fields: list[str] | None = None):
    """Return (disciplines, subfields) sorted by relevance."""
    disc_scores: dict[str, int] = {}
    sub_scores: dict[str, int] = {}

    for raw in source_fields or []:
        for part in re.split(r"»|>", raw):
            key = part.strip().lower()
            if key in EURAXESS_FIELD_MAP:
                d, s = EURAXESS_FIELD_MAP[key]
                if d is None:
                    continue
                disc_scores[d] = disc_scores.get(d, 0) + 6
                if s:
                    sub_scores[s] = sub_scores.get(s, 0) + 6

    _accumulate(title, 3, disc_scores, sub_scores)
    body_d: dict[str, int] = {}
    body_s: dict[str, int] = {}
    _accumulate(body[:6000], 1, body_d, body_s)

    sub_parent = {s.id: d.id for d in DISCIPLINES for s in d.subfields}
    # "Head" evidence = the title and the source's own field labels. Postings open with
    # employer boilerplate ("we build quantum computers"), so when the head says what the
    # role is, a discipline found only in the body needs much stronger support.
    head_disc = set(disc_scores) | {sub_parent[s] for s in sub_scores}
    strict = bool(head_disc)
    body_only_min = 6 if strict else 3
    sub_body_min = 4 if strict else 2

    total_d = {d: disc_scores.get(d, 0) + body_d.get(d, 0) for d in set(disc_scores) | set(body_d)}
    disciplines = [
        d for d, sc in sorted(total_d.items(), key=lambda x: -x[1])
        if (d in head_disc and sc >= 3) or body_d.get(d, 0) >= body_only_min
    ]
    subfields = []
    for sid in sorted(set(sub_scores) | set(body_s),
                      key=lambda x: -(sub_scores.get(x, 0) + body_s.get(x, 0))):
        parent = sub_parent[sid]
        head, bod = sub_scores.get(sid, 0), body_s.get(sid, 0)
        if head >= 3 or bod >= sub_body_min or (head and head + bod >= 2):
            subfields.append(sid)
            if parent not in disciplines and (head >= 3 or (not strict and bod >= 4)):
                disciplines.append(parent)
    subfields = [s for s in subfields if sub_parent[s] in disciplines]
    return disciplines[:4], subfields[:6]


# ---------------------------------------------------------------- requirements

_DEGREE_CUE = re.compile(
    r"(degree|diploma|bachelor\W?s?|master\W?s?|m\.?sc\.?|b\.?sc\.?|b\.?s\.?|m\.?s\.?|"
    r"ph\.?\s?d\.?|doctorate|background|qualification|graduate[ds]?|education|studies|"
    r"major(?:ing)?|trained|training)\s+(?:\(?or equivalent\)?\s+)?(?:in|of|on)\b",
    re.I,
)
_DEGREE_WINDOW = 160
_PEOPLE = {
    "physics": re.compile(r"\bphysicists?\b", re.I),
    "chemistry": re.compile(r"\bchemists?\b", re.I),
    "mathematics": re.compile(r"\bmathematicians?\b|\bstatisticians?\b", re.I),
    "computer-science": re.compile(r"\bcomputer scientists?\b", re.I),
    "electrical-engineering": re.compile(r"\belectrical engineers?\b|\belectronics? engineers?\b", re.I),
    "mechanical-engineering": re.compile(r"\bmechanical engineers?\b", re.I),
    "aerospace-engineering": re.compile(r"\baerospace engineers?\b", re.I),
    "chemical-engineering": re.compile(r"\bchemical engineers?\b", re.I),
    "materials-science": re.compile(r"\bmaterials? scientists?\b", re.I),
    "civil-engineering": re.compile(r"\bcivil engineers?\b", re.I),
    "earth-sciences": re.compile(r"\bgeologists?\b|\bgeoscientists?\b|\bgeophysicists?\b", re.I),
    "life-sciences": re.compile(r"\bbiologists?\b", re.I),
}
# "physicist" as a job title ("Physicist - Laser Systems") is a requirement too.


def required_degrees(title: str, body: str, explicit: list[str] | None = None) -> list[str]:
    """Disciplines whose degree the posting explicitly asks for."""
    found: list[str] = list(explicit or [])
    windows = [body[m.end(): m.end() + _DEGREE_WINDOW] for m in _DEGREE_CUE.finditer(body)]
    text_windows = " | ".join(windows)
    for did, (_drx, deg_rx, _subs) in _patterns().items():
        if did in found:
            continue
        if deg_rx.search(text_windows):
            found.append(did)
            continue
        people = _PEOPLE.get(did)
        if people and (people.search(title) or people.search(body)):
            found.append(did)
    return found


_EDU_RULES = [
    ("phd", re.compile(r"\b(ph\.?\s?d\.?|doctorate|doctoral degree)\b[^.]{0,40}\b(required|in|degree)\b"
                       r"|\b(hold|have|completed|obtained)\b[^.]{0,30}\b(ph\.?\s?d|doctorate)", re.I)),
    ("masters", re.compile(r"\b(master'?s?|m\.?sc\.?|m\.?s\.?|diploma|msc|ma)\s*(degree|in|or equivalent)\b", re.I)),
    ("bachelor", re.compile(r"\b(bachelor'?s?|b\.?sc\.?|b\.?s\.?|bsc|undergraduate)\s*(degree|in|or equivalent)\b", re.I)),
]


def education_level(kind: str, body: str) -> str | None:
    if kind == "postdoc":
        return "phd"
    hits = [lvl for lvl, rx in _EDU_RULES if rx.search(body)]
    if kind == "phd":
        return "masters" if "masters" in hits else (hits[-1] if hits else "masters")
    return hits[0] if hits else None


# ---------------------------------------------------------------- entry point

def enrich(opp: Opportunity, kind_hint: str | None = None) -> Opportunity:
    """Fill kind, disciplines, subfields, requirements and education level in place."""
    body = opp.description or ""
    source_hint = kind_hint or (opp.kind if opp.kind and opp.kind != "job" else None)
    opp.kind = infer_kind(opp.title, body, source_hint)
    disc, subs = classify_fields(opp.title, body, opp.source_fields)
    opp.disciplines = _merge(opp.disciplines, disc)
    opp.subfields = _merge(opp.subfields, subs)
    opp.required_degrees = required_degrees(opp.title, body, opp.required_degrees)
    if not opp.education_level:
        opp.education_level = education_level(opp.kind, body)
    return opp


def _merge(a: list[str], b: list[str]) -> list[str]:
    out = list(a)
    for x in b:
        if x not in out:
            out.append(x)
    return out
