"""Current per-target accounting without repairing or excluding missing works."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from ocd_kernel.library._common import PipelineError, _reject_duplicate_keys
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.release.verify import verify_release_v2


def _bound_json(root: Path, binding: dict) -> dict:
    if set(binding) != {"path", "sha256"}:
        raise PipelineError("evidence requires exact path and SHA-256")
    content = resolve_repo_path(root, binding["path"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != binding["sha256"]:
        raise PipelineError(f"evidence changed: {binding['path']}")
    value = json.loads(content, object_pairs_hook=_reject_duplicate_keys)
    if not isinstance(value, dict):
        raise PipelineError("evidence requires an object")
    return value


def account_targets(root: Path, *, scope: dict, selection: dict, release_report: dict) -> dict:
    """Account a previously verified release; this result is not a readiness gate.

    The caller verifies the release independently. No report status substitutes
    for that verification in the public CLI below.
    """
    baseline = _bound_json(root, scope["baseline"])
    targets = baseline["targets"]
    identities = [row["target_id"] for row in targets]
    if not identities or len(set(identities)) != len(identities):
        raise PipelineError("frozen corpus targets must be nonempty and unique")
    links = scope["links"]
    if len({row["target_id"] for row in links}) != len(links):
        raise PipelineError("ambiguous target links")
    if set(row["target_id"] for row in links) - set(identities):
        raise PipelineError("target link is outside frozen corpus scope")
    by_target = {row["target_id"]: row for row in links}
    holds = scope.get("holds", [])
    if (len({row["target_id"] for row in holds}) != len(holds)
            or set(row["target_id"] for row in holds) - set(identities)):
        raise PipelineError("ambiguous or out-of-scope holds")
    held_targets = {row["target_id"]: row for row in holds}
    selected = {row["acceptance_path"]: row for row in selection["items"]}
    if len(selected) != len(selection["items"]):
        raise PipelineError("duplicate selected acceptance")
    if set(selected) - {row["acceptance"]["path"] for row in links}:
        raise PipelineError("release contains an acceptance outside declared target links")
    emitted = {row["acceptance_path"]: row for row in release_report["items"]}
    if set(emitted) != set(selected) or len(emitted) != len(release_report["items"]):
        raise PipelineError("release does not account for the original selection")
    results = []
    for target in targets:
        subject = target["subject"]
        if target["target_id"] != f"{subject['kind']}:{subject['id']}":
            raise PipelineError("frozen subject identity differs from target identity")
        item = {"target_id": target["target_id"], "subject": subject,
                "metadata_evidence": target["metadata_evidence"],
                "status": "unlinked", "category": None, "acceptance": None,
                "reason": "No declared accepted-master handoff; existing source review may still be reusable."}
        try:
            metadata = _bound_json(root, target["metadata_evidence"])
            if metadata["subject"] != subject:
                raise PipelineError("metadata subject differs from frozen target")
            hold = held_targets.get(target["target_id"])
            if hold:
                state = _bound_json(root, hold["state"])
                blocked = [row for row in state["targets"]
                           if row["target_id"] == hold["edition_id"] and row["target_type"] == "edition"
                           and row["stage"] == "blocked"]
                if state["work_id"] != hold["work_id"] or len(blocked) != 1:
                    raise PipelineError("declared hold no longer matches current state")
                item.update(status="blocked", reason=blocked[0]["reason"], hold_evidence=hold["state"])
                results.append(item)
                continue
            link = by_target.get(target["target_id"])
            if link:
                item["acceptance"] = link["acceptance"]
                acceptance = _bound_json(root, link["acceptance"])
                member = link.get("edition_member")
                original_member = (target.get("existing_integration") or {}).get("edition_member")
                if original_member is not None and member != original_member:
                    raise PipelineError("frozen edition-member association changed or missing")
                if member is not None:
                    if member not in acceptance.get("scope", {}).get("expected_members", []):
                        raise PipelineError("linked member is outside accepted edition scope")
                    item["edition_member"] = member
                path = link["acceptance"]["path"]
                if path not in selected:
                    item["status"] = "blocked"
                    item["reason"] = "Linked acceptance is outside this release selection."
                else:
                    row = emitted[path]
                    request = selected[path]
                    if any(row[key] != request[key] for key in ("item_id", "category")):
                        raise PipelineError("release item identity differs from selection")
                    item["category"] = row["category"]
                    item["release_item_id"] = row["item_id"]
                    if row["status"] in ("included", "warned"):
                        item.update(status="included", reason="Linked edition is included in the independently verified release.",
                                    warnings=row["reasons"])
                    elif row["status"] == "excluded" and request.get("exclude_reason"):
                        item.update(status="excluded", reason=request["exclude_reason"])
                    elif row["status"] == "failed":
                        item.update(status="failed", reason="; ".join(row["reasons"]))
                    else:
                        raise PipelineError("unaccounted or implicit release exclusion")
        except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
            item.update(status="failed", reason=str(exc))
        results.append(item)
    counts = Counter(row["status"] for row in results)
    categories = {}
    for row in results:
        category = row["category"] or "unassigned"
        categories.setdefault(category, Counter())[row["status"]] += 1
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "phase": "target-accounting", "retirement_readiness": "not-ready",
            "readiness_blockers": ["Consumer, dependency, freshness and required full-suite gate evaluation remains outstanding."]
                + (["Some corpus targets are unlinked, blocked or failed."]
                   if counts["unlinked"] or counts["blocked"] or counts["failed"] else []),
            "counts": {"targets": len(results), **{key: counts[key] for key in ("included", "excluded", "unlinked", "blocked", "failed")}},
            "categories": {key: dict(value) for key, value in sorted(categories.items())},
            "distinct_release_editions": len(emitted), "targets": results,
            "publication_performed": False, "retirement_performed": False}


def report_corpus(root: Path, release: Path, *, scope: dict, selection: dict) -> dict:
    report_path = release / "internal/release-report.json"
    content = report_path.read_bytes()
    verification = verify_release_v2(root, release, selection=selection)
    if verification["status"] != "pass":
        raise PipelineError(f"release verification failed: {verification['errors']}")
    if content != report_path.read_bytes():
        raise PipelineError("release changed during accounting")
    result = account_targets(root, scope=scope, selection=selection, release_report=json.loads(content))
    result.update(release=str(release.resolve()), release_report_sha256=hashlib.sha256(content).hexdigest(),
                  release_verification=verification, baseline=scope["baseline"])
    from .cutover_readiness import complete_readiness
    return complete_readiness(root, scope, result)
