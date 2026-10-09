"""AcademicJobsOnline.org: postdocs, faculty and PhD positions worldwide.

Strong in physics, astronomy, mathematics and CS (many US, Canadian and Asian
institutions, plus European theory groups). See ``_academicjobs`` for the
crawling strategy (RSS + listing + cached detail pages, 5 s crawl delay).
"""

from __future__ import annotations

from ._academicjobs import AcademicJobsBoard

BASE = "https://academicjobsonline.org"


class AcademicJobsOnline(AcademicJobsBoard):
    id = "ajo"
    name = "AcademicJobsOnline"
    homepage = BASE + "/ajo/jobs"
    base = BASE
    rss_url = BASE + "/ajo?joblist-0-0-0-----rss--"
    listing_url = BASE + "/ajo?joblst-0-0--0------"
    job_path = "/ajo/jobs/"
    detail_url = BASE + "/ajo/jobs/{id}"
    public_url = BASE + "/ajo/jobs/{id}"
    # AJO hosts every discipline (law, history, ...): skip obviously non-STEM ads.
    skip_non_stem = True
