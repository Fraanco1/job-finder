"""Offline geocoder backed by the GeoNames ``cities15000`` gazetteer.

Data files are downloaded once into ``data/geonames/`` (git-ignored) and
reused. Geocoding is pure dictionary lookups, so there are no rate limits
and results are reproducible.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import requests

from .models import Location

log = logging.getLogger(__name__)

GEONAMES = "https://download.geonames.org/export/dump/"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "geonames"

COUNTRY_ALIASES = {
    "usa": "US", "u.s.": "US", "u.s.a.": "US", "us": "US", "united states of america": "US",
    "america": "US", "uk": "GB", "u.k.": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "great britain": "GB", "britain": "GB",
    "the netherlands": "NL", "holland": "NL", "czechia": "CZ", "czech republic": "CZ",
    "south korea": "KR", "korea": "KR", "republic of korea": "KR", "russia": "RU",
    "taiwan": "TW", "vietnam": "VN", "türkiye": "TR", "turkiye": "TR", "turkey": "TR",
    "uae": "AE", "iran": "IR", "deutschland": "DE", "schweiz": "CH", "suisse": "CH",
    "españa": "ES", "brasil": "BR", "méxico": "MX", "macedonia": "MK", "moldova": "MD",
    "slovak republic": "SK", "hong kong sar": "HK", "the bahamas": "BS", "ivory coast": "CI",
    "côte d'ivoire": "CI", "palestine": "PS", "laos": "LA", "syria": "SY", "tanzania": "TZ",
    "bolivia": "BO", "venezuela": "VE", "brunei": "BN", "cape verde": "CV",
}

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
}
CA_PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "QC", "SK", "NT", "NU", "YT"}

REMOTE_RX = re.compile(r"\b(remote|anywhere|work from home|wfh|distributed|virtual)\b", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class City:
    name: str
    cc: str
    admin1: str
    pop: int
    lat: float
    lon: float


def _download(name: str) -> bytes:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / name
    if not path.exists():
        log.info("downloading GeoNames %s", name)
        r = requests.get(GEONAMES + name, timeout=120)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path.read_bytes()


class Gazetteer:
    def __init__(self):
        self.cities: dict[str, list[City]] = {}
        self.countries: dict[str, str] = {}       # code -> name
        self.country_by_name: dict[str, str] = {}  # normalized name -> code
        self.capital: dict[str, str] = {}
        self.admin1: dict[tuple[str, str], str] = {}   # (cc, code) -> name
        self.admin1_by_name: dict[str, tuple[str, str]] = {}
        self._load()

    def _load(self):
        info = _download("countryInfo.txt").decode("utf-8")
        for line in info.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            cols = line.split("\t")
            cc, name, capital = cols[0], cols[4], cols[5]
            self.countries[cc] = name
            self.country_by_name[norm(name)] = cc
            self.capital[cc] = capital
        for alias, cc in COUNTRY_ALIASES.items():
            self.country_by_name[norm(alias)] = cc

        adm = _download("admin1CodesASCII.txt").decode("utf-8")
        for line in adm.splitlines():
            cols = line.split("\t")
            if len(cols) < 3:
                continue
            cc, code = cols[0].split(".")
            self.admin1[(cc, code)] = cols[1]
            self.admin1_by_name.setdefault(norm(cols[2] or cols[1]), (cc, code))

        raw = _download("cities15000.zip")
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            text = z.read("cities15000.txt").decode("utf-8")
        for line in text.splitlines():
            c = line.split("\t")
            city = City(c[1], c[8], c[10], int(c[14] or 0), float(c[4]), float(c[5]))
            names = {norm(c[1]), norm(c[2])}
            # alternate names: keep short-ish ones (skip airport codes / long transliterations)
            for alt in c[3].split(","):
                if 3 <= len(alt) <= 40:
                    names.add(norm(alt))
            for n in names:
                if n:
                    self.cities.setdefault(n, []).append(city)
        for lst in self.cities.values():
            lst.sort(key=lambda x: -x.pop)

    # -------------------------------------------------------------- lookups

    def country_code(self, token: str) -> str | None:
        t = token.strip()
        if len(t) == 2 and t.isupper() and t in self.countries and t not in US_STATES:
            return t
        return self.country_by_name.get(norm(t))

    def find_city(self, name: str, cc: str | None = None, admin1: str | None = None) -> City | None:
        cands = self.cities.get(norm(name))
        if not cands:
            return None
        if cc:
            cands = [c for c in cands if c.cc == cc]
        if admin1:
            pref = [c for c in cands if c.admin1 == admin1]
            cands = pref or cands
        return cands[0] if cands else None

    def country_point(self, cc: str) -> City | None:
        cap = self.capital.get(cc)
        return self.find_city(cap, cc) if cap else None


@lru_cache(maxsize=1)
def gazetteer() -> Gazetteer:
    return Gazetteer()


@lru_cache(maxsize=20000)
def _geocode_cached(text: str, country_hint: str | None) -> tuple:
    loc = _geocode(text, country_hint)
    return (loc.city, loc.region, loc.country, loc.country_code, loc.lat, loc.lon,
            loc.remote, loc.precision)


def geocode(text: str | None, country_hint: str | None = None, city_hint: str | None = None) -> Location:
    """Geocode a free-form location string ("Boulder, CO", "Delft, Netherlands", "Remote - US")."""
    if city_hint:
        text = f"{city_hint}, {text or ''}"
    if not text and not country_hint:
        return Location()
    return Location(*_geocode_cached(text or "", country_hint))


def _geocode(text: str, country_hint: str | None) -> Location:
    g = gazetteer()
    remote = bool(REMOTE_RX.search(text))
    cleaned = REMOTE_RX.sub(" ", text)
    tokens = [t.strip(" .()") for t in re.split(r"[,/|–—]|\s-\s|\(|\)", cleaned) if t.strip(" .()")]

    cc = g.country_code(country_hint) if country_hint else None
    admin1 = None
    # Two-letter upper-case tokens are ambiguous ("DE": Delaware or Germany,
    # "CA": California or Canada). Keep every reading and let the city decide.
    readings: list[tuple[str, str | None]] = []
    city_tokens = []
    for t in tokens:
        raw = t.strip()
        if len(raw) == 2 and raw.isupper():
            if raw in US_STATES:
                readings.append(("US", raw))
            if raw in CA_PROVINCES:
                readings.append(("CA", None))
            if raw in g.countries:
                readings.append((raw, None))
            if readings:
                continue
        code = g.country_code(t)
        if code:
            cc = cc or code
            continue
        adm = g.admin1_by_name.get(norm(t))
        if adm and (cc is None or adm[0] == cc) and not g.cities.get(norm(t)):
            cc, admin1 = adm
            continue
        city_tokens.append(t)

    if cc:
        readings = [r for r in readings if r[0] == cc] or [(cc, admin1)]
    elif not readings:
        readings = [(None, None)]

    for t in city_tokens:
        # strip postal codes / street numbers
        name = re.sub(r"\b\d[\d\s-]*\b", " ", t).strip()
        if not name:
            continue
        for rcc, radm in readings:
            c = g.find_city(name, rcc, radm)
            if c and (radm is None or c.admin1 == radm or rcc != "US"):
                region = g.admin1.get((c.cc, c.admin1))
                return Location(c.name, region, g.countries.get(c.cc), c.cc, c.lat, c.lon,
                                remote, "city")
    if not cc and readings and readings[0][0]:
        cc = readings[-1][0] if len(readings) > 1 and readings[0][0] == "US" and not city_tokens else readings[0][0]
    if cc:
        cap = g.country_point(cc)
        if cap:
            return Location(None, None, g.countries.get(cc), cc, cap.lat, cap.lon, remote, "country")
        return Location(None, None, g.countries.get(cc), cc, None, None, remote, None)
    return Location(remote=remote)
