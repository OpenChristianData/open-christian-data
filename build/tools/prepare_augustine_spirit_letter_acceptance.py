"""Stage, without installing, Augustine's exact current Phase A TEI acceptance."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tei.selected_thml_oracle import _oracle
from cvw_app.capture_review import verify_bundle
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.selected_thml_check import check_selected_thml
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/augustine-spirit-and-letter")
EDITION = WORK / "forms/augustine-spirit-and-letter-english/editions/augustine-spirit-and-letter-ccel"
ACQUISITION = EDITION / "acquisitions/augustine-spirit-and-letter-retained.json"
SOURCE = Path("raw/ccel/npnf1/npnf105.xml")
MANIFEST = Path("sources/work-units-phase-a/augustine-spirit-and-letter/source-manifest.json")
STATE_EVIDENCE = {
    Path("sources/work-units-phase-a/augustine-spirit-and-letter/README.md"):
        "990166d73ed7f7b588387c6d6c23418501fda125dc9834044a219a4a840c908e",
    Path("metadata/source-evidence/catalog/augustine-spirit-and-letter.json"):
        "c2d4faa0edf2b08556eb5dfb387a3c4e88167657812c44009791c548f0c26943",
}
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37a-05-augustine-spirit-and-letter.md")
REPORT = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-07-cohort22/reviews/37a-05-phase-a-20260924.md")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/source-to-tei-current-library-21-20260923/augustine-spirit-and-letter-contents-credit")
REPLAY = CANDIDATE.with_name(CANDIDATE.name + "-replay")
CAPTURES = Path("D:/Library/Open Christian Data/candidate-reviews/37a-05-phase-a-cvw-captures-20260924")
IDENTITY = dict(
    work_id="augustine-spirit-and-letter",
    textual_form_id="augustine-spirit-and-letter-english",
    edition_id="augustine-spirit-and-letter-ccel",
    acquisition_id="augustine-spirit-and-letter-retained",
)
SOURCE_SHA = "224f0e6a188ddfe691c1433c8db9a883755a9f030b71fede644d4af6c18ee63f"
ACQUISITION_SHA = "7106c59c00fe342c1d8d9083a6b3ee0f0666984b86338d9a34aa3541b879aabc"
MANIFEST_SHA = "b40ce765ce2586689eda65addf09e3102df712bb2c088749022d66ab093961f7"
PACKAGE_SHA = "8b241e4b950398faff886a2c5ac53abd405471844bbcaa7a66fa509eb82b51d9"
TEI_SHA = "9e42edb811009f3b6cfb03278d125e27c66376e58fd5b2028aff25a6b04cc88f"
ACCOUNT_SHA = "e8356a8c5792712d28fa3a8c4a0609e8e23fa12de13c2ccfc2ee9805946352c1"
VALIDATION_SHA = "f72b966507149edfaf75447737d0deca10e6408c63bf50765bcf41e184e41431"
VALIDATION_REPORT_SHA = "63df9258afb8bf4f62f2dabbe0517abceca417412ec567b196ec59b60477e62c"
REPORT_SHA = "cd06e8d9ffc6114c7245487588ca847411909859468c2f465f43a549ff0f919b"
SESSION_ID = "ad98b14518ef4aea9c353b26d852a8b0"
IMPLEMENTATION_SHA = "939675c889b21666b5a31171ac429e76c0c46f573e04dc3e27e9a275ba99a3c5"
SELECTION_SHA = "26991d831fc311417abf80b755244599ceb23ccaf009696e91e394a38a04cfdd"
SCOPE = "xi (body); shared credits: ii-p2, ii-p3, ii-p7, ii-p9, ii-p10, ix-p14, iii-p15, iii-p74 (contents allocation for this work)"
REVISION_ID = "augustine-spirit-letter-ccel-phase-a-header-v1"
PROOFS = ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure")
FRAMES = {
    "xi": ("xi", "src-1", "3bcc0abe08490c655a7b919df08ae5fe744ead94ee66dabd58ae4d4663863599", "d35faf1ebd7c641e722e8a754610c399d2d9162cf0acf8166d472f34815a1086"),
    "xi.iv": ("xi.iv", "src-52", "1e242488f9f390cfba99c7a8bf392c83c1331510c14bab49cd165561f041a01e", "426f77f2d3b7359103194e4cd8fcb74317492a70676743b1add99b32ce5f585c"),
    "xi.xxxv": ("xi.xxxv", "src-647", "169a4193cbf9c7470e446b32f3058b88bfa1b8c00f8a23ad6df37e74af39aa17", "57c3acdebbf8d2cfa51c8969e859b72a40f41de3410286b087e91fbff350bbcd"),
    "xi.lxix": ("xi.lxix", "src-1625", "2b27e07eba52ebe94a3c385a1b241eb740f9344df3422f685f20465a7d86f085", "37712ba37d75712ff384874212506489e1934a802de1abea171c1c06b2fbb8f4"),
    "xi.lxix-ending-v3": ("xi.lxix", "src-1625", "2fc66eadd14da9661198d8f46402286366d062d587dd332722a2be0c992f0250", "05ee044880b2b388545596eb7b997336b7471a40e1c3207668d556722a8a57d7"),
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"required Augustine evidence is missing: {path}") from exc
    if expected is not None and _sha(content) != expected:
        raise PipelineError(f"Augustine evidence SHA-256 mismatch: {path}")
    return content


def _json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid Augustine JSON: {label}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"Augustine JSON is not an object: {label}")
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
        raise PipelineError(f"Augustine staging root must be fresh: {stage}")
    resolved = stage.resolve()
    for protected in (root.resolve(), CANDIDATE.resolve(), REPLAY.resolve(), CAPTURES.resolve()):
        if resolved == protected or protected in resolved.parents or resolved in protected.parents:
            raise PipelineError("Augustine staging root overlaps protected input")
    if not stage.parent.is_dir() or stage.parent.is_symlink():
        raise PipelineError("Augustine staging parent must be an existing ordinary directory")
    return stage


def _revision_only(original: bytes, revision: dict[str, str], source_url: str) -> bytes:
    """Add only the missing acceptance revision to the already source-bound header."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    tree = etree.fromstring(original, parser)
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    headers = tree.xpath("./t:teiHeader", namespaces=ns)
    if len(headers) != 1 or headers[0].xpath("./t:revisionDesc", namespaces=ns):
        raise PipelineError("Augustine reviewed TEI header already has revision history")
    bibl = headers[0].xpath("./t:fileDesc/t:sourceDesc/t:bibl", namespaces=ns)
    if len(bibl) != 1:
        raise PipelineError("Augustine reviewed source description is ambiguous")
    required = dict(IDENTITY) | {"source_sha256": SOURCE_SHA, "source_bytes": "4501690", "sha256": SOURCE_SHA, "source_selection_sha256": SELECTION_SHA}
    for kind, expected in required.items():
        nodes = bibl[0].xpath("./t:idno[@type=$kind]", namespaces=ns, kind=kind)
        if len(nodes) != 1 or "".join(nodes[0].itertext()) != expected:
            raise PipelineError(f"Augustine reviewed header {kind} differs")
    for kind, expected in (("source-location", SOURCE.as_posix()), ("source-scope", SCOPE)):
        nodes = bibl[0].xpath("./t:note[@type=$kind]", namespaces=ns, kind=kind)
        if len(nodes) != 1 or "".join(nodes[0].itertext()) != expected:
            raise PipelineError(f"Augustine reviewed header {kind} differs")
    if bibl[0].xpath("./t:ptr/@target", namespaces=ns) != [source_url]:
        raise PipelineError("Augustine reviewed source URL differs")
    if bibl[0].xpath("./t:idno[@type='representation_revision']", namespaces=ns):
        raise PipelineError("Augustine reviewed TEI already has a representation revision")
    close_bibl = b"</bibl></sourceDesc>"
    close_header = b"</teiHeader>"
    if original.count(close_bibl) != 1 or original.count(close_header) != 1:
        raise PipelineError("Augustine reviewed header byte boundaries are ambiguous")
    idno = f'<idno type="representation_revision">{revision["id"]}</idno>'.encode()
    change = (f'<revisionDesc><change xml:id="{revision["id"]}" when="{revision["date"]}">'
              f'{revision["note"]}</change></revisionDesc>').encode()
    derived = original.replace(close_bibl, idno + close_bibl, 1).replace(close_header, change + close_header, 1)
    etree.fromstring(derived, parser)
    if derived.replace(idno, b"", 1).replace(change, b"", 1) != original:
        raise PipelineError("Augustine header derivation altered reviewed TEI bytes")
    return derived


