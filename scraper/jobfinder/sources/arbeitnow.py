"""Arbeitnow job board API: STEM internships and working-student jobs (mostly Germany).

https://www.arbeitnow.com/api/job-board-api is a free public JSON API
(paginated with ``?page=``; descriptions included, so no detail requests).
Regular industry jobs are covered by the ATS sources, so this source keeps
only internships, working-student ("Werkstudent"), thesis, trainee and
graduate-programme postings whose title or tags look technical.
"""

from __future__ import annotations

import re

from ..dates import parse_timestamp
from ..geocode import geocode
from ..models import Opportunity
from ._de_fields import german_fields
from .base import Source, html_to_text

API = "https://www.arbeitnow.com/api/job-board-api"

STUDENT = re.compile(
    r"\b(intern|interns|internship|praktik\w*|pflichtpraktik\w*|werkstudent\w*|working student|"
    r"studentische\w*|student\w*|thesis|abschlussarbeit|masterarbeit|bachelorarbeit|trainee\w*|"
    r"graduate program\w*|graduate programme|absolvent\w*|duales studium|dual\w* student|"
    r"stage|stagiaire|alternance|apprenti\w*|ausbildung)\b", re.I)
STUDENT_TYPES = {"intern", "internship", "student", "working student", "trainee", "graduate",
                 "apprenticeship", "werkstudent", "praktikum"}
TECH = re.compile(
    r"\b(engineer\w*|engineering|ingenieur\w*|software|developer|entwickl\w*|data|ai|ki|"
    r"machine learning|ml|deep learning|informatik\w*|computer|it|elektro\w*|electrical|electronic\w*|"
    r"mechani\w*|maschinenbau|mechatroni\w*|physi\w*|chemi\w*|chemistry|bio\w*|robot\w*|embedded|"
    r"hardware|firmware|fpga|cloud|devops|security|cyber\w*|r&d|research|forschung\w*|labor\w*|lab|"
    r"simulation|cad|automati\w*|energ\w*|quantum|math\w*|statisti\w*|analytics|network\w*|backend|"
    r"frontend|full-?stack|python|java|c\+\+|rust|qa|test\w*|verification|semiconductor|battery|"
    r"batterie\w*|aerospace|luft- und raumfahrt|space|propulsion|materials?|werkstoff\w*|"
    r"verfahrenstechnik|process engineering|photonic\w*|optic\w*|laser|sensor\w*|computer vision|"
    r"systems?|infrastructure|platform|sre|linux|technik|techni\w*)\b", re.I)
NON_STEM = re.compile(
    r"\b(marketing|sales|vertrieb|finance|finanz\w*|accounting|buchhaltung|controlling|hr|"
    r"human resources|people|recruit\w*|talent|personal\w*|legal|recht\w*|office|assistenz|"
    r"content|social media|communications?|kommunikation|pr|events?|customer|kundenservice|"
    r"einkauf|procurement|purchasing|graphic|grafik|kreation|copywrit\w*|brand|fundrais\w*|"
    r"account manag\w*|business development|tax|steuer\w*|audit|go-to-market|seo|"
    r"designer|ux|ui|product design)\b", re.I)


def is_student_tech(job: dict) -> bool:
    title = job.get("title") or ""
    types = {t.lower() for t in job.get("job_types") or []}
    student = bool(STUDENT.search(title)) or bool(types & STUDENT_TYPES)
    if not student:
        return False
    if NON_STEM.search(title):
        return False
    text = " ".join([title] + list(job.get("tags") or []))
    return bool(TECH.search(text))


class Arbeitnow(Source):
    id = "arbeitnow"
    name = "Arbeitnow (STEM internships & working students)"
    homepage = "https://www.arbeitnow.com/"
    min_interval = 2.0  # the API answers 429 at 1 request/s
    max_pages = 80

    def fetch(self):
        seen: set[str] = set()
        kept = 0
        for page in range(1, self.max_pages + 1):
            data = self.http.get_json(API, params={"page": page})
            jobs = data.get("data") or []
            if not jobs:
                break
            for job in jobs:
                slug = job.get("slug")
                if not slug or slug in seen:
                    continue
                seen.add(slug)
                if not is_student_tech(job):
                    continue
                kept += 1
                yield self.to_opportunity(job)
                if self.limit and kept >= self.limit:
                    return
            if not (data.get("links") or {}).get("next"):
                break
        self.log.info("%d postings scanned, %d student/tech kept", len(seen), kept)

    def to_opportunity(self, job: dict) -> Opportunity:
        loc_txt = (job.get("location") or "").strip()
        loc = geocode(loc_txt, country_hint="Germany") if loc_txt else geocode(None, country_hint="Germany")
        if loc.precision != "city" and loc_txt:
            alt = geocode(loc_txt)
            if alt.lat is not None:
                loc = alt
        loc.remote = bool(job.get("remote")) or loc.remote
        types = job.get("job_types") or []
        return Opportunity(
            source=self.id,
            source_id=job["slug"],
            url=job.get("url") or f"https://www.arbeitnow.com/view/{job['slug']}",
            title=job.get("title") or "",
            organization=job.get("company_name"),
            kind="internship",
            description=html_to_text(job.get("description"))[:8000],
            locations=[loc] if loc.lat is not None else [],
            posted=parse_timestamp(job.get("created_at")),
            contract=", ".join(types) or None,
            source_fields=list(job.get("tags") or []) + german_fields(job.get("title"), " ".join(job.get("tags") or [])),
            tags=[t for t in types if t] + (["Remote"] if job.get("remote") else []),
        )
