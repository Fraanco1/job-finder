"""Command line entry point: ``python -m jobfinder <command>``."""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jobfinder", description="STEM opportunity scrapers")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scrape", help="run scrapers and write web/public/data/opportunities.json")
    sc.add_argument("--only", nargs="+", metavar="SOURCE", help="run only these sources")
    sc.add_argument("--limit", type=int, help="max items per source (quick test; no snapshot saved)")
    sc.add_argument("--workers", type=int, default=6, help="sources run in parallel")

    sub.add_parser("sources", help="list available sources")
    sub.add_parser("build", help="rebuild the data file from saved snapshots, without scraping")
    sd = sub.add_parser("seed", help="copy snapshots into data/seed/ (committed) for sites that block CI")
    sd.add_argument("sources", nargs="*", default=["euraxess", "daad"])

    sv = sub.add_parser("serve", help="serve the built site with a /api/refresh endpoint")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--host", default="127.0.0.1")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    if args.cmd == "sources":
        from .sources import all_sources
        for sid, cls in all_sources().items():
            print(f"{sid:20} {cls.name:30} {cls.homepage}")
    elif args.cmd in ("scrape", "build"):
        from .pipeline import run
        if args.cmd == "build":
            payload = run(scrape=False)
        else:
            payload = run(only=args.only, limit=args.limit, workers=args.workers)
        for s in payload["sources"]:
            flag = "ok " if s.get("ok") else "ERR"
            extra = " (stale)" if s.get("stale") else ""
            print(f"[{flag}] {s['id']:20} {s.get('count', 0):6d}{extra} {s.get('error', '')}")
        print(f"total: {len(payload['items'])}")
    elif args.cmd == "seed":
        from .pipeline import save_seeds
        for sid, n in save_seeds(args.sources).items():
            print(f"seeded {sid}: {n} open postings")
    elif args.cmd == "serve":
        from .server import serve
        serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