def _visual_inputs(root: Path, report: bytes) -> tuple[dict[str, bytes], str]:
    files: dict[str, bytes] = {}
    captured_at = ""
    for name, (source_locus, tei_locus, capture_sha, frame_sha) in FRAMES.items():
        directory = CAPTURES / name
        capture_bytes = _read(directory / "capture.json", capture_sha)
        try:
            capture = verify_bundle(directory)
        except (OSError, ValueError, KeyError) as exc:
            raise PipelineError(f"Augustine CVW bundle is invalid: {name}") from exc
        route = capture.get("browser_state", {}).get("route", "")
        comparison = _json(_read(directory / "compare.json", capture["files"]["compare.json"]), f"compare {name}")
        session = _json(_read(directory / "session.json", capture["files"]["session.json"]), f"session {name}")
        if (capture.get("session", {}).get("session_id") != SESSION_ID
                or capture.get("session", {}).get("candidate_sha256") != [PACKAGE_SHA]
                or capture.get("session", {}).get("implementation_sha256") != IMPLEMENTATION_SHA
                or session.get("session", {}).get("session_id") != SESSION_ID
                or session.get("session", {}).get("state") != "ready"
                or comparison.get("left", {}).get("artifact", {}).get("sha256") != SOURCE_SHA
                or comparison.get("right", {}).get("artifact", {}).get("sha256") != TEI_SHA
                or comparison.get("left", {}).get("location", {}).get("value") != source_locus
                or comparison.get("right", {}).get("location", {}).get("value") != tei_locus
                or f"source-{MANIFEST_SHA}" not in route
                or f"tei-{PACKAGE_SHA}" not in route
                or f"leftLocation={source_locus}" not in route
                or f"rightLocation={tei_locus}" not in route
                or capture.get("files", {}).get("frame.png") != frame_sha
                or capture.get("page_errors") != []
                or capture.get("acceptance") != "not-established"
                or frame_sha.encode() not in report):
            raise PipelineError(f"Augustine CVW capture does not bind exact reviewed pair: {name}")
        if name.endswith("ending-v3") and not all(
            capture.get("targets", {}).get(side, {}).get("visible") is True
            for side in ("left", "right")
        ):
            raise PipelineError("Augustine final text was not visibly targeted in both panes")
        frame = _read(directory / "frame.png", frame_sha)
        if not frame.startswith(b"\x89PNG\r\n\x1a\n") or capture.get("image_dimensions") != [1440, 1000]:
            raise PipelineError(f"Augustine visual frame is not the expected PNG: {name}")
        for member in ("frame.png", "compare.json", "session.json"):
            files[f"cvw/{name}/{member}"] = _read(directory / member, capture["files"][member])
        files[f"cvw/{name}/capture.json"] = capture_bytes
        captured_at = max(captured_at, capture["captured_at"])
    return files, captured_at


