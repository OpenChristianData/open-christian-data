"""Prepare a frozen Brenton Septuagint acceptance/install handoff.

The selected staging root is self-contained.  This command does not promote a
master, install a work, change canonical lifecycle state, or decide rights.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, io_glob, io_path
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from build.tei.brenton_septuagint import write_candidate
from build.tei.brenton_septuagint_oracle import verify as oracle_verify


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/brenton-septuagint")
EDITION = WORK / "forms/brenton-septuagint-retained-en/editions/brenton-septuagint-electronic"
ACQUISITION = EDITION / "acquisitions/brenton-septuagint-acquired.json"
MEMBER_SET = EDITION / "source-member-set.json"
CONFIG = Path("sources/structured-text/brenton-septuagint/config.json")
RAW = Path("raw/clean-ready-acquisition-to-tei/master-3/21/brenton-septuagint")
REBIND = Path("reports/clean-ready-acquisition-to-tei/master-3/21/brenton-septuagint/source-rebind-20260930")
PREDECESSOR = Path("reports/clean-ready-acquisition-to-tei/master-3/21/brenton-septuagint/acceptance-handoff-20260930-v2")
PREDECESSOR_RECEIPT_SHA = "9b8d5cd55d484aa9302a822a6b8e18a6647549c5be4e64ce6fba093ce16f1500"
PREDECESSOR_ACCEPTANCE_SHA = "7fe5410671d0bc30b7adbccf35ed8e75f55a8e3fa05baa176e1541c82ee4ad5a"
PREDECESSOR_CANDIDATE_SHA = "605ab2a5f30dab1689fc7f560d44574d3f217c32270a1ba697f5a1fe75f49437"
IDENTITY = {
    "work_id": "brenton-septuagint",
    "textual_form_id": "brenton-septuagint-retained-en",
    "edition_id": "brenton-septuagint-electronic",
    "acquisition_id": "brenton-septuagint-acquired",
}
ORIGINAL_SHA = "a858ba5423a0c72407763c005a1848906955a06d1cdf695912dc17c186c3306f"
SCOPE = "Complete corrected eBible eng-Brenton 60-member electronic USFM edition; no claim to independent historical-print collation."
REVISION = {
    "id": "brenton-electronic-whole-work-v1",
    "date": "2026-09-30",
    "note": "Acceptance identity and corrected retained-member-set bindings added; all bytes after the original teiHeader are unchanged.",
}
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")
BOUND_ANA = b'ana="#nonaccepted-candidate"'
PREDECESSOR_ANA = b'ana="#technical-acceptance-candidate"'
NEUTRAL_ANA = b'ana="#retained-source-representation"'
BOUND_PUBLISHER = b"Open Christian Data nonaccepted ticket-21 candidate; not publication."
PREDECESSOR_PUBLISHER = b"Open Christian Data technical acceptance candidate pending review; not publication."
NEUTRAL_PUBLISHER = b"Open Christian Data TEI representation of the retained eBible source; not publication."


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write(path: Path, value: object) -> None:
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    io_path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _copy_file(root: Path, stage: Path, relative: Path) -> None:
    source = resolve_repo_path(root, relative.as_posix())
    target = stage / relative
    if io_path(target).exists():
        if io_path(target).read_bytes() != io_path(source).read_bytes():
            raise PipelineError(f"conflicting staged evidence: {relative}")
        return
    io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(io_path(source), io_path(target))


def _copy_declared_evidence(root: Path, stage: Path) -> None:
    for sidecar in (WORK / "work.json", WORK / "state.json"):
        document = json.loads((root / sidecar).read_bytes())
        queues = [document.get("evidence", [])]
        queues.extend(target.get("evidence", []) for target in document.get("targets", []))
        for values in queues:
            for reference in values:
                if not isinstance(reference, str):
                    raise PipelineError(f"non-string Brenton evidence reference in {sidecar}")
                relative = Path(reference.split("#", 1)[0])
                _copy_file(root, stage, relative)


def _package_inventory(package: Path) -> list[dict[str, object]]:
    return [
        {"name": path.name, "bytes": path.stat().st_size, "sha256": _sha(path.read_bytes())}
        for path in sorted(package.iterdir())
        if path.is_file()
    ]


def _source_notice(config: dict) -> str:
    return f"""# Source notice - Brenton Septuagint

