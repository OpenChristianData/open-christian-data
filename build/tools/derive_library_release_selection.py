"""Derive an offline release selection from current library authority.

Profile mode resolves editorial scope from library/publication-profiles and rights
from current normalized records. Legacy notice-selection mode preserves its existing
historical coverage interface. Both write only a fresh selection and private input
receipt; neither assembles or publishes a release.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from ocd_kernel.library._common import PipelineError, io_glob, io_path, load_json
from ocd_kernel.library.identities import discover_library
from ocd_kernel.lib.storage_topology import repository_relative_path
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.profile import resolve_publication_profile
from ocd_kernel.release.selection import (
    load_release_selection,
    resolve_acceptance_path,
    validate_release_selection,
    validate_work_cohort,
)


OCR_LINE = re.compile(
    r"(?m)^\*\*Publishing status:\*\*\s*OCR\s*/\s*Outside(?: of)? Publishing Scope\b"
)
TICKET_NAME = re.compile(r"37c-\d{3}-(.+)\.md")
OCR_REASON = "OCR / Outside Publishing Scope"


def _digest(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _ocr_tickets(root: Path, work_ids: set[str]) -> dict[str, dict[str, str]]:
    issues = root / "plans/2026-08-31-sample-first-library-verification/issues"
    if not issues.is_dir():
        raise PipelineError(f"missing OCR scope issue directory: {issues}")
    result: dict[str, dict[str, str]] = {}
    for ticket in sorted(issues.glob("37c-*.md")):
        if not OCR_LINE.search(ticket.read_text(encoding="utf-8")):
            continue
        match = TICKET_NAME.fullmatch(ticket.name)
        if match is None or match.group(1) not in work_ids:
            raise PipelineError(f"OCR scope ticket has no exact canonical work: {ticket}")
        work_id = match.group(1)
        if work_id in result:
            raise PipelineError(f"duplicate OCR scope ticket: {work_id}")
        result[work_id] = {"ticket": _relative(root, ticket), "sha256": _digest(ticket)}
    return result


def _prior_item_decisions(root: Path, prior: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in prior["items"]:
        notices = item.get("public_notices")
        if notices or "exclude_reason" in item or "license" in item:
            decision = "exclusion" if "exclude_reason" in item else "rights"
            acceptance_path = resolve_acceptance_path(root, item["acceptance_path"])
            identity = load_json(acceptance_path).get("identity")
            if (
                not isinstance(identity, dict)
                or item["item_id"] != f"{identity.get('work_id')}--{identity.get('edition_id')}"
                or ("work_id" in item and item["work_id"] != identity.get("work_id"))
            ):
                raise PipelineError(
                    f"prior {decision} item does not match its accepted edition: {item['item_id']}"
                )
            result[item["item_id"]] = item
    return result


def derive_selection(
    root: Path, *, release_id: str, notice_selection: Path
) -> tuple[dict, dict]:
    """Return a validated selection and its input binding receipt without writing."""
    root = Path(root).resolve(strict=True)
    works = discover_library(root)
    by_id = {work.work_id: work for work in works}
    prior = load_release_selection(notice_selection)
    coverage = prior.get("work_coverage")
    if coverage is None:
        raise PipelineError("original selection requires explicit work_coverage; do not infer exclusions from identity-only records or historical tickets")
    included = set(coverage["included_work_ids"])
    excluded = {entry["work_id"]: entry["reason"] for entry in coverage["excluded_works"]}
    declared = included | set(excluded)
    if declared != set(by_id):
        raise PipelineError(
            "original selection work_coverage differs from current canonical works: "
            f"missing={sorted(set(by_id) - declared)}, extra={sorted(declared - set(by_id))}"
        )
    prior_decisions = _prior_item_decisions(root, prior)
    items: list[dict] = []
    bindings: list[dict] = []
    work_bindings: list[dict] = []
    pending: list[str] = []
    expected_acceptances: set[Path] = set()
    for work in works:
        state_path = work.path.parent / "state.json"
        state = load_json(state_path)
        if state.get("work_id") != work.work_id:
            raise PipelineError(f"state identity differs from work: {state_path}")
        work_sha = _digest(work.path)
        state_sha = _digest(state_path)
        work_bindings.append({
            "work_id": work.work_id,
            "work_path": _relative(root, work.path),
            "work_sha256": work_sha,
            "state_path": _relative(root, state_path),
            "state_sha256": state_sha,
            "ocr_excluded": excluded.get(work.work_id) == OCR_REASON,
            "exclusion_reason": excluded.get(work.work_id),
        })
        if work.work_id in excluded:
            continue
        form_categories = {
            form["textual_form_id"]: form.get("category")
            for form in work.record.get("textual_forms", [])
        }
        for edition in work.editions:
            acceptance_path = edition.path.with_name("acceptance.json")
            expected_acceptances.add(acceptance_path)
            if not io_path(acceptance_path).is_file():
                continue
            record = load_json(acceptance_path)
            status = record.get("promotion", {}).get("status")
            if status == "pending":
                pending.append(_relative(root, acceptance_path))
                continue
            if status != "promoted":
                raise PipelineError(f"unknown acceptance promotion status: {acceptance_path}: {status}")
            identity = record["identity"]
            if (
                identity["work_id"] != work.work_id
                or identity["textual_form_id"] != edition.textual_form_id
                or identity["edition_id"] != edition.edition_id
                or identity["acquisition_id"] not in edition.record.get("acquisition_ids", [])
            ):
                raise PipelineError(f"promoted acceptance differs from declared edition: {acceptance_path}")
            item_id = f"{work.work_id}--{edition.edition_id}"
            prior = prior_decisions.pop(item_id, None)
            category = edition.record.get("category")
            if category is None:
                category = form_categories.get(edition.textual_form_id)
            if (
                category is None
                and prior is not None
                and "exclude_reason" in prior
                and prior.get("category") == "unassigned"
            ):
                category = "unassigned"
            if not isinstance(category, str) or not category:
                raise PipelineError(f"promoted edition has no exact category: {acceptance_path}")
            category = {
                "doctrinal-documents": "doctrinal_documents",
                "reference-entries": "reference_entries",
                "topical-indexes": "topical_indexes",
            }.get(category, category)
            master_sha = _digest(edition.path)
            if master_sha != record["promotion"]["master"]["sha256"]:
                raise PipelineError(f"promoted master SHA-256 differs: {edition.path}")
            state_target = next(
                (target for target in state.get("targets", [])
                 if target.get("target_type") == "edition"
                 and target.get("target_id") == edition.edition_id),
                None,
            )
            if not isinstance(state_target, dict) or state_target.get("stage") != "accepted":
                raise PipelineError(f"promoted edition state is not accepted: {state_path}: {edition.edition_id}")
            if not { _relative(root, edition.path), _relative(root, acceptance_path) }.issubset(
                state_target.get("evidence", [])
            ):
                raise PipelineError(f"accepted state lacks master/acceptance evidence: {state_path}")
            item = {
                "item_id": item_id,
                "work_id": work.work_id,
                "category": category,
                "acceptance_path": _relative(root, acceptance_path),
            }
            bound = {
                "item_id": item_id,
                "acceptance_sha256": _digest(acceptance_path),
                "master_sha256": master_sha,
                "work_sha256": work_sha,
                "state_sha256": state_sha,
                "category": category,
            }
            if prior is not None:
                if "exclude_reason" in prior:
                    if prior["acceptance_path"] != item["acceptance_path"]:
                        raise PipelineError(f"prior exclusion acceptance path differs: {item_id}")
                    item["exclude_reason"] = bound["exclude_reason"] = prior["exclude_reason"]
                else:
                    if "license" in prior:
                        item["license"] = bound["license"] = prior["license"]
                    if "public_notices" in prior:
                        item["public_notices"] = prior["public_notices"]
                        notice_texts_for_item(root, item, io_path(acceptance_path))
                        bound["public_notices"] = item["public_notices"]
            items.append(item)
            bindings.append(bound)
    exclusions = sorted(key for key, item in prior_decisions.items() if "exclude_reason" in item)
    if exclusions:
        raise PipelineError(f"prior exclusions lost promoted accepted text: {exclusions}")
    if prior_decisions:
        raise PipelineError(f"prior rights decisions lost selected text: {sorted(prior_decisions)}")
    actual_acceptances = set(io_glob(root / "library/works", "*/forms/*/editions/*/acceptance.json"))
    orphaned = actual_acceptances - expected_acceptances
    if orphaned:
        raise PipelineError(f"acceptance outside declared edition: {sorted(orphaned)}")
    if not items:
        raise PipelineError("no promoted accepted text in current selected cohort")
    selection = validate_release_selection(
        {
            "schema_version": "2.0",
            "release_id": release_id,
            "items": items,
            "work_coverage": coverage,
        }
    )
    validate_work_cohort(root, selection)
    selected = [item for item in items if "exclude_reason" not in item]
    receipt = {
        "scope": "Interim private selection; human acceptance, rights, and publication remain separate.",
        "canonical_works": len(works),
        "included_works": len(included),
        "excluded_ocr_works": sum(reason == OCR_REASON for reason in excluded.values()),
        "excluded_works": len(excluded),
        "selected_text_items": len(selected),
        "excluded_text_items": len(items) - len(selected),
        "selected_text_work_count": len({item["work_id"] for item in selected}),
        "included_works_without_selected_text": len(included - {item["work_id"] for item in selected}),
        "categories": dict(sorted(Counter(item["category"] for item in selected).items())),
        "work_exclusion_reasons": excluded,
        "pending_acceptances_not_selected": sorted(pending),
        "work_bindings": sorted(work_bindings, key=lambda item: item["work_id"]),
        "item_bindings": sorted(bindings, key=lambda item: item["item_id"]),
        "notice_selection": {
            "path": repository_relative_path(root, notice_selection),
            "sha256": _digest(notice_selection),
        },
    }
    return selection, receipt


def _write_new(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--release-id", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--notice-selection", type=Path, help="Legacy historical selection derivation")
    source.add_argument("--profile", type=Path, help="Private library-owned editorial publication profile")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    output = args.output_dir.resolve(strict=False)
    if output.exists():
        raise PipelineError(f"refusing to replace existing selection evidence: {output}")
    if args.profile is not None:
        selection, receipt = resolve_publication_profile(
            root, release_id=args.release_id, profile_path=args.profile
        )
    else:
        notice_selection = args.notice_selection
        if not notice_selection.is_absolute():
            notice_selection = root / notice_selection
        selection, receipt = derive_selection(
            root, release_id=args.release_id, notice_selection=notice_selection
        )
    output.mkdir(parents=True, exist_ok=False)
    _write_new(output / "selection.json", selection)
    _write_new(output / "derivation.json", receipt)
    print(
        json.dumps(
            {
                "canonical_works": receipt["canonical_works"],
                "included_works": receipt["included_works"],
                "excluded_ocr_works": receipt["excluded_ocr_works"],
                "selected_text_items": receipt["selected_text_items"],
                "selection_sha256": _digest(output / "selection.json"),
                "derivation_sha256": _digest(output / "derivation.json"),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