def _preflight(root: Path) -> tuple[dict, dict[str, bytes], str, dict]:
    source = _read(resolve_repo_path(root, SOURCE.as_posix()), SOURCE_SHA)
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    manifest.verify()
    if manifest.sha256 != MANIFEST_SHA or len(source) != 4_501_690 or manifest.record.get("work_id") != IDENTITY["work_id"]:
        raise PipelineError("Augustine source authority differs from reviewed Phase A selection")
    acquisition = _json(_read(root / ACQUISITION, ACQUISITION_SHA), "acquisition")
    selection = acquisition.get("source_selection", {})
    member = acquisition.get("retained_files", [])
    if (acquisition.get("acquisition_id") != IDENTITY["acquisition_id"]
            or acquisition.get("edition_id") != IDENTITY["edition_id"]
            or acquisition.get("source_scope") != SCOPE
            or selection.get("selection_id") != "augustine-spirit-and-letter-selection-v1"
            or selection.get("member_path") != SOURCE.as_posix()
            or [unit.get("native_id") for unit in selection.get("units", [])] != ["xi"]
            or [unit.get("native_id") for unit in selection.get("dependencies", [])] != ["ii-p2", "ii-p3", "ii-p7", "ii-p9", "ii-p10", "ix-p14", "iii-p15", "iii-p74"]
            or len(member) != 1
            or any(member[0].get(key) != value for key, value in (("path", SOURCE.as_posix()), ("bytes", len(source)), ("sha256", SOURCE_SHA)))):
        raise PipelineError("Augustine acquisition selection or identity differs")
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
        raise PipelineError("Augustine candidate or validation differs from reviewed pair")
    report = _read(root / REPORT, REPORT_SHA)
    if any(anchor.encode() not in report for anchor in (SOURCE_SHA, MANIFEST_SHA, PACKAGE_SHA, TEI_SHA, SESSION_ID)):
        raise PipelineError("Augustine current-pair report lacks exact evidence anchors")
    visual_files, captured_at = _visual_inputs(root, report)
    replay_files = ["package/manifest.json", *(f"package/{name}" for name in package.member_names), "validation.json"]
    replay_hashes = {}
    for name in replay_files:
        current = _read(CANDIDATE / name)
        replay = _read(REPLAY / name)
        if current != replay:
            raise PipelineError(f"Augustine clean-process replay differs: {name}")
        replay_hashes[name] = _sha(current)
    fresh_report = validate(manifest, package, _oracle)
    checked = check_selected_thml(root, acquisition, work, CANDIDATE / "package/content.tei.xml")
    if (fresh_report.status != "pass" or fresh_report.sha256 != VALIDATION_REPORT_SHA
            or checked.get("status") != "pass" or checked.get("checked_elements") != 1653
            or checked.get("selection_sha256") != SELECTION_SHA):
        raise PipelineError("Augustine current source-bound fidelity checks differ")
    files = {"ticket.md": _read(root / TICKET), "report.md": report,
             "source-manifest.json": _read(root / MANIFEST, MANIFEST_SHA),
             "acquisition.json": _read(root / ACQUISITION, ACQUISITION_SHA),
             "validation.json": validation_bytes}
    files.update({f"package/{name}": package.member_bytes(name) for name in package.member_names})
    files["package/manifest.json"] = _read(CANDIDATE / "package/manifest.json", PACKAGE_SHA)
    files.update(visual_files)
    return acquisition, files, captured_at, replay_hashes


