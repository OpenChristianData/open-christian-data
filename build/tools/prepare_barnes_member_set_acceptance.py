"""Stage a pending, source-scoped Barnes SWORD TEI acceptance record.

The complete extracted electronic source is represented, including explicit
byte-provenance gaps. This stage does not assert a fully readable transcription.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from lxml import etree

from build.tei.barnes_nt_notes_oracle import _oracle
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/barnes-nt-notes")
EDITION = WORK / "forms/barnes-english/editions/crosswire-sword-v1.1"
ACQUISITION = EDITION / "acquisitions/barnes-sword-v1.1.json"
MANIFEST = Path("sources/barnes-nt-notes/barnes-nt-notes.candidate-source-manifest-20260926.json")
HANDOFF = Path("sources/barnes-nt-notes/barnes-member-set-candidate-rebind-20260926.json")
REVIEW = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-066-barnes-nt-notes.md")
EVIDENCE = WORK / "integration/barnes-member-set-agent-handoff-v1"
IDENTITY = {
    "work_id": "barnes-nt-notes",
    "textual_form_id": "barnes-english",
    "edition_id": "crosswire-sword-v1.1",
    "acquisition_id": "barnes-sword-v1.1",
}
MANIFEST_SHA = "b86ff5234dff59b0406adfedb2a5ef588538255719b43ec25f5963c6b3e9dcf6"
PACKAGE_SHA = "822304c59b5fbc44720f637b8c7caaf9cce6a899bcc6c0040862db263f242c35"
TEI_SHA = "3f59fbeacc7f2020f3fbb7c5b220f6ff10f8f85e5732ee295527bdd527841dd1"
ACCOUNT_SHA = "481df53109501780a887112cf2672c1687cba62b86f9e4b1720591afe6b3cc9e"
HISTORICAL_TEI = Path("D:/Library/Open Christian Data/candidate-reviews/37c-066-barnes-nt-notes-20260918-v6-byte-spans/package/content.tei.xml")
HISTORICAL_TEI_SHA = "31814b6a8fe5a3f47aaf19b1e8fe1ad7f8e8e5909d1e7b94bd2a610689af8f58"
HISTORICAL_ACCOUNT = HISTORICAL_TEI.parent / "source-accountability.json"
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    data = path.read_bytes()
    if expected is not None and _sha(data) != expected:
        raise PipelineError(f"Barnes evidence hash mismatch: {path}")
    return data


def _copy(stage: Path, relative: Path, data: bytes) -> Path:
    path = stage / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _write(stage: Path, relative: Path, value: object) -> Path:
    return _copy(stage, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))


def _check_gaps(account: dict, original: bytes) -> dict[str, int]:
    if (account.get("slot_count") != 8246
            or account.get("unrepresentable_range_count") != 166
            or account.get("unrepresentable_byte_count") != 166
            or account.get("unrepresentable_byte_counts") != {"invalid_utf8": 68, "xml_1_0_forbidden": 98}
            or len(account.get("invalid_utf8_slots", [])) != 60
            or len(account.get("xml_incompatible_slots", [])) != 76):
        raise PipelineError("Barnes source gap census changed")
    tree = etree.fromstring(original, etree.XMLParser(resolve_entities=False, no_network=True))
    gaps = tree.xpath("//t:gap", namespaces={"t": "http://www.tei-c.org/ns/1.0"})
    if len(gaps) != 166 or any(gap.get("reason") != "unrepresentable" for gap in gaps):
        raise PipelineError("Barnes TEI gap census differs from source accounting")
    return {"source_slots": 8246, "affected_slots": 136, "gap_ranges": 166, "unrepresentable_bytes": 166}


def _reviewed_body(content: bytes) -> bytes:
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
    texts = root.xpath("./t:text", namespaces={"t": "http://www.tei-c.org/ns/1.0"})
    if len(texts) != 1:
        raise PipelineError("Barnes candidate has an ambiguous text body")
    return etree.tostring(texts[0], encoding="utf-8")


def prepare(root: Path, candidate_root: Path, stage: Path) -> Path:
    root = root.resolve()
    candidate_root = candidate_root.resolve()
    stage = stage.absolute()
    if stage.exists() or not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("Barnes stage must be a fresh path under an ordinary existing parent")
    resolved = stage.resolve()
    for protected in (root, candidate_root):
        if resolved == protected or protected in resolved.parents or resolved in protected.parents:
            raise PipelineError("Barnes stage overlaps protected input")

    handoff = json.loads(_read(root / HANDOFF))
    if handoff.get("status") != "nonaccepted-candidate-only" or handoff.get("candidate", {}).get("root") != candidate_root.as_posix():
        raise PipelineError("Barnes current candidate handoff differs")
    manifest_path = root / MANIFEST
    _read(manifest_path, MANIFEST_SHA)
    manifest = SourceManifest.load(manifest_path, repository_root=root)
    manifest.verify()
    package = CandidatePackage.load(candidate_root / "package")
    if package.sha256 != PACKAGE_SHA or package.manifest["source_manifest"]["sha256"] != MANIFEST_SHA:
        raise PipelineError("Barnes package is not bound to the extracted source set")
    original = package.member_bytes("content.tei.xml")
    if _sha(original) != TEI_SHA:
        raise PipelineError("Barnes current TEI changed")
    account_bytes = package.member_bytes("source-accountability.json")
    if _sha(account_bytes) != ACCOUNT_SHA:
        raise PipelineError("Barnes source-accountability member changed")
    historical = _read(HISTORICAL_TEI, HISTORICAL_TEI_SHA)
    if _reviewed_body(original) != _reviewed_body(historical) or _read(HISTORICAL_ACCOUNT, ACCOUNT_SHA) != account_bytes:
        raise PipelineError("Barnes current text or byte accounting differs from reviewed v6")
    census = _check_gaps(json.loads(account_bytes), original)
    report = validate(manifest, package, _oracle)
    if report.status != "pass" or report.findings:
        raise PipelineError("Barnes current independent oracle did not pass")
    recorded = json.loads(_read(candidate_root / "validation.json"))
    if (recorded.get("status") != "pass" or recorded.get("candidate_sha256") != PACKAGE_SHA
            or recorded.get("source_manifest_sha256") != MANIFEST_SHA
            or recorded.get("report_sha256") != report.sha256):
        raise PipelineError("Barnes stored validation differs from fresh oracle")
    acquisition = json.loads(_read(root / ACQUISITION))
    if acquisition.get("source_kind") != "retained-member-set" or len(acquisition.get("retained_files", [])) != 3:
        raise PipelineError("Barnes acquisition no longer identifies three extracted source members")
    member_set = json.loads(_read(root / acquisition["source_path"], acquisition["source_sha256"]))
    if len(member_set.get("members", [])) != 3:
        raise PipelineError("Barnes source member set changed")
    source = {key: acquisition[key] for key in ("source_path", "source_sha256", "source_bytes", "source_scope", "source_kind")}
    now = datetime.now(timezone.utc)
    revision = {
        "id": "barnes-crosswire-electronic-gaps-v1",
        "date": now.date().isoformat(),
        "note": "Bind the complete extracted SWORD electronic witness with 166 explicit byte-provenance gaps; no missing glyphs are inferred.",
    }
    derived = bind_reviewed_header(
        original, expected_sha256=TEI_SHA, identity=IDENTITY, source=source,
        source_url=acquisition["url"], declared_scope=source["source_scope"], revision=revision,
    )
    previous_status = b"Nonaccepted technical candidate; rights and publication not assessed."
    accepted_status = b"Agent-accepted retained electronic witness with 166 explicit source-byte gaps; rights and publication not assessed."
    if derived.count(previous_status) != 1:
        raise PipelineError("Barnes candidate publication statement differs")
    derived = derived.replace(previous_status, accepted_status, 1)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Barnes header binding changed reviewed TEI body")

    shutil.copytree(root / WORK, stage / WORK)
    _copy(stage, MANIFEST, _read(manifest_path, MANIFEST_SHA))
    _copy(stage, HANDOFF, _read(root / HANDOFF))
    for member in acquisition["retained_files"]:
        _copy(stage, Path(member["path"]), _read(resolve_repo_path(root, member["path"]), member["sha256"]))
    state = json.loads(_read(stage / WORK / "state.json"))
    for target in state["targets"]:
        for reference in target["evidence"]:
            relative = Path(reference)
            if relative.is_absolute() or ".." in relative.parts:
                raise PipelineError("Barnes state evidence path is unsafe")
            if (stage / relative).is_file() or (stage / WORK / relative).is_file():
                continue
            source_evidence = (resolve_repo_path(root, reference) if relative.parts[0] == "raw"
                               else root / relative)
            _copy(stage, relative, _read(source_evidence))
    evidence = stage / EVIDENCE
    for name in package.member_names:
        _copy(stage, EVIDENCE / "inputs/current-package" / name, package.member_bytes(name))
    _copy(stage, EVIDENCE / "inputs/current-package/manifest.json", _read(candidate_root / "package/manifest.json", PACKAGE_SHA))
    _copy(stage, EVIDENCE / "inputs/validation.json", _read(candidate_root / "validation.json"))
    _copy(stage, EVIDENCE / "inputs/review-ticket.md", _read(root / REVIEW))
    candidate = _copy(stage, EVIDENCE / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"Barnes acceptance TEI XSD failed: {errors[:3]}")

    members = acquisition["retained_files"]
    expected = [{"path": item["path"], "position": index} for index, item in enumerate(members, 1)]
    included = [entry | {"bytes": item["bytes"], "sha256": item["sha256"], "scope": item["scope"]}
                for entry, item in zip(expected, members, strict=True)]
    scope = {"kind": "edition", "declared": source["source_scope"], "expected_members": expected,
             "included_members": included, "excluded_members": []}
    common = {"identity": IDENTITY, "source": source, "candidate": make_file_binding(stage, candidate),
              "scope": source["source_scope"], "accepted_scope": {"kind": "edition", "declared": source["source_scope"]},
              "expected_members": expected, "included_members": included, "excluded_members": [],
              "missing_members": [], "unknown_members": []}
    source_accounting = _write(stage, EVIDENCE / "source-accounting.json", common | {
        "source_sha256": source["source_sha256"], "source_bytes": source["source_bytes"],
        "census": census, "source_manifest_sha256": MANIFEST_SHA,
        "package_sha256": PACKAGE_SHA, "accountability_sha256": ACCOUNT_SHA,
    })
    inputs = {"manifest": make_file_binding(stage, stage / MANIFEST),
              "package": make_file_binding(stage, evidence / "inputs/current-package/manifest.json"),
              "validation": make_file_binding(stage, evidence / "inputs/validation.json"),
              "review": make_file_binding(stage, evidence / "inputs/review-ticket.md")}
    command = "py -3 -m build.tools.prepare_barnes_member_set_acceptance --stage <fresh-external-root>"
    details = {
        "validation": "Current independent oracle and validation sidecar pass; the derived TEI passes vendored XSD.",
        "accounting": "All 8,246 indexed slots are accounted; all 166 problematic bytes have one TEI gap and exact range provenance.",
        "fidelity": "Representable spans and ThML structure pass the independent oracle; no character is guessed for malformed or forbidden bytes.",
        "reproducibility": "The current package reproduces the historical v6 TEI body and byte-range ledger; this stage adds header bindings only.",
        "schema": "The current package and header-derived TEI pass their declared schemas.",
        "closure": "The installed acquisition, extracted member set, current source manifest, package, validation, and review ticket are hash-bound.",
    }
    technical = {"producer": {"id": package.manifest["converter"]["id"]},
                 "checker": {"id": manifest.record["validator"]["id"]},
                 "shared_assumptions": ["Producer and oracle share the exact SWORD members and profile; source byte ranges are independently decoded and checked against TEI structure."],
                 "independent_corroboration": "Current independent oracle pass, historical mutation and clean-process tests, direct source decompression spot checks, and documented v6 visual samples with byte-identical current TEI body."}
    for name in PROOFS:
        path = _write(stage, EVIDENCE / f"{name}.json", common | {
            "status": "pass", "command": command, "exit_code": 0, "description": details[name],
            "inputs": inputs, "oracle_report_sha256": report.sha256, "gap_census": census,
        })
        technical[name] = {"path": path, "status": "pass", "command": command, "exit_code": 0}
    coverage = {"status": "partial", "declared": source["source_scope"],
                "reached": ["extracted-member-set"],
                "inspected": ["extracted-member-set/historical-v6-opening-middle-ending"],
                "unreviewed": ["extracted-member-set/unsampled-source-content"]}
    uncertainty = [
        "The source declares UTF-8 but 68 bytes are invalid UTF-8 and 98 bytes are XML 1.0-forbidden controls; the exact bytes remain gaps, not readable characters.",
        "Four source blockquote starts have no close in their carriers; TEI closes them at the carrier boundary with explicit warnings.",
        "The historical v6 visual sample covers opening, middle, and ending; the current TEI body is byte-identical but was not separately displayed in CVW.",
    ]
    residual = ["The 166 source bytes remain unreadable; exhaustive visual proofreading and print edition identity are unassessed."]
    reviewed_at = now.isoformat().replace("+00:00", "Z")
    review = {"reviewer": "agent:barnes-extracted-member-set-review", "reviewed_at": reviewed_at,
              "coverage": coverage, "source_quality_uncertainty": uncertainty,
              "discrepancies": [], "unreviewed_residuals": residual}
    review_path = _write(stage, EVIDENCE / "review.json", common | review | {
        "inputs": inputs, "gap_census": census,
        "supported_claim": "faithful representation of the complete retained electronic member set, with explicit byte-provenance gaps",
        "unassessed": ["complete readable transcription", "inferred missing characters", "original print witness", "human acceptance", "rights", "release", "publication"],
    })
    decision = {"source_local_disposition": "Agent acceptance of the exact extracted SWORD electronic source as representable TEI with 166 explicitly unresolved source bytes.",
                "blockers": [],
                "agent_assessment": {"status": "accepted", "actor": review["reviewer"], "assessed_at": reviewed_at,
                                     "supported_scope": source["source_scope"], "unresolved_claims": [],
                                     "unassessed_stronger_claims": ["complete readable transcription", "interpretation of 166 source bytes", "original print witness", "human textual acceptance", "rights clearance", "release", "publication"]},
                "human_decision": {"status": "not-recorded"}}
    record = build_acceptance_record(
        stage, identity=IDENTITY, candidate_path=candidate, source_accounting_path=source_accounting,
        scope=scope, technical=technical, review=review | {"report_path": review_path},
        representation_revision=revision, decision=decision,
    )
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    return acceptance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidate", type=Path, default=Path("C:/Scratch/barnes-member-rebind-candidate-20260926-v1"))
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    acceptance = prepare(args.root, args.candidate, args.stage)
    print(json.dumps({"status": "validated-pending", "acceptance_path": str(acceptance)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
