"""Stage a bounded acceptance of Robertson's two retained CCEL XML components.

The existing per-file acquisitions remain separate.  A third acquisition binds
their ordered source set for the edition-level acceptance; it does not assert a
complete print volume, source rights, or human approval.  This command only
writes to a fresh, caller-selected staging root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from build.tei.robertson_word_pictures_vol1_oracle import validate as oracle
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.acquisitions import source_member_set_bytes, validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/robertson-word-pictures-vol1")
EDITION = WORK / (
    "forms/robertson-word-pictures-vol1-ccel-retained-en/"
    "editions/robertson-word-pictures-vol1-matthew-mark-ccel"
)
ACQUISITION_ID = "robertson-word-pictures-vol1-matthew-mark-source-set"
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
MEMBER_SET = EDITION / "source-member-set.json"
MANIFEST = Path("sources/commentaries/robertson-word-pictures-vol1/source-manifest.json")
REVIEW = Path(
    "plans/2026-08-31-sample-first-library-verification/artifacts/"
    "2026-09-08-ticket37/reviews/37c-266-cvw-review-20260918.md"
)
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-266-robertson-word-pictures-vol1.md")
EVIDENCE = WORK / "integration/ccel-matthew-mark-agent-handoff-v1"
DEFAULT_CANDIDATE = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "37c-266-robertson-word-pictures-vol1-20260918-v1"
)
MANIFEST_SHA = "8eb5e9df89be8868ab20bd4128b7379b882f17af059769f90dca6eb761ace17d"
PACKAGE_SHA = "d98d0906fd11564b143bc21d359389b57e79f20ec78f77497283b5f9ed5cfe4c"
TEI_SHA = "d2b875087b97f15195522f36371700a11acb2bdc01d9343d591d30f50f777ef7"
REPORT_SHA = "96372f6c35a7c2e93e640fd4f64a07f04fa54ba468f2411ec684d12bb6fa4a28"
SOURCES = (
    ("robertson-word-pictures-vol1-01-robertson-at-wp-matt-acquired", "matthew", "e5c904c810a4582c881e2c13486654c3e0b7eed569cb83d667a4cd1c136b62ae"),
    ("robertson-word-pictures-vol1-02-robertson-at-wp-mark-acquired", "mark", "d3666fb8e0e261776ce3b02bf072764af7c21ced0712c32161d5e6e58d9cfc52"),
)
IDENTITY = {
    "work_id": "robertson-word-pictures-vol1",
    "textual_form_id": "robertson-word-pictures-vol1-ccel-retained-en",
    "edition_id": "robertson-word-pictures-vol1-matthew-mark-ccel",
    "acquisition_id": ACQUISITION_ID,
}
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    data = io_path(path).read_bytes()
    if expected is not None and _sha(data) != expected:
        raise PipelineError(f"Robertson evidence hash mismatch: {path}")
    return data


def _copy(stage: Path, relative: Path, data: bytes) -> Path:
    path = stage / relative
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    io_path(path).write_bytes(data)
    return path


def _write(stage: Path, relative: Path, value: object) -> Path:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return _copy(stage, relative, data)


def _stage_path(root: Path, candidate: Path, stage: Path) -> Path:
    stage = stage.absolute()
    if stage.exists() or not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("Robertson acceptance stage must be fresh under an ordinary parent")
    resolved = stage.resolve()
    for protected in (root, candidate):
        if resolved == protected or protected in resolved.parents or resolved in protected.parents:
            raise PipelineError("Robertson stage overlaps an input root")
    return stage


def prepare(root: Path, candidate_root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    candidate_root = candidate_root.resolve(strict=True)
    stage = _stage_path(root, candidate_root, stage)
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    package = CandidatePackage.load(candidate_root / "package")
    if manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA:
        raise PipelineError("Robertson source manifest or package changed")
    original = package.member_bytes("content.tei.xml")
    if _sha(original) != TEI_SHA or package.manifest.get("status") != "nonaccepted":
        raise PipelineError("Robertson reviewed TEI changed")
    report = validate(manifest, package, oracle)
    if report.status != "pass" or report.findings or report.sha256 != REPORT_SHA:
        raise PipelineError("Robertson current independent oracle did not pass")
    stored = json.loads(_read(candidate_root / "validation.json"))
    if (
        stored.get("status") != "pass"
        or stored.get("candidate_sha256") != PACKAGE_SHA
        or stored.get("source_manifest_sha256") != MANIFEST_SHA
        or stored.get("report_sha256") != REPORT_SHA
    ):
        raise PipelineError("Robertson stored validation differs from current oracle")
    visual = _read(root / REVIEW)
    ticket = _read(root / TICKET)
    if (b"37c-266" not in visual or PACKAGE_SHA.encode() not in visual
            or b"six declared samples" not in visual or PACKAGE_SHA.encode() not in ticket):
        raise PipelineError("Robertson six-view report lost its selected package binding")
    # CVW's native capture records the actual TEI hash; the prose report calls
    # the package hash a TEI hash.  Keep both identities distinct in this packet.
    capture_root = Path("D:/Library/Open Christian Data/candidate-reviews/37c-266-cvw-review-20260918-v1")
    captures = []
    for name in (
        "01-matthew-title", "02-matthew-ch14", "03-matthew-index",
        "04-mark-title", "05-mark-ch8", "06-mark-index",
    ):
        content = _read(capture_root / name / "capture.json")
        capture = json.loads(content)
        comparison = _read(capture_root / name / "compare.json", capture["files"]["compare.json"])
        if TEI_SHA.encode() not in comparison or PACKAGE_SHA.encode() not in comparison or PACKAGE_SHA.encode() not in content:
            raise PipelineError(f"Robertson CVW capture lost exact TEI/package pair: {name}")
        for filename, digest in capture["files"].items():
            _read(capture_root / name / filename, digest)
        captures.append((name, _sha(content)))

    work = load_work(root / WORK / "work.json")
    old_ids = work["textual_forms"][0]["editions"][0]["acquisition_ids"]
    if old_ids != [item[0] for item in SOURCES] or io_path(root / ACQUISITION).exists():
        raise PipelineError("Robertson original acquisition declaration changed")
    retained = []
    original_records = []
    for acquisition_id, member_name, digest in SOURCES:
        old_path = root / EDITION / "acquisitions" / f"{acquisition_id}.json"
        old = json.loads(_read(old_path))
        member = old["retained_files"]
        authority = next(item for item in manifest.record["authorities"] if item["name"] == member_name)
        if (
            old["acquisition_id"] != acquisition_id
            or len(member) != 1
            or member[0]["sha256"] != digest
            or member[0]["path"] != authority["path"]
            or member[0]["bytes"] != authority["bytes"]
            or old["source_path"] != member[0]["path"]
            or old["source_sha256"] != digest
        ):
            raise PipelineError(f"Robertson original member authority changed: {member_name}")
        if _sha(_read(resolve_repo_path(root, member[0]["path"]))) != digest:
            raise PipelineError(f"Robertson retained XML changed: {member_name}")
        retained.append(member[0])
        original_records.append((old_path, old))

    scope_text = (
        "Complete assigned Matthew then Mark CCEL electronic witness, including both XML document envelopes, "
        "title pages, Matthew introduction, chapters, indexes, electronic headers, styles, and source instructions. "
        "This does not establish the complete print Vol. I, the absent general preface, or rights clearance."
    )
    composite = {
        "schema_version": "2.0", "acquisition_id": ACQUISITION_ID,
        "edition_id": IDENTITY["edition_id"], "provider": "Christian Classics Ethereal Library",
        "url": original_records[0][1]["url"], "route": "born-digital",
        "retained_files": retained, "source_kind": "retained-member-set",
        "source_path": MEMBER_SET.as_posix(), "source_scope": scope_text,
        "warnings": [
            "Coordinated acquisition binds the two separate retained CCEL XML files; the two original acquisition records and URLs remain authoritative per component.",
            f"Matthew URL: {original_records[0][1]['url']}; Mark URL: {original_records[1][1]['url']}.",
            "Bibliographic print-volume identity, CCEL rights and data-path attribution, human review, and publication remain separate.",
        ],
    }
    member_set = source_member_set_bytes(composite)
    composite["source_bytes"] = len(member_set)
    composite["source_sha256"] = _sha(member_set)
    now = datetime.now(timezone.utc)
    revision = {
        "id": "robertson-matthew-mark-electronic-v1", "date": now.date().isoformat(),
        "note": "Bind the reviewed Matthew and Mark CCEL electronic components as one ordered edition witness.",
    }
    source = {key: composite[key] for key in ("source_path", "source_sha256", "source_bytes", "source_scope", "source_kind")}
    derived = bind_reviewed_header(
        original, expected_sha256=TEI_SHA, identity=IDENTITY, source=source,
        source_url=composite["url"], declared_scope=scope_text, revision=revision,
    )
    old_status = b"Nonaccepted reconstruction; no rights or publication decision."
    new_status = b"Agent-accepted assigned electronic witness; no rights or publication decision."
    if derived.count(old_status) != 1:
        raise PipelineError("Robertson candidate publication statement changed")
    derived = derived.replace(old_status, new_status, 1)
    opening = b'<bibl xmlns="http://www.tei-c.org/ns/1.0">'
    ending = b'</bibl></sourceDesc>'
    if derived.count(opening) != 1 or derived.count(ending) != 1:
        raise PipelineError("Robertson acceptance bibl cannot be placed in the existing source description")
    derived = derived.replace(opening, b'<p xmlns="http://www.tei-c.org/ns/1.0"><bibl>', 1)
    derived = derived.replace(ending, b'</bibl></p></sourceDesc>', 1)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Robertson reviewed TEI body changed during header binding")

    shutil.copytree(io_path(root / WORK), io_path(stage / WORK))
    for relative in (MANIFEST, REVIEW, TICKET):
        _copy(stage, relative, _read(root / relative))
    for old_path, old in original_records:
        member = old["retained_files"][0]
        _copy(stage, Path(member["path"]), _read(resolve_repo_path(root, member["path"]), member["sha256"]))
    _copy(stage, MEMBER_SET, member_set)
    _write(stage, ACQUISITION, composite)
    staged_work = json.loads(_read(stage / WORK / "work.json"))
    staged_work["textual_forms"][0]["editions"][0]["acquisition_ids"].append(ACQUISITION_ID)
    for reference in (ACQUISITION.as_posix(), MEMBER_SET.as_posix()):
        if reference not in staged_work["evidence"]:
            staged_work["evidence"].append(reference)
    _write(stage, WORK / "work.json", staged_work)
    staged_state = json.loads(_read(stage / WORK / "state.json"))
    staged_state["targets"].append({
        "target_id": ACQUISITION_ID, "target_type": "acquisition", "stage": "acquired",
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "evidence": [ACQUISITION.as_posix(), MEMBER_SET.as_posix(), *[p.relative_to(root).as_posix() for p, _ in original_records]],
    })
    _write(stage, WORK / "state.json", staged_state)
    for reference in set(staged_work["evidence"] + [item for target in staged_state["targets"] for item in target["evidence"]]):
        relative = Path(reference.split("#", 1)[0])
        if (stage / relative).is_file() or (stage / WORK / relative).is_file():
            continue
        source_path = resolve_repo_path(root, reference) if relative.parts[0] in {"raw", "reports", "exports"} else root / relative
        _copy(stage, relative, _read(source_path))
    validate_acquisition(stage / ACQUISITION, root=stage)
    evidence = stage / EVIDENCE
    for name in package.member_names:
        _copy(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _copy(stage, EVIDENCE / "inputs/package/manifest.json", _read(candidate_root / "package/manifest.json", PACKAGE_SHA))
    _copy(stage, EVIDENCE / "inputs/validation.json", _read(candidate_root / "validation.json"))
    for name, _ in captures:
        capture_bytes = _read(capture_root / name / "capture.json")
        _copy(stage, EVIDENCE / "inputs/cvw" / name / "capture.json", capture_bytes)
        for filename, digest in json.loads(capture_bytes)["files"].items():
            _copy(stage, EVIDENCE / "inputs/cvw" / name / filename, _read(capture_root / name / filename, digest))
    candidate = _copy(stage, EVIDENCE / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"Robertson acceptance TEI XSD failed: {errors[:3]}")

    expected = [{"path": item["path"], "position": index} for index, item in enumerate(retained, 1)]
    included = [entry | {"bytes": item["bytes"], "sha256": item["sha256"], "scope": item["scope"]}
                for entry, item in zip(expected, retained, strict=True)]
    accepted_scope = {"kind": "edition", "declared": scope_text}
    scope = accepted_scope | {"expected_members": expected, "included_members": included, "excluded_members": []}
    common = {"identity": IDENTITY, "source": source, "candidate": make_file_binding(stage, candidate),
              "scope": scope_text, "accepted_scope": accepted_scope, "expected_members": expected,
              "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting = _write(stage, EVIDENCE / "source-accounting.json", common | {
        "source_sha256": source["source_sha256"], "source_bytes": source["source_bytes"],
        "original_acquisitions": [
            {"path": p.relative_to(root).as_posix(), "bytes": len(_read(p)), "sha256": _sha(_read(p))}
            for p, _ in original_records
        ],
        "original_urls": [old["url"] for _, old in original_records],
        "source_manifest_sha256": MANIFEST_SHA, "package_sha256": PACKAGE_SHA,
        "original_tei_sha256": TEI_SHA, "oracle_report_sha256": REPORT_SHA,
    })
    inputs = {"manifest": make_file_binding(stage, stage / MANIFEST),
              "package": make_file_binding(stage, evidence / "inputs/package/manifest.json"),
              "validation": make_file_binding(stage, evidence / "inputs/validation.json"),
              "cvw": [make_file_binding(stage, evidence / "inputs/cvw" / name / "capture.json") for name, _ in captures]}
    command = "py -3 -m build.tools.prepare_robertson_electronic_acceptance --stage <fresh-external-root>"
    descriptions = {
        "validation": "Current independent Robertson oracle passes for the exact two XML members and reviewed package.",
        "accounting": "Both complete XML document envelopes and their separate original acquisitions are included in Matthew then Mark order.",
        "fidelity": "Source-to-TEI node, text, attachment, reference, and header relationships pass the independent oracle; six exact CVW samples found no mismatch.",
        "reproducibility": "The pinned package and validation are the ticket's deterministic clean-process output; this stage changes only the acceptance header.",
        "schema": "The original package and header-derived TEI pass the vendored TEI XSD.",
        "closure": "Original acquisition URLs, two source hashes, current source manifest, candidate package, validation, and six native capture hashes are sealed.",
    }
    technical = {
        "producer": {"id": package.manifest["converter"]["id"]},
        "checker": {"id": manifest.record["validator"]["id"]},
        "shared_assumptions": ["Producer and oracle share source policy; oracle independently traverses the retained XML and TEI, with an Expat source census."],
        "independent_corroboration": "Current oracle pass, recorded mutation/reproduction tests, and six exact-pair CVW visual samples.",
    }
    for name in PROOFS:
        path = _write(stage, EVIDENCE / f"{name}.json", common | {
            "status": "pass", "command": command, "exit_code": 0,
            "description": descriptions[name], "inputs": inputs,
            "oracle_report_sha256": REPORT_SHA,
        })
        technical[name] = {"path": path, "status": "pass", "command": command, "exit_code": 0}
    coverage = {
        "status": "partial", "declared": scope_text,
        "reached": ["matthew", "mark"],
        "inspected": ["matthew/title", "matthew/chapter-14", "matthew/index", "mark/title", "mark/chapter-8", "mark/index"],
        "unreviewed": ["matthew/other-content", "mark/other-content"],
    }
    reviewed_at = now.isoformat().replace("+00:00", "Z")
    review = {
        "reviewer": "agent:robertson-electronic-witness-review", "reviewed_at": reviewed_at,
        "coverage": coverage,
        "source_quality_uncertainty": ["The CCEL files do not establish completeness or fidelity to an original print Vol. I witness."],
        "discrepancies": [],
        "unreviewed_residuals": ["Visual inspection was a declared six-view sample; the rest of both XML files was checked mechanically."],
    }
    review_path = _write(stage, EVIDENCE / "review.json", common | review | {
        "inputs": inputs, "package_sha256": PACKAGE_SHA, "original_tei_sha256": TEI_SHA,
        "clarification": "The historical prose report calls the package digest the content.tei.xml digest; native CVW captures bind the actual TEI digest.",
        "unassessed": ["complete print Vol. I identity", "general preface outside the two XML files", "human acceptance", "rights clearance", "publication"],
    })
    decision = {
        "source_local_disposition": "Agent acceptance of the complete assigned Matthew then Mark CCEL electronic witness only.",
        "blockers": [],
        "agent_assessment": {
            "status": "accepted", "actor": review["reviewer"], "assessed_at": reviewed_at,
            "supported_scope": scope_text, "unresolved_claims": [],
            "unassessed_stronger_claims": ["complete print Vol. I identity", "absent general preface", "exhaustive proofreading", "human textual acceptance", "rights clearance", "publication"],
        },
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(
        stage, identity=IDENTITY, candidate_path=candidate,
        source_accounting_path=accounting, scope=scope, technical=technical,
        review=review | {"report_path": review_path}, representation_revision=revision,
        decision=decision,
    )
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    return acceptance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    acceptance = prepare(args.root, args.candidate, args.stage)
    print(json.dumps({"status": "validated-pending", "acceptance_path": str(acceptance)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
