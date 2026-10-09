"""Run sources, normalize, filter, de-duplicate and write the frontend data file."""

from __future__ import annotations

import json
import logging
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

from .classify import enrich
from .dates import find_deadline, find_start
from .models import KIND_LABELS, Opportunity
from .sources import all_sources
from .taxonomy import public_taxonomy

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "web" / "public" / "data" / "opportunities.json"
SNAPSHOT_DIR = ROOT / "data" / "snapshots"
SEED_DIR = ROOT / "data" / "seed"
# A run returning less than this share of the previous count is treated as blocked/broken.
SHRINK_GUARD = 0.5


# Roles that are never STEM, whatever the employer. Checked on the title only.
NON_STEM_TITLE = re.compile(
    r"\b(graphic design\w*|marketing|sales|accountant|accounting|bookkeep\w*|recruit(?:er|ing|ment)|"
    r"talent acquisition|human resources|hr (?:manager|business partner|generalist|specialist|officer)|"
    r"people (?:partner|operations)|legal counsel|lawyer|attorney|paralegal|office manager|"
    r"(?:executive|administrative|personal) assistant|receptionist|secretary|"
    r"communications? (?:officer|manager|specialist|intern|coordinator)|public relations|press officer|"
    r"events? (?:manager|coordinator)|social media|copywriter|content writer|"
    r"finance (?:manager|analyst|director)|financial (?:analyst|controller)|treasury|"
    r"procurement|purchasing|payroll|customer success|customer support|business development|"
    r"account (?:executive|manager)|fundrais\w*|translator|interpreter|chef|cleaner|janitor)\b",
    re.I,
)


def normalize(opp: Opportunity) -> Opportunity | None:
    """Fill gaps from the description and drop what we cannot use."""
    if not opp.title or not opp.url:
        return None
    if NON_STEM_TITLE.search(opp.title):
        return None
    text = opp.description or ""
    if opp.deadline is None:
        opp.deadline = find_deadline(text)
    if opp.start_date is None and not opp.start_text:
        opp.start_date = find_start(text)
    today = date.today()
    # A start date already in the past means "as soon as possible".
    if opp.start_date and opp.start_date < today:
        opp.start_date = None
        opp.start_text = opp.start_text or "As soon as possible"
    # Deadlines earlier than the posting date are parsing noise.
    if opp.deadline and opp.posted and opp.deadline < opp.posted:
        opp.deadline = None
    enrich(opp)
    if not opp.disciplines:
        return None  # not STEM
    if opp.deadline and opp.deadline < today:
        return None  # expired
    return opp


def _dedupe_key(o: Opportunity) -> str:
    t = re.sub(r"[^a-z0-9]+", " ", o.title.lower()).strip()
    org = re.sub(r"[^a-z0-9]+", " ", (o.organization or "").lower()).strip()
    return f"{t}|{org}"


def run_source(cls, limit: int | None) -> tuple[list[Opportunity], dict]:
    started = time.time()
    status = {"id": cls.id, "name": cls.name, "homepage": cls.homepage}
    try:
        src = cls(limit=limit)
        raw = list(src.fetch())
        items = [o for o in (normalize(x) for x in raw) if o]
        status.update(ok=True, fetched=len(raw), kept=len(items))
        log.info("%s: %d fetched, %d kept (%.0fs)", cls.id, len(raw), len(items), time.time() - started)
        return items, status
    except Exception as e:  # noqa: BLE001
        log.error("%s failed: %s\n%s", cls.id, e, traceback.format_exc())
        status.update(ok=False, error=f"{type(e).__name__}: {e}"[:300])
        return [], status


