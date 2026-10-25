"""Retain only a pinned asset census, serialized against its article run."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from build.tools.acquire_newadvent_envelope import verified_members
from build.tools.retain_newadvent_sources import checked_url, retain


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _write(path, record):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def acquire(census_path: Path, census_sha256: str, article_run: Path,
            destination: Path, batch_size: int = 100, *, continue_missing=False,
            fetch=retain, sleeper=time.sleep) -> dict:
    payload = census_path.read_bytes()
    if _sha(payload) != census_sha256:
        raise ValueError("Pinned asset census digest mismatch")
    census = json.loads(payload)
    if census.get("contract") != "ocd-newadvent-image-census-v1" or batch_size < 1:
        raise ValueError("Unsupported census or invalid batch size")
    images, stylesheets = census["image_urls"], census["stylesheet_urls"]
    urls = images + stylesheets
    if len(urls) != len(set(urls)):
        raise ValueError("Duplicate census URLs")
    for selected, prefix in ((images, "/images/"), (stylesheets, "/utility/")):
        for url in selected:
            checked_url(url, allow_images=True, allow_stylesheets=True)
            if not urlsplit(url).path.startswith(prefix):
                raise ValueError("Asset classification mismatch")
    sources = []
    for member in census["source_members"]:
        raw = Path(member["path"]).read_bytes()
        if _sha(raw) != member["sha256"] or ("bytes" in member and len(raw) != member["bytes"]):
            raise ValueError("Census source binding changed")
        sources.append({**member, "bytes": len(raw)})
    if len({member["url"] for member in sources}) != len(sources):
        raise ValueError("Duplicate census source members")
    if not article_run.is_dir() or article_run.resolve() == destination.resolve():
        raise ValueError("Article run must be an existing distinct directory")
    # Holding the article run's own exclusive lock also prevents a later article
    # restart from overlapping this asset stream.
    article_lock = article_run / "acquisition.lock"
    with article_lock.open("x", encoding="utf-8") as stream:
        stream.write(f"asset acquisition pid={os.getpid()}")
    try:
        destination.mkdir(parents=True, exist_ok=True)
        lock = destination / "acquisition.lock"
        with lock.open("x", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
        try:
            plan = {"contract": "ocd-newadvent-asset-run-v1", "census_path": str(census_path.resolve()),
                    "census_sha256": census_sha256, "source_members": sources,
                    "article_run": str(article_run.resolve()), "image_urls": images,
                    "stylesheet_urls": stylesheets, "batch_size": batch_size,
                    "continue_missing": continue_missing, "delay_seconds": 1.0}
            plan_path = destination / "run-plan.json"
            if plan_path.exists():
                if json.loads(plan_path.read_bytes()) != plan:
                    raise ValueError("Existing run plan differs")
            else:
                _write(plan_path, plan)
            retained, failures, receipts = {}, {}, []
            prior_receipts = {}
            for outcome_path in sorted(destination.glob("outcome-*.json")):
                for evidence in json.loads(outcome_path.read_bytes())["receipts"]:
                    if evidence["path"] in prior_receipts and prior_receipts[evidence["path"]] != evidence:
                        raise ValueError("Conflicting historical receipt bindings")
                    prior_receipts[evidence["path"]] = evidence

            def inspect(batch):
                receipt_path = batch / "acquisition.json"
                receipt_bytes = receipt_path.read_bytes()
                receipt = json.loads(receipt_bytes)
                requested = json.loads((batch / "request-plan.json").read_bytes())["urls"]
                members = receipt["members"]
                if [m["url"] for m in members] != requested or len(set(requested)) != len(requested) or set(requested) - set(urls):
                    raise ValueError("Receipt URLs differ from declared request envelope")
                if set(requested) & (set(retained) | set(failures)):
                    raise ValueError("Duplicate already attempted asset URLs")
                incoming = verified_members(batch, allow_images=True, allow_stylesheets=True)
                if set(incoming) & set(retained):
                    raise ValueError("Duplicate retained asset witnesses")
                for member in members:
                    if member["status"] not in {"retained", "failed", "not-attempted"}:
                        raise ValueError("Incomplete asset attempt requires review")
                    if member["status"] == "failed":
                        if member["url"] in failures:
                            raise ValueError("Duplicate failed asset attempts")
                        if member.get("http_status") is not None and member.get("error_response") is None:
                            raise ValueError("HTTP failure lacks exact response evidence")
                        failures[member["url"]] = member
                retained.update(incoming)
                receipts.append({"path": str(receipt_path.resolve()), "sha256": _sha(receipt_bytes),
                                 "request_plan_sha256": _sha((batch / "request-plan.json").read_bytes()),
                                 "events_sha256": _sha((batch / "acquisition.events.jsonl").read_bytes())})
                if receipts[-1]["path"] in prior_receipts and receipts[-1] != prior_receipts[receipts[-1]["path"]]:
                    raise ValueError("Historical acquisition evidence changed")

            batches = sorted(destination.glob("batch-[0-9][0-9][0-9][0-9]"))
            for batch in batches:
                inspect(batch)
            if set(prior_receipts) - {receipt["path"] for receipt in receipts}:
                raise ValueError("Historical acquisition receipt disappeared")
            def stopped():
                return bool(failures) and (not continue_missing or any(m.get("http_status") not in {404, 410} for m in failures.values()))
            number = len(batches)
            pending = [url for url in urls if url not in retained and url not in failures]
            while pending and not stopped():
                if number >= 9999:
                    raise ValueError("Asset batch limit reached")
                number += 1
                if number > 1:
                    sleeper(1.0)
                batch = destination / f"batch-{number:04d}"
                fetch(pending[:batch_size], batch, allow_images=True, allow_stylesheets=True)
                before = len(retained) + len(failures)
                inspect(batch)
                if len(retained) + len(failures) == before:
                    raise ValueError("Asset batch made no progress")
                pending = [url for url in urls if url not in retained and url not in failures]
                with (destination / "progress.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"batch": number, "retained": len(retained), "failed": len(failures), "pending": len(pending)}) + "\n")
            outcome = {"status": "stopped-on-failure" if stopped() else "declared-assets-accounted-with-unavailable-members" if failures else "declared-assets-retained",
                       "census_sha256": census_sha256, "retained": len(retained), "declared": len(urls),
                       "remaining": len(urls) - len(retained), "failures": failures, "receipts": receipts,
                       "images": {"declared": len(images), "retained": len(set(images) & set(retained))},
                       "stylesheets": {"declared": len(stylesheets), "retained": len(set(stylesheets) & set(retained))},
                       "unresolved_census_occurrences": census.get("unresolved", []),
                       "scope": "declared census image_urls and stylesheet_urls only",
                       "work_completeness_established": False, "asset_closure_established": False}
            ordinal = len(list(destination.glob("outcome-*.json"))) + 1
            _write(destination / f"outcome-{ordinal:04d}.json", outcome)
            return outcome
        finally:
            lock.unlink()
    finally:
        article_lock.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--census-sha256", required=True)
    parser.add_argument("--article-run", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--continue-missing", action="store_true")
    args = parser.parse_args()
    outcome = acquire(args.census, args.census_sha256, args.article_run, args.destination,
                      args.batch_size, continue_missing=args.continue_missing)
    print(json.dumps(outcome), flush=True)
    return 0 if outcome["status"] == "declared-assets-retained" else 1


if __name__ == "__main__":
    raise SystemExit(main())
