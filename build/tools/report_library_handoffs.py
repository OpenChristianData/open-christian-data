"""Report explicit library handoff evidence without changing its authorities."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from build.tools.count_dataset_records import _manifest_config_ids
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.identities import load_work


ROOT = Path(__file__).resolve().parents[2]
TICKETS = Path("plans/2026-08-31-sample-first-library-verification/issues")
INSPECTED_TEI_RECEIPTS = (
    Path("plans/2026-09-22-source-preflight/openmgh-bsb00000750-child-batch-20260926.json"),
    Path("plans/2026-09-22-source-preflight/openmgh-bsb830-inspected-batch-20260926.json"),
    Path("plans/2026-09-22-source-preflight/openmgh-bsb752-inspected-batch-20260926.json"),
    Path("plans/2026-09-22-source-preflight/openmgh-bsb752-remaining-six-20260926.json"),
)
OCR = re.compile(
    r"\*\*Publishing status:\*\*\s*OCR\s*/\s*Outside (?:of )?Publishing Scope", re.I
)
TICKET_ID = re.compile(
    r"(?:\*\*Work ID:\*\*\s*|catalog entry\s*)`([a-z0-9][a-z0-9-]*)`"
)
STATUS = re.compile(r"\*\*Status(?:\s*\([^)]*\))?:\*\*\s*([^\r\n]+)")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_json(path: Path) -> tuple[dict, str]:
    content = io_path(path).read_bytes()
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("JSON root is not an object")
    return value, _sha(content)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _issue(issues: list[dict], kind: str, path: str, detail: str) -> None:
    issues.append(dict(kind=kind, path=path, detail=detail))


def _is_link(path: Path) -> bool:
    try:
        mode = path.lstat()
    except OSError:
        return True
    return (
        path.is_symlink()
        or bool(mode.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        if hasattr(mode, "st_file_attributes")
        else path.is_symlink()
    )


def _ticket_index(root: Path, issues: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = defaultdict(list)
    for path in sorted((root / TICKETS).glob("37c-*.md")):
        relative = _relative(root, path)
        try:
            content = path.read_bytes()
            text = content.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            _issue(issues, "ticket-unreadable", relative, str(exc))
            continue
        identities = set(TICKET_ID.findall(text[:3000]))
        if len(identities) != 1:
            _issue(
                issues,
                "ticket-identity-not-explicit",
                relative,
                f"found {sorted(identities)}",
            )
            continue
        status = STATUS.search(text[:4000])
        index[next(iter(identities))].append(
            dict(
                path=relative,
                sha256=_sha(content),
                status=status.group(1).strip() if status else None,
                ocr_excluded=bool(OCR.search(text)),
            )
        )
    return index


def _manifest_index(
    root: Path, works: set[str], issues: list[dict]
) -> tuple[dict, dict]:
    by_work: dict[str, list[dict]] = defaultdict(list)
    by_path: dict[str, dict] = {}
    for path in sorted((root / "sources").rglob("*source-manifest.json")):
        relative = _relative(root, path)
        try:
            manifest, digest = _read_json(path)
            config_bindings = []
            config_invalid = False
            for authority in manifest.get("authorities", []):
                if (
                    not isinstance(authority, dict)
                    or not isinstance(authority.get("path"), str)
                    or Path(authority["path"]).name != "config.json"
                ):
                    continue
                config_relative = Path(authority["path"])
                if config_relative.is_absolute() or ".." in config_relative.parts:
                    _issue(
                        issues,
                        "manifest-config-invalid",
                        relative,
                        str(config_relative),
                    )
                    config_invalid = True
                    continue
                config_path = root / config_relative
                try:
                    _config, config_sha = _read_json(config_path)
                    if authority.get("sha256") and authority["sha256"] != config_sha:
                        raise ValueError("declared config SHA-256 differs")
                    config_bindings.append(
                        dict(path=config_relative.as_posix(), sha256=config_sha)
                    )
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                    _issue(
                        issues,
                        "manifest-config-invalid",
                        relative,
                        f"{config_relative}: {exc}",
                    )
                    config_invalid = True
            if config_invalid:
                continue
            declared = sorted(_manifest_config_ids(manifest, root))
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValueError,
            PipelineError,
        ) as exc:
            _issue(issues, "manifest-unreadable-or-invalid", relative, str(exc))
            continue
        entry = dict(
            path=relative,
            sha256=digest,
            work_ids=declared,
            config_bindings=sorted(config_bindings, key=lambda item: item["path"]),
            association="explicit-manifest-or-config-identity",
        )
        by_path[relative] = entry
        for work_id in declared:
            if work_id in works:
                by_work[work_id].append(entry)
            else:
                _issue(issues, "manifest-id-not-canonical", relative, work_id)
    return by_work, by_path


def _candidate_index(
    candidate_root: Path | None, manifests: dict, issues: list[dict]
) -> tuple[dict, dict]:
    by_work: dict[str, list[dict]] = defaultdict(list)
    counts = dict(
        package_manifests=0,
        current_manifest_matches=0,
        stale_manifest_matches=0,
        recorded_validation_passes=0,
        pruned_paths=0,
    )
    if candidate_root is None:
        return by_work, counts
    if not candidate_root.is_dir() or _is_link(candidate_root):
        _issue(
            issues,
            "candidate-root-inaccessible",
            str(candidate_root),
            "not an ordinary directory",
        )
        return by_work, counts

    def walk_error(exc: OSError) -> None:
        _issue(issues, "candidate-directory-unreadable", str(exc.filename), str(exc))

    for directory, dirs, files in os.walk(
        candidate_root, topdown=True, followlinks=False, onerror=walk_error
    ):
        base = Path(directory)
        kept = []
        for name in sorted(dirs):
            path = base / name
            if name.startswith(".") or _is_link(path):
                counts["pruned_paths"] += 1
                _issue(
                    issues,
                    "candidate-directory-pruned",
                    str(path),
                    "hidden or linked directory",
                )
            else:
                kept.append(name)
        dirs[:] = kept
        if "manifest.json" not in files:
            continue
        path = base / "manifest.json"
        try:
            manifest, digest = _read_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            _issue(issues, "candidate-manifest-unreadable", str(path), str(exc))
            continue
        if manifest.get("contract") != "ocd-candidate-package-v1":
            continue
        counts["package_manifests"] += 1
        binding = manifest.get("source_manifest")
        if not isinstance(binding, dict):
            _issue(
                issues,
                "candidate-source-binding-missing",
                str(path),
                "no source_manifest object",
            )
            continue
        source_path = binding.get("path")
        current = manifests.get(source_path)
        if current is None:
            _issue(
                issues,
                "candidate-source-manifest-external-or-missing",
                str(path),
                str(source_path),
            )
            continue
        manifest_current = binding.get("sha256") == current["sha256"]
        if not manifest_current:
            counts["stale_manifest_matches"] += 1
            _issue(
                issues, "candidate-source-manifest-stale", str(path), str(source_path)
            )
        else:
            counts["current_manifest_matches"] += 1
        validation_path = base.parent / "validation.json"
        validation = None
        validation_sha = None
        if validation_path.is_file():
            try:
                validation, validation_sha = _read_json(validation_path)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                _issue(
                    issues,
                    "candidate-validation-unreadable",
                    str(validation_path),
                    str(exc),
                )
        else:
            _issue(
                issues,
                "candidate-validation-missing",
                str(validation_path),
                "no recorded validation sidecar",
            )
        recorded_pass = bool(
            manifest_current
            and
            validation
            and validation.get("status") == "pass"
            and validation.get("candidate_sha256") == digest
            and validation.get("source_manifest_sha256") == current["sha256"]
        )
        if validation is not None and not recorded_pass:
            _issue(
                issues,
                "candidate-validation-not-matching-pass",
                str(validation_path),
                "status or exact candidate/source binding differs",
            )
        if recorded_pass:
            counts["recorded_validation_passes"] += 1
        entry = dict(
            package_manifest=str(path),
            package_sha256=digest,
            source_manifest=source_path,
            source_manifest_sha256=binding.get("sha256"),
            current_source_manifest_sha256=current["sha256"],
            source_binding="current" if manifest_current else "stale",
            recorded_validation="matching-pass"
            if recorded_pass
            else "absent-or-not-matching-pass",
            validation_path=str(validation_path) if validation is not None else None,
            validation_sha256=validation_sha,
            claim=(
                "current-manifest-and-recorded-pass discovery only; collection routes do not prove child completeness"
                if recorded_pass
                else "source-manifest discovery only; no matching recorded validation pass and no collection-child completeness proof"
            ),
        )
        for work_id in current["work_ids"]:
            by_work[work_id].append(entry)
    return by_work, counts


def _integration_candidates(root: Path, work_id: str, issues: list[dict]) -> list[dict]:
    """Locate work-local candidate bytes without treating them as accepted TEI."""
    integration = root / "library/works" / work_id / "integration"
    if not integration.is_dir():
        return []
    found = []
    for path in sorted(integration.rglob("candidate.tei.xml")):
        if _is_link(path) or not path.is_file():
            _issue(issues, "integration-candidate-inaccessible", str(path), "linked or unreadable")
            continue
        relative = _relative(root, path)
        try:
            digest = _sha(path.read_bytes())
        except OSError as exc:
            _issue(issues, "integration-candidate-unreadable", relative, str(exc))
            continue
        validation_path = path.with_name("validation.json")
        validation = None
        if validation_path.is_file():
            try:
                validation, _ = _read_json(validation_path)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                _issue(issues, "integration-validation-unreadable", _relative(root, validation_path), str(exc))
        candidate = validation.get("candidate") if validation else None
        identity = validation.get("identity") if validation else None
        bound = bool(
            validation
            and validation.get("status") == "pass"
            and isinstance(identity, dict)
            and identity.get("work_id") == work_id
            and isinstance(candidate, dict)
            and candidate.get("path") == relative
            and candidate.get("sha256") == digest
        )
        found.append(dict(
            path=relative,
            sha256=digest,
            validation_path=_relative(root, validation_path) if validation else None,
            evidence="matching-local-validation" if bound else "candidate-file-only-or-unmatched-validation",
            claim="work-local discovery only; source and completeness require separate assessment",
        ))
    return found


def _accepted_editions(root: Path, work_id: str, editions: list[dict], issues: list[dict]) -> list[dict]:
    """Confirm installed master bytes against their edition acceptance sidecars."""
    accepted = []
    for edition in editions:
        if not edition["master_exists"] and not edition["acceptance_exists"]:
            continue
        acceptance_path = root / edition["acceptance_path"]
        master_path = root / edition["master_path"]
        if not (edition["master_exists"] and edition["acceptance_exists"]):
            _issue(issues, "installed-master-pair-incomplete", edition["master_path"], work_id)
            continue
        try:
            acceptance, acceptance_sha = _read_json(acceptance_path)
            master_sha = _sha(io_path(master_path).read_bytes())
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            _issue(issues, "installed-master-pair-unreadable", edition["master_path"], str(exc))
            continue
        promotion = acceptance.get("promotion")
        identity = acceptance.get("identity")
        decision = acceptance.get("decision")
        if not all(isinstance(item, dict) for item in (promotion, identity, decision)):
            _issue(issues, "installed-master-binding-mismatch", edition["acceptance_path"], work_id)
            continue
        promoted = promotion.get("master")
        assessment = decision.get("agent_assessment")
        if not (
            acceptance.get("contract") == "ocd-tei-acceptance-v1"
            and isinstance(promoted, dict)
            and isinstance(assessment, dict)
            and assessment.get("status") == "accepted"
            and identity.get("work_id") == work_id
            and identity.get("textual_form_id") == edition["textual_form_id"]
            and identity.get("edition_id") == edition["edition_id"]
            and promoted.get("path") == edition["master_path"]
            and promoted.get("sha256") == master_sha
            and promotion.get("status") == "promoted"
        ):
            _issue(issues, "installed-master-binding-mismatch", edition["acceptance_path"], work_id)
            continue
        accepted.append(dict(
            edition_id=edition["edition_id"],
            master_path=edition["master_path"],
            master_sha256=master_sha,
            acceptance_path=edition["acceptance_path"],
            acceptance_sha256=acceptance_sha,
            claim="recorded installed-master binding; full acceptance validation is separate",
        ))
    return accepted


def _ir_discovery(root: Path, issues: list[dict]) -> list[dict]:
    """Inventory repository-local TEI without guessing work identity from names."""
    result = []
    for path in sorted((root / "ir").rglob("*.tei.xml")):
        relative = _relative(root, path)
        if _is_link(path):
            _issue(issues, "ir-tei-inaccessible", relative, "linked file")
            continue
        try:
            size = io_path(path).stat().st_size
        except OSError as exc:
            _issue(issues, "ir-tei-inaccessible", relative, str(exc))
            continue
        result.append(dict(
            path=relative,
            bytes=size,
            association="unbound; filename and TEI title do not establish canonical work identity",
        ))
    return result


def _inspected_tei_index(
    root: Path, candidate_root: Path | None, works: set[str], issues: list[dict]
) -> dict[str, list[dict]]:
    """Join named inspection receipts by exact work ID and present TEI bytes.

    This is candidate discovery, not a current validation or acceptance claim.
    The receipts supply work identity where package manifests lack a direct
    per-work source-manifest association.
    """
    by_work: dict[str, list[dict]] = defaultdict(list)
    if candidate_root is None or not candidate_root.is_dir():
        return by_work
    allowed_root = candidate_root.resolve()
    for relative in INSPECTED_TEI_RECEIPTS:
        receipt_path = root / relative
        if not io_path(receipt_path).is_file():
            continue
        try:
            receipt, receipt_sha = _read_json(receipt_path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            _issue(issues, "inspected-tei-receipt-unreadable", relative.as_posix(), str(exc))
            continue
        rows = receipt.get("works")
        if not isinstance(rows, list):
            _issue(issues, "inspected-tei-receipt-invalid", relative.as_posix(), "works is not a list")
            continue
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("work_id"), str):
                _issue(issues, "inspected-tei-receipt-invalid", relative.as_posix(), "work identity is missing")
                continue
            work_id = row["work_id"]
            if work_id not in works:
                _issue(issues, "inspected-tei-work-not-canonical", relative.as_posix(), work_id)
                continue
            candidate_dir = row.get("candidate_root")
            expected_sha = row.get("candidate_tei_sha256")
            if not isinstance(candidate_dir, str) or not isinstance(expected_sha, str):
                _issue(issues, "inspected-tei-binding-invalid", relative.as_posix(), work_id)
                continue
            candidate_dir_path = Path(candidate_dir)
            try:
                resolved_dir = candidate_dir_path.resolve(strict=True)
                resolved_dir.relative_to(allowed_root)
                tei_path = resolved_dir / "package/content.tei.xml"
                if _is_link(tei_path) or _sha(io_path(tei_path).read_bytes()) != expected_sha:
                    raise ValueError("candidate TEI differs from the receipt")
            except (OSError, RuntimeError, ValueError) as exc:
                _issue(issues, "inspected-tei-binding-invalid", relative.as_posix(), f"{work_id}: {exc}")
                continue
            by_work[work_id].append(dict(
                receipt_path=relative.as_posix(),
                receipt_sha256=receipt_sha,
                candidate_tei_path=str(tei_path),
                candidate_tei_sha256=expected_sha,
                claim="exact receipt-bound TEI present; current source, fidelity, and acceptance require separate checks",
            ))
    return by_work


def build_report(root: Path, *, candidate_root: Path | None = None) -> dict:
    root = root.resolve(strict=True)
    issues: list[dict] = []
    rows: dict[str, dict] = {}
    for path in sorted((root / "library/works").glob("*/work.json")):
        relative = _relative(root, path)
        try:
            work = load_work(path)
            digest = _sha(path.read_bytes())
        except (OSError, UnicodeError, json.JSONDecodeError, PipelineError) as exc:
            _issue(issues, "work-invalid", relative, str(exc))
            continue
        work_id = work["work_id"]
        if path.parent.name != work_id or work_id in rows:
            _issue(issues, "work-path-identity-mismatch", relative, work_id)
            continue
        editions = []
        for form in work["textual_forms"]:
            for edition in form["editions"]:
                base = (
                    path.parent
                    / "forms"
                    / form["textual_form_id"]
                    / "editions"
                    / edition["edition_id"]
                )
                master = base / "master.tei.xml"
                acceptance = base / "acceptance.json"
                editions.append(
                    dict(
                        edition_id=edition["edition_id"],
                        textual_form_id=form["textual_form_id"],
                        master_path=_relative(root, master),
                        master_exists=io_path(master).is_file(),
                        acceptance_path=_relative(root, acceptance),
                        acceptance_exists=io_path(acceptance).is_file(),
                    )
                )
        raw = []
        for ref in sorted(set(work.get("evidence", []))):
            if not ref.startswith("raw/"):
                continue
            file_path, _, locator = ref.partition("#")
            target = root / file_path
            exists = target.is_file()
            raw.append(
                dict(
                    reference=ref,
                    file_path=file_path,
                    locator=locator or None,
                    file_exists=exists,
                    locator_checked=False,
                )
            )
            if not exists:
                _issue(issues, "raw-evidence-missing", relative, file_path)
        rows[work_id] = dict(
            work_id=work_id,
            title=work["title"],
            work_path=relative,
            work_sha256=digest,
            editions=sorted(editions, key=lambda e: e["edition_id"]),
            direct_raw_evidence=raw,
        )
    tickets = _ticket_index(root, issues)
    manifest_by_work, manifests = _manifest_index(root, set(rows), issues)
    candidates, candidate_counts = _candidate_index(candidate_root, manifests, issues)
    inspected_tei = _inspected_tei_index(root, candidate_root, set(rows), issues)
    for work_id, row in rows.items():
        row["tickets"] = sorted(tickets.get(work_id, []), key=lambda t: t["path"])
        row["source_manifests"] = sorted(
            manifest_by_work.get(work_id, []), key=lambda m: m["path"]
        )
        row["candidate_discovery"] = sorted(
            candidates.get(work_id, []), key=lambda c: c["package_manifest"]
        )
        row["integration_candidate_discovery"] = _integration_candidates(
            root, work_id, issues
        )
        row["inspected_tei_receipts"] = sorted(
            inspected_tei.get(work_id, []), key=lambda item: item["receipt_path"]
        )
        row["accepted_master_bindings"] = _accepted_editions(
            root, work_id, row["editions"], issues
        )
        ocr = any(ticket["ocr_excluded"] for ticket in row["tickets"])
        row["handoff_group"] = (
            "ocr-outside-publishing-scope"
            if ocr
            else "declared-edition"
            if row["editions"]
            else "explicit-source-manifest"
            if row["source_manifests"]
            else "direct-raw-evidence"
            if row["direct_raw_evidence"]
            else "lookup"
        )
        if ocr:
            row["reconciliation"] = "ocr-outside-publishing-scope"
        elif row["accepted_master_bindings"]:
            row["reconciliation"] = "recorded-accepted-master"
        elif any(c["recorded_validation"] == "matching-pass" for c in row["candidate_discovery"]):
            row["reconciliation"] = "current-source-bound-candidate"
        elif any(
            issue["kind"].startswith("installed-master-")
            and issue["path"].startswith(f"library/works/{work_id}/")
            for issue in issues
        ):
            row["reconciliation"] = "installed-master-evidence-mismatch"
        elif row["candidate_discovery"] or row["integration_candidate_discovery"]:
            row["reconciliation"] = "stale-or-partial-candidate-evidence"
        elif row["inspected_tei_receipts"]:
            row["reconciliation"] = "inspected-receipt-bound-tei"
        elif candidate_root is None or any(
            issue["kind"] in {"candidate-root-inaccessible", "candidate-directory-unreadable"}
            for issue in issues
        ):
            row["reconciliation"] = "candidate-search-incomplete"
        else:
            row["reconciliation"] = "no-work-bound-candidate-in-scanned-locations"
    ordered = [rows[key] for key in sorted(rows)]
    groups = {
        name: sum(row["handoff_group"] == name for row in ordered)
        for name in (
            "ocr-outside-publishing-scope",
            "declared-edition",
            "explicit-source-manifest",
            "direct-raw-evidence",
            "lookup",
        )
    }
    reconciliation = dict(Counter(row["reconciliation"] for row in ordered))
    candidate_counts["current_manifest_work_ids"] = sum(
        any(candidate["source_binding"] == "current" for candidate in row["candidate_discovery"])
        for row in ordered
    )
    candidate_counts["recorded_validation_pass_work_ids"] = sum(
        any(
            candidate["recorded_validation"] == "matching-pass"
            for candidate in row["candidate_discovery"]
        )
        for row in ordered
    )
    direct = [row for row in ordered if row["handoff_group"] == "direct-raw-evidence"]
    direct_files = {
        ref["file_path"]: ref["file_exists"]
        for row in direct
        for ref in row["direct_raw_evidence"]
    }
    ir_tei = _ir_discovery(root, issues)
    return dict(
        contract="ocd-read-only-library-handoff-inventory-v1",
        authority="Generated discovery report; work, state, acquisition, accepted TEI, and source manifests retain authority.",
        searched_locations=[
            "library/works/*/forms/*/editions/*/{acceptance.json,master.tei.xml}",
            "library/works/*/integration/**/candidate.tei.xml",
            "ir/**/*.tei.xml (unassociated inventory)",
            "four named openMGH inspected batch receipts, when present",
            str(candidate_root) if candidate_root is not None else "external candidate root: not supplied",
        ],
        search_limits="External package discovery requires an explicit root. IR TEI is not assigned to a work without a canonical identity binding. Inspected TEI receipts identify existing per-work files but do not establish current source validation or acceptance. Candidate absence means no work-bound candidate in these searched locations only; ticket and state labels are not candidate proof.",
        counts=dict(
            works=len(ordered),
            groups=groups,
            reconciliation=reconciliation,
            source_manifests=len(manifests),
            direct_raw_references=sum(
                len(row["direct_raw_evidence"]) for row in ordered
            ),
            direct_raw_unique_files=len(direct_files),
            direct_raw_missing_files=sum(
                not exists for exists in direct_files.values()
            ),
            candidate_discovery=candidate_counts,
            unassociated_ir_tei=len(ir_tei),
            issues=len(issues),
        ),
        works=ordered,
        unassociated_ir_tei=ir_tei,
        issues=sorted(issues, key=lambda i: (i["kind"], i["path"], i["detail"])),
    )


def render_markdown(report: dict) -> str:
    counts = report["counts"]
    lines = [
        "# Library handoff inventory",
        "",
        report["authority"],
        "",
        "Searched locations: " + "; ".join(report["searched_locations"]),
        report["search_limits"],
        "",
        f"Canonical works: {counts['works']}; source manifests: {counts['source_manifests']}.",
        f"Candidate discovery: {counts['candidate_discovery']['current_manifest_work_ids']} works match a current manifest; "
        f"{counts['candidate_discovery']['recorded_validation_pass_work_ids']} works have a matching recorded validation pass.",
        "Reconciliation is limited to canonical edition pairs, the selected external candidate root, and work-local integration candidates. An absent match is not proof that no candidate exists elsewhere.",
        "",
        "| Reconciliation | Works |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {number} |" for name, number in sorted(counts["reconciliation"].items()))
    lines.extend([
        "",
        "| Handoff group | Works |",
        "|---|---:|",
    ])
    lines.extend(f"| {name} | {number} |" for name, number in counts["groups"].items())
    lines.extend(
        [
            "",
            "Candidate matches mean current source-manifest path and hash only. A recorded pass is counted separately. Neither establishes fidelity, acceptance, or collection-child completeness.",
            "",
            "| Work | Reconciliation | Group | Accepted masters | Editions | Explicit manifests | Direct raw | Current manifest candidates | Recorded passes | Local candidates | Inspected TEI receipts |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report["works"]:
        lines.append(
            f"| {row['work_id']} | {row['reconciliation']} | {row['handoff_group']} | {len(row['accepted_master_bindings'])} | {len(row['editions'])} | "
            f"{len(row['source_manifests'])} | {len(row['direct_raw_evidence'])} | {sum(candidate['source_binding'] == 'current' for candidate in row['candidate_discovery'])} | "
            f"{sum(candidate['recorded_validation'] == 'matching-pass' for candidate in row['candidate_discovery'])} | {len(row['integration_candidate_discovery'])} | {len(row['inspected_tei_receipts'])} |"
        )
    notes = Counter(issue["kind"] for issue in report["issues"])
    lines.extend(
        [
            "",
            "## Discovery notes (not failed works)",
            "",
            f"{counts['issues']} notes are retained individually in the JSON report. "
            "Old or external candidate packages are reconciliation evidence, not new reconstruction defects.",
            "",
            "| Note type | Count |",
            "|---|---:|",
        ]
    )
    lines.extend(f"| {kind} | {number} |" for kind, number in sorted(notes.items()))
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidate-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args(argv)
    report = build_report(args.root, candidate_root=args.candidate_root)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    if args.markdown:
        args.markdown.write_text(
            render_markdown(report), encoding="utf-8", newline="\n"
        )
    if not args.output and not args.markdown:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