def _read_json_list(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _open_items(items: list[dict]) -> list[dict]:
    today = date.today().isoformat()
    return [x for x in items if not x.get("deadline") or x["deadline"] >= today]


def _load_snapshot(source_id: str) -> list[dict]:
    """Last good result for a source: the local snapshot, or the committed seed if that
    has more open postings (sites that block cloud IPs are seeded from a home machine)."""
    snap = _open_items(_read_json_list(SNAPSHOT_DIR / f"{source_id}.json"))
    seed = _open_items(_read_json_list(SEED_DIR / f"{source_id}.json"))
    return seed if len(seed) > len(snap) else snap


def save_seeds(source_ids: list[str]) -> dict[str, int]:
    """Copy the current snapshots of ``source_ids`` into data/seed/ (committed to git)."""
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    written = {}
    for sid in source_ids:
        items = _open_items(_read_json_list(SNAPSHOT_DIR / f"{sid}.json"))
        if items:
            (SEED_DIR / f"{sid}.json").write_text(json.dumps(items, ensure_ascii=False, separators=(",", ":")))
            written[sid] = len(items)
    return written


def _save_snapshot(source_id: str, items: list[dict]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    (SNAPSHOT_DIR / f"{source_id}.json").write_text(json.dumps(items, ensure_ascii=False))


def run(only: list[str] | None = None, limit: int | None = None, workers: int = 6,
        output: Path = OUTPUT, scrape: bool = True) -> dict:
    """Scrape the selected sources (all by default) and write the data file.

    With ``scrape=False`` nothing is fetched: the data file is rebuilt from the saved
    per-source snapshots (useful after editing snapshots or the output format).
    """
    sources = all_sources()
    selected = {k: v for k, v in sources.items() if scrape and (not only or k in only)}
    if only and (missing := set(only) - set(selected)):
        raise SystemExit(f"unknown source(s): {', '.join(sorted(missing))}. "
                         f"Available: {', '.join(sources)}")

    per_source: dict[str, list[dict]] = {}
    statuses: dict[str, dict] = {}
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(run_source, cls, limit): sid for sid, cls in selected.items()}
        for fut in as_completed(futs):
            sid = futs[fut]
            items, status = fut.result()
            public = [o.to_public() for o in items]
            # An empty result almost always means the site changed or blocked us, not that every
            # posting vanished overnight, so it never overwrites the previous snapshot.
            previous = _load_snapshot(sid)
            # A sudden collapse (or an empty result) almost always means the site changed or
            # blocked us, not that the postings vanished overnight, so it never overwrites the
            # previous snapshot. Quick --limit runs are exempt.
            shrunk = (limit is None and len(previous) >= 20
                      and len(public) < SHRINK_GUARD * len(previous))
            if status["ok"] and public and not shrunk:
                if limit is None:
                    _save_snapshot(sid, public)
                per_source[sid] = public
            else:
                per_source[sid] = previous
                status["stale"] = bool(previous)
                if status["ok"]:
                    status["ok"] = False
                    status.setdefault("error", f"only {len(public)} items (previously {len(previous)})"
                                      if public else "no items returned")
            statuses[sid] = status

    # Sources not run this time (``--only``) keep their previous snapshot.
    for sid in sources:
        if sid not in per_source:
            snap = _load_snapshot(sid)
            if snap:
                per_source[sid] = snap
                statuses[sid] = {"id": sid, "name": sources[sid].name,
                                 "homepage": sources[sid].homepage, "ok": True}

    merged: dict[str, dict] = {}
    for sid in sorted(per_source):
        for item in per_source[sid]:
            key = re.sub(r"[^a-z0-9]+", " ", f"{item['title']}|{item.get('org', '')}".lower())
            if key in merged:
                continue
            merged[key] = item
    items = sorted(merged.values(), key=lambda x: (x.get("deadline") or "9999", x["title"]))
    for sid, st in statuses.items():
        st["count"] = sum(1 for x in items if x["source"] == sid)

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "taxonomy": public_taxonomy(),
        "kinds": [{"id": k, "label": v} for k, v in KIND_LABELS.items()],
        "sources": sorted(statuses.values(), key=lambda s: s["id"]),
        "items": items,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    tmp.replace(output)
    log.info("wrote %d opportunities to %s", len(items), output)
    return payload
