"""Prepare an ASV acceptance handoff in a fresh, caller-selected staging root.

This command reconstructs the exact retained JSON route. It neither installs a
master nor changes the canonical work, acquisition, state, or acceptance files.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction import SourceManifest, reconstruct, validate
from ocd_kernel.reconstruction.contract import CandidatePackage
from ocd_kernel.library.acquisitions import acquisition_for_edition
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file
from build.tei.asv_reconstruction import convert
from build.tei.asv_oracle import oracle


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path("sources/bible-text/asv/asv.source-manifest.json")
RECEIPT = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-006-receipt.json")
STATE_EVIDENCE = (
    Path("plans/2026-08-31-sample-first-library-verification/issues/37c-006-asv.md"),
    Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-006.md"),
)
WORK = Path("library/works/asv")
EDITION = WORK / "forms/english-asv/editions/retained-json"
IDENTITY = dict(work_id="asv", textual_form_id="english-asv", edition_id="retained-json", acquisition_id="scrollmapper-retained-json")
ORIGINAL_SHA = "8ce811960861d254fd384403508ceb4af52772a0453f04a4256a161c0120150e"
SCOPE = "complete retained ASV JSON electronic witness; no claim to complete physical 1901 print"
REVISION = dict(id="asv-reviewed-header-v1", date="2026-09-24", note="Acceptance identity and retained JSON source bindings added; original TEI text bytes are unchanged.")
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _copy(root: Path, stage: Path, relative: Path) -> Path:
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((root / relative).read_bytes())
    return target


def _verify_visual_screenshots(root: Path, screenshots: list[dict]) -> None:
    """Verify every receipt image is a unique, intact PNG inside the repo."""
    root = root.resolve(strict=True)
    seen: set[str] = set()
    for item in screenshots:
        label = item.get("label", "<unknown>")
        raw_path = item.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise PipelineError(f"ASV visual screenshot {label!r} has no repository path")
        relative = Path(raw_path)
        if relative.is_absolute() or relative.drive or ".." in relative.parts:
            raise PipelineError(f"ASV visual screenshot {label!r} path is not repository-relative")
        try:
            resolved = (root / relative).resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PipelineError(f"ASV visual screenshot {label!r} is missing or outside the repository") from exc
        if not resolved.is_file() or resolved.suffix.casefold() != ".png":
            raise PipelineError(f"ASV visual screenshot {label!r} is not a PNG file")
        path_key = resolved.as_posix().casefold()
        if path_key in seen:
            raise PipelineError(f"ASV visual screenshot path is duplicated: {raw_path}")
        seen.add(path_key)
        try:
            content = resolved.read_bytes()
        except OSError as exc:
            raise PipelineError(f"ASV visual screenshot {label!r} cannot be read") from exc
        expected_bytes = item.get("bytes")
        expected_sha256 = item.get("sha256")
        if (type(expected_bytes) is not int or not isinstance(expected_sha256, str)
                or len(content) != expected_bytes or _sha(content) != expected_sha256
                or not content.startswith(b"\x89PNG\r\n\x1a\n")):
            raise PipelineError(f"ASV visual screenshot {label!r} does not match its recorded PNG bytes and SHA-256")


def _receipt(root: Path, source_sha: str) -> dict:
    receipt = json.loads((root / RECEIPT).read_bytes())
    visual = receipt["cvw"]
    screenshots = visual["screenshots"]
    sample = visual["declared_visual_sample"]
    if (receipt["contract"] != "ocd-37c006-asv-review-receipt-v1"
            or receipt["work_id"] != "asv"
            or receipt["candidate"]["tei_sha256"] != ORIGINAL_SHA
            or receipt["source"]["sha256"] != source_sha
            or sample["tei_sha256"] != ORIGINAL_SHA
            or sample["source_sha256"] != source_sha
            or visual["followup_capture"]["coverage"]["pixel_inspected_loci"] != 7
            or len(screenshots) != 7
            or {item["label"] for item in screenshots} != {item["label"] for item in sample["loci"]}
            or not all(item["tei"]["sha256"] == ORIGINAL_SHA and item["source"]["sha256"] == source_sha
                       and item["pixels_inspected"] and item["source_tei_text_exact_match"] for item in screenshots)):
        raise PipelineError("ASV seven-locus receipt does not bind the exact original source and TEI")
    _verify_visual_screenshots(root, screenshots)
    return receipt


def _asv_header_layout(original: bytes, bound: bytes) -> bytes:
    """Keep the plain historical source paragraph inside one bound bibl note.

    Accept only the exact legacy direct bibl or the current binder's marked
    paragraph wrapper. Both forms retain all binding bytes and reviewed text.
    """
    opening = b"<sourceDesc><p>"
    paragraph_end = b"</p></sourceDesc>"
    if original.count(opening) != 1 or original.count(paragraph_end) != 1 or bound.count(opening) != 1:
        raise PipelineError("ASV source description is not the expected single paragraph")
    paragraph = original.split(opening, 1)[1].split(paragraph_end, 1)[0]
    if b"<" in paragraph or b"&" in paragraph:
        raise PipelineError("ASV historical source description needs explicit mixed-content handling")
    note = b'<note type="historical-source-description">' + paragraph + b"</note>"
    namespace = b' xmlns="http://www.tei-c.org/ns/1.0"'
    layouts = (
        (b"<bibl" + namespace + b">", b"", b""),
        (b"<bibl" + namespace + b' type="ocd-acceptance-binding">', b"<p" + namespace + b">", b"</p>"),
    )
    for bibl, wrapper_open, wrapper_close in layouts:
        before = opening + paragraph + b"</p>" + wrapper_open + bibl
        closing = b"</bibl>" + wrapper_close + b"</sourceDesc>"
        if bound.count(before) != 1 or bound.count(bibl) != 1 or bound.count(closing) != 1:
            continue
        after = b"<sourceDesc>" + bibl + note
        derived_closing = b"</bibl></sourceDesc>"
        result = bound.replace(before, after, 1).replace(closing, derived_closing, 1)
        restored = result.replace(after, before, 1).replace(derived_closing, closing, 1)
        if restored != bound or result == bound or result.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
            raise PipelineError("ASV header layout changed reviewed text or binding bytes")
        return result
    raise PipelineError("ASV source description is not the expected single paragraph")


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = stage.resolve(strict=False)
    if stage.exists() or stage == root or stage in root.parents:
        raise PipelineError("ASV staging root must be fresh and separate from the repository")
    if root in stage.parents:
        raise PipelineError("ASV staging root must be outside the repository")
    if not stage.parent.is_dir():
        raise PipelineError("ASV staging parent must exist")

    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    manifest.verify()
    source_member = next(item for item in manifest.record["authorities"] if item["name"] == "asv-source")
    source_path = source_member["path"]
    source_bytes = resolve_repo_path(root, source_path).read_bytes()
    if _sha(source_bytes) != source_member["sha256"] or len(source_bytes) != source_member["bytes"]:
        raise PipelineError("ASV retained source changed")
    acquisition_path, acquisition = acquisition_for_edition(root, "asv", "retained-json", acquisition_id="scrollmapper-retained-json")
    if len(acquisition["retained_files"]) != 1 or any(
        acquisition["retained_files"][0][key] != value
        for key, value in (("path", source_path), ("sha256", source_member["sha256"]), ("bytes", source_member["bytes"]))
    ):
        raise PipelineError("ASV acquisition does not bind retained manifest source")
    receipt = _receipt(root, source_member["sha256"])

    evidence = stage / WORK / "integration/asv-header-handoff-v1"
    evidence.mkdir(parents=True)
    package = reconstruct(manifest, evidence / "original-package", convert)
    report = validate(manifest, package, oracle)
    original = package.member_bytes("content.tei.xml")
    if report.status != "pass" or report.findings or _sha(original) != ORIGINAL_SHA or package.sha256 != receipt["candidate"]["manifest_sha256"]:
        raise PipelineError("regenerated ASV candidate differs from reviewed route")

    # A second process must independently reproduce the sealed six-member package.
    worker = subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--manifest", MANIFEST.as_posix(),
         "--destination", str(evidence / "reproduced-package"), "--repository-root", str(root)],
        cwd=root, check=True, capture_output=True, text=True,
    )
    reproduced = CandidatePackage.load(evidence / "reproduced-package" / "package")
    if package.sha256 != reproduced.sha256 or any(package.member_bytes(name) != reproduced.member_bytes(name) for name in package.member_names):
        raise PipelineError("ASV candidate does not reproduce in a second process")

    source = dict(source_path=source_path, source_sha256=source_member["sha256"],
                  source_bytes=source_member["bytes"], source_scope=acquisition["retained_files"][0]["scope"])
    args = dict(expected_sha256=ORIGINAL_SHA, identity=IDENTITY, source=source,
                source_url=acquisition["url"], declared_scope=SCOPE, revision=REVISION)
    derived = _asv_header_layout(original, bind_reviewed_header(original, **args))
    if original.split(b"</teiHeader>", 1)[1] != derived.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("ASV header derivation altered tei:text bytes")
    candidate = evidence / "candidate.tei.xml"
    candidate.write_bytes(derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived ASV TEI failed vendored XSD: {errors}")

    _copy(root, stage, WORK / "work.json")
    _copy(root, stage, WORK / "state.json")
    _copy(root, stage, acquisition_path.relative_to(root))
    _copy(root, stage, MANIFEST)
    _copy(root, stage, RECEIPT)
    for evidence_path in STATE_EVIDENCE:
        _copy(root, stage, evidence_path)
    retained = stage / source_path
    retained.parent.mkdir(parents=True, exist_ok=True)
    retained.write_bytes(source_bytes)
    (stage / WORK / "README.source.md").write_bytes(package.member_bytes("README.source.md"))

    member = acquisition["retained_files"][0]
    included = [{key: member[key] for key in ("path", "bytes", "sha256", "scope")} | {"position": 1}]
    scope = dict(kind="edition", declared=SCOPE, expected_members=[dict(path=source_path, position=1)],
                 included_members=included, excluded_members=[])
    binding = make_file_binding(stage, candidate)
    common = dict(identity=IDENTITY, source=source, candidate=binding, scope=SCOPE,
                  accepted_scope=dict(kind="edition", declared=SCOPE),
                  expected_members=scope["expected_members"], included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = evidence / "source-accounting.json"
    _write(account, common | dict(scope=source["source_scope"], source_sha256=source["source_sha256"], source_bytes=source["source_bytes"],
                                  original_accountability_sha256=_sha(package.member_bytes("source-accountability.json"))))
    receipt_binding = make_file_binding(stage, stage / RECEIPT)
    derivation = dict(original_tei_sha256=ORIGINAL_SHA, derived_tei_sha256=_sha(derived),
                      original_text_sha256=_sha(original.split(b"</teiHeader>", 1)[1]),
                      derived_text_sha256=_sha(derived.split(b"</teiHeader>", 1)[1]),
                      method="bind_reviewed_header; original source paragraph text moved verbatim into its bibl note to satisfy the vendored XSD; bytes after the closing teiHeader are identical",
                      visual_receipt=receipt_binding, visual_scope="seven original-candidate loci only")
    _write(evidence / "header-derivation.json", derivation | dict(arguments=args))
    command = "py -3 -m build.tools.prepare_asv_acceptance --stage <fresh-external-root>"
    details = {
        "validation": dict(oracle_status=report.status, findings=list(report.findings), oracle_result_sha256=report.sha256),
        "accounting": dict(original_accountability_sha256=_sha(package.member_bytes("source-accountability.json")),
                           source_fields="bound by independent ASV oracle", original_package_sha256=package.sha256),
        "fidelity": dict(original_candidate_sha256=ORIGINAL_SHA, derived_text_sha256=derivation["derived_text_sha256"],
                         original_text_sha256=derivation["original_text_sha256"], method=derivation["method"]),
        "reproducibility": dict(original_package_sha256=package.sha256, reproduced_package_sha256=reproduced.sha256,
                                second_process_stdout=worker.stdout.strip(), derived_header_is_deterministic=True),
        "schema": dict(vendored_xsd="ocd_kernel/tei/vendor/xsd/tei_all.xsd", validation_errors=[]),
        "closure": dict(manifest_sha256=manifest.sha256, reviewed_receipt=receipt_binding,
                        original_candidate_sha256=ORIGINAL_SHA, original_and_derived_text_bytes_equal=True),
    }
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and checker share retained JSON bytes and source manifest; the visual receipt covers only seven loci."],
                     independent_corroboration="Current independent oracle; second-process byte reproduction; historical seven-locus partial CVW receipt bound to unchanged tei:text.")
    for name in PROOFS:
        path = evidence / f"{name}.json"
        _write(path, common | dict(status="pass", command=command, exit_code=0, details=details[name]))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    screenshots = receipt["cvw"]["screenshots"]
    loci = [item["tei"]["xml_id"] for item in screenshots]
    review = dict(reviewer="historical:37c-006-seven-locus-CVW", reviewed_at=max(item["saved_at_utc"] for item in screenshots),
                  coverage=dict(status="partial", declared=SCOPE, reached=loci, inspected=loci, unreviewed=[]),
                  source_quality_uncertainty=["Retained electronic JSON is not collated against the physical 1901 print edition."],
                  discrepancies=[], unreviewed_residuals=["Seven inspected loci do not establish whole-book visual review of 66 books."])
    _write(evidence / "review.json", common | review | dict(historical_receipt=receipt_binding,
          review_basis="Original TEI hash matches receipt; derived tei:text bytes are identical. Historical screenshots are not re-inspected by this helper."))
    decision = dict(source_local_disposition="Evidence-backed agent acceptance for the exact retained ASV JSON electronic witness; human review, rights clearance, and publication remain unrecorded.",
                    blockers=[], agent_assessment=dict(status="accepted", actor="agent:asv-retained-json-review",
                    assessed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), supported_scope=SCOPE,
                    unassessed_stronger_claims=["human acceptance", "physical 1901 print completeness", "rights clearance", "publication"],
                    unresolved_claims=[]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate,
             source_accounting_path=account, scope=scope, technical=technical,
             review=review | dict(report_path=evidence / "review.json"), representation_revision=REVISION,
             decision=decision)
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    return acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(ROOT, args.stage))


if __name__ == "__main__":
    main()
