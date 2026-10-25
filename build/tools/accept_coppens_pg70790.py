"""Build a pinned, nonaccepted PG 70790 Coppens acceptance stage."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path, install_accepted_work
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "charles-coppens-spiritual-exercises-adaptation"
FORM_ID = "charles-coppens-eight-days-six-triduums-1916"
EDITION_ID = "charles-coppens-exercises-1916-pg70790"
ACQUISITION_ID = "pg70790-retained-zip"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
INTEGRATION = WORK / "integration/pg70790-source-native-v5"
EVIDENCE = INTEGRATION / "acceptance-v1"
CANDIDATE = INTEGRATION / "candidate"
PACKAGE = CANDIDATE / "package"
MANIFEST = Path("sources/manifest-acquisitions/coppens-pg70790-source-native-v5-20261004/source-manifest.json")
PROFILE = Path("sources/manifest-acquisitions/coppens-pg70790-source-native-v5-20261004/profile.json")
POLICY = Path("sources/manifest-acquisitions/coppens-pg70790-source-native-v5-20261004/policy.json")
NOTICE = Path("sources/manifest-acquisitions/coppens-pg70790-source-native-v5-20261004/README.source.md")
SOURCE = Path("raw/gutenberg/70790/pg70790-h.zip")
SOURCE_HTML = "pg70790-images.html"
COVER_MEMBER = "images/cover.jpg"
SOURCE_URL = "https://www.gutenberg.org/cache/epub/70790/pg70790-h.zip"
SOURCE_SHA = "fdfcd5228a14f985fff53cb1bddca74574cee04daca68400b0b11a66a81fcedf"
SOURCE_BYTES = 1596270
HTML_SHA = "5a824563e0a08ed885c4b4e4bac49c43750ae91946e677d06b3e5ce701e50b54"
HTML_BYTES = 451272
COVER_SHA = "514e7a598719e6950f1c645feaa09b37ab98712d42991866a2cb9fd124a147df"
COVER_BYTES = 1450734
MANIFEST_SHA = "52388607e93edf315cb962aa6443199c3eb3d6dc02c9520f5f08e4ec997bb0cf"
PACKAGE_SHA = "61f0687a6e75e2b95568ded35fac4c42c67c98681cdf62f37ff0d521a4e3dbb4"
CONTENT_SHA = "274838d6615134eaf66218eb6728176d47f406e94783f4496d8b89fd506347ba"
VALIDATION_REPORT_SHA = "39b38069a62105f67f517dde7cb09500665f4685b6d24e9062a4a9c9f4c74337"
VALIDATION_SHA = "57ba8d4f5afa48f46e3067e50966bab761b3dab4030eafb0f28ad382d5dc90d1"
PARENT_SOURCE_REVIEW_SHA = "c40d843f46e7f66a718d6e9bd3565ee1229e4a8de52f2368b733ef239e982af8"
MUTATION_RERUN_SHA = "7fbf3a924218e0659c9e090532797e0613b63b440f2b3ca7aad5afc2d0311bbc"
REPLAY_SHA = "809ba2211f2a975c08a8dd0a540130332454bbe7c8b2d9f02d06cfd5960c98be"
EVIDENCE_HOME = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence")
PROFILE_ID = "ocd-prose-coppens-pg70790-source-native-v1"
REVISION_DATE = "2026-10-04"
REVIEW_PATH = EVIDENCE_HOME / "COPPENS_PG70790_V5_SOURCE_PACKAGE_PARENT_REVIEW_20261004.json"
MUTATION_PATH = EVIDENCE_HOME / "COPPENS_PG70790_V5_RESEALED_CONTROLS_PARENT_RERUN_20261004.json"
REPLAY_PATH = EVIDENCE_HOME / "COPPENS_PG70790_V5_FRESH_REPLAY_20261004.json"
NS = "http://www.tei-c.org/ns/1.0"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _write(path: Path, content: bytes) -> Path:
    _io_path(path.parent).mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(content)
    return path


def _json(path: Path, value: object) -> Path:
    return _write(
        path,
        (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
    )


def _copy(source: Path, target: Path) -> None:
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(source), _io_path(target))


def _external_package() -> Path:
    return Path(r"D:\Library\Open Christian Data\candidate-reviews\coppens-pg70790-source-native-v5-20261004-v1\package")


def _pinned_inputs(root: Path) -> tuple[SourceManifest, CandidatePackage, object, dict, dict]:
    validation_path = EVIDENCE_HOME / "COPPENS_PG70790_V5_BUILD_VALIDATION_20261004.json"
    expected = {
        MANIFEST: MANIFEST_SHA,
        validation_path: VALIDATION_SHA,
        REVIEW_PATH: PARENT_SOURCE_REVIEW_SHA,
        MUTATION_PATH: MUTATION_RERUN_SHA,
        REPLAY_PATH: REPLAY_SHA,
    }
    for relative, digest in expected.items():
        if _sha(root / relative) != digest:
            raise PipelineError(f"reviewed file changed: {relative}")
    source_manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    if source_manifest.sha256 != MANIFEST_SHA:
        raise PipelineError("current source manifest identity differs")
    package = CandidatePackage.load(_external_package())
    if package.sha256 != PACKAGE_SHA or package.member_bytes("content.tei.xml") and hashlib.sha256(package.member_bytes("content.tei.xml")).hexdigest() != CONTENT_SHA:
        raise PipelineError("frozen candidate package differs")
    # Recheck the independent source and validation route against the live pinned bytes.
    from build.tei.coppens_pg70790_source_native_v5_oracle import _oracle

    report = validate(source_manifest, package, _oracle)
    validation = _read(root / validation_path)
    if report.status != "pass" or report.findings or report.sha256 != VALIDATION_REPORT_SHA or validation.get("validation_report_sha256") != report.sha256:
        raise PipelineError("maintained current source validation differs")
    for item in source_manifest.record["authorities"]:
        relative = Path(item["path"])
        source_path = resolve_repo_path(root, item["path"]) if relative.parts[0] == "raw" else root / relative
        if _io_path(source_path).stat().st_size != item["bytes"] or _sha(source_path) != item["sha256"]:
            raise PipelineError(f"source authority changed: {item['name']}")
    with zipfile.ZipFile(resolve_repo_path(root, SOURCE.as_posix())) as archive:
        if archive.testzip() is not None:
            raise PipelineError("retained ZIP has a failing CRC member")
        html = archive.read(SOURCE_HTML)
        cover = archive.read(COVER_MEMBER)
    if len(html) != HTML_BYTES or hashlib.sha256(html).hexdigest() != HTML_SHA:
        raise PipelineError("retained HTML member differs from the reviewed source")
    if len(cover) != COVER_BYTES or hashlib.sha256(cover).hexdigest() != COVER_SHA:
        raise PipelineError("retained cover member differs from the reviewed source")
    return source_manifest, package, report, validation, {"html": html, "cover": cover}


def _bind_header(original: bytes, *, identity: dict, acquisition: dict, revision: dict) -> bytes:
    retained = acquisition["retained_files"]
    if len(retained) != 1:
        raise PipelineError("one exact retained archive source is required for this acceptance binding")
    source = {
        "source_path": retained[0]["path"],
        "source_sha256": retained[0]["sha256"],
        "source_bytes": retained[0]["bytes"],
        "source_kind": acquisition.get("source_kind"),
    }
    source = {key: value for key, value in source.items() if value is not None}
    bound = bind_reviewed_header(
        original,
        expected_sha256=hashlib.sha256(original).hexdigest(),
        identity=identity,
        source=source,
        source_url=acquisition["url"],
        declared_scope=retained[0]["scope"],
        revision=revision,
        historical_source_description={"pointers": [], "sha256": []},
    )
    binding = re.compile(rb'<bibl xmlns="' + re.escape(NS.encode()) + rb'" type="ocd-acceptance-binding">.*?</bibl>', re.DOTALL)
    match = binding.search(bound)
    if match is None:
        raise PipelineError("reviewed header binding insertion is missing")
    wrapped = b'<p xmlns="' + NS.encode() + b'">' + match.group(0) + b"</p>"
    ready = bound[:match.start()] + wrapped + bound[match.end():]
    if ready.replace(wrapped, match.group(0), 1) != bound:
        raise PipelineError("acceptance paragraph wrapper is not exactly reversible")
    if original.split(b"</teiHeader>", 1)[1] != ready.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("acceptance header binding changed source body bytes")
    original_has_revision = b"</revisionDesc>" in original
    if _sha_bytes(_remove_binding(ready, revision_desc_was_present=original_has_revision)) != hashlib.sha256(original).hexdigest():
        raise PipelineError("acceptance header binding inverse does not recover the original TEI")
    return ready


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _remove_binding(value: bytes, *, revision_desc_was_present: bool) -> bytes:
    binding = re.compile(rb'<p xmlns="' + re.escape(NS.encode()) + rb'"><bibl xmlns="' + re.escape(NS.encode()) + rb'" type="ocd-acceptance-binding">.*?</bibl></p>', re.DOTALL)
    match = binding.search(value)
    if match is None:
        raise PipelineError("exact acceptance binding wrapper not found for inverse")
    without_bibl = value[:match.start()] + value[match.end():]
    change = rb'<change xmlns="' + re.escape(NS.encode()) + rb'" xml:id="coppens-pg70790-accepted-v1" when="[0-9]{4}-[0-9]{2}-[0-9]{2}">.*?</change>'
    if revision_desc_was_present:
        changes = re.findall(change, without_bibl, re.DOTALL)
        if len(changes) != 1:
            raise PipelineError("exact acceptance revision change not found for inverse")
        return without_bibl.replace(changes[0], b"", 1)
    revision = re.findall(rb'<revisionDesc xmlns="' + re.escape(NS.encode()) + rb'">' + change + rb'</revisionDesc>', without_bibl, re.DOTALL)
    if len(revision) != 1:
        raise PipelineError("exact inserted revisionDesc wrapper not found for inverse")
    return without_bibl.replace(revision[0], b"", 1)


def _acquisition() -> dict:
    declared = "One complete English Coppens adaptation book in the retained Project Gutenberg 70790 electronic witness; not Ignatius's complete original Exercises or all Coppens writings."
    return {
        "schema_version": "2.0",
        "acquisition_id": ACQUISITION_ID,
        "edition_id": EDITION_ID,
        "provider": "Project Gutenberg",
        "url": SOURCE_URL,
        "accessed_at": "2026-09-23",
        "route": "born-digital",
        "rights": "Project Gutenberg metadata states public domain in the USA. This records the source claim only; independent rights review and human clearance have not been performed.",
        "retained_files": [
            {"path": SOURCE.as_posix(), "bytes": SOURCE_BYTES, "sha256": SOURCE_SHA,
             "media_type": "application/zip", "scope": declared}
        ],
    }


def _source_from_acquisition(acquisition: dict) -> dict:
    if any(key in acquisition for key in ("source_path", "source_bytes", "source_scope")):
        raise PipelineError("Coppens ZIP must remain a retained carrier, not an original-file source_path")
    if len(acquisition["retained_files"]) != 1:
        raise PipelineError("one retained source archive required")
    retained = acquisition["retained_files"][0]
    return {"source_path": retained["path"], "source_sha256": retained["sha256"],
            "source_bytes": retained["bytes"], "source_scope": retained["scope"]}


def _initial_work() -> tuple[dict, dict]:
    work = {
        "schema_version": "2.0",
        "work_id": WORK_ID,
        "title": "The Spiritual Exercises of St. Ignatius Adapted to an Eight Days Retreat and Six Triduums",
        "creators": [{"name": "Charles Coppens", "role": "author", "evidence": [MANIFEST.as_posix()]}],
        "evidence": [SOURCE.as_posix(), MANIFEST.as_posix(), PROFILE.as_posix(), NOTICE.as_posix()],
        "textual_forms": [{
            "textual_form_id": FORM_ID,
            "title": "Coppens's adaptation for an eight days retreat and six triduums; for Jesuit use",
            "language": "en",
            "editions": [{
                "edition_id": EDITION_ID,
                "title": "1916 B. Herder imprint; Project Gutenberg 70790 electronic witness",
                "language": "en",
                "category": "prose",
                "acquisition_ids": [ACQUISITION_ID],
            }],
        }],
    }
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    state = {
        "schema_version": "2.0",
        "work_id": WORK_ID,
        "targets": [
            {"target_id": ACQUISITION_ID, "target_type": "acquisition", "stage": "acquired", "updated_at": "2026-09-23T00:00:00Z",
             "evidence": [ACQUISITION.relative_to(WORK).as_posix(), MANIFEST.as_posix()]},
            {"target_id": EDITION_ID, "target_type": "edition", "stage": "review", "updated_at": now,
             "reason": "Current v5 retained-source candidate passed maintained source validation, P5, replay, and source-bound controls; technical acceptance is prepared separately, with human/rights/print/publication decisions still open.",
             "evidence": [MANIFEST.as_posix(), (INTEGRATION / "candidate/validation.json").as_posix(),
                         REVIEW_PATH.as_posix(), MUTATION_PATH.as_posix(), REPLAY_PATH.as_posix()]},
        ],
    }
    return work, state


def _projection(root: Path, *, expected_rows: int | None = None) -> dict:
    acceptance = root / EDITION / "acceptance.json"
    projected = project_accepted_prose(root, acceptance_path=acceptance)
    errors = verify_accepted_prose(root, acceptance_path=acceptance, rows=projected["rows"], receipt=projected["receipt"])
    if errors:
        raise PipelineError(f"current native/prose reader rejected accepted master: {errors[:5]}")
    if expected_rows is not None and len(projected["rows"]) != expected_rows:
        raise PipelineError(f"accepted projection row count differs: {len(projected['rows'])}")
    return projected


def stage(stage_root: Path) -> dict:
    root = ROOT.resolve(strict=True)
    audit = (root / ".tmp_audit").resolve(strict=True)
    stage_root = stage_root.absolute()
    target = root / WORK
    if (stage_root.exists() or stage_root.parent != audit or not stage_root.name.startswith(WORK_ID + "-accept-stage-")
            or _io_path(target).exists()):
        raise PipelineError("fresh stage under .tmp_audit and absent canonical work required")
    manifest, package, report, validation, resources = _pinned_inputs(root)
    work, state = _initial_work()
    acquisition = _acquisition()
    source_binding = _source_from_acquisition(acquisition)
    stage_root.mkdir()
    stage_work = stage_root / WORK
    for relative, document in ((WORK / "work.json", work), (WORK / "state.json", state), (ACQUISITION, acquisition)):
        _json(stage_root / relative, document)
    load_work(stage_work / "work.json")
    _copy(resolve_repo_path(root, SOURCE.as_posix()), stage_root / SOURCE)
    validate_acquisition(stage_root / ACQUISITION, root=stage_root)

    # Stage the exact acquisition/source authorities needed by the acceptance validators.
    for relative in (MANIFEST, PROFILE, POLICY, NOTICE):
        _copy(root / relative, stage_root / relative)
    for relative in (REVIEW_PATH, MUTATION_PATH, REPLAY_PATH,
                     EVIDENCE_HOME / "COPPENS_PG70790_V5_BUILD_VALIDATION_20261004.json"):
        _copy(root / relative, stage_root / relative)

    _io_path(stage_root / PACKAGE).mkdir(parents=True, exist_ok=True)
    for member in package.manifest["members"]:
        name = member["name"]
        _copy(_external_package() / name, stage_root / PACKAGE / name)
    _copy(root / (EVIDENCE_HOME / "COPPENS_PG70790_V5_BUILD_VALIDATION_20261004.json"), stage_root / CANDIDATE / "validation.json")
    _copy(root / REVIEW_PATH, stage_root / EVIDENCE / "parent-source-review.json")
    _copy(root / MUTATION_PATH, stage_root / EVIDENCE / "mutation-controls-parent-rerun.json")
    _copy(root / REPLAY_PATH, stage_root / EVIDENCE / "fresh-replay.json")
    validate_state(stage_work / "state.json", root=stage_root)

    scope_declared = source_binding["source_scope"]
    identity = {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID, "acquisition_id": ACQUISITION_ID}
    revision = {"id": "coppens-pg70790-accepted-v1", "date": REVISION_DATE,
                "note": "Bind the complete 1916 Coppens adaptation book in the retained PG 70790 electronic witness."}
    original = package.member_bytes("content.tei.xml")
    bound = _bind_header(original, identity=identity, acquisition=acquisition, revision=revision)
    candidate = _write(stage_root / EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(candidate):
        raise PipelineError(f"accepted TEI failed maintained P5: {errors[:5]}")
    candidate_cover = _write(stage_root / EVIDENCE / "candidate/images/cover.jpg", resources["cover"])
    edition_cover = _write(stage_root / EDITION / "images/cover.jpg", resources["cover"])
    if _sha(candidate_cover) != COVER_SHA or _sha(edition_cover) != COVER_SHA:
        raise PipelineError("candidate/master local cover bytes do not match retained archive")

    retained = acquisition["retained_files"]
    expected = [{"path": item["path"], "position": index} for index, item in enumerate(retained, 1)]
    included = [{"path": item["path"], "position": index, "bytes": item["bytes"], "sha256": item["sha256"], "scope": scope_declared}
                for index, item in enumerate(retained, 1)]
    scope = {"kind": "work", "declared": scope_declared, "expected_members": expected, "included_members": included, "excluded_members": []}
    common = {"identity": identity, "source": source_binding, "scope": scope_declared,
              "source_sha256": source_binding["source_sha256"], "source_bytes": source_binding["source_bytes"],
              "candidate": make_file_binding(stage_root, candidate), "accepted_scope": {"kind": "work", "declared": scope_declared},
              "expected_members": expected, "included_members": included, "excluded_members": [], "missing_members": [], "unknown_members": []}
    source_accountability = json.loads(package.member_bytes("source-accountability.json"))
    accounting_doc = source_accountability | common | {
        "contract": "ocd-coppens-pg70790-acceptance-accounting-v1",
        "projection_profile": PROFILE_ID,
        "source_manifest_sha256": manifest.sha256,
        "candidate_package_sha256": package.sha256,
        "current_validation_report_sha256": report.sha256,
        "independent_source_review_sha256": PARENT_SOURCE_REVIEW_SHA,
        "resealed_mutation_rerun_sha256": MUTATION_RERUN_SHA,
        "fresh_replay_receipt_sha256": REPLAY_SHA,
        "source_html_member": {"path": SOURCE_HTML, "bytes": HTML_BYTES, "sha256": HTML_SHA},
        "support_assets": [{"member": COVER_MEMBER, "candidate_path": (EVIDENCE / "candidate/images/cover.jpg").as_posix(),
                             "edition_path": (EDITION / "images/cover.jpg").as_posix(), "bytes": COVER_BYTES,
                             "sha256": COVER_SHA, "candidate_and_master_relative_urls_resolved": True}],
        "reviewed_source_body_sha256": _sha_bytes(original.split(b"</teiHeader>", 1)[1]),
        "accepted_body_sha256": _sha_bytes(bound.split(b"</teiHeader>", 1)[1]),
        "accepted_body_unchanged": original.split(b"</teiHeader>", 1)[1] == bound.split(b"</teiHeader>", 1)[1],
        "header_binding_inverse_sha256": hashlib.sha256(original).hexdigest(),
        "human_decision": "not-recorded",
        "rights_clearance": "not-performed",
        "publication": "not-authorized",
    }
    accounting = _json(stage_root / EVIDENCE / "source-accounting.json", accounting_doc)
    master = _write(stage_root / EDITION / "master.tei.xml", bound)
    if validate_file(master):
        raise PipelineError("promoted master failed maintained P5")

    command = "py -3 -m build.tools.accept_coppens_pg70790 stage"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    gate_notes = {
        "validation": "Maintained source-manifest validation passed against exact retained archive and V5 candidate.",
        "accounting": "Complete retained title boundary, 3,612 source body nodes, attributes, two archive members, and support cover are pinned.",
        "fidelity": "Independent source-first review verified source body structure, 348,724 normalized characters, head inventory, and source attributes.",
        "reproducibility": "Fresh v5 reconstruction replay is byte-equal across the six package members.",
        "schema": "Current maintained TEI P5 validation passes on candidate and promoted master.",
        "closure": "Eleven sealed source-bound mutation controls pass; body bytes and both relative cover resolutions are preserved.",
    }
    technical = {
        "producer": {"id": manifest.record["converter"]["id"]},
        "checker": {"id": manifest.record["validator"]["id"]},
        "shared_assumptions": ["The source producer and its oracle use the declared V5 source/profile conventions; independent raw-source review and maintained P5 validation corroborate, but do not constitute human collation."],
        "independent_corroboration": "Parent source review used independent source parsing; parent independently reran the resealed controls and fresh package review.",
    }
    for name, note in gate_notes.items():
        gate = _json(stage_root / EVIDENCE / f"{name}.json", common | {
            "contract": "ocd-coppens-pg70790-acceptance-gate-v1", "gate": name, "status": "pass",
            "command": command, "exit_code": 0, "source_manifest_sha256": manifest.sha256,
            "candidate_package_sha256": package.sha256, "validation_report_sha256": report.sha256,
            "source_review_sha256": PARENT_SOURCE_REVIEW_SHA, "mutation_rerun_sha256": MUTATION_RERUN_SHA,
            "replay_sha256": REPLAY_SHA, "detail": note,
        })
        technical[name] = {"path": gate, "status": "pass", "command": command, "exit_code": 0}
    review = {
        "reviewer": "agent:charles-coppens-pg70790-technical-assessment",
        "reviewed_at": now,
        "coverage": {"status": "partial", "declared": scope_declared,
                     "reached": ["complete source title boundary", "full retained HTML body structure/text/attributes", "complete HTML head inventory", "retained cover bytes and relative URL locations"],
                     "inspected": ["complete source title boundary", "full retained HTML body structure/text/attributes", "complete HTML head inventory", "retained cover bytes and relative URL locations"],
                     "unreviewed": ["human visual collation", "1916 print exemplar collation", "human verification"]},
        "source_quality_uncertainty": ["This is a Project Gutenberg electronic witness; it has not been collated against a 1916 print exemplar.", "Project Gutenberg's USA public-domain statement is a source claim, not independent rights clearance."],
        "discrepancies": [],
        "unreviewed_residuals": ["Human visual verification and print collation remain open.", "Independent rights review, release selection, and publication authorization remain open."],
    }
    review_path = _json(stage_root / EVIDENCE / "review.json", common | review | {
        "independent_source_review_path": REVIEW_PATH.as_posix(), "independent_source_review_sha256": PARENT_SOURCE_REVIEW_SHA,
        "mutation_rerun_path": MUTATION_PATH.as_posix(), "mutation_rerun_sha256": MUTATION_RERUN_SHA,
        "replay_path": REPLAY_PATH.as_posix(), "replay_sha256": REPLAY_SHA,
    })
    decision = {
        "source_local_disposition": "Accept only this complete source-titled 1916 Coppens adaptation as one electronic edition; do not claim the complete original Ignatian work or all Coppens writings.",
        "blockers": [],
        "agent_assessment": {"status": "accepted", "actor": review["reviewer"], "assessed_at": now,
                             "supported_scope": scope_declared, "unresolved_claims": [],
                             "unassessed_stronger_claims": ["human verification", "print collation", "rights clearance", "release selection", "publication"]},
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(stage_root, identity=identity, candidate_path=candidate,
                                    source_accounting_path=accounting, scope=scope, technical=technical,
                                    review=review | {"report_path": review_path},
                                    representation_revision=revision, decision=decision)
    acceptance = stage_root / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage_root, master))
    write_acceptance(acceptance, record)
    state_path = stage_work / "state.json"
    state = _read(state_path)
    editions = [item for item in state["targets"] if item["target_type"] == "edition" and item["target_id"] == EDITION_ID]
    if len(editions) != 1 or editions[0]["stage"] != "review":
        raise PipelineError("exact one edition review target required before acceptance")
    editions[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    editions[0]["evidence"].extend([(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()])
    _json(state_path, state)
    validate_acceptance(acceptance, root=stage_root)
    validate_state(state_path, root=stage_root)
    projected = _projection(stage_root)
    # Verify the candidate copy's relative media independently of the master location.
    if _sha(stage_root / EVIDENCE / "candidate/images/cover.jpg") != COVER_SHA:
        raise PipelineError("accepted candidate's relative image target does not resolve to retained cover bytes")
    before = {}
    after = _files(stage_work)
    result = {
        "contract": "ocd-coppens-pg70790-acceptance-stage-v1",
        "status": "staged-only", "work_id": WORK_ID, "stage_root": stage_root.as_posix(),
        "before": before, "after": after, "new_title_home_previously_absent": True,
        "source_archive_sha256": SOURCE_SHA, "source_archive_bytes": SOURCE_BYTES,
        "source_html_sha256": HTML_SHA, "source_html_bytes": HTML_BYTES,
        "source_manifest_sha256": manifest.sha256, "candidate_package_sha256": package.sha256,
        "source_validation_report_sha256": report.sha256,
        "parent_source_review_sha256": PARENT_SOURCE_REVIEW_SHA,
        "mutation_control_rerun_sha256": MUTATION_RERUN_SHA, "fresh_replay_sha256": REPLAY_SHA,
        "candidate_sha256": _sha(candidate), "master_sha256": _sha(master),
        "acceptance_sha256": _sha(acceptance), "source_accounting_sha256": _sha(accounting),
        "candidate_cover_sha256": _sha(candidate_cover), "edition_cover_sha256": _sha(edition_cover),
        "cover_candidate_and_master_relative_urls_resolve": True,
        "candidate_p5_errors": [], "master_p5_errors": [],
        "projection_category": "prose", "projection_status": "pass", "projection_rows": len(projected["rows"]),
        "projection_receipt": projected["receipt"], "projection_rows_sha256": hashlib.sha256(json.dumps(projected["rows"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "human_decision": "not-recorded", "rights_clearance": "not-performed", "publication": "not-authorized",
        "installation": "not-performed",
    }
    receipt_path = stage_root / "stage-receipt.json"
    _json(receipt_path, result)
    result["stage_receipt_sha256"] = _sha(receipt_path)
    return result


def preflight(stage_root: Path, expected_sha256: str) -> dict:
    root = ROOT.resolve(strict=True)
    stage_root = stage_root.resolve(strict=True)
    if (stage_root.parent != (root / ".tmp_audit").resolve(strict=True)
            or not stage_root.name.startswith(WORK_ID + "-accept-stage-")
            or _sha(stage_root / "stage-receipt.json") != expected_sha256):
        raise PipelineError("stage location or receipt pin differs")
    receipt = _read(stage_root / "stage-receipt.json")
    if (receipt.get("status") != "staged-only" or receipt.get("work_id") != WORK_ID
            or receipt.get("stage_root") != stage_root.as_posix() or receipt.get("installation") != "not-performed"):
        raise PipelineError("stage receipt claim differs")
    if _io_path(root / WORK).exists() or _files(stage_root / WORK) != receipt["after"]:
        raise PipelineError("canonical preimage or frozen staged work generation changed")
    if _sha(stage_root / EVIDENCE / "candidate.tei.xml") != receipt["candidate_sha256"]:
        raise PipelineError("candidate TEI changed")
    if _sha(stage_root / EVIDENCE / "candidate/images/cover.jpg") != COVER_SHA or _sha(stage_root / EDITION / "images/cover.jpg") != COVER_SHA:
        raise PipelineError("one of the exact candidate/master image resolutions changed")
    validate_acquisition(stage_root / ACQUISITION, root=stage_root)
    validate_acceptance(stage_root / EDITION / "acceptance.json", root=stage_root)
    validate_state(stage_root / WORK / "state.json", root=stage_root)
    projection = _projection(stage_root, expected_rows=receipt["projection_rows"])
    if projection["receipt"] != receipt["projection_receipt"]:
        raise PipelineError("fresh prose/native receipt differs from staged projection")
    return {"status": "ready-for-parent-review", "stage_receipt_sha256": expected_sha256,
            "files": len(receipt["after"]), "projection_rows": len(projection["rows"]),
            "candidate_cover_sha256": COVER_SHA, "edition_cover_sha256": COVER_SHA,
            "installation": "not-performed"}


def apply(stage_root: Path, expected_sha256: str) -> dict:
    root = ROOT.resolve(strict=True)
    preflight(stage_root, expected_sha256)

    def checkpoint(point: str) -> None:
        if point == "after-validated":
            validate_acceptance(root / EDITION / "acceptance.json", root=root)
            validate_state(root / WORK / "state.json", root=root)
            if _files(root / WORK) != _read(stage_root / "stage-receipt.json")["after"]:
                raise PipelineError("installed generation differs from reviewed stage")
            _projection(root)
            if _sha(root / EDITION / "images/cover.jpg") != COVER_SHA:
                raise PipelineError("installed edition cover differs from retained source")

    return {"preflight": preflight(stage_root, expected_sha256),
            "installation": install_accepted_work(root, stage_root, work_id=WORK_ID, fail_at=checkpoint)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "preflight", "apply"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    if args.action == "stage":
        result = stage(args.path)
    elif not args.expected_sha256:
        parser.error("--expected-sha256 is required for preflight and apply")
    elif args.action == "preflight":
        result = preflight(args.path, args.expected_sha256)
    else:
        result = apply(args.path, args.expected_sha256)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
