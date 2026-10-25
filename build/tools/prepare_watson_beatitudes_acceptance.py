"""Prepare an exact-route Watson Beatitudes agent-acceptance handoff in a fresh stage."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.sax.saxutils import escape, quoteattr

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/watson-beatitudes")
EDITION = WORK / "forms/watson-beatitudes-route-source-form/editions/watson-beatitudes-retained-thml-route"
ACQUISITION = EDITION / "acquisitions/watson-beatitudes-retained-source.json"
SOURCE = Path("raw/ccel/watson/beatitudes.xml")
MANIFEST = Path("sources/structured-text/watson-beatitudes/watson-beatitudes.source-manifest.json")
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-314-watson-beatitudes.md")
REPORT = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-314.md")
RECEIPT = REPORT.with_name("37c-314-receipt.json")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/37c314-20260919-candidate-v1")
CVW = Path("D:/Library/Open Christian Data/candidate-reviews/37c314-20260919-candidate-v1-evidence")
IDENTITY = dict(
    work_id="watson-beatitudes",
    textual_form_id="watson-beatitudes-route-source-form",
    edition_id="watson-beatitudes-retained-thml-route",
    acquisition_id="watson-beatitudes-retained-source",
)
SOURCE_SHA = "d85ea8ded5de4feff3b2a9156bece9c471ffec3045eb8dc300b2784f5753f837"
WORK_SHA = "751da848bf3d2a837ddf0a8cac3d61e1180555f253a6bcd6c0ac152821526003"
ACQUISITION_SHA = "839eb297426c1ff07ea81502572d663829a77f01f392ee749c0779a46a44403c"
MANIFEST_SHA = "8598d6562f80487911e6f4aa29793d9f063aa1c0201ad317c541838c1431819a"
PACKAGE_SHA = "f5a38c221caf112a9088c866a582f963e3fb9d26abaa8f37982d6a390e0be411"
TEI_SHA = "6fcf25f7fc12af921654febac977f8dcecd76bce7f9f3eeac89f36cfc066e1c7"
VALIDATION_SHA = "b6e20dc4c824475028a3c8175f886ce2601d479943b8994cec9edbc17741e6db"
VALIDATION_REPORT_SHA = "2317f847787ac5f12fb5fe27300650e6f95f1668e5e31ac61dab4501e98a02ef"
TICKET_SHA = "8e3dfcb7f1178c5e3a7b588f4de28fe3baebfb7a7c2c3499e407e0633eb100b5"
REPORT_SHA = "82a2b09ed4529cbaee3480dc54d81af4dc397be86102d5e654bd429f89b78958"
ORACLE_SHA = "6dc00660c57e008755d7029ffbb0990db25bd8702db517edfa6b52c12c5e60b8"
SELECTION_ID = "watson-beatitudes-all-direct-div1-route-envelope-v1"
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")
FRAMES = {
    "front-matter": ("visual-postfix-20260919-v1/01-front-matter-reference", "i", "src-1", 0, 0,
                     "e8864091f56ae517b74d0901ea3a3c2762898e5212cb2160aee3064e421b3b13",
                     "20aa0fbbd68903df5fb1b78d2d9d1608c2de8dc0b848adad9cab951261cb4907"),
    "opening-body": ("20260920-completion-visual/01-opening-body-prose", "iii", "src-14", 0, 0,
                     "be7803358394812e588a5d58d65d866eb65a13c9a8257e906105abaf02f6a8a8",
                     "d53800145af3f17ee2da951bce9fab14a0c84f722eac9577b75ade716ed7f425"),
    "middle-body": ("visual-postfix-20260919-v1/03-middle-body-prose", "xvii", "src-1229", 6, 6,
                    "f13b6faa9a4336712ca914385d6c4b81e2cbd829d409916a33c722f830d6868c",
                    "356c92df823dbfa08e1dc180ff51261e7079fb89694a0937bf11376039e97590"),
    "back-index": ("20260920-completion-visual/02-back-matter-index", "xxv", "src-3056", 15, 15,
                   "8fde552b4442802f0cd62b58471c5fc949b95279e2546a818f7dffc16b92da21",
                   "0109d0d4969428256f41a06f37af1d2e3f5ac7bc47d4d52d445300048fa6ffd1"),
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"required Beatitudes evidence is unavailable: {path}") from exc
    if expected is not None and _sha(content) != expected:
        raise PipelineError(f"Beatitudes evidence SHA-256 mismatch: {path}")
    return content


def _json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid Beatitudes JSON: {label}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"Beatitudes JSON is not an object: {label}")
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
    if stage.exists() or stage.is_symlink():
        raise PipelineError(f"Beatitudes staging root must be fresh: {stage}")
    resolved = stage.resolve()
    for area in (root.resolve(), CANDIDATE.resolve(), CVW.resolve()):
        if resolved == area or area in resolved.parents or resolved in area.parents:
            raise PipelineError("Beatitudes stage overlaps checkout or protected evidence")
    if not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("Beatitudes stage parent must be an existing ordinary directory")
    return stage


def _derived(original: bytes, revision: dict[str, str]) -> bytes:
    if original.count(b"</bibl>") != 1 or original.count(b"</teiHeader>") != 1:
        raise PipelineError("Beatitudes TEI header boundary is ambiguous")
    identity_note = (
        '<idno type="representation_revision">' + escape(revision["id"]) + "</idno>"
    ).encode("utf-8")
    change = (
        '<revisionDesc xmlns="http://www.tei-c.org/ns/1.0"><change xml:id='
        + quoteattr(revision["id"]) + " when=" + quoteattr(revision["date"])
        + ">" + escape(revision["note"]) + "</change></revisionDesc>"
    ).encode("utf-8")
    return original.replace(b"</bibl>", identity_note + b"</bibl>", 1).replace(
        b"</teiHeader>", change + b"</teiHeader>", 1
    )


def _preflight(root: Path) -> tuple[dict, dict, dict[str, bytes], bytes]:
    source = _read(resolve_repo_path(root, SOURCE.as_posix()), SOURCE_SHA)
    _read(root / WORK / "work.json", WORK_SHA)
    acquisition_bytes = _read(root / ACQUISITION, ACQUISITION_SHA)
    acquisition = _json(acquisition_bytes, "acquisition")
    manifest_bytes = _read(root / MANIFEST, MANIFEST_SHA)
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    selection = acquisition.get("source_selection", {})
    units = selection.get("units", [])
    if (
        acquisition.get("acquisition_id") != IDENTITY["acquisition_id"]
        or acquisition.get("edition_id") != IDENTITY["edition_id"]
        or acquisition.get("source_path") != SOURCE.as_posix()
        or acquisition.get("source_sha256") != SOURCE_SHA
        or acquisition.get("source_bytes") != len(source)
        or selection.get("selection_id") != SELECTION_ID
        or selection.get("member_path") != SOURCE.as_posix()
        or len(units) != 25
        or len({item.get("native_id") for item in units}) != 25
        or len(acquisition.get("retained_files", [])) != 1
    ):
        raise PipelineError("Beatitudes acquisition does not bind the exact source envelope")
    member = acquisition["retained_files"][0]
    if any(member.get(key) != value for key, value in (
        ("path", SOURCE.as_posix()), ("sha256", SOURCE_SHA), ("bytes", len(source))
    )):
        raise PipelineError("Beatitudes retained member binding differs")
    if manifest.record.get("work_id") != IDENTITY["work_id"] or manifest.record["validator"].get("implementation_sha256") != ORACLE_SHA:
        raise PipelineError("Beatitudes manifest route or oracle differs")
    ticket = _read(root / TICKET, TICKET_SHA)
    report = _read(root / REPORT, REPORT_SHA)
    receipt_bytes = _read(root / RECEIPT)
    receipt = _json(receipt_bytes, "ticket receipt")
    route = receipt.get("route", {})
    handoff = receipt.get("changed_scope", {}).get("candidate_handoff", {})
    cvw = receipt.get("cvw_visual_review_completion_2026_09_20", {})
    if (
        receipt.get("work_id") != IDENTITY["work_id"]
        or receipt.get("status") != "technical-complete"
        or route.get("current_manifest_sha256") != MANIFEST_SHA
        or handoff.get("candidate_sha256") != PACKAGE_SHA
        or handoff.get("validation_report_sha256") != VALIDATION_REPORT_SHA
        or handoff.get("validation_sidecar_sha256") != VALIDATION_SHA
        or handoff.get("acceptance_status") != "nonaccepted"
        or cvw.get("status") != "pass_four_declared_exact_pairs_visually_inspected"
        or cvw.get("source_sha256") != SOURCE_SHA
        or cvw.get("source_manifest_sha256") != MANIFEST_SHA
        or cvw.get("candidate_package_sha256") != PACKAGE_SHA
        or cvw.get("tei_member_sha256") != TEI_SHA
        or cvw.get("unique_locus_count") != 4
        or cvw.get("visually_inspected_locus_count") != 4
        or cvw.get("comparison_linked") is not False
        or cvw.get("correspondence") != "absent"
        or cvw.get("capture_blocker") is not None
    ):
        raise PipelineError("Beatitudes receipt no longer binds the exact technical route")
    for anchor in (SOURCE_SHA, MANIFEST_SHA, PACKAGE_SHA, TEI_SHA):
        if anchor.encode() not in report or anchor.encode() not in receipt_bytes:
            raise PipelineError(f"Beatitudes report or receipt lacks evidence anchor: {anchor}")
    if b"37c-314" not in ticket:
        raise PipelineError("Beatitudes ticket identity differs")
    package = CandidatePackage.load(CANDIDATE / "package")
    original = package.member_bytes("content.tei.xml")
    if package.sha256 != PACKAGE_SHA or _sha(original) != TEI_SHA or package.manifest.get("status") != "nonaccepted":
        raise PipelineError("Beatitudes candidate package differs")
    from ocd_kernel.tei.acceptance import _beatitudes_oracle

    validate(manifest, package, _beatitudes_oracle())
    validation_bytes = _read(CANDIDATE / "validation.json", VALIDATION_SHA)
    validation = _json(validation_bytes, "validation")
    if (
        validation.get("status") != "pass"
        or validation.get("findings") != []
        or validation.get("candidate_sha256") != PACKAGE_SHA
        or validation.get("source_manifest_sha256") != MANIFEST_SHA
        or validation.get("report_sha256") != VALIDATION_REPORT_SHA
        or validation.get("attestation", {}).get("source_sha256") != SOURCE_SHA
        or validation.get("attestation", {}).get("implementation_sha256") != ORACLE_SHA
    ):
        raise PipelineError("Beatitudes validation sidecar differs")
    files = {
        "ticket.md": ticket,
        "report.md": report,
        "receipt.json": receipt_bytes,
        "source-manifest.json": manifest_bytes,
        "validation.json": validation_bytes,
    }
    files.update({f"package/{name}": package.member_bytes(name) for name in package.member_names})
    files["package/manifest.json"] = _read(CANDIDATE / "package/manifest.json", PACKAGE_SHA)
    pairs = cvw.get("pairs", [])
    if len(pairs) != len(FRAMES):
        raise PipelineError("Beatitudes receipt must declare four exact CVW pairs")
    for name, (directory, source_id, tei_id, left_page, right_page, frame_sha, capture_sha) in FRAMES.items():
        pair = next((item for item in pairs if item.get("source_carrier") == source_id), None)
        if (
            pair is None or pair.get("tei_anchor") != tei_id
            or pair.get("source_segment") != left_page
            or pair.get("tei_segment") != right_page
            or pair.get("frame_sha256", frame_sha) != frame_sha
            or pair.get("capture_json_sha256", capture_sha) != capture_sha
            or Path(pair.get("evidence_path", "")).resolve() != (CVW / directory).resolve()
        ):
            raise PipelineError(f"Beatitudes CVW receipt pair differs: {name}")
        capture_dir = CVW / directory
        capture_bytes = _read(capture_dir / "capture.json", capture_sha)
        capture = _json(capture_bytes, f"CVW capture {name}")
        route = parse_qs(urlsplit(capture.get("browser_state", {}).get("route", "")).query)
        expected_route = {
            "leftLocation": source_id,
            "rightLocation": tei_id,
            "leftArtifact": f"source-{MANIFEST_SHA}",
            "rightArtifact": f"tei-{PACKAGE_SHA}",
            "linked": "false",
            "correspondence": "absent",
        }
        if any(route.get(key) != [value] for key, value in expected_route.items()):
            raise PipelineError(f"Beatitudes CVW capture route differs: {name}")
        if capture.get("session", {}).get("candidate_sha256") != [PACKAGE_SHA] or capture.get("files", {}).get("frame.png") != frame_sha or capture.get("page_errors") != [] or capture.get("acceptance") != "not-established":
            raise PipelineError(f"Beatitudes CVW capture binding differs: {name}")
        for file_name, digest in capture["files"].items():
            files[f"cvw/{name}/{file_name}"] = _read(capture_dir / file_name, digest)
        files[f"cvw/{name}/capture.json"] = capture_bytes
    files["cvw/completion-session.json"] = _read(
        Path(cvw["session_receipt_path"]), cvw["session_receipt_sha256"]
    )
    files["cvw/completion-events.jsonl"] = _read(
        Path(cvw["session_events_path"]), cvw["session_events_sha256"]
    )
    return receipt, acquisition, files, source


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = _check_stage(root, stage)
    receipt, acquisition, files, source_bytes = _preflight(root)
    stage.mkdir()
    evidence = stage / WORK / "integration/ccel-thml-agent-handoff"
    for name, content in files.items():
        _copy(stage, evidence.relative_to(stage) / "inputs" / name, content)
    _copy(stage, TICKET, files["ticket.md"])
    _copy(stage, REPORT, files["report.md"])
    for relative, expected in ((WORK / "work.json", WORK_SHA), (ACQUISITION, ACQUISITION_SHA)):
        _copy(stage, relative, _read(root / relative, expected))
    for relative in (WORK / "state.json",):
        _copy(stage, relative, _read(root / relative))
    _copy(stage, SOURCE, source_bytes)
    _copy(stage, MANIFEST, files["source-manifest.json"])
    now = datetime.now(timezone.utc)
    revision = dict(
        id="watson-beatitudes-retained-thml-route-source-v1",
        date=now.date().isoformat(),
        note="Bind only the exact retained ThML route envelope; source form and edition identity remain unresolved.",
    )
    original = files["package/content.tei.xml"]
    derived = _derived(original, revision)
    if original.split(b"</teiHeader>", 1)[1] != derived.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Beatitudes revision derivation changed TEI text")
    candidate = _copy(stage, evidence.relative_to(stage) / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived Beatitudes TEI failed vendored XSD: {errors}")
    member = acquisition["retained_files"][0]
    scope_text = acquisition["source_scope"]
    included = [{key: member[key] for key in ("path", "bytes", "sha256", "scope")} | {"position": 1}]
    expected = [{"path": SOURCE.as_posix(), "position": 1}]
    scope = dict(kind="selection", declared=scope_text, expected_members=expected,
                 included_members=included, excluded_members=[])
    source = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                  source_bytes=len(source_bytes), source_scope=scope_text)
    common = dict(identity=IDENTITY, source=source, candidate=make_file_binding(stage, candidate),
                  scope=scope_text, accepted_scope=dict(kind="selection", declared=scope_text),
                  expected_members=expected, included_members=included, excluded_members=[],
                  missing_members=[], unknown_members=[])
    account = evidence / "source-accounting.json"
    _write(account, common | dict(source_sha256=SOURCE_SHA, source_bytes=len(source_bytes),
                                  selected_native_carriers=[item["native_id"] for item in acquisition["source_selection"]["units"]],
                                  original_accountability_sha256=_sha(files["package/source-accountability.json"])))
    bindings = {name: make_file_binding(stage, evidence / "inputs" / name) for name in files}
    details = {
        "validation": dict(status="pass", findings=[], sidecar=bindings["validation.json"],
                           report_sha256=VALIDATION_REPORT_SHA),
        "accounting": dict(source_sha256=SOURCE_SHA, original_member=bindings["package/source-accountability.json"],
                           selected_carrier_count=25),
        "fidelity": dict(original_tei_sha256=TEI_SHA, derived_tei_sha256=_sha(derived),
                         header_only_derivation=True),
        "reproducibility": dict(original_package_sha256=PACKAGE_SHA,
                                historical_checks=receipt["checks"], no_reconstruction_performed=True),
        "schema": dict(vendored_xsd="ocd_kernel/tei/vendor/xsd/tei_all.xsd", validation_errors=[]),
        "closure": dict(source_manifest_sha256=MANIFEST_SHA, original_package_sha256=PACKAGE_SHA,
                        evidence_files=bindings),
    }
    technical = dict(
        producer=dict(id="ocd-watson-beatitudes-selected-thml-route"),
        checker=dict(id="ocd-watson-beatitudes-independent-source-walk"),
        shared_assumptions=["Producer and oracle share the retained member and source manifest; visual inspection covers four sampled loci."],
        independent_corroboration="Historical source-led accounting, independent oracle and mutations, reproducible package, passing validation, and four exact-pair CVW captures; this stage adds a header-only revision.",
    )
    command = "py -3 -m build.tools.prepare_watson_beatitudes_acceptance --stage <fresh-external-root>"
    for name in PROOFS:
        proof = evidence / f"{name}.json"
        _write(proof, common | dict(status="pass", command=command, exit_code=0, details=details[name]))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    loci = [f"{item[1]} -> {item[2]}" for item in FRAMES.values()]
    review = dict(
        reviewer="historical:37c-314-four-locus-agent-CVW",
        reviewed_at=receipt["cvw_visual_review_completion_2026_09_20"]["observed_at_utc"],
        coverage=dict(status="partial", declared=scope_text, reached=loci, inspected=loci,
                      unreviewed=["All other locations in the retained member"]),
        source_quality_uncertainty=["Bibliographic work, constituent part, form, edition, and witness identity remain unresolved."],
        discrepancies=[],
        unreviewed_residuals=["Four inspected pairs do not establish exhaustive proofreading or visual collation.",
                             "CVW panes were unlinked and correspondence was absent; no match was inferred."],
    )
    _write(evidence / "review.json", common | review | dict(
        capture_bindings={name: bindings[f"cvw/{name}/capture.json"] for name in FRAMES},
        no_new_pixel_review=True,
        route_coordinate_limitation="The historical machine xxv right coordinate 17 differs from the rendered Compare segment 15 for src-3056.",
        review_basis="The four historical captures bind the unchanged source, manifest, package, and original TEI. The staged revision changes only the TEI header.",
    ))
    decision = dict(
        source_local_disposition="Agent acceptance only of the exact declared retained-source route and its 25 ordered direct div1 carriers.",
        blockers=[],
        agent_assessment=dict(
            status="accepted", actor="agent:watson-beatitudes-exact-route-review",
            assessed_at=now.isoformat().replace("+00:00", "Z"), supported_scope=scope_text,
            unassessed_stronger_claims=["bibliographic work identity", "constituent-part identity",
                                        "textual-form or translation identity", "edition identity", "witness identity",
                                        "human acceptance", "rights clearance", "exhaustive visual review",
                                        "integration", "release", "publication"],
            unresolved_claims=["The source envelope and route binder do not settle bibliographic identity or metadata adoption."],
        ),
        human_decision=dict(status="not-recorded"),
    )
    record = build_acceptance_record(
        stage, identity=IDENTITY, candidate_path=candidate, source_accounting_path=account,
        scope=scope, technical=technical, review=review | dict(report_path=evidence / "review.json"),
        representation_revision=revision, decision=decision,
    )
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
