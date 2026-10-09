"""Date parsing helpers for the messy formats job boards use."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from dateutil import parser as du

MONTHS = ("january february march april may june july august september october november december")
_MONTH_RE = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"

# "12 Nov 2026", "November 12, 2026", "2026-11-12", "12/11/2026", "12.11.2026"
DATE_PATTERNS = [
    r"\b\d{4}-\d{2}-\d{2}\b",
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH_RE}\s*,?\s+\d{{4}}\b",
    rf"\b{_MONTH_RE}\s+\d{{1,2}}(?:st|nd|rd|th)?\s*,?\s+\d{{4}}\b",
    r"\b\d{1,2}[./]\d{1,2}[./]\d{4}\b",
]
_ANY_DATE = re.compile("|".join(f"(?:{p})" for p in DATE_PATTERNS), re.I)


def parse_date(text: str | None, dayfirst: bool = True) -> date | None:
    """Parse a single date-ish string. Returns None on failure."""
    if not text:
        return None
    text = text.strip()
    m = _ANY_DATE.search(text)
    candidate = m.group(0) if m else text
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            return None
    try:
        dt = du.parse(candidate, dayfirst=dayfirst, fuzzy=True,
                      default=datetime(datetime.now().year, 1, 1))
    except (ValueError, OverflowError):
        return None
    d = dt.date()
    if not (2000 <= d.year <= 2100):
        return None
    return d


def parse_timestamp(value) -> date | None:
    """Epoch seconds/milliseconds or ISO string -> date."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        if value > 1e12:
            value /= 1000
        return datetime.fromtimestamp(value, timezone.utc).date()
    return parse_date(str(value), dayfirst=False)


_DEADLINE_CUES = re.compile(
    r"(application\s+deadline|closing\s+date|deadline(?:\s+for\s+applications?)?|apply\s+(?:by|before)|"
    r"applications?\s+(?:must\s+be\s+(?:received|submitted)\s+)?(?:by|before|until|no later than)|"
    r"closes?\s+on|review\s+of\s+applications\s+will\s+begin)",
    re.I,
)
_START_CUES = re.compile(
    r"(start(?:ing)?\s+date|starting\s+(?:on|from|in)|start\s+(?:on|in|from|by)|"
    r"(?:position|project|contract|employment)\s+(?:will\s+)?(?:start|begin)s?(?:\s+on|\s+in)?|"
    r"commenc\w+\s+(?:on|in)?|earliest\s+start|available\s+from)",
    re.I,
)
_SEASON = re.compile(
    rf"\b(spring|summer|fall|autumn|winter|{_MONTH_RE})\s*(?:of\s+)?(\d{{4}})\b", re.I)
_SEASON_MONTH = {"spring": 3, "summer": 6, "fall": 9, "autumn": 9, "winter": 1}


def _date_after_cue(text: str, cue: re.Pattern, window: int = 120) -> date | None:
    for m in cue.finditer(text):
        tail = text[m.end(): m.end() + window]
        d = _ANY_DATE.search(tail)
        if d:
            parsed = parse_date(d.group(0))
            if parsed:
                return parsed
        s = _SEASON.search(tail)
        if s:
            word, year = s.group(1).lower(), int(s.group(2))
            month = _SEASON_MONTH.get(word)
            if month is None:
                month = parse_date(f"1 {word} {year}").month if parse_date(f"1 {word} {year}") else None
            if month:
                return date(year, month, 1)
    return None


def find_deadline(text: str) -> date | None:
    return _date_after_cue(text, _DEADLINE_CUES)


def find_start(text: str) -> date | None:
    return _date_after_cue(text, _START_CUES)


def today() -> date:
    return date.today()


def is_plausible_future(d: date | None, horizon_days: int = 3 * 365) -> bool:
    return d is not None and d <= today() + timedelta(days=horizon_days)
