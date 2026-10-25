"""Seal a source-bound reconciliation of a stopped New Advent acquisition run.

This accounts for retained and unavailable members of one pinned frontier. It
does not establish article-link closure, asset completeness, or TEI acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.tools.acquire_newadvent_envelope import verified_members
from build.tools.retain_newadvent_sources import checked_url


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def reconcile(run: Path, supplemental_failure_cohorts: list[Path] | None = None, historical_request_graphs: list[tuple[Path, str]] | None = None) -> dict:
    if (run / "acquisition.lock").exists():
        raise ValueError("Acquisition lock exists; reconcile only after the owning process stops")
    plan_path = run / "run-plan.json"
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    graph_path = Path(plan["graph_path"])
    graph_bytes = graph_path.read_bytes()
    if _sha(graph_bytes) != plan["graph_sha256"]:
        raise ValueError("Pinned graph digest changed")
    graph = json.loads(graph_bytes)
    urls = plan["article_urls"]
    if graph.get("contract") != "ocd-newadvent-link-census-v1" or graph["missing_linked_indexes"] or urls != graph["article_urls_in_first_occurrence_order"]:
        raise ValueError("Run plan does not bind the declared graph envelope")
    if not urls or len(urls) != len(set(urls)):
        raise ValueError("Invalid declared URL envelope")
    for url in urls:
        checked_url(url)
    for source in graph["members"]:
        payload = Path(source["path"]).read_bytes()
        if len(payload) != source["bytes"] or _sha(payload) != source["sha256"]:
            raise ValueError("Graph source byte binding changed")
    request_graphs = [(graph_path, _sha(graph_bytes), graph)]
    for path, expected_sha in historical_request_graphs or []:
        raw = path.read_bytes()
        historical = json.loads(raw)
        if _sha(raw) != expected_sha or historical.get("contract") != "ocd-newadvent-link-census-v1":
            raise ValueError("Historical request graph binding changed")
        for source in historical["members"]:
            body = Path(source["path"]).read_bytes()
            if len(body) != source["bytes"] or _sha(body) != source["sha256"]:
                raise ValueError("Historical request graph source binding changed")
        request_graphs.append((path, expected_sha, historical))
    supplemental = supplemental_failure_cohorts or []
    cohorts = [*(Path(path) for path in plan["prior_cohorts"]), *sorted(run.glob("batch-[0-9][0-9][0-9][0-9]")), *supplemental]
    if len({path.resolve() for path in cohorts}) != len(cohorts):
        raise ValueError("Duplicate acquisition cohort")
    retained = {}
    histories = {url: [] for url in urls}
    receipts = []
    for cohort in cohorts:
        receipt_path = cohort / "acquisition.json"
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes)
        incoming = verified_members(cohort)
        if set(incoming) & set(retained):
            raise ValueError("Duplicate retained source witnesses")
        if cohort in supplemental and incoming:
            raise ValueError("Supplemental failure evidence cannot replace source witnesses")
        request_path = cohort / "request-plan.json"
        receipt_urls = [member["url"] for member in receipt["members"]]
        if request_path.is_file():
            request_bytes = request_path.read_bytes()
            requests = json.loads(request_bytes)["urls"]
            declaration = {"kind": "cohort-request-plan", "path": str(request_path.resolve()), "sha256": _sha(request_bytes)}
        elif str(cohort.resolve()) in plan["prior_cohorts"]:
            matching = [(path, sha) for path, sha, record in request_graphs if record.get("selected_acquisition_urls") == receipt_urls]
            if len(matching) != 1:
                raise ValueError("Historical cohort lacks a unique pinned pre-request declaration")
            path, sha = matching[0]
            requests = receipt_urls
            declaration = {"kind": "pinned-link-census-selection", "path": str(path.resolve()), "sha256": sha, "json_pointer": "/selected_acquisition_urls", "limitation": "This earlier cohort has no separate request-plan file; its ordered selection was retained in the pinned census before acquisition."}
        else:
            raise ValueError("Acquisition cohort lacks its request plan")
        if requests != [member["url"] for member in receipt["members"]] or len(requests) != len(set(requests)):
            raise ValueError("Receipt/request-plan member identity drift")
        if set(requests) - set(urls):
            raise ValueError("Acquisition member lies outside the pinned envelope")
        allowed_files = {"acquisition.json", "request-plan.json", "acquisition.events.jsonl"}
        for member in receipt["members"]:
            if member["status"] not in {"retained", "failed", "not-attempted"}:
                raise ValueError("Unfinished or unknown acquisition member status")
            if member.get("path"):
                allowed_files.add(member["path"])
            if member.get("error_response"):
                allowed_files.add(member["error_response"]["path"])
            histories[member["url"]].append({"receipt": str(receipt_path.resolve()), "receipt_sha256": _sha(receipt_bytes), **member})
        if {path.name for path in cohort.iterdir()} - allowed_files:
            raise ValueError("Unaccounted acquisition cohort files require disposition")
        retained.update(incoming)
        receipts.append({"path": str(receipt_path.resolve()), "sha256": _sha(receipt_bytes), "request_declaration": declaration})
    unavailable = []
    pending = []
    for url in urls:
        if url in retained:
            continue
        failures = [item for item in histories[url] if item["status"] == "failed"]
        if failures and all(item.get("http_status") in {404, 410} for item in failures):
            unavailable.append(url)
        else:
            pending.append(url)
    members = [{"url": url, "disposition": "retained" if url in retained else "unavailable" if url in unavailable else "pending-or-other-failure", "history": histories[url]} for url in urls]
    return {
        "contract": "ocd-newadvent-acquisition-reconciliation-v1",
        "run_plan": {"path": str(plan_path.resolve()), "sha256": _sha(plan_bytes)},
        "graph": {"path": str(graph_path.resolve()), "sha256": _sha(graph_bytes)},
        "source_receipts": receipts, "members": members,
        "declared": len(urls), "retained": len(retained),
        "retained_bytes": sum(item["bytes"] for item in retained.values()),
        "unavailable_urls": unavailable, "pending_urls": pending,
        "declared_frontier_accounted": not pending,
        "declared_frontier_retained": len(retained) == len(urls),
        "article_link_and_asset_closure_established": False,
        "work_completeness_established": False,
        "historical_source_claims_reconciled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--supplemental-failure-cohort", type=Path, action="append", default=[])
    parser.add_argument("--historical-request-graph", nargs=2, action="append", default=[], metavar=("PATH", "SHA256"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = reconcile(args.run, args.supplemental_failure_cohort, [(Path(path), sha) for path, sha in args.historical_request_graph])
    payload = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with args.output.open("xb") as stream:
        stream.write(payload)
    print(json.dumps({"output": str(args.output), "sha256": _sha(payload), "declared": result["declared"], "retained": result["retained"], "unavailable": len(result["unavailable_urls"]), "pending": len(result["pending_urls"])}))
    return 0 if result["declared_frontier_retained"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
