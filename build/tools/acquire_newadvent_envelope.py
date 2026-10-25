"""Acquire a pinned New Advent index envelope in immutable, resumable batches."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from build.tools.retain_newadvent_sources import checked_url, retain


def verified_members(cohort: Path, *, allow_images: bool = False, allow_stylesheets: bool = False) -> dict[str, dict]:
    receipt = json.loads((cohort / "acquisition.json").read_bytes())
    if receipt.get("contract") != "ocd-newadvent-retained-cohort-v1":
        raise ValueError(f"Wrong receipt: {cohort}")
    members = {}
    for member in receipt["members"]:
        if member["status"] != "retained":
            error_response = member.get("error_response")
            if error_response is not None:
                error_path = cohort / error_response["path"]
                if Path(error_response["path"]).name != error_response["path"] or error_path.is_symlink() or error_path.resolve().parent != cohort.resolve():
                    raise ValueError("Unsafe retained error response path")
                error_bytes = error_path.read_bytes()
                if len(error_bytes) != error_response["bytes"] or hashlib.sha256(error_bytes).hexdigest() != error_response["sha256"]:
                    raise ValueError("Retained error response byte mismatch")
            continue
        filename = member["path"]
        if Path(filename).name != filename or Path(filename).is_absolute():
            raise ValueError(f"Unsafe member path: {filename}")
        path = cohort / filename
        if path.resolve().parent != cohort.resolve() or path.is_symlink():
            raise ValueError(f"Member escapes cohort: {path}")
        payload = path.read_bytes()
        if len(payload) != member["bytes"] or hashlib.sha256(payload).hexdigest() != member["sha256"]:
            raise ValueError(f"Source byte mismatch: {path}")
        if member.get("http_status") != 200 or member.get("final_url") != member["url"]:
            raise ValueError(f"Source response identity mismatch: {path}")
        if member["url"] in members:
            raise ValueError(f"Duplicate URL: {member['url']}")
        members[checked_url(member["url"], allow_images=allow_images, allow_stylesheets=allow_stylesheets)] = {**member, "cohort": str(cohort.resolve())}
    return members


def acquire(graph_path: Path, graph_sha256: str, prior_cohorts: list[Path], destination: Path, batch_size: int = 100, *, fetch=retain, sleeper=time.sleep, continue_missing: bool = False) -> dict:
    payload = graph_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != graph_sha256:
        raise ValueError("Pinned index graph digest mismatch")
    graph = json.loads(payload)
    urls = graph["article_urls_in_first_occurrence_order"]
    if graph.get("contract") != "ocd-newadvent-link-census-v1" or graph["missing_linked_indexes"]:
        raise ValueError("Incomplete or unsupported index graph")
    if not urls or len(urls) != len(set(urls)) or batch_size < 1:
        raise ValueError("Invalid declared envelope or batch size")
    for url in urls:
        checked_url(url)
    for member in graph["members"]:
        raw = Path(member["path"]).read_bytes()
        if len(raw) != member["bytes"] or hashlib.sha256(raw).hexdigest() != member["sha256"]:
            raise ValueError(f"Index source binding changed: {member['path']}")
    destination.mkdir(parents=True, exist_ok=True)
    plan = {"graph_sha256": graph_sha256, "graph_path": str(graph_path.resolve()), "article_urls": urls, "prior_cohorts": [str(path.resolve()) for path in prior_cohorts]}
    plan_path = destination / "run-plan.json"
    if plan_path.exists():
        if json.loads(plan_path.read_bytes()) != plan:
            raise ValueError("Existing run plan differs")
    else:
        with plan_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(plan, stream, indent=2)
            stream.write("\n")
    lock = destination / "acquisition.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        complete = {}
        unavailable = {}
        if continue_missing:
            policy = {"graph_sha256": graph_sha256, "continue_after_http_statuses": [404, 410], "disposition": "retain failure evidence and continue other declared targets; unavailable members remain unresolved and prevent complete-source claims"}
            policy_path = destination / "continuation-policy.json"
            if policy_path.exists():
                if json.loads(policy_path.read_bytes()) != policy:
                    raise ValueError("Existing continuation policy differs")
            else:
                with policy_path.open("x", encoding="utf-8", newline="\n") as stream:
                    json.dump(policy, stream, indent=2)
                    stream.write("\n")
        def record_missing(receipt, cohort):
            for member in receipt["members"]:
                if member.get("status") == "failed" and member.get("http_status") in (404, 410):
                    unavailable[member["url"]] = {"http_status": member["http_status"], "receipt": str(cohort / "acquisition.json"), "receipt_sha256": hashlib.sha256((cohort / "acquisition.json").read_bytes()).hexdigest()}
        batches = sorted(destination.glob("batch-[0-9][0-9][0-9][0-9]"))
        for cohort in [*prior_cohorts, *batches]:
            incoming = verified_members(cohort)
            overlap = set(complete) & set(incoming)
            if overlap:
                raise ValueError(f"Duplicate retained witnesses need reconciliation: {sorted(overlap)[:3]}")
            complete.update(incoming)
            receipt = json.loads((cohort / "acquisition.json").read_bytes())
            record_missing(receipt, cohort)
            if any(member.get("http_status") in (403, 429) for member in receipt["members"]):
                raise ValueError(f"Prior provider access/rate-limit stop requires review before resuming: {cohort}")
        if (set(complete) | set(unavailable)) - set(urls):
            raise ValueError("Prior acquisition contains URLs outside the pinned envelope")
        pending = [url for url in urls if url not in complete and not (continue_missing and url in unavailable)]
        number = len(batches)
        while pending:
            number += 1
            batch = destination / f"batch-{number:04d}"
            if number > 1 or complete:
                sleeper(1.0)
            outcome = fetch(pending[:batch_size], batch)
            complete.update(verified_members(batch))
            record_missing(outcome, batch)
            pending = [url for url in urls if url not in complete and not (continue_missing and url in unavailable)]
            event = {"batch": str(batch), "status": outcome["status"], "retained": len(complete), "remaining": len(urls) - len(complete), "pending_requests": len(pending), "unavailable": len(set(unavailable) - set(complete)), "declared": len(urls)}
            with (destination / "progress.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(event) + "\n")
            print(json.dumps(event), flush=True)
            if outcome["status"] != "declared-urls-retained":
                failures = [member for member in outcome["members"] if member["status"] == "failed"]
                if not continue_missing or not failures or any(member.get("http_status") not in (404, 410) for member in failures):
                    return event
        unresolved = {url: evidence for url, evidence in unavailable.items() if url not in complete}
        if unresolved:
            return {"status": "declared-envelope-accounted-with-unavailable-members", "retained": len(complete), "remaining": len(urls) - len(complete), "declared": len(urls), "unavailable_members": unresolved, "work_completeness_established": False}
        return {"status": "declared-envelope-retained", "retained": len(complete), "remaining": 0, "declared": len(urls), "work_completeness_established": False}
    finally:
        lock.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--graph-sha256", required=True)
    parser.add_argument("--prior-cohort", action="append", type=Path, default=[])
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--continue-missing", action="store_true", help="Continue other targets after retaining HTTP 404/410 failure evidence; completeness remains blocked")
    args = parser.parse_args()
    result = acquire(args.graph, args.graph_sha256, args.prior_cohort, args.destination, args.batch_size, continue_missing=args.continue_missing)
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "declared-envelope-retained" else 1


if __name__ == "__main__":
    raise SystemExit(main())
