"""MathJobs.org (American Mathematical Society): mathematics and statistics jobs.

Faculty, postdoc, lecturer and some PhD positions worldwide, heavily US but
with many Canadian, Chinese, European and Australian employers. Same engine
as AcademicJobsOnline (see ``_academicjobs``).
"""

from __future__ import annotations

from ._academicjobs import AcademicJobsBoard

BASE = "https://www.mathjobs.org"


class MathJobs(AcademicJobsBoard):
    id = "mathjobs"
    name = "MathJobs.org (AMS)"
    homepage = BASE + "/jobs"
    base = BASE
    rss_url = BASE + "/jobs?joblst------rss"
    listing_url = BASE + "/jobs?joblst-0-0--0------"
    job_path = "/jobs/list/"
    detail_url = BASE + "/jobs/list/{id}"
    public_url = BASE + "/jobs/list/{id}"
    base_disciplines = ["mathematics"]
