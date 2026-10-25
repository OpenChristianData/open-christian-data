"""Prepare an exact-source Watson Contentment agent handoff without installing it."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction.contract import CandidatePackage
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/watson-divine-contentment")
EDITION = WORK / "forms/watson-divine-contentment-english/editions/watson-divine-contentment-ccel-thml"
ACQUISITION = EDITION / "acquisitions/watson-divine-contentment-ccel-retained.json"
IDENTITY = dict(
    work_id="watson-divine-contentment",
    textual_form_id="watson-divine-contentment-english",
    edition_id="watson-divine-contentment-ccel-thml",
    acquisition_id="watson-divine-contentment-ccel-retained",
)
SOURCE = Path("raw/ccel/watson/contentment.xml")
MANIFEST = Path("sources/structured-text/watson-divine-contentment/watson-divine-contentment.source-manifest.json")
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-316-watson-divine-contentment.md")
REPORT = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-316.md")
RECEIPT = REPORT.with_name("37c-316-receipt.json")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/37c-316-watson-20260920-parent-refresh")
PRIOR_CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/37c-316-watson-20260920")
CVW = Path("D:/Library/Open Christian Data/reports/runs/37c-316-watson-20260920/cvw")
SESSION_ID = "26eb5975968041309a16f6621b6a4d86"
SOURCE_SHA = "767ed95de4c4c990480670084e8dd1ac16b6c61d50b864e8b0202e528a076d7b"
MANIFEST_SHA = "056e2f07288f95c86831de301e2b7981824236d224143207dfac8402c458e415"
PACKAGE_SHA = "cd4e3b055480a4ffa086fa45956d8cc0ab098f0e99ce252d7792d5890ee3c965"
PRIOR_PACKAGE_SHA = "87bb4d3049836ea86d8c6dca7e558f7595b69ec7d71c44f6a623f021e1f3a9b1"
TEI_SHA = "2ff3064a49c82a248259d3fbcd2edfa1fa6cfc42596587e0b49f5c27d14077bf"
VALIDATION_SHA = "7ee3a3cf8a299f572d96ece0942e803a249f80aacf2d400dff5f32a74fa47b34"
VALIDATION_REPORT_SHA = "d0c4b1906debf975801ac803e18cfb6f570e32de7da56b4e5e194bea4a85d936"
SESSION_SHA = "be0e14ef0c8bf29caa5f7c6aa2446552ae03a21c258f8a4d2ae7df1f7097b3fb"
EVENTS_SHA = "ef4f4f6208f7a390366ebb1b5b631cbbb21bed88436cf9274c298fbe13dce274"
PRESENT = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix")
MISSING = ("ix", "x")
SCOPE = ("One exact retained ThML member bound to one work. All 17 present top-level "
         "ThML.body div1 carriers are represented in source order. The table of contents "
         "names Chapters VI and VII, but their expected div1 identifiers ix and x are "
         "absent from this retained member; that source completeness gap remains "
         "explicit and no replacement text is inferred.")
FRAMES = {
    "opening": ("cvw-capture-opening-v5", "start", "start", "cc099c7dc142030b6bc986e544397da805353d6aa71a7c822745c072e187d3c1", "d117840859ae8da890799e0e000dfaf929480ebecf419ae3f33138a406061220"),
    "midpoint": ("cvw-capture-midpoint-v1", "xiii", "src-245", "77c16231aa680e0c934866d628bcb013ea7923b1bd0024faff7e9ff7db8bb286", "8d47d8ca3680e391e94e501b7e57f24388fc6e144a11bd65a30be50710f252ba"),
    "ending": ("cvw-capture-ending-v1", "xix", "src-866", "b6780d404483a6b63e525ecbd2d2d84be0a3e0339c8978ef788193918a599392", "b9c3cccd6c1d05a8b0d3dd91cd1b91d80a72ca6c33323612745396f420f4b8a4"),
}
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"required Watson Contentment evidence is missing: {path}") from exc
    if expected is not None and _sha(content) != expected:
        raise PipelineError(f"Watson Contentment evidence SHA-256 mismatch: {path}")
    return content


def _json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid Watson Contentment JSON: {label}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"Watson Contentment JSON is not an object: {label}")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _copy(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def _check_stage(root: Path, stage: Path) -> Path:
    stage = stage.absolute()
    if stage.exists():
        raise PipelineError(f"Watson Contentment staging root must be fresh: {stage}")
    resolved = stage.resolve()
    for area in (root.resolve(), CANDIDATE.resolve(), PRIOR_CANDIDATE.resolve(), CVW.resolve()):
        if resolved == area or area in resolved.parents or resolved in area.parents:
            raise PipelineError("Watson Contentment stage overlaps a protected input or checkout")
    if not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("Watson Contentment staging parent must be an existing ordinary directory")
    return stage



def _bind_existing_header(original: bytes, acquisition: dict, revision: dict) -> bytes:
    """Add only a revision binding to the candidate's already source-bound header."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    tree = etree.fromstring(original, parser)
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    headers = tree.xpath("./t:teiHeader", namespaces=ns)
    if len(headers) != 1 or headers[0].xpath("./t:revisionDesc", namespaces=ns):
        raise PipelineError("Watson Contentment header has an unexpected revision layout")
    bibls = headers[0].xpath("./t:fileDesc/t:sourceDesc/t:bibl", namespaces=ns)
    if len(bibls) != 1:
        raise PipelineError("Watson Contentment header needs one source bibl")
    bibl = bibls[0]
    facts = {node.get("type"): "".join(node.itertext()).strip()
             for node in bibl.xpath("./t:idno", namespaces=ns)}
    expected = dict(IDENTITY) | {"source_sha256": SOURCE_SHA,
                                 "source_bytes": "293615", "sha256": SOURCE_SHA}
    if (any(facts.get(key) != value for key, value in expected.items())
            or "representation_revision" in facts
            or bibl.xpath("./t:ptr/@target", namespaces=ns) != [acquisition["url"]]
            or bibl.xpath("./t:note[@type='source-location']/text()", namespaces=ns) != [SOURCE.as_posix()]
            or bibl.xpath("./t:note[@type='source-scope']/text()", namespaces=ns) != [SCOPE]):
        raise PipelineError("Watson Contentment existing header differs from bound source authority")
    bibl_end = b"</bibl>"
    header_end = b"</teiHeader>"
    if original.count(bibl_end) != 1 or original.count(header_end) != 1:
        raise PipelineError("Watson Contentment header boundaries are not unique")
    identity_note = ('<idno type="representation_revision">'
                     + escape(revision["id"]) + '</idno>').encode("utf-8")
    change = ('<revisionDesc xmlns="http://www.tei-c.org/ns/1.0"><change xml:id='
              + quoteattr(revision["id"]) + " when=" + quoteattr(revision["date"])
              + ">" + escape(revision["note"]) + "</change></revisionDesc>").encode("utf-8")
    derived = original.replace(bibl_end, identity_note + bibl_end, 1)
    derived = derived.replace(header_end, change + header_end, 1)
    etree.fromstring(derived, parser)
    if derived.replace(identity_note, b"", 1).replace(change, b"", 1) != original:
        raise PipelineError("Watson Contentment header binding changed reviewed bytes")
    return derived