def prepare(root: Path, stage: Path) -> Path:
    root = root.resolve(strict=True)
    stage = _stage_path(root, stage)
    state_evidence = {
        relative: _read(root / relative, expected)
        for relative, expected in STATE_EVIDENCE.items()
    }
    acquisition, files, captured_at, replay_hashes = _preflight(root)
    stage.mkdir()
    evidence = stage / WORK / "integration/phase-a-agent-handoff"
    for name, content in files.items():
        _copy(stage, evidence.relative_to(stage) / "inputs" / name, content)
    for relative in (WORK / "work.json", WORK / "state.json", ACQUISITION, TICKET, REPORT):
        _copy(stage, relative, _read(root / relative))
    for relative, content in state_evidence.items():
        staged = _copy(stage, relative, content)
        if _read(staged, STATE_EVIDENCE[relative]) != content:
            raise PipelineError(f"staged Augustine state evidence differs: {relative}")
    _copy(stage, SOURCE, _read(resolve_repo_path(root, SOURCE.as_posix()), SOURCE_SHA))
    _copy(stage, MANIFEST, files["source-manifest.json"])
    now = datetime.now(timezone.utc)
    revision = dict(id=REVISION_ID, date=now.date().isoformat(),
                    note="Bind the accepted Phase A CCEL source selection; reviewed TEI text unchanged.")
    original = files["package/content.tei.xml"]
    derived = _revision_only(original, revision, acquisition["url"])
    if original.split(b"</teiHeader>", 1)[1] != derived.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Augustine revision changed reviewed TEI text bytes")
    candidate = _copy(stage, evidence.relative_to(stage) / "candidate.tei.xml", derived)
    errors = validate_file(candidate)
    if errors:
        raise PipelineError(f"derived Augustine TEI failed vendored XSD: {errors}")
    member = acquisition["retained_files"][0]
    included = [dict(path=member["path"], bytes=member["bytes"], sha256=member["sha256"],
                     scope=SCOPE, position=1)]
    scope = dict(kind="edition", declared=SCOPE,
                 expected_members=[dict(path=SOURCE.as_posix(), position=1)],
                 included_members=included, excluded_members=[])
    source = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                  source_bytes=member["bytes"], source_scope=SCOPE)
    common = dict(identity=IDENTITY, source=source, candidate=make_file_binding(stage, candidate),
                  scope=SCOPE, accepted_scope=dict(kind="edition", declared=SCOPE),
                  expected_members=scope["expected_members"], included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = evidence / "source-accounting.json"
    _write(account, common | dict(source_sha256=SOURCE_SHA, source_bytes=member["bytes"],
                                  original_accountability_sha256=ACCOUNT_SHA))
    bindings = {name: make_file_binding(stage, evidence / "inputs" / name) for name in files}
    details = {
        "validation": dict(status="pass", findings=[], original_report_sha256=VALIDATION_REPORT_SHA,
                           sidecar=bindings["validation.json"], fresh_oracle_replayed=True),
        "accounting": dict(selection_sha256=SELECTION_SHA, checked_elements=1653,
                           original_accountability_sha256=ACCOUNT_SHA,
                           original_member=bindings["package/source-accountability.json"]),
        "fidelity": dict(original_tei_sha256=TEI_SHA,
                         original_text_sha256=_sha(original.split(b"</teiHeader>", 1)[1]),
                         derived_text_sha256=_sha(derived.split(b"</teiHeader>", 1)[1]),
                         header_only_derivation=True),
        "reproducibility": dict(original_package_sha256=PACKAGE_SHA,
                                clean_process_replay_member_sha256=replay_hashes,
                                no_reconstruction_performed=True),
        "schema": dict(vendored_xsd="ocd_kernel/tei/vendor/xsd/tei_all.xsd", validation_errors=[]),
        "closure": dict(source_manifest_sha256=MANIFEST_SHA, original_package_sha256=PACKAGE_SHA,
                        evidence_files=bindings),
    }
    command = "py -3 -m build.tools.prepare_augustine_spirit_letter_acceptance --stage <fresh-external-root>"
    technical = dict(
        producer=dict(id="ocd-selected-thml-to-tei"),
        checker=dict(id="ocd-selected-thml-independent-check"),
        shared_assumptions=["Producer and oracle use the same retained XML and SourceManifest; four body loci are only a visual sample."],
        independent_corroboration="Fresh independent Phase A oracle and 1,653-element selected-ThML check; byte-identical clean-process replay; five current-pair CVW frames at four body loci; unchanged reviewed TEI text after header revision.",
    )
    for name in PROOFS:
        path = evidence / f"{name}.json"
        _write(path, common | dict(status="pass", command=command, exit_code=0,
                                   details=details[name]))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    windows = ["xi:opening-window", "xi.iv:chapter-1-window", "xi.xxxv:chapter-32-window",
               "xi.lxix:chapter-66-opening-window", "xi.lxix:ending-window"]
    review = dict(
        reviewer="agent:37a-05-phase-a-exact-pair-cvw",
        reviewed_at=captured_at.replace("+00:00", "Z"),
        coverage=dict(status="partial", declared=SCOPE, reached=windows,
                      inspected=windows, unreviewed=["remaining-body-and-shared-credit-pixels"]),
        source_quality_uncertainty=["The retained electronic witness has not been independently collated with print.",
                                    "Translator attribution is source-supported but no new independent authorship decision was made."],
        discrepancies=[],
        unreviewed_residuals=["Five frames at four body loci do not visually inspect the other chapters, notes, page markers, or every reference.",
                             "The two source-credit paragraph comparisons were exact text/locator checks, not additional pixel review.",
                             "Governed CVW correspondence is absent; panes were selected independently."],
    )
    _write(evidence / "review.json", common | review | dict(
        capture_bindings={name: bindings[f"cvw/{name}/capture.json"] for name in FRAMES},
        current_pair_report=bindings["report.md"],
        reviewed_original_tei_sha256=TEI_SHA,
        shared_credit_text_loci=["iii-p15", "iii-p74"],
        derived_text_bytes_unchanged=True))
    decision = dict(
        source_local_disposition="Evidence-backed agent acceptance of Augustine's selected xi body and eight shared credit paragraphs in the exact retained CCEL electronic witness.",
        blockers=[],
        agent_assessment=dict(status="accepted", actor="agent:augustine-spirit-letter-phase-a-review",
                              assessed_at=now.isoformat().replace("+00:00", "Z"), supported_scope=SCOPE,
                              unassessed_stronger_claims=["human acceptance", "rights clearance", "complete underlying print work",
                                                          "print collation", "exhaustive proofreading", "release", "publication"],
                              unresolved_claims=[]),
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
