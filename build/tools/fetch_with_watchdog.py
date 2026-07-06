"""Stall-resilient wrapper around fetch_ia_pages.py for one NSH volume.

The IA remotezip range-reads hang silently near the end of a volume (the
fetch process stops writing pages but never exits or errors). This watchdog
launches the fetcher as a child, watches the rebuild dir's page_*.jpg count,
and:

  * if the count stops growing for STALL_SECS  -> kills the child and relaunches
    (the fetcher is idempotent: a resume skips already-fetched pages by sha256),
  * if the child exits non-zero (transient HTTP errors on a few pages)
    -> relaunches to retry those pages,
  * if the child exits 0 (clean: errors=0)     -> done; writes a .done marker.

It stops when the fetch exits clean, or when MAX_RESTARTS is hit, or when two
consecutive relaunches make zero new progress (the remaining pages are stuck and
need manual attention -- logged, never silently dropped).

Non-destructive: only ever writes into the rebuild out-dir / manifest that
fetch_ia_pages.py owns. The live volume is untouched.

Usage:
  py -3 build/tools/fetch_with_watchdog.py --volume 1 \
      --primary-leaf-page-spec "37:1,38:2,...,45:9" \
      --out-dir raw/internet-archive/schaff-herzog-pages/vol_01_rebuild \
      --manifest raw/internet-archive/schaff-herzog-pages/vol_01_rebuild.manifest.json
  py -3 build/tools/fetch_with_watchdog.py --selftest
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FETCHER = REPO_ROOT / "build" / "tools" / "fetch_ia_pages.py"
LOG_FILE = REPO_ROOT / "logs" / "fetch_with_watchdog.log"

# --- Tuning (PY-03: config at the top) -------------------------------------
POLL_SECS = 20          # how often to check progress / child state
STALL_SECS = 180        # no new page for this long => the read has hung
MAX_RESTARTS = 30       # hard cap on relaunches (runaway backstop)
MAX_NO_PROGRESS = 2      # consecutive relaunches with zero new pages => give up

logger = logging.getLogger("fetch_with_watchdog")


def _setup_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
                  logging.StreamHandler()],
    )


def restart_decision(proc_exited: bool, returncode: int | None,
                     secs_since_progress: float) -> str:
    """Pure decision for the watch loop. Returns one of:
    'done'    -- child exited 0 (clean), stop.
    'relaunch'-- child exited non-zero (retry transient failures).
    'kill'    -- child still running but stalled past STALL_SECS.
    'wait'    -- child running and making/None progress; keep watching.
    """
    if proc_exited:
        return "done" if returncode == 0 else "relaunch"
    if secs_since_progress > STALL_SECS:
        return "kill"
    return "wait"


def count_pages(out_dir: Path) -> int:
    return sum(1 for _ in out_dir.glob("page_*.jpg")) if out_dir.exists() else 0


def _build_cmd(volume: int, primary_leaf_page_spec: str | None,
               out_dir: Path, manifest: Path, workers: int) -> list[str]:
    cmd = [sys.executable, str(FETCHER), "--volume", str(volume),
           "--pages", "all", "--out-dir", str(out_dir),
           "--manifest", str(manifest), "--workers", str(workers)]
    if primary_leaf_page_spec:
        cmd += ["--primary-leaf-page-spec", primary_leaf_page_spec]
    return cmd


def run(volume: int, primary_leaf_page_spec: str | None, out_dir: Path,
        manifest: Path, workers: int = 4) -> int:
    out_dir = Path(out_dir)
    cmd = _build_cmd(volume, primary_leaf_page_spec, out_dir, manifest, workers)
    done_marker = Path(str(manifest) + ".done")

    restarts = 0
    no_progress_streak = 0
    while restarts <= MAX_RESTARTS:
        count_at_launch = count_pages(out_dir)
        logger.info("vol_%02d: launch #%d (have %d pages): %s",
                    volume, restarts + 1, count_at_launch, " ".join(cmd))
        # PY/SUB: we manage the child explicitly; check=False because a non-zero
        # exit (transient page errors) is an expected, recoverable signal here.
        proc = subprocess.Popen(cmd)  # noqa: S603 -- args are code-controlled
        last_count = count_at_launch
        last_progress = time.monotonic()

        while True:
            time.sleep(POLL_SECS)
            rc = proc.poll()
            c = count_pages(out_dir)
            if c > last_count:
                last_count = c
                last_progress = time.monotonic()
            decision = restart_decision(rc is not None, rc,
                                        time.monotonic() - last_progress)
            if decision == "wait":
                continue
            if decision == "done":
                logger.info("vol_%02d: clean exit (rc=0) with %d pages -- DONE",
                            volume, c)
                done_marker.write_text(f"clean rc=0 pages={c}\n", encoding="utf-8")
                return 0
            if decision == "kill":
                logger.warning("vol_%02d: STALL (%ds no new page at %d); killing+relaunch",
                               volume, STALL_SECS, c)
                proc.kill()
                proc.wait()
            elif decision == "relaunch":
                logger.warning("vol_%02d: child exit rc=%s with %d pages; relaunch to retry",
                               volume, rc, c)
            break  # leave inner loop -> relaunch

        # Track whether this attempt advanced at all (stuck-page detection).
        if count_pages(out_dir) <= count_at_launch:
            no_progress_streak += 1
            if no_progress_streak >= MAX_NO_PROGRESS:
                logger.error("vol_%02d: %d relaunches with no new pages (have %d); "
                             "remaining pages appear stuck -- stopping for manual review",
                             volume, no_progress_streak, count_pages(out_dir))
                return 1
        else:
            no_progress_streak = 0
        restarts += 1

    logger.error("vol_%02d: hit MAX_RESTARTS=%d with %d pages -- stopping",
                 volume, MAX_RESTARTS, count_pages(out_dir))
    return 1


def _selftest() -> int:
    """Adversarial check of the pure restart decision (TEST-09)."""
    assert restart_decision(True, 0, 0) == "done"
    assert restart_decision(True, 1, 0) == "relaunch"
    assert restart_decision(True, 1, 9999) == "relaunch"        # exit wins over stall
    assert restart_decision(False, None, STALL_SECS + 1) == "kill"
    assert restart_decision(False, None, STALL_SECS - 1) == "wait"
    assert restart_decision(False, None, 0) == "wait"
    print("selftest OK: restart decision true-positives + true-negatives pass")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stall-resilient NSH volume fetch.")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--volume", type=int)
    parser.add_argument("--primary-leaf-page-spec", default=None)
    parser.add_argument("--out-dir")
    parser.add_argument("--manifest")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.volume is None or not args.out_dir or not args.manifest:
        parser.error("--volume, --out-dir and --manifest are required unless --selftest")
    _setup_logging()
    return run(args.volume, args.primary_leaf_page_spec,
               Path(args.out_dir), Path(args.manifest), args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
