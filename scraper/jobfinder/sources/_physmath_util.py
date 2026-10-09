"""Small helpers shared by the physics/mathematics academic sources."""

from __future__ import annotations

import re
from datetime import date

from ..dates import parse_date
from ..geocode import gazetteer


def country_name(code: str | None) -> str | None:
    """ISO alpha-2 -> English country name (geocode() misreads 'CA'/'DE'/'IN' as US states)."""
    if not code:
        return None
    code = code.strip()
    if len(code) == 2:
        return gazetteer().countries.get(code.upper(), code)
    return code


def ymd(text: str | None) -> date | None:
    """'2026/12/31 23:59:59 ...' -> date (dateutil mis-reads Y/M/D with dayfirst)."""
    if not text:
        return None
    m = re.search(r"\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return parse_date(text)