def _preflight(root: Path) -> tuple[dict, dict, dict[str, bytes], bytes]:
    """Verify current bytes and the prior pair's identical TEI before any output."""
    source = _read(resolve_repo_path(root, SOURCE.as_posix()), SOURCE_SHA)
    if len(source) != 293_615:
        raise PipelineError("Watson Contentment source byte count changed")
    manifest_bytes = _read(root / MANIFEST, MANIFEST_SHA)
    manifest = _json(manifest_bytes, "source manifest")
    acquisition = _json(_read(root / ACQUISITION), "acquisition")
    work = _json(_read(root / WORK / "work.json"), "work")
    member = acquisition.get("retained_files", [])
    units = acquisition.get("source_selection", {}).get("units", [])
    if (work.get("work_id") != IDENTITY["work_id"]
            or manifest.get("work_id") != IDENTITY["work_id"]
            or manifest.get("source_id") != "37c-316-watson-divine-contentment-retained-thml-complete-present"
            or acquisition.get("acquisition_id") != IDENTITY["acquisition_id"]
            or acquisition.get("edition_id") != IDENTITY["edition_id"]
            or len(member) != 1
            or any(member[0].get(key) != value for key, value in
                   (("path", SOURCE.as_posix()), ("bytes", len(source)), ("sha256", SOURCE_SHA)))
            or tuple(unit.get("native_id") for unit in units) != PRESENT):
        raise PipelineError("Watson Contentment identity or present-source selection changed")
    receipt_bytes = _read(root / RECEIPT)
    receipt = _json(receipt_bytes, "ticket receipt")
    candidate_binding = receipt.get("candidate", {})
    source_binding = receipt.get("source", {})
    cvw_binding = receipt.get("cvw", {})
    gap = source_binding.get("source_completeness_gap", {})
    if (receipt.get("work_id") != IDENTITY["work_id"]
            or receipt.get("acceptance_status") != "nonaccepted"
            or source_binding.get("sha256") != SOURCE_SHA
            or source_binding.get("source_manifest_sha256") != MANIFEST_SHA
            or tuple(source_binding.get("selected_native_ids", [])) != PRESENT
            or tuple(gap.get("expected_chapters", [])) != ("VI", "VII")
            or tuple(source_binding.get("absent_native_ids", [])) != MISSING
            or candidate_binding.get("candidate_sha256") != PACKAGE_SHA
            or candidate_binding.get("validation_sidecar_sha256") != VALIDATION_SHA
            or candidate_binding.get("validation_report_sha256") != VALIDATION_REPORT_SHA
            or candidate_binding.get("validation_status") != "pass"
            or candidate_binding.get("validation_findings") != []
            or cvw_binding.get("session_id") != SESSION_ID
            or cvw_binding.get("session_receipt_sha256") != SESSION_SHA
            or cvw_binding.get("session_events_sha256") != EVENTS_SHA
            or cvw_binding.get("manual_visual_inspection", {}).get("loci") != list(FRAMES)
            or receipt.get("visual_reuse_basis", {}).get("content_tei_sha256") != TEI_SHA):
        raise PipelineError("Watson Contentment receipt no longer binds this scope and pair")
    ticket = _read(root / TICKET)
    report = _read(root / REPORT)
    for anchor in (SOURCE_SHA, MANIFEST_SHA, PACKAGE_SHA, TEI_SHA, SESSION_ID):
        if anchor.encode() not in report:
            raise PipelineError(f"Watson Contentment report lacks evidence anchor: {anchor}")
    package = CandidatePackage.load(CANDIDATE / "package")
    prior_package = CandidatePackage.load(PRIOR_CANDIDATE / "package")
    original = package.member_bytes("content.tei.xml")
    if (package.sha256 != PACKAGE_SHA or prior_package.sha256 != PRIOR_PACKAGE_SHA
            or _sha(original) != TEI_SHA
            or prior_package.member_bytes("content.tei.xml") != original
            or package.manifest.get("status") != "nonaccepted"
            or package.manifest.get("source_manifest", {}).get("sha256") != MANIFEST_SHA):
        raise PipelineError("Watson Contentment current/prior package binding changed")
    accountability = _json(package.member_bytes("source-accountability.json"), "source accountability")
    source_gap = accountability.get("source_completeness_gap", {})
    if (tuple(item.get("native_id") for item in accountability.get("source_envelope", [])) != PRESENT
            or tuple(source_gap.get("absent_native_ids", [])) != MISSING
            or source_gap.get("disposition") != "unresolved; no replacement text inferred"):
        raise PipelineError("Watson Contentment accounting no longer preserves the source gap")
    validation_bytes = _read(CANDIDATE / "validation.json", VALIDATION_SHA)
    validation = _json(validation_bytes, "validation")
    attestation = validation.get("attestation", {})
    if (validation.get("status") != "pass" or validation.get("findings") != []
            or validation.get("candidate_sha256") != PACKAGE_SHA
            or validation.get("source_manifest_sha256") != MANIFEST_SHA
            or validation.get("report_sha256") != VALIDATION_REPORT_SHA
            or attestation.get("source_sha256") != SOURCE_SHA
            or attestation.get("status") != "pass"):
        raise PipelineError("Watson Contentment validation no longer binds the candidate")
    session_path = CVW / "session" / f"{SESSION_ID}.receipt.json"
    session_bytes = _read(session_path, SESSION_SHA)
    session = _json(session_bytes, "CVW session")
    if session.get("session", {}).get("candidate_sha256") != [PRIOR_PACKAGE_SHA]:
        raise PipelineError("Watson Contentment historical CVW session changed")
    files = {
        "ticket.md": ticket, "report.md": report, "receipt.json": receipt_bytes,
        "source-manifest.json": manifest_bytes, "validation.json": validation_bytes,
        "cvw/session-receipt.json": session_bytes,
        "cvw/events.jsonl": _read(CVW / "session" / f"{SESSION_ID}.events.jsonl", EVENTS_SHA),
        "prior-package-manifest.json": _read(PRIOR_CANDIDATE / "package/manifest.json", PRIOR_PACKAGE_SHA),
    }
    files.update({f"package/{name}": package.member_bytes(name) for name in package.member_names})
    frames = cvw_binding.get("captures", [])
    if len(frames) != len(FRAMES):
        raise PipelineError("Watson Contentment visual evidence must contain three frames")
    for name, (directory_name, source_locus, tei_locus, frame_sha, compare_sha) in FRAMES.items():
        item = next((entry for entry in frames if entry.get("name") == name), None)
        if (item is None or item.get("source_location") != source_locus
                or item.get("tei_location") != tei_locus
                or item.get("frame_sha256") != frame_sha
                or item.get("compare_sha256") != compare_sha):
            raise PipelineError(f"Watson Contentment receipt frame differs: {name}")
        directory = CVW / "captures" / directory_name
        capture_bytes = _read(directory / "capture.json")
        capture = _json(capture_bytes, f"CVW capture {name}")
        route = capture.get("browser_state", {}).get("route", "")
        if (capture.get("session", {}).get("candidate_sha256") != [PRIOR_PACKAGE_SHA]
                or capture.get("session", {}).get("session_id") != SESSION_ID
                or f"leftLocation={source_locus}" not in route
                or f"rightLocation={tei_locus}" not in route
                or "linked=false&correspondence=absent" not in route
                or capture.get("files", {}).get("frame.png") != frame_sha
                or capture.get("files", {}).get("compare.json") != compare_sha
                or capture.get("acceptance") != "not-established"):
            raise PipelineError(f"Watson Contentment capture does not bind the old pair: {name}")
        for member_name, digest in capture["files"].items():
            files[f"cvw/{name}/{member_name}"] = _read(directory / member_name, digest)
        files[f"cvw/{name}/capture.json"] = capture_bytes
    return receipt, acquisition, files, source


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = _check_stage(root, stage)
    receipt, acquisition, files, source_bytes = _preflight(root)
    stage.mkdir()
    evidence = stage / WORK / "integration/ccel-thml-agent-handoff"
    for name, content in files.items():
        _copy(stage, evidence.relative_to(stage) / "inputs" / name, content)
    for relative in (WORK / "work.json", WORK / "state.json", ACQUISITION, TICKET, REPORT):
        _copy(stage, relative, _read(root / relative))
    _copy(stage, SOURCE, source_bytes)
    _copy(stage, MANIFEST, files["source-manifest.json"])
    original = files["package/content.tei.xml"]
    member = acquisition["retained_files"][0]
    source = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                  source_bytes=len(source_bytes), source_scope=acquisition["source_scope"])
    now = datetime.now(timezone.utc)
    revision = dict(id="watson-divine-contentment-ccel-thml-present-source-v1",
                    date=now.date().isoformat(),
                    note="Bind the retained present-source envelope; reviewed TEI text bytes remain unchanged and native ix/x gaps remain open.")
    derived = _bind_existing_header(original, acquisition, revision)
    original_text = original.split(b"</teiHeader>", 1)[1]
    derived_text = derived.split(b"</teiHeader>", 1)[1]
    if original_text != derived_text:
        raise PipelineError("Watson Contentment header derivation changed reviewed TEI text")
    candidate = _copy(stage, evidence.relative_to(stage) / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived Watson Contentment TEI failed vendored XSD: {errors}")
    included = [{key: member[key] for key in ("path", "bytes", "sha256", "scope")} | {"position": 1}]
    scope = dict(kind="edition", declared=SCOPE,
                 expected_members=[dict(path=SOURCE.as_posix(), position=1)],
                 included_members=included, excluded_members=[])
    common = dict(identity=IDENTITY, source=source, candidate=make_file_binding(stage, candidate),
                  scope=SCOPE, accepted_scope=dict(kind="edition", declared=SCOPE),
                  expected_members=scope["expected_members"], included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[],
                  absent_native_carriers=list(MISSING))
    account = evidence / "source-accounting.json"
    account_sha = _sha(files["package/source-accountability.json"])
    _write(account, common | dict(source_sha256=SOURCE_SHA, source_bytes=len(source_bytes),
                                  present_native_carriers=list(PRESENT),
                                  source_completeness_gap=dict(
                                      absent_native_ids=list(MISSING), expected_chapters=["VI", "VII"],
                                      disposition="unresolved; no replacement text inferred"),
                                  original_accountability_sha256=account_sha))
    bindings = {name: make_file_binding(stage, evidence / "inputs" / name) for name in files}
    details = {
        "validation": dict(status="pass", findings=[], sidecar=bindings["validation.json"],
                           validation_report_sha256=VALIDATION_REPORT_SHA),
        "accounting": dict(source_sha256=SOURCE_SHA, original_accountability_sha256=account_sha,
                           original_member=bindings["package/source-accountability.json"],
                           absent_native_carriers=list(MISSING)),
        "fidelity": dict(original_tei_sha256=TEI_SHA, original_text_sha256=_sha(original_text),
                         derived_text_sha256=_sha(derived_text), header_only_derivation=True),
        "reproducibility": dict(original_package_sha256=PACKAGE_SHA,
                                historical_focused_checks=receipt["checks"],
                                no_reconstruction_performed=True),
        "schema": dict(vendored_xsd="ocd_kernel/tei/vendor/xsd/tei_all.xsd", validation_errors=[]),
        "closure": dict(source_manifest_sha256=MANIFEST_SHA, original_package_sha256=PACKAGE_SHA,
                        evidence_files=bindings),
    }
    technical = dict(
        producer=dict(id="ocd-watson-complete-present-thml-to-tei"),
        checker=dict(id="ocd-watson-independent-present-thml-oracle"),
        shared_assumptions=["Producer and oracle share the retained source and manifest; the three visual loci are a partial sample."],
        independent_corroboration="Historical source accounting, independent oracle, mutation checks, clean-process reproduction, passing current validation, and three exact-pair CVW frames bound through identical source and TEI bytes.",
    )
    command = "py -3 -m build.tools.prepare_watson_divine_contentment_acceptance --stage <fresh-external-root>"
    for name in PROOFS:
        path = evidence / f"{name}.json"
        _write(path, common | dict(status="pass", command=command, exit_code=0,
                                   details=details[name]))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    loci = [f"{name}: {FRAMES[name][1]} -> {FRAMES[name][2]}" for name in FRAMES]
    review = dict(
        reviewer="historical:37c-316-three-locus-agent-CVW",
        reviewed_at=max(_json(files[f"cvw/{name}/capture.json"], "capture")["captured_at"]
                        for name in FRAMES).replace("+00:00", "Z"),
        coverage=dict(status="partial", declared=SCOPE, reached=loci, inspected=loci,
                      unreviewed=["All other locations in the retained member"]),
        source_quality_uncertainty=["The underlying print witness and edition lineage are unresolved.",
                                    "Native ix and x and expected chapters VI and VII are absent from the retained source."],
        discrepancies=[],
        unreviewed_residuals=["Three sampled loci do not establish exhaustive visual collation or proofreading.",
                             "CVW panes were unlinked and correspondence was absent; no location match was inferred."],
    )
    _write(evidence / "review.json", common | review | dict(
        historical_cvw_session=bindings["cvw/session-receipt.json"],
        capture_bindings={name: bindings[f"cvw/{name}/capture.json"] for name in FRAMES},
        no_new_pixel_review=True,
        review_basis="The old CVW package and current package contain byte-identical content.tei.xml; the retained source SHA-256 is unchanged. Historical artifact IDs are preserved."))
    decision = dict(
        source_local_disposition="Agent acceptance of the complete present retained CCEL ThML source envelope only; absent chapters remain unresolved.",
        blockers=[],
        agent_assessment=dict(
            status="accepted", actor="agent:watson-divine-contentment-present-source-review",
            assessed_at=now.isoformat().replace("+00:00", "Z"), supported_scope=SCOPE,
            unassessed_stronger_claims=["underlying print work completeness", "absent chapter reconstruction",
                                        "edition identity resolution", "human acceptance", "rights clearance",
                                        "exhaustive visual review", "release", "publication"],
            unresolved_claims=["Native ix and x are absent; expected chapters VI and VII remain missing from this witness."],
        ),
        human_decision=dict(status="not-recorded"),
    )
    record = build_acceptance_record(
        stage, identity=IDENTITY, candidate_path=candidate,
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