This work-local notice accompanies the retained electronic edition of **The
Septuagint Version of the Old Testament**, translated into English by **Sir
Lancelot Charles Lee Brenton**.

The transformation authority is the corrected `eng-Brenton` electronic USFM
edition retained from eBible.org: {config['source_url']}

The currently retained eBible source and details pages identify this Brenton
edition as **Public Domain**. That provider statement is preserved as source
evidence. Open Christian Data has not used this notice to decide release
eligibility, applicable law, territory-specific status, or publication.

The retained eBible PDF is a generated rendering witness. It is not an
independent historical print scan and is not the transformation authority.
"""


def _correct_status_assertions(bound: bytes, predecessor: bytes) -> bytes:
    """Correct exactly two current-status assertions in the bound TEI.

    The earlier revision statement remains historical: it accurately records
    that the source-derived package began as a nonaccepted candidate.
    """
    expected_predecessor = bound.replace(BOUND_ANA, PREDECESSOR_ANA, 1).replace(
        BOUND_PUBLISHER, PREDECESSOR_PUBLISHER, 1
    )
    if _sha(predecessor) != PREDECESSOR_CANDIDATE_SHA or expected_predecessor != predecessor:
        raise PipelineError("Brenton predecessor candidate is not the exact held generation")
    if predecessor.count(PREDECESSOR_ANA) != 1 or predecessor.count(PREDECESSOR_PUBLISHER) != 1:
        raise PipelineError("Brenton predecessor lacks the two expected workflow-status assertions")
    if NEUTRAL_ANA in predecessor or NEUTRAL_PUBLISHER in predecessor:
        raise PipelineError("Brenton predecessor already contains status-neutral assertions")
    corrected = predecessor.replace(PREDECESSOR_ANA, NEUTRAL_ANA, 1).replace(
        PREDECESSOR_PUBLISHER, NEUTRAL_PUBLISHER, 1
    )
    restored = corrected.replace(NEUTRAL_ANA, PREDECESSOR_ANA, 1).replace(
        NEUTRAL_PUBLISHER, PREDECESSOR_PUBLISHER, 1
    )
    if restored != predecessor or corrected.count(b"nonaccepted") != 1:
        raise PipelineError("Brenton status correction changed bytes beyond the two assertions")
    if corrected.split(b"</teiHeader>", 1)[1] != predecessor.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Brenton status correction changed source-derived TEI content")
    return corrected


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = stage.resolve(strict=False)
    if stage.exists() or stage == root or stage in root.parents or root in stage.parents:
        raise PipelineError("Brenton staging root must be fresh and outside the repository")
    if not stage.parent.is_dir():
        raise PipelineError("Brenton staging parent must exist")

    acquisition = json.loads((root / ACQUISITION).read_bytes())
    members = acquisition["retained_files"]
    if (
        acquisition.get("source_kind") != "retained-member-set"
        or acquisition.get("source_sha256") != _sha((root / MEMBER_SET).read_bytes())
        or acquisition.get("source_bytes") != (root / MEMBER_SET).stat().st_size
        or len(members) != 60
    ):
        raise PipelineError("Brenton acquisition is not the corrected 60-member set")
    numeric = [int(Path(item["path"]).name.split("-", 1)[0]) for item in members]
    if numeric != sorted(numeric):
        raise PipelineError("Brenton retained members are not in numeric source order")

    stage.mkdir()
    shutil.copytree(io_path(root / WORK), io_path(stage / WORK))
    shutil.copytree(io_path(resolve_repo_path(root, RAW.as_posix())), io_path(stage / RAW))
    _copy_file(root, stage, CONFIG)
    _copy_declared_evidence(root, stage)

    evidence = stage / WORK / "integration/brenton-electronic-whole-work-v1"
    original_package = evidence / "original-package"
    write_candidate(stage, original_package)
    original = (original_package / "content.tei.xml").read_bytes()
    if _sha(original) != ORIGINAL_SHA:
        raise PipelineError("fresh Brenton candidate differs from the reviewed route")
    original_validation = json.loads((original_package / "validation.json").read_bytes())
    if original_validation.get("status") != "pass":
        raise PipelineError("fresh Brenton candidate validation did not pass")
    oracle = oracle_verify(stage, original_package / "content.tei.xml")

    reproduced_package = evidence / "reproduced-package"
    command = [
        sys.executable,
        "-m",
        "build.tei.brenton_septuagint",
        "--repository-root",
        str(stage),
        "--output-relative",
        "reports/clean-ready-acquisition-to-tei/master-3/21/brenton-septuagint/reproduced-package",
    ]
    worker = subprocess.run(command, cwd=root, check=True, capture_output=True, text=True)
    generated = stage / "reports/clean-ready-acquisition-to-tei/master-3/21/brenton-septuagint/reproduced-package"
    shutil.move(str(generated), reproduced_package)
    original_inventory = _package_inventory(original_package)
    reproduced_inventory = _package_inventory(reproduced_package)
    if original_inventory != reproduced_inventory:
        raise PipelineError("Brenton package did not reproduce byte for byte in a second process")

    source = {
        key: acquisition[key]
        for key in ("source_path", "source_sha256", "source_bytes", "source_scope", "source_kind")
    }
    args = {
        "expected_sha256": ORIGINAL_SHA,
        "identity": IDENTITY,
        "source": source,
        "source_url": acquisition["url"],
        "declared_scope": SCOPE,
        "revision": REVISION,
    }
    bound = bind_reviewed_header(original, **args)
    predecessor_candidate_path = resolve_repo_path(
        root,
        (PREDECESSOR / WORK / "integration/brenton-electronic-whole-work-v1/candidate.tei.xml").as_posix(),
    )
    predecessor_candidate = io_path(predecessor_candidate_path).read_bytes()
    derived = _correct_status_assertions(bound, predecessor_candidate)
    if original.split(b"</teiHeader>", 1)[1] != derived.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Brenton header derivation altered tei:text bytes")
    candidate = evidence / "candidate.tei.xml"
    candidate.write_bytes(derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived Brenton TEI failed vendored XSD: {errors}")
    derived_oracle = oracle_verify(stage, candidate)
    if derived_oracle != oracle:
        raise PipelineError("header binding changed independent-oracle results")

    notice = stage / WORK / "SOURCE_NOTICE.md"
    config = json.loads((stage / CONFIG).read_bytes())
    notice.write_text(_source_notice(config), encoding="utf-8", newline="\n")
    inputs = evidence / "inputs"
    inputs.mkdir()
    for relative in (REBIND / "manifest.json", REBIND / "apply-receipt.json"):
        target = inputs / relative.name
        target.write_bytes(resolve_repo_path(root, relative.as_posix()).read_bytes())
    predecessor_files = {
        "held-predecessor-receipt.json": (PREDECESSOR / "BRENTON_HANDOFF_RECEIPT.json", PREDECESSOR_RECEIPT_SHA),
        "held-predecessor-acceptance.json": (PREDECESSOR / EDITION / "acceptance.json", PREDECESSOR_ACCEPTANCE_SHA),
        "held-predecessor-candidate.tei.xml": (
            PREDECESSOR / WORK / "integration/brenton-electronic-whole-work-v1/candidate.tei.xml",
            PREDECESSOR_CANDIDATE_SHA,
        ),
    }
    for name, (relative, expected_sha) in predecessor_files.items():
        content = io_path(resolve_repo_path(root, relative.as_posix())).read_bytes()
        if _sha(content) != expected_sha:
            raise PipelineError(f"held Brenton predecessor changed: {relative}")
        io_path(inputs / name).write_bytes(content)
    _write(inputs / "predecessor-hold.json", {
        "contract": "ocd-brenton-acceptance-predecessor-hold-v1",
        "status": "held-no-accept-promote-install",
        "reason": "The TEI embeds mutable technical-acceptance and pending-review workflow status.",
        "receipt": make_file_binding(stage, inputs / "held-predecessor-receipt.json"),
        "acceptance": make_file_binding(stage, inputs / "held-predecessor-acceptance.json"),
        "candidate": make_file_binding(stage, inputs / "held-predecessor-candidate.tei.xml"),
    })

    expected = [
        {"path": item["path"], "position": position}
        for position, item in enumerate(members, start=1)
    ]
    included = [
        {key: item[key] for key in ("path", "bytes", "sha256", "scope")}
        | {"position": position}
        for position, item in enumerate(members, start=1)
    ]
    scope = {
        "kind": "edition",
        "declared": SCOPE,
        "expected_members": expected,
        "included_members": included,
        "excluded_members": [],
    }
    candidate_binding = make_file_binding(stage, candidate)
    common = {
        "identity": IDENTITY,
        "source": source,
        "candidate": candidate_binding,
        "scope": SCOPE,
        "accepted_scope": {"kind": "edition", "declared": SCOPE},
        "expected_members": expected,
        "included_members": included,
        "excluded_members": [],
        "missing_members": [],
        "unknown_members": [],
    }
    accounting = evidence / "source-accounting.json"
    _write(accounting, common | {
        "scope": source["source_scope"],
        "source_sha256": source["source_sha256"],
        "source_bytes": source["source_bytes"],
        "details": {
            "numeric_prefixes": numeric,
            "member_count": len(members),
            "rebind_manifest": make_file_binding(stage, inputs / "manifest.json"),
            "rebind_apply_receipt": make_file_binding(stage, inputs / "apply-receipt.json"),
        },
    })
    command_text = "py -3 -m build.tools.prepare_brenton_septuagint_acceptance --stage <fresh-external-root>"
    details = {
        "validation": {"historical_validation_status": "pass", "oracle": oracle},
        "accounting": {"expected": 60, "included": 60, "excluded": 0, "missing": 0, "unknown": 0},
        "fidelity": {
            "original_candidate_sha256": ORIGINAL_SHA,
            "held_predecessor_candidate_sha256": PREDECESSOR_CANDIDATE_SHA,
            "original_text_sha256": _sha(original.split(b"</teiHeader>", 1)[1]),
            "derived_text_sha256": _sha(derived.split(b"</teiHeader>", 1)[1]),
            "status_corrections": [
                {"before": PREDECESSOR_ANA.decode("ascii"), "after": NEUTRAL_ANA.decode("ascii")},
                {"before": PREDECESSOR_PUBLISHER.decode("ascii"), "after": NEUTRAL_PUBLISHER.decode("ascii")},
            ],
            "independent_oracle": derived_oracle,
        },
        "reproducibility": {
            "original_package": original_inventory,
            "reproduced_package": reproduced_inventory,
            "second_process_stdout": worker.stdout.strip(),
        },
        "schema": {"vendored_xsd": "ocd_kernel/tei/vendor/xsd/tei_all.xsd", "validation_errors": []},
        "closure": {
            "source_member_set_sha256": source["source_sha256"],
            "candidate_sha256": candidate_binding["sha256"],
            "source_notice": make_file_binding(stage, notice),
            "rights_disposition": "unassessed-separate-from-technical-acceptance",
        },
    }
    technical: dict[str, object] = {
        "producer": {"id": "build.tei.brenton_septuagint"},
        "checker": {"id": "build.tei.brenton_septuagint_oracle"},
        "shared_assumptions": [
            "Producer and checker share the retained USFM bytes, corrected member-set declaration, TEI vocabulary, and lxml XML parser.",
        ],
        "independent_corroboration": "Independent source traversal and readable-TEI oracle; exact raw-line conservation; USFX census; vendored P5 validation; second-process eight-file byte reproduction.",
    }
    for name in PROOFS:
        path = evidence / f"{name}.json"
        _write(path, common | {"status": "pass", "command": command_text, "exit_code": 0, "details": details[name]})
        technical[name] = {"path": path, "status": "pass", "command": command_text, "exit_code": 0}

    reviewed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    coverage = {
        "status": "partial",
        "declared": SCOPE,
        "reached": ["electronic-witness/mechanical"],
        "inspected": ["electronic-witness/mechanical/whole-work"],
        "unreviewed": ["electronic-witness/visual/current-cvw"],
    }
    uncertainty = ["No independent historical print scan was retained or collated against the electronic edition."]
    residuals = ["Current human pixel-level visual comparison in CVW is unperformed and remains separate from agent technical acceptance."]
    review_document = common | {
        "reviewer": "agent:brenton-whole-work-technical-review",
        "reviewed_at": reviewed_at,
        "coverage": coverage,
        "source_quality_uncertainty": uncertainty,
        "discrepancies": [],
        "unreviewed_residuals": residuals,
        "review_basis": "Complete machine-readable source/accounting/fidelity inspection; no human visual-review credit claimed.",
    }
    review_path = evidence / "review.json"
    _write(review_path, review_document)
    decision = {
        "source_local_disposition": "Technical acceptance evidence is complete for the corrected Brenton electronic USFM edition; the acceptance decision remains pending parent review, while visual review, rights clearance, release, and publication remain separate.",
        "blockers": [],
        "agent_assessment": {
            "status": "unassessed",
            "actor": "agent:brenton-whole-work-technical-review",
            "assessed_at": reviewed_at,
            "supported_scope": SCOPE,
            "unassessed_stronger_claims": [
                "human visual acceptance",
                "historical print completeness",
                "rights clearance under applicable law",
                "release or publication authorization",
            ],
            "unresolved_claims": ["Technical acceptance decision pending parent review of the frozen bundle."],
        },
        "human_decision": {"status": "not-recorded"},
    }
    review = {
        "report_path": review_path,
        "reviewer": review_document["reviewer"],
        "reviewed_at": reviewed_at,
        "coverage": coverage,
        "source_quality_uncertainty": uncertainty,
        "discrepancies": [],
        "unreviewed_residuals": residuals,
    }
    record = build_acceptance_record(
        stage,
        identity=IDENTITY,
        candidate_path=candidate,
        source_accounting_path=accounting,
        scope=scope,
        technical=technical,
        review=review,
        representation_revision=REVISION,
        decision=decision,
    )
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)

    canonical_hashes = {
        path.relative_to(root / WORK).as_posix(): _sha(io_path(path).read_bytes())
        for path in sorted(io_glob(root / WORK, "**/*"))
        if io_path(path).is_file()
    }
    staged_hashes = {
        path.relative_to(stage / WORK).as_posix(): _sha(io_path(path).read_bytes())
        for path in sorted(io_glob(stage / WORK, "**/*"))
        if io_path(path).is_file()
    }
    receipt = {
        "contract": "ocd-brenton-frozen-acceptance-install-handoff-v3",
        "status": "frozen-pending-parent-review",
        "identity": IDENTITY,
        "predecessor": {
            "status": "held-no-accept-promote-install",
            "root": PREDECESSOR.as_posix(),
            "receipt_sha256": PREDECESSOR_RECEIPT_SHA,
            "acceptance_sha256": PREDECESSOR_ACCEPTANCE_SHA,
            "candidate_sha256": PREDECESSOR_CANDIDATE_SHA,
            "hold": make_file_binding(stage, inputs / "predecessor-hold.json"),
        },
        "canonical_before": canonical_hashes,
        "staged_work": staged_hashes,
        "candidate": make_file_binding(stage, candidate),
        "acceptance": make_file_binding(stage, acceptance),
        "source_notice": make_file_binding(stage, notice),
        "promotion_performed": False,
        "installation_performed": False,
        "next_actions": [
            "Parent reviews this exact frozen bundle.",
            "After explicit review, record the acceptance decision in a newly frozen successor bundle.",
            "After that accepted record validates, promote_accepted_master into a fresh reviewed root.",
            "After promotion validation, serialize install_accepted_work for brenton-septuagint.",
            "Verify the installed work and keep rights, release, publication, and human visual review separate.",
        ],
    }
    _write(stage / "BR﻿ENTON_HANDOFF_RECEIPT.json".replace("﻿", ""), receipt)
    return acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(ROOT, args.stage))


if __name__ == "__main__":
    main()
