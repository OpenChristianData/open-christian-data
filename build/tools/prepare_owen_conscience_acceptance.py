"""Stage acceptance of the exact retained John Owen Conscience electronic witness."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tei.selected_thml_oracle import _oracle
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.selected_thml_check import check_selected_thml
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/john-owen-conscience")
EDITION = WORK / "forms/john-owen-conscience-english/editions/john-owen-conscience-ccel"
ACQUISITION = EDITION / "acquisitions/john-owen-conscience-retained.json"
SOURCE = Path("raw/ccel/owen/conscience.xml")
MANIFEST = Path("sources/work-units-phase-a/john-owen-conscience/source-manifest.json")
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-217-john-owen-conscience.md")
REPORT = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-217.md")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/source-to-tei-current-library-21-20260924/john-owen-conscience")
CVW = Path("D:/Library/Open Christian Data/reports/runs/cvw-john-owen-conscience-20260924-current-candidate")
IDENTITY = dict(work_id="john-owen-conscience", textual_form_id="john-owen-conscience-english",
                edition_id="john-owen-conscience-ccel", acquisition_id="john-owen-conscience-retained")
SOURCE_SHA = "472e1fd7c0b3abfb9999369cbbe7d091026ef7f6cc314c3576476f787edcb836"
MANIFEST_SHA = "d212bcd407d1c119a00d8ef23e30d6bc2fd1f355ce1150b8fb166ce536fdb885"
PACKAGE_SHA = "c6719609f12979f55aa72c54694f06105f8765316a1a0706b13092ec0c47415e"
TEI_SHA = "45a2b17225bb1a62651e5f18e178a361a0cabf55b2275b8b494eabed9d493d5d"
VALIDATION_SHA = "1b9da99b3301a48f3f8d9e62e3a06f37d1e5961b84d9757a4d6cc3c1181889be"
VALIDATION_REPORT_SHA = "f307201dcea86e52fedc8afe78420df49a1e61137a4ef6c0fa1c3ca55d6104ba"
ACCOUNT_SHA = "ce538c41bd12cbbc7ea21f48ef10086a1bc5397d2fbc49a40de528d2f0c84196"
COVERAGE_SHA = "2ae1d76dd4a61836694d6912f3d3fbb79ef55467f962e666135a906e27ff9a04"
SELECTION_SHA = "543e1ef4dfb08ea199c26f7778c4f6a4ec47c3951ea33e75922de7bc3d9e6363"
SCOPE = "i (body); ii (back); shared credits: none"
REVISION_ID = "john-owen-conscience-ccel-electronic-witness-v1"
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"required Conscience evidence is missing: {path}") from exc
    if expected is not None and _sha(content) != expected:
        raise PipelineError(f"Conscience evidence SHA-256 mismatch: {path}")
    return content


def _json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid Conscience JSON: {label}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"Conscience JSON is not an object: {label}")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _copy(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def _stage_path(root: Path, stage: Path) -> Path:
    stage = stage.absolute()
    if stage.exists():
        raise PipelineError(f"Conscience staging root must be fresh: {stage}")
    resolved = stage.resolve()
    for protected in (root.resolve(), CANDIDATE.resolve(), CVW.resolve()):
        if resolved == protected or protected in resolved.parents or resolved in protected.parents:
            raise PipelineError("Conscience staging root overlaps protected input")
    if not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("Conscience staging parent must be an existing ordinary directory")
    return stage


def _revision_only(original: bytes, revision: dict[str, str], source_url: str) -> bytes:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    tree = etree.fromstring(original, parser)
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    header = tree.xpath("./t:teiHeader", namespaces=ns)
    if len(header) != 1 or header[0].xpath("./t:revisionDesc", namespaces=ns):
        raise PipelineError("Conscience reviewed TEI header has unexpected revision history")
    bibl = header[0].xpath("./t:fileDesc/t:sourceDesc/t:bibl", namespaces=ns)
    if len(bibl) != 1:
        raise PipelineError("Conscience reviewed source description is ambiguous")
    required = dict(IDENTITY) | {"source_sha256": SOURCE_SHA, "source_bytes": "169775",
                                 "sha256": SOURCE_SHA, "source_selection_sha256": SELECTION_SHA}
    for kind, expected in required.items():
        nodes = bibl[0].xpath("./t:idno[@type=$kind]", namespaces=ns, kind=kind)
        if len(nodes) != 1 or "".join(nodes[0].itertext()) != expected:
            raise PipelineError(f"Conscience reviewed header {kind} differs")
    for kind, expected in (("source-location", SOURCE.as_posix()), ("source-scope", SCOPE)):
        nodes = bibl[0].xpath("./t:note[@type=$kind]", namespaces=ns, kind=kind)
        if len(nodes) != 1 or "".join(nodes[0].itertext()) != expected:
            raise PipelineError(f"Conscience reviewed header {kind} differs")
    if bibl[0].xpath("./t:ptr/@target", namespaces=ns) != [source_url]:
        raise PipelineError("Conscience reviewed source URL differs")
    close_bibl, close_header = b"</bibl></sourceDesc>", b"</teiHeader>"
    if original.count(close_bibl) != 1 or original.count(close_header) != 1:
        raise PipelineError("Conscience header byte boundaries are ambiguous")
    idno = f'<idno type="representation_revision">{revision["id"]}</idno>'.encode()
    change = (f'<revisionDesc><change xml:id="{revision["id"]}" when="{revision["date"]}">'
              f'{revision["note"]}</change></revisionDesc>').encode()
    derived = original.replace(close_bibl, idno + close_bibl, 1).replace(close_header, change + close_header, 1)
    etree.fromstring(derived, parser)
    if derived.replace(idno, b"", 1).replace(change, b"", 1) != original:
        raise PipelineError("Conscience header derivation altered reviewed TEI bytes")
    return derived


def _visual_inputs() -> tuple[dict[str, bytes], dict]:
    receipt_bytes = _read(CVW / "coverage-receipt.json", COVERAGE_SHA)
    receipt = _json(receipt_bytes, "CVW coverage")
    binding = receipt.get("bindings", {})
    coverage = receipt.get("coverage", {})
    points = coverage.get("points", [])
    if (receipt.get("work_id") != IDENTITY["work_id"]
            or receipt.get("disposition") != "declared_sample_complete_within_scope"
            or receipt.get("candidate_status") != "nonaccepted"
            or binding.get("source_sha256") != SOURCE_SHA
            or binding.get("source_manifest_sha256") != MANIFEST_SHA
            or binding.get("candidate_package_sha256") != PACKAGE_SHA
            or binding.get("candidate_tei_sha256") != TEI_SHA
            or coverage.get("declared_points") != 21
            or coverage.get("captured_points") != 21
            or coverage.get("pixel_inspected_points") != 21
            or coverage.get("all_routes_bound_to_same_source_and_candidate") is not True
            or coverage.get("all_panes_unlinked") is not True
            or len(points) != 21):
        raise PipelineError("Conscience CVW receipt does not bind the declared current sample")
    files = {"cvw/coverage-receipt.json": receipt_bytes,
             "cvw/visual-review.md": _read(CVW / "visual-review.md")}
    for ordinal, point in enumerate(points, 1):
        screenshot, record = (point.get(key) for key in ("screenshot_file", "record_file"))
        if (point.get("ordinal") != ordinal or point.get("visually_inspected") is not True
                or not isinstance(screenshot, str) or not isinstance(record, str)
                or Path(screenshot).is_absolute() or Path(record).is_absolute()
                or ".." in Path(screenshot).parts or ".." in Path(record).parts):
            raise PipelineError(f"Conscience visual point {ordinal} is incomplete")
        frame = _read(CVW / screenshot, point.get("screenshot_sha256"))
        record_bytes = _read(CVW / record)
        item = _json(record_bytes, f"CVW point {ordinal}")
        if (not frame.startswith(b"\x89PNG\r\n\x1a\n")
                or len(frame) != point.get("screenshot_bytes")
                or item.get("ordinal") != ordinal
                or item.get("source_location") != point.get("source_location")
                or item.get("tei_location") != point.get("tei_location")
                or item.get("route_digest") != point.get("route_digest")
                or item.get("linked") is not False
                or item.get("correspondence") != "absent"
                or MANIFEST_SHA not in item.get("route", "")
                or PACKAGE_SHA not in item.get("route", "")):
            raise PipelineError(f"Conscience visual point {ordinal} is not the reviewed exact pair")
        files[f"cvw/{screenshot}"] = frame
        files[f"cvw/{record}"] = record_bytes
    for session in receipt.get("session_files", {}).values():
        relative = Path(session["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise PipelineError("Conscience CVW session path is unsafe")
        content = _read(CVW / relative, session["sha256"])
        if len(content) != session["bytes"]:
            raise PipelineError("Conscience CVW session byte count differs")
        files[f"cvw/{relative.as_posix()}"] = content
    return files, receipt


def _preflight(root: Path) -> tuple[dict, dict[str, bytes], dict]:
    source = _read(resolve_repo_path(root, SOURCE.as_posix()), SOURCE_SHA)
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    manifest.verify()
    if manifest.sha256 != MANIFEST_SHA or len(source) != 169775:
        raise PipelineError("Conscience source or manifest differs from the reviewed pair")
    acquisition_bytes = _read(root / ACQUISITION)
    acquisition = _json(acquisition_bytes, "acquisition")
    members = acquisition.get("retained_files", [])
    selection = acquisition.get("source_selection", {})
    if (acquisition.get("acquisition_id") != IDENTITY["acquisition_id"]
            or acquisition.get("edition_id") != IDENTITY["edition_id"]
            or acquisition.get("source_scope") != SCOPE
            or selection.get("selection_id") != "john-owen-conscience-selection-v1"
            or selection.get("member_path") != SOURCE.as_posix()
            or [(unit.get("native_id"), unit.get("role")) for unit in selection.get("units", [])] != [("i", "body"), ("ii", "back")]
            or selection.get("dependencies") != [] or len(members) != 1
            or any(members[0].get(key) != value for key, value in
                   (("path", SOURCE.as_posix()), ("bytes", len(source)), ("sha256", SOURCE_SHA)))):
        raise PipelineError("Conscience acquisition selection or identity changed")
    work = load_work(root / WORK / "work.json")
    package = CandidatePackage.load(CANDIDATE / "package")
    original = package.member_bytes("content.tei.xml")
    validation_bytes = _read(CANDIDATE / "validation.json", VALIDATION_SHA)
    validation = _json(validation_bytes, "validation")
    if (package.sha256 != PACKAGE_SHA or _sha(original) != TEI_SHA
            or _sha(package.member_bytes("source-accountability.json")) != ACCOUNT_SHA
            or package.manifest.get("status") != "nonaccepted"
            or package.manifest.get("source_manifest", {}).get("sha256") != MANIFEST_SHA
            or validation.get("status") != "pass" or validation.get("findings") != []
            or validation.get("candidate_sha256") != PACKAGE_SHA
            or validation.get("source_manifest_sha256") != MANIFEST_SHA
            or validation.get("report_sha256") != VALIDATION_REPORT_SHA
            or validation.get("attestation", {}).get("source_sha256") != SOURCE_SHA):
        raise PipelineError("Conscience candidate or validation differs from reviewed pair")
    report = validate(manifest, package, _oracle)
    selected = check_selected_thml(root, acquisition, work, CANDIDATE / "package/content.tei.xml")
    if (report.status != "pass" or report.sha256 != VALIDATION_REPORT_SHA
            or selected.get("status") != "pass" or selected.get("checked_elements") != 633
            or selected.get("selection_sha256") != SELECTION_SHA):
        raise PipelineError("Conscience current source-bound fidelity checks differ")
    visual_files, coverage = _visual_inputs()
    ticket, review = _read(root / TICKET), _read(root / REPORT)
    for anchor in (SOURCE_SHA, MANIFEST_SHA, PACKAGE_SHA, TEI_SHA):
        if anchor.encode() not in ticket + review:
            raise PipelineError(f"Conscience ticket/review lacks exact evidence anchor: {anchor}")
    files = {"ticket.md": ticket, "report.md": review,
             "source-manifest.json": _read(root / MANIFEST, MANIFEST_SHA),
             "acquisition.json": acquisition_bytes, "validation.json": validation_bytes}
    files.update({f"package/{name}": package.member_bytes(name) for name in package.member_names})
    files["package/manifest.json"] = _read(CANDIDATE / "package/manifest.json", PACKAGE_SHA)
    files.update(visual_files)
    return acquisition, files, coverage


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = _stage_path(root, stage)
    acquisition, files, coverage = _preflight(root)
    stage.mkdir()
    evidence = stage / WORK / "integration/ccel-electronic-witness-agent-handoff"
    for name, content in files.items():
        _copy(stage, evidence.relative_to(stage) / "inputs" / name, content)
    for relative in (WORK / "work.json", WORK / "state.json", ACQUISITION, TICKET, REPORT):
        _copy(stage, relative, _read(root / relative))
    _copy(stage, Path("reports/runs/cvw-john-owen-conscience-20260924-current-candidate/coverage-receipt.json"),
          files["cvw/coverage-receipt.json"])
    _copy(stage, SOURCE, _read(resolve_repo_path(root, SOURCE.as_posix()), SOURCE_SHA))
    _copy(stage, MANIFEST, files["source-manifest.json"])
    original = files["package/content.tei.xml"]
    now = datetime.now(timezone.utc)
    revision = dict(id=REVISION_ID, date=now.date().isoformat(),
                    note="Bind the accepted retained CCEL electronic witness; reviewed TEI text unchanged.")
    derived = _revision_only(original, revision, acquisition["url"])
    candidate = _copy(stage, evidence.relative_to(stage) / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived Conscience TEI failed vendored XSD: {errors}")
    included = [dict(path=SOURCE.as_posix(), bytes=169775, sha256=SOURCE_SHA, scope=SCOPE, position=1)]
    scope = dict(kind="edition", declared=SCOPE,
                 expected_members=[dict(path=SOURCE.as_posix(), position=1)],
                 included_members=included, excluded_members=[])
    source = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                  source_bytes=169775, source_scope=SCOPE)
    common = dict(identity=IDENTITY, source=source, candidate=make_file_binding(stage, candidate),
                  scope=SCOPE, accepted_scope=dict(kind="edition", declared=SCOPE),
                  expected_members=scope["expected_members"], included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = evidence / "source-accounting.json"
    _write(account, common | dict(source_sha256=SOURCE_SHA, source_bytes=169775,
                                  original_accountability_sha256=ACCOUNT_SHA))
    bindings = {name: make_file_binding(stage, evidence / "inputs" / name) for name in files}
    details = {
        "validation": dict(status="pass", findings=[], report_sha256=VALIDATION_REPORT_SHA,
                           sidecar=bindings["validation.json"], fresh_oracle_replayed=True),
        "accounting": dict(selection_sha256=SELECTION_SHA, checked_elements=633,
                           original_accountability_sha256=ACCOUNT_SHA,
                           original_member=bindings["package/source-accountability.json"]),
        "fidelity": dict(original_tei_sha256=TEI_SHA,
                         original_text_sha256=_sha(original.split(b"</teiHeader>", 1)[1]),
                         derived_text_sha256=_sha(derived.split(b"</teiHeader>", 1)[1]),
                         header_only_derivation=True),
        "reproducibility": dict(original_package_sha256=PACKAGE_SHA,
                                source_bound_candidate_retained=True,
                                no_reconstruction_performed=True),
        "schema": dict(vendored_xsd="ocd_kernel/tei/vendor/xsd/tei_all.xsd", validation_errors=[]),
        "closure": dict(source_manifest_sha256=MANIFEST_SHA, original_package_sha256=PACKAGE_SHA,
                        evidence_files=bindings),
    }
    command = "py -3 -m build.tools.prepare_owen_conscience_acceptance --stage <fresh-external-root>"
    technical = dict(producer=dict(id="ocd-selected-thml-to-tei"),
                     checker=dict(id="ocd-selected-thml-independent-check"),
                     shared_assumptions=["Producer and oracle share retained XML, source selection, and SourceManifest; the 21 visual points are a bounded sample."],
                     independent_corroboration="Fresh independent oracle and 633-element selected-ThML check; source-accountability ledger and current-pair 21-point CVW review; unchanged TEI text after header revision.")
    for name in PROOFS:
        path = evidence / f"{name}.json"
        _write(path, common | dict(status="pass", command=command, exit_code=0, details=details[name]))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    points = coverage["coverage"]["points"]
    inspected = [f'{point["source_location"]} / {point["tei_location"]}' for point in points]
    review = dict(reviewer="agent:37c-217-current-candidate-cvw",
                  reviewed_at=coverage["reviewed_at_utc"],
                  coverage=dict(status="partial", declared=SCOPE, reached=inspected,
                                inspected=inspected, unreviewed=["whole-document pixel collation beyond the 21 declared points"]),
                  source_quality_uncertainty=["Exact print exemplar and electronic transcription lineage remain unknown."],
                  discrepancies=[],
                  unreviewed_residuals=["The complete declared sample was inspected, not every word or pixel of the witness.",
                                       "Work/sermon granularity and print edition identity remain unresolved bibliographic questions."])
    _write(evidence / "review.json", common | review | dict(
        coverage_receipt=bindings["cvw/coverage-receipt.json"],
        screenshot_bindings=[bindings[f'cvw/{point["screenshot_file"]}'] for point in points],
        reviewed_original_tei_sha256=TEI_SHA, derived_text_bytes_unchanged=True,
        no_new_pixel_review=True))
    decision = dict(
        source_local_disposition="Evidence-backed agent acceptance of the selected i body and ii back matter in the exact retained CCEL electronic witness.",
        blockers=[],
        agent_assessment=dict(status="accepted", actor="agent:john-owen-conscience-electronic-witness-review",
                              assessed_at=now.isoformat().replace("+00:00", "Z"), supported_scope=SCOPE,
                              unassessed_stronger_claims=["human acceptance", "rights clearance", "print edition identification",
                                                          "standalone work versus constituent sermon decision", "exhaustive proofreading",
                                                          "release", "publication"], unresolved_claims=[]),
        human_decision=dict(status="not-recorded"),
    )
    record = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate,
                                     source_accounting_path=account, scope=scope, technical=technical,
                                     review=review | dict(report_path=evidence / "review.json"),
                                     representation_revision=revision, decision=decision)
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
