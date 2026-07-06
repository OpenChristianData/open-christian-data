#!/usr/bin/env bash
# One-shot runner: crawl Catholic Encyclopedia volumes 2-15 from newadvent.org.
# Stops immediately if any volume hard-exits (429/403 rate-limit per parser policy).
set -uo pipefail
cd "$(dirname "$0")"
LOG="ce_crawl_run.log"
echo "=== CE crawl run started $(date) ===" > "$LOG"
for v in 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  echo "--- volume $v starting $(date) ---" | tee -a "$LOG"
  py -3 -m build.parsers.catholic_encyclopedia --volume "$v" >> "$LOG" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "!!! volume $v exited rc=$rc (likely rate-limit hard-stop). Halting run." | tee -a "$LOG"
    exit $rc
  fi
  echo "--- volume $v done $(date) ---" | tee -a "$LOG"
done
echo "=== CE crawl run finished $(date) ===" | tee -a "$LOG"
