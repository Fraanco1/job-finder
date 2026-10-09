#!/usr/bin/env bash
# Refresh the committed seed snapshots for sources that block GitHub's servers
# (EURAXESS rate-limits cloud IPs, DAAD returns 403), then push so the next
# GitHub Actions run publishes them. Run from a home connection, e.g. weekly.
set -euo pipefail
cd "$(dirname "$0")/../scraper"
python -m jobfinder scrape --only euraxess daad
python -m jobfinder seed euraxess daad
cd ..
git add data/seed
if git diff --cached --quiet; then
  echo "Seeds unchanged."
else
  git commit -m "Refresh EURAXESS and DAAD seed data"
  git push
fi
