"""Varbi-hosted university job boards (Sweden, Denmark).

Many Nordic universities publish every vacancy (PhD students, postdocs,
research engineers, ...) on ``<org>.varbi.com``. The English listing page is
a plain HTML table (title, city, department, deadline) and each advert page
has a "quick info" table (employment type, first day of employment, city,
country, published, last application date) plus the full text.
Detail pages are fetched once and cached.
"""

from __future__ import annotations

import re

from ..dates import parse_date
from ..geocode import geocode
from ..models import Opportunity
from .base import DetailCache, Source, html_to_text, soup

# subdomain -> (organization, country)
SITES: dict[str, tuple[str, str]] = {
    "kth": ("KTH Royal Institute of Technology", "Sweden"),
    "uu": ("Uppsala University", "Sweden"),
    "lu": ("Lund University", "Sweden"),
    "su": ("Stockholm University", "Sweden"),
    "umu": ("Umeå University", "Sweden"),
    "ki": ("Karolinska Institutet", "Sweden"),
    "kau": ("Karlstad University", "Sweden"),
    "miun": ("Mid Sweden University", "Sweden"),
    "hh": ("Halmstad University", "Sweden"),
    "hkr": ("Kristianstad University", "Sweden"),
    "aau": ("Aalborg University", "Denmark"),
}

# Swedish / Danish title words -> kind hint (English titles are handled by the classifier).
_KIND_HINTS = [
    ("postdoc", re.compile(r"\bpost-?dokt\w*|\bforskarassistent\b", re.I)),
    ("phd", re.compile(r"\bdoktorand\w*|\bph\.?d\.?[- ]?(stipend|studerende)\w*|\bdoktorandtjänst\w*|"
                       r"\bph\.?d\.?[- ]?stilling\w*|\bph\.?d\.?[- ]?fellowship", re.I)),
    ("internship", re.compile(r"\bexamensarbete\b|\bpraktik\w*|\bamanuens\w*|\bstudentmedarbet\w*", re.I)),
]


def parse_varbi_date(text: str | None):
    """Varbi writes dates as "16.Oct.2026" or ISO "2026-10-16"."""
    if not text:
        return None
    return parse_date(text.replace(".", " ").strip())


class Varbi(Source):
    id = "varbi"
    name = "Varbi university boards (SE/DK)"
    homepage = "https://kth.varbi.com/en/"
    min_interval = 0.7
    sites = SITES

    # ------------------------------------------------------------ listing

    @staticmethod
    def parse_listing(html: str, sub: str) -> list[dict]:
        s = soup(html)
        out = []
        for tr in s.select("table tr"):
            a = tr.select_one("a[href*='what:job/jobID:']")
            tds = tr.find_all("td")
            if not a or len(tds) < 2:
                continue
            m = re.search(r"jobID:(\d+)", a["href"])
            if not m:
                continue
            cells = [td.get_text(" ", strip=True) for td in tds]
            deadline = next((c for c in reversed(cells) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", c)), None)
            out.append({
                "id": f"{sub}:{m.group(1)}",
                "job_id": m.group(1),
                "sub": sub,
                "title": a.get_text(" ", strip=True),
                "city": cells[1] if len(cells) > 1 else None,
                "department": cells[2] if len(cells) > 2 else None,
                "deadline": deadline,
            })
        return out

    def crawl_listing(self) -> list[dict]:
        rows: list[dict] = []
        for sub in self.sites:
            try:
                r = self.http.get(f"https://{sub}.varbi.com/en/")
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001 - one board failing must not stop the rest
                self.log.warning("%s listing failed: %s", sub, e)
                continue
            seen = {x["id"] for x in rows}
            new = [x for x in self.parse_listing(r.text, sub) if x["id"] not in seen]
            rows.extend(new)
            self.log.info("%s: %d vacancies", sub, len(new))
            if self.limit and len(rows) >= self.limit:
                return rows[: self.limit]
        return rows

    # ------------------------------------------------------------ detail

    @staticmethod
    def parse_detail(html: str) -> dict:
        s = soup(html)
        info: dict[str, str] = {}
        for tr in s.select("table.quick-info tr, tr[class^='quick-info']"):
            th, td = tr.find("th"), tr.find("td")
            if th and td:
                info.setdefault(th.get_text(" ", strip=True), " ".join(td.get_text(" ", strip=True).split()))
        h1 = s.select_one("h1")
        org = s.select_one("h2.org-desc")
        desc = s.select_one(".job-desc")
        return {
            "title": h1.get_text(" ", strip=True) if h1 else None,
            "department": org.get_text(" ", strip=True) if org else None,
            "info": info,
            "description": html_to_text(str(desc))[:8000] if desc else "",
        }

    def fetch_detail(self, sub: str, job_id: str) -> dict | None:
        r = self.http.get(f"https://{sub}.varbi.com/en/what:job/jobID:{job_id}/")
        if r.status_code != 200:
            return None
        return self.parse_detail(r.text)

    # ------------------------------------------------------------ main

    def fetch(self):
        rows = self.crawl_listing()
        cache = DetailCache(self.id)
        todo = [c for c in rows if cache.get(c["id"]) is None]
        self.log.info("%d vacancies, %d new detail pages", len(rows), len(todo))
        for i, c in enumerate(todo):
            try:
                d = self.fetch_detail(c["sub"], c["job_id"])
            except Exception as e:  # noqa: BLE001
                self.log.warning("detail %s failed: %s", c["id"], e)
                continue
            if d:
                cache.set(c["id"], d)
            if i and i % 50 == 0:
                cache.save()
        cache.save()
        for c in rows:
            yield self.to_opportunity(c, cache.get(c["id"]) or {})

    def to_opportunity(self, c: dict, d: dict) -> Opportunity:
        info = d.get("info") or {}
        org, country = self.sites.get(c["sub"], (None, None))
        title = d.get("title") or c["title"]
        kind = next((k for k, rx in _KIND_HINTS if rx.search(title)), "job")

        city = info.get("City") or c.get("city")
        loc = geocode(city, country_hint=info.get("Country") or country) if city else \
            geocode(None, country_hint=info.get("Country") or country)

        first_day = info.get("First day of employment")
        start = parse_varbi_date(first_day) if first_day and re.search(r"\d{4}", first_day) else None
        start_text = None if start else (first_day or None)

        department = d.get("department") or c.get("department")
        description = d.get("description") or ""
        if department:
            description = f"{department}\n{description}"
        contract = ", ".join(x for x in (info.get("Type of employment"), info.get("Contract type")) if x) or None
        return Opportunity(
            source=self.id,
            source_id=c["id"],
            url=f"https://{c['sub']}.varbi.com/en/what:job/jobID:{c['job_id']}/",
            title=title,
            organization=org or (department.split(",")[0] if department else None),
            kind=kind,
            description=description,
            locations=[loc] if loc.lat is not None else [],
            posted=parse_varbi_date(info.get("Published")),
            deadline=parse_varbi_date(info.get("Last application date")) or parse_date(c.get("deadline")),
            start_date=start,
            start_text=start_text,
            salary=info.get("Salary"),
            contract=contract,
            tags=[x for x in (department,) if x],
        )
