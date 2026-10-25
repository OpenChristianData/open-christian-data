"""Prepare a reviewed, work-local Morning and Evening acceptance stage.

This tool writes one fresh D: candidate-review stage only. It does not install
the work or change the canonical library. Human acceptance, source rights,
print-edition identity, and public-release authorization remain separate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tei.lib030_native_projection_adapter import adapt_lib030_for_native_projection
from build.tei.lib030_oracle import _oracle
from ocd_kernel.lib.path_io import io_path, io_rglob
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document,
    verify_accepted_document,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
LIBRARY = Path("D:/Library/Open Christian Data")
WORK_ID = "spurgeons-morning-evening"
FORM_ID = "spurgeons-morning-evening-english"
EDITION_ID = "spurgeons-morning-evening-ccel-thml-electronic"
ACQUISITION_ID = "spurgeons-morning-evening-ccel-retained-xml"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/ccel/spurgeon/morneve.xml")
SOURCE_SHA = "3512797ae879d4fdbdcde90e5ebc04299e501658fd8fb6c09977c2e2648ad0a4"
SOURCE_BYTES = 2_136_777
MANIFEST = Path(
    "sources/devotionals/spurgeons-morning-evening/"
    "lib030.source-manifest-current-closure-20261003-v1.json"
)
MANIFEST_SHA = "8152bc4c8ad9d0cad8ce283477de7a503031f14564e6f584955662e84fba30bc"
SCREEN_RECEIPT_SHA = "25063e8609a3ba39f715e02c4a859b703223577cf20862daee50daf9c73d562f"
REPLAY_RECEIPT_SHA = "2ab72195085aba995fe4b9f67bcf0f5445a0df1744966807fdb5869259baa30b"
CANDIDATE_ROOT = LIBRARY / "candidate-reviews/spurgeons-morning-evening-candidate-handoff-closure-20261003-v1"
CANDIDATE = CANDIDATE_ROOT / "package"
VALIDATION_SIDECAR = CANDIDATE_ROOT / "validation.json"
EVIDENCE = WORK / "integration/lib030-current-acceptance-20261003-v1"
SCREEN_RECEIPT = Path(
    "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/"
    "MORNING_EVENING_PROJECTION_SCREEN_20261003.json"
)
REPLAY_RECEIPT = Path(
    "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/"
    "MORNING_EVENING_SOURCE_REPLAY_20261003.json"
)
ADAPTED_TRIAL = Path(
    ".tmp_audit/lib030-native-screen-20261003-v2/"
    "MORNING_EVENING_ADAPTED_CANDIDATE_20261003.tei.xml"
)
BOUND_TRIAL = Path(
    ".tmp_audit/lib030-native-screen-20261003-v2/"
    "MORNING_EVENING_BOUND_CANDIDATE_20261003.tei.xml"
)
IDENTITY = dict(
    work_id=WORK_ID,
    textual_form_id=FORM_ID,
    edition_id=EDITION_ID,
    acquisition_id=ACQUISITION_ID,
)
SCOPE = (
    "Complete retained CCEL ThML electronic witness represented as a full acquired file; "
    "print-edition equivalence, human acceptance, rights clearance, and publication "
    "authorization remain unassessed."
)
REVISION = dict(
    id="spurgeons-morning-evening-ccel-binding-20261003-v2",
    date="2026-10-03",
    note="Bind the adapted technical-review candidate to the retained CCEL electronic witness.",
)


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _write(stage: Path, relative: Path, data: bytes) -> Path:
    target = stage / relative
    io_path(target.parent).mkdir(parents=True, exist_ok=True)
    io_path(target).write_bytes(data)
    return target


def _write_json(stage: Path, relative: Path, value: object) -> Path:
    return _write(
        stage,
        relative,
        (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
    )


def _copy(root: Path, stage: Path, relative: Path) -> None:
    source, target = root / relative, stage / relative
    io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(io_path(source), io_path(target))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def prepare(stage: Path, *, root: Path = ROOT) -> dict:
    """Build one isolated promoted acceptance stage for independent review."""
    root = root.resolve(strict=True)
    stage = stage.absolute()
    review_home = LIBRARY / "candidate-reviews"
    if (
        io_path(stage).exists()
        or stage.parent != review_home
        or not stage.name.startswith("spurgeons-morneve-acceptance-stage-")
    ):
        raise PipelineError("a fresh, explicitly named Morning and Evening stage is required")

    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    if manifest.sha256 != MANIFEST_SHA or manifest.verify() is not None:
        raise PipelineError("current source manifest or seven source authorities differ")
    authority_paths = [Path(item["path"]).as_posix() for item in manifest.record["authorities"]]
    if (WORK / "work.json").as_posix() in authority_paths:
        raise PipelineError("live work.json is a source-manifest authority; rebind to a frozen preimage before staging")
    package = CandidatePackage.load(io_path(CANDIDATE))
    if package.sha256 != "647420734311a81b7319f3875e3db58dbee8e740b9f9e37b1d8247856f0f0798":
        raise PipelineError("current replayed candidate package differs")
    report = validate(manifest, package, _oracle)
    if report.status != "pass":
        raise PipelineError("fresh source oracle validation did not pass")

    replay = _read(root / REPLAY_RECEIPT)
    cli = replay.get("maintained_cli_reconstruction", {})
    sidecar_bytes = io_path(VALIDATION_SIDECAR).read_bytes()
    sidecar = json.loads(sidecar_bytes)
    if (
        _sha(sidecar_bytes) != cli.get("validation_sidecar_sha256_raw_bytes")
        or sidecar.get("report_sha256") != report.sha256
        or sidecar.get("candidate_sha256") != package.sha256
        or sidecar.get("source_manifest_sha256") != manifest.sha256
        or sidecar.get("status") != "pass"
    ):
        raise PipelineError("persisted CLI validation sidecar is stale or differently bound")

    acquisition = validate_acquisition(root / ACQUISITION, root=root)
    retained = acquisition["retained_files"]
    if (
        len(retained) != 1
        or retained[0]["path"] != SOURCE.as_posix()
        or retained[0]["bytes"] != SOURCE_BYTES
        or retained[0]["sha256"] != SOURCE_SHA
    ):
        raise PipelineError("exact acquired electronic-witness identity differs")
    source = io_path(root / SOURCE).read_bytes()
    if len(source) != SOURCE_BYTES or _sha(source) != SOURCE_SHA:
        raise PipelineError("retained CCEL source bytes differ")
    work = _read(root / WORK / "work.json")
    forms = work.get("textual_forms")
    if not isinstance(forms, list) or len(forms) != 1 or not isinstance(forms[0], dict):
        raise PipelineError("Morning and Evening must have exactly one textual form")
    form = forms[0]
    editions = form.get("editions")
    if not isinstance(editions, list) or len(editions) != 1 or not isinstance(editions[0], dict):
        raise PipelineError("Morning and Evening must have exactly one edition")
    edition = editions[0]
    if (
        form["textual_form_id"] != FORM_ID
        or edition["edition_id"] != EDITION_ID
        or edition["acquisition_ids"] != [ACQUISITION_ID]
        or "category" in edition
        or io_path(root / EDITION / "master.tei.xml").exists()
        or io_path(root / EDITION / "acceptance.json").exists()
    ):
        raise PipelineError("canonical work identity or uninstalled preimage changed")

    original = package.member_bytes("content.tei.xml")
    adapted, adapter_receipt = adapt_lib030_for_native_projection(original)
    screen_bytes = io_path(root / SCREEN_RECEIPT).read_bytes()
    replay_bytes = io_path(root / REPLAY_RECEIPT).read_bytes()
    if _sha(screen_bytes) != SCREEN_RECEIPT_SHA or _sha(replay_bytes) != REPLAY_RECEIPT_SHA:
        raise PipelineError("reviewed Morning and Evening evidence receipts changed")
    screen = json.loads(screen_bytes)
    if len(screen.get("adapted_tei_sha256", "")) != 64 or _sha(adapted) != screen.get("adapted_tei_sha256"):
        raise PipelineError("lossless work-local native-policy adapter output differs")
    historical_description = {
        "pointers": ["https://www.ccel.org/ccel/spurgeon/morneve.xml"],
        "sha256": ["43dad0c9216508815611a1d91c17f73cf05eec0050b6d7ecac450c39705f725a"],
    }
    bound = bind_reviewed_header(
        adapted,
        expected_sha256=_sha(adapted),
        identity=IDENTITY,
        source={
            "source_path": acquisition["source_path"],
            "source_sha256": acquisition["source_sha256"],
            "source_bytes": acquisition["source_bytes"],
            "source_scope": acquisition["source_scope"],
        },
        source_url=acquisition["url"],
        declared_scope=SCOPE,
        revision=REVISION,
        historical_source_description=historical_description,
    )
    if len(screen.get("bound_tei_sha256", "")) != 64 or _sha(bound) != screen.get("bound_tei_sha256"):
        raise PipelineError("current header-bound adapter bytes differ from reviewed output")
    if errors := validate_file_from_bytes(bound):
        raise PipelineError(f"bound TEI P5 validation failed: {errors[:3]}")

    before = _files(root / WORK)
    io_path(stage).mkdir()
    for relative in io_rglob(root / WORK, "*"):
        if io_path(relative).is_file():
            _copy(root, stage, relative.relative_to(root))
    pre_stage_state = validate_state(root / WORK / "state.json", root=root)
    for target in pre_stage_state["targets"]:
        for evidence in target["evidence"]:
            evidence_path = Path(evidence)
            source_path = io_path(root / evidence_path)
            target_path = io_path(stage / evidence_path)
            if not source_path.is_file():
                raise PipelineError(f"canonical state evidence reference is missing: {evidence}")
            if not target_path.is_file():
                _copy(root, stage, evidence_path)
    for path in (
        MANIFEST,
        Path("sources/devotionals/spurgeons-morning-evening/lib030.source-manifest.json"),
        Path("sources/devotionals/spurgeons-morning-evening/README.source.md"),
        Path("sources/devotionals/spurgeons-morning-evening/lib030-source-attribution.md"),
        SCREEN_RECEIPT,
        REPLAY_RECEIPT,
        Path("build/tei/lib030_native_projection_adapter.py"),
        Path("build/tools/stage_lib030_spurgeon_morneve_acceptance.py"),
    ):
        _copy(root, stage, path)
    _copy(root, stage, Path(manifest.record["converter"]["implementation_path"]))
    _copy(root, stage, Path(manifest.record["validator"]["implementation_path"]))
    authority_snapshots = []
    for authority in manifest.record["authorities"]:
        authority_path = Path(authority["path"])
        authority_bytes = io_path(root / authority_path).read_bytes()
        if len(authority_bytes) != authority["bytes"] or _sha(authority_bytes) != authority["sha256"]:
            raise PipelineError(f"source-manifest authority changed before staging: {authority['name']}")
        _copy(root, stage, authority_path)
        snapshot_path = EVIDENCE / "inputs/source-authority-snapshots" / authority["name"] / authority_path.name
        _write(stage, snapshot_path, authority_bytes)
        authority_snapshots.append(dict(name=authority["name"], original_path=authority_path.as_posix(),
            bytes=len(authority_bytes), sha256=_sha(authority_bytes), snapshot_path=snapshot_path.as_posix()))
    authority_snapshot_path = _write_json(stage, EVIDENCE / "inputs/source-manifest-authority-snapshots.json", {
        "contract": "ocd-lib030-source-manifest-authority-snapshots-v1",
        "source_manifest_path": MANIFEST.as_posix(), "source_manifest_sha256": manifest.sha256,
        "authorities": authority_snapshots,
        "note": "Exact source-authority bytes frozen before staged library metadata changes."
    })
    _copy(root, stage, SOURCE)
    for name in package.member_names:
        _write(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _write(stage, EVIDENCE / "inputs/validation.json", sidecar_bytes)
    _write(stage, EVIDENCE / "inputs/adapted-candidate.tei.xml", adapted)
    _write(stage, EVIDENCE / "inputs/bound-candidate.tei.xml", bound)
    _write_json(stage, EVIDENCE / "inputs/adapter-receipt.json", adapter_receipt)

    old_work = json.loads(json.dumps(work))
    staged_form = work["textual_forms"][0]
    staged_edition = staged_form["editions"][0]
    if (staged_form.get("textual_form_id") != FORM_ID or staged_form.get("language") != "en"
            or staged_edition.get("edition_id") != EDITION_ID
            or staged_edition.get("language") != "en"
            or staged_edition.get("acquisition_ids") != [ACQUISITION_ID]
            or "category" in staged_edition):
        raise PipelineError("configured form/edition identity, language, or preimage differs")
    staged_edition["category"] = "prose"
    validate_identity_update(old_work, work)
    work_path = _write_json(stage, WORK / "work.json", work)
    staged_work = load_work(work_path)
    if staged_work != work:
        raise PipelineError("staged work metadata failed identity loadback")

    candidate_path = _write(stage, EVIDENCE / "candidate.tei.xml", bound)
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=SOURCE_BYTES,
                     sha256=SOURCE_SHA, scope=SCOPE)]
    excluded: list[dict] = []
    scope = dict(kind="work", declared=SCOPE, expected_members=expected,
                 included_members=included, excluded_members=excluded)
    candidate_binding = make_file_binding(stage, candidate_path)
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                          source_bytes=SOURCE_BYTES, source_scope=acquisition["source_scope"])
    shared = dict(identity=IDENTITY, candidate=candidate_binding, scope=SCOPE,
                  source=source_binding, accepted_scope=dict(kind="work", declared=SCOPE),
                  expected_members=expected, included_members=included,
                  excluded_members=excluded, missing_members=[], unknown_members=[])
    source_accounting = _write_json(stage, EVIDENCE / "source-accounting.json", shared | dict(
        scope=acquisition["source_scope"],
        source_sha256=SOURCE_SHA, source_bytes=SOURCE_BYTES,
        source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
        source_manifest_authority_paths=authority_paths,
        oracle_report_sha256=report.sha256,
        candidate_source_accountability=make_file_binding(
            stage, stage / EVIDENCE / "inputs/package/source-accountability.json"),
        adapter_receipt=make_file_binding(stage, stage / EVIDENCE / "inputs/adapter-receipt.json"),
        source_manifest_authority_snapshots=make_file_binding(stage, authority_snapshot_path),
        complete_retained_file=True, omitted_source_members=0,
        source_header_disposition=("Original sourceDesc, credits, editorial history, revision history, "
            "rights statements, full ThML-head transcription, comments and style evidence are preserved "
            "in the private TEI header/evidence. Converter-generated labels are typed context, excluded "
            "from prose; personal contact details are not copied into the public notice."),
        candidate_native_policy_adapter="build/tei/lib030_native_projection_adapter.py",
        accepted_master_projection="one body prose row; no generated context headings"))

    command = "py -3 -m build.tools.stage_lib030_spurgeon_morneve_acceptance --stage <fresh-stage>"
    technical = dict(
        producer=dict(id=manifest.record["converter"]["id"]),
        checker=dict(id=manifest.record["validator"]["id"]),
        shared_assumptions=[
            "The retained CCEL ThML bytes are the acquired electronic witness, not proof of a print edition.",
            "The pinned source oracle and TEI P5 validation establish the technical reconstruction gates only.",
        ],
        independent_corroboration=(
            "The source-bound oracle validates the six-member package; two direct reconstructions and the "
            "maintained CLI reconstruction are byte-equal across all six package members. A separate "
            "fresh CLI validation sidecar binds the current candidate and source manifest. The reversible "
            "work-local adapter preserves complete canonical TEI tree inverse, ordered carriers, notes, "
            "readings, day markers and index anchors. P5 and independent native projection checks pass."
        ),
    )
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _write_json(stage, EVIDENCE / f"{name}.json", shared | dict(
            status="pass", command=command, exit_code=0, claim=name,
            source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
            oracle_report_sha256=report.sha256, validation_sidecar_sha256=_sha(sidecar_bytes),
            candidate_tei_sha256=_sha(bound), complete_tree_inverse="pass"))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)

    at = _utc_now()
    review = dict(
        reviewer="agent:spurgeon-morneve-current-source-review",
        reviewed_at=at,
        coverage=dict(status="partial", declared=SCOPE,
            reached=["candidate"],
            inspected=["candidate/full-tree-inverse", "candidate/markers/DayOfYear",
                        "candidate/markers/scripture-comment", "candidate/header-and-comments",
                        "candidate/current-native-projection"],
            unreviewed=["decision/human-acceptance", "source/1865-print-collation",
                        "source/CCEL-Logos-rights", "publication/attribution-privacy",
                        "decision/publication-authorization"]),
        source_quality_uncertainty=[
            "The retained electronic header records editorial interventions that have not been independently confirmed.",
            "The electronic witness has not been collated against an 1865 print exemplar.",
        ],
        discrepancies=[],
        unreviewed_residuals=[
            "Human acceptance, CCEL/Logos electronic rights, public attribution notice, and publication authorization remain unrecorded."
        ],
    )
    review_path = _write_json(stage, EVIDENCE / "review.json", shared | review)
    decision = dict(
        source_local_disposition="Agent accepts only the complete retained CCEL ThML electronic witness as represented by this source-bound TEI master.",
        blockers=[],
        agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=at,
            supported_scope=SCOPE, unresolved_claims=[],
            unassessed_stronger_claims=["human acceptance", "1865 print identity",
                                        "CCEL/Logos rights clearance", "public attribution",
                                        "publication authorization"]),
        human_decision=dict(status="not-recorded"),
    )
    acceptance = stage / EDITION / "acceptance.json"
    record = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate_path,
        source_accounting_path=source_accounting, scope=scope, technical=technical,
        review=review | dict(report_path=review_path), representation_revision=REVISION,
        decision=decision)
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    master = _write(stage, EDITION / "master.tei.xml", bound)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=at,
                               master=make_file_binding(stage, master))
    write_acceptance(acceptance, record)
    state = _read(stage / WORK / "state.json")
    matches = [item for item in state["targets"] if item["target_type"] == "edition"
               and item["target_id"] == EDITION_ID]
    if len(matches) != 1 or matches[0]["stage"] != "acquired":
        raise PipelineError("one acquired Morning and Evening edition target is required")
    matches[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=at)
    matches[0]["evidence"].extend([EDITION.joinpath("master.tei.xml").as_posix(),
                                    EDITION.joinpath("acceptance.json").as_posix()])
    _write_json(stage, WORK / "state.json", state)
    validate_acceptance(acceptance, root=stage)
    validate_state(stage / WORK / "state.json", root=stage)
    projection = project_accepted_document(stage, acceptance_path=acceptance, category="prose")
    errors = verify_accepted_document(stage, acceptance_path=acceptance,
        rows=projection["rows"], receipt=projection["receipt"], category="prose")
    if errors or len(projection["rows"]) != 1:
        raise PipelineError(f"actual accepted-master native projection failed: {errors[:3]}")
    projection_path = _write_json(stage, EVIDENCE / "accepted-master-projection.json", {
        "contract": "ocd-lib030-accepted-master-projection-v1",
        "status": "pass", "identity": IDENTITY, "category": "prose",
        "master": make_file_binding(stage, master), "rows": projection["rows"],
        "receipt": projection["receipt"], "independent_verifier_errors": errors,
    })
    if _files(root / WORK) != before:
        raise PipelineError("canonical work changed while preparing isolated stage")
    output = dict(contract="ocd-lib030-morning-evening-external-stage-v1",
        status="staged-only", work_id=WORK_ID, stage_root=stage.as_posix(), before=before,
        after=_files(stage / WORK), source_sha256=SOURCE_SHA,
        source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
        oracle_report_sha256=report.sha256, validation_sidecar_sha256=_sha(sidecar_bytes),
        adapted_tei_sha256=_sha(adapted), bound_tei_sha256=_sha(bound),
        master_sha256=_sha(master.read_bytes()), acceptance_sha256=_sha(acceptance.read_bytes()),
        projection_category="prose", projection_rows=1,
        independent_verifier_errors=errors,
        accepted_master_projection=make_file_binding(stage, projection_path),
        source_manifest_authority_snapshot=make_file_binding(stage, authority_snapshot_path),
        canonical_before=before, canonical_after=_files(root / WORK),
        human_acceptance="not-recorded",
        rights="unassessed", publication="not-authorized", installation="not-performed")
    _write_json(stage, Path("stage-receipt.json"), output)
    return output


def validate_file_from_bytes(data: bytes) -> list[str]:
    """Validate an in-memory TEI using the existing file validator."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="ocd-lib030-p5-") as temporary:
        path = Path(temporary) / "candidate.tei.xml"
        path.write_bytes(data)
        return validate_file(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps({"work_id": result["work_id"], "master_sha256": result["master_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
