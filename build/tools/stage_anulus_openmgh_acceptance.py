"""Stage and guardedly install the Anulus openMGH electronic witness.

The default command is read-only. --prepare creates a separate reviewed
generation and receipt; --apply requires that exact receipt. A ZIP is package
evidence only: the extracted XML is the source authority.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from build.tei.openmgh_exclusive_oracle import _oracle
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    validate,
)
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "anulus-et-baculus-verses"
WORK = Path("library/works") / WORK_ID
EDITION_ID = "anulus-et-baculus-verses-openmgh-electronic"
FORM_ID = "anulus-et-baculus-verses-openmgh-retained"
ACQUISITION_ID = "anulus-et-baculus-verses-openmgh-acquired"
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/openmgh/bsb00000830/tei/bsb00000830.xml")
PACKAGE_ARCHIVE = Path("raw/openmgh/bsb00000830/bsb00000830.zip")
ACQUISITION_RECEIPT = Path("raw/openmgh/bsb00000830/acquisition-receipt.json")
MANIFEST = Path("sources/openmgh-exclusive") / WORK_ID / "source-manifest.json"
PROFILE = MANIFEST.with_name("reconstruction-profile.json")
BOUNDARY = MANIFEST.with_name("boundary-review.json")
POLICY = Path("sources/openmgh-exclusive/validation-policy.json")
PILOT = Path("plans/2026-09-22-source-preflight/openmgh-exclusive-pilot-20260926.json")
EVIDENCE = WORK / "integration/openmgh-exclusive-electronic-v1"
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
CANDIDATE_ROOT = Path(
    "C:/Scratch/Open Christian Data/openmgh-exclusive-pilot-20260926/anulus-et-baculus-verses-verified"
)
STAGE = Path("C:/Scratch/oae26")
RECEIPT = (
    ROOT
    / "plans/2026-09-22-source-preflight/anulus-openmgh-electronic-acceptance-stage-20260926.json"
)
CONTRACT = "ocd-anulus-openmgh-complete-generation-v1"
SOURCE_SHA = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
MANIFEST_SHA = "9b272caf7ed7426e0e4b693425e4e7dc048d968f2152f413deb269a37c52947a"
PACKAGE_SHA = "02c56f71d234327648e954983be6512b4d9d74342c2a2986c959b03aecd3c491"
ORIGINAL_SHA = "6b402bd584d3de697c332be77488022308bc8e6bb84a7f2f66a09afbd71f554c"
IDENTITY = {
    "work_id": WORK_ID,
    "textual_form_id": FORM_ID,
    "edition_id": EDITION_ID,
    "acquisition_id": ACQUISITION_ID,
}
SCOPE = (
    "The complete last work division 'De anulo et baculo versus' in the extracted "
    "openMGH bsb00000830 XML electronic witness, including its one verse block, "
    "82 line breaks and three page breaks. The other 28 work divisions and volume "
    "shell remain in the retained XML outside this accepted selection. No print "
    "collation or visual text review is claimed."
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def put(root: Path, relative: Path, data: bytes) -> Path:
    path = root / relative
    _io_path(path.parent).mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(data)
    return path


def put_json(root: Path, relative: Path, value: object) -> Path:
    return put(
        root,
        relative,
        (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode(),
    )


def copy_tree(source: Path, dest: Path) -> dict[str, str]:
    if _io_path(dest).exists():
        raise PipelineError(f"destination must be fresh: {dest}")
    files = _files(source)
    if not files:
        raise PipelineError("source work generation is empty")
    _io_path(dest).mkdir(parents=True)
    for rel in files:
        target = _io_path(dest / rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(source / rel), target)
    if _files(dest) != files:
        raise PipelineError("copied work generation differs")
    return files


def prepare(
    root: Path = ROOT,
    candidate_root: Path = CANDIDATE_ROOT,
    stage: Path = STAGE,
    receipt: Path = RECEIPT,
) -> dict[str, object]:
    root, candidate_root, stage = (
        root.resolve(strict=True),
        candidate_root.resolve(strict=True),
        stage.absolute(),
    )
    if (
        _io_path(stage).exists()
        or not stage.parent.is_dir()
        or stage.parent.is_symlink()
        or receipt.exists()
    ):
        raise PipelineError("Anulus stage and receipt must be fresh")
    if (
        root == stage
        or root in stage.parents
        or candidate_root == stage
        or candidate_root in stage.parents
    ):
        raise PipelineError("Anulus stage overlaps protected input")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    package = CandidatePackage.load(candidate_root / "package")
    if (
        manifest.sha256 != MANIFEST_SHA
        or package.sha256 != PACKAGE_SHA
        or package.manifest.get("status") != "nonaccepted"
    ):
        raise PipelineError("Anulus pilot candidate or source manifest changed")
    original = package.member_bytes("content.tei.xml")
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA:
        raise PipelineError("Anulus original TEI changed")
    report = validate(manifest, package, _oracle)
    previous = json.loads(_io_path(candidate_root / "validation.json").read_bytes())
    if (
        report.status != "pass"
        or report.findings
        or previous.get("report_sha256") != report.sha256
        or previous.get("candidate_sha256") != PACKAGE_SHA
    ):
        raise PipelineError("Anulus independent oracle result changed")
    source = root / SOURCE
    if digest(source) != SOURCE_SHA:
        raise PipelineError("Anulus extracted XML changed")
    acquisition = validate_acquisition(
        _io_path(root / ACQUISITION), root=_io_path(root)
    )
    if (
        acquisition["source_path"] != SOURCE.as_posix()
        or acquisition["source_sha256"] != SOURCE_SHA
    ):
        raise PipelineError("Anulus acquisition does not bind extracted XML")
    before = _files(root / WORK)
    if (
        ACCEPTANCE.relative_to(WORK).as_posix() in before
        or MASTER.relative_to(WORK).as_posix() in before
    ):
        raise PipelineError("Anulus master or acceptance already installed")
    copy_tree(root / WORK, stage / WORK)
    for rel in (
        SOURCE,
        PACKAGE_ARCHIVE,
        ACQUISITION_RECEIPT,
        MANIFEST,
        PROFILE,
        BOUNDARY,
        POLICY,
        PILOT,
    ):
        put(stage, rel, _io_path(root / rel).read_bytes())
    work = json.loads(_io_path(stage / WORK / "work.json").read_bytes())
    edition = work["textual_forms"][0]["editions"][0]
    if edition["edition_id"] != EDITION_ID or "category" in edition:
        raise PipelineError("Anulus edition identity/category changed")
    edition["category"] = "poetry"
    put_json(stage, WORK / "work.json", work)
    load_work(stage / WORK / "work.json")
    acquisition["source_scope"] = SCOPE
    extracted = next(
        item
        for item in acquisition["retained_files"]
        if item["path"] == SOURCE.as_posix()
    )
    extracted["scope"] = (
        "The complete extracted XML remains retained; this edition selects its complete last work division, with the other 28 divisions and volume shell outside the accepted readable text."
    )
    put_json(stage, ACQUISITION, acquisition)
    validate_acquisition(_io_path(stage / ACQUISITION), root=_io_path(stage))
    evidence = stage / EVIDENCE
    for name in package.member_names:
        put(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    for rel in (Path("package/manifest.json"), Path("validation.json")):
        put(
            stage,
            EVIDENCE / "inputs" / rel,
            _io_path(candidate_root / rel).read_bytes(),
        )
    source_binding = {
        "source_path": SOURCE.as_posix(),
        "source_sha256": SOURCE_SHA,
        "source_bytes": acquisition["source_bytes"],
        "source_scope": acquisition["source_scope"],
    }
    revision = {
        "id": "anulus-openmgh-electronic-v1",
        "date": datetime.now(timezone.utc).date().isoformat(),
        "note": "Accept the source-bound complete Anulus work division of the extracted openMGH electronic witness.",
    }
    derived = bind_reviewed_header(
        original,
        expected_sha256=ORIGINAL_SHA,
        identity=IDENTITY,
        source=source_binding,
        source_url=acquisition["url"],
        declared_scope=SCOPE,
        revision=revision,
    )
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError(
            "Anulus candidate body changed during acceptance header binding"
        )
    candidate = put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise PipelineError(f"Anulus acceptance TEI XSD failed: {errors[:3]}")
    retained = next(
        (x for x in acquisition["retained_files"] if x["path"] == SOURCE.as_posix()),
        None,
    )
    if retained is None or retained["sha256"] != SOURCE_SHA:
        raise PipelineError("Anulus retained extracted XML member changed")
    expected = [
        {"path": PACKAGE_ARCHIVE.as_posix(), "position": 1},
        {"path": SOURCE.as_posix(), "position": 2},
    ]
    excluded = [
        {
            "path": PACKAGE_ARCHIVE.as_posix(),
            "position": 1,
            "reason": "Retained download package only; the extracted XML is the source of text.",
        }
    ]
    included = [
        {
            **expected[1],
            "bytes": retained["bytes"],
            "sha256": SOURCE_SHA,
            "scope": retained["scope"],
        }
    ]
    scope = {
        "kind": "selection",
        "declared": SCOPE,
        "expected_members": expected,
        "included_members": included,
        "excluded_members": excluded,
    }
    common = {
        "identity": IDENTITY,
        "source": source_binding,
        "candidate": make_file_binding(stage, candidate),
        "scope": SCOPE,
        "accepted_scope": {"kind": "selection", "declared": SCOPE},
        "expected_members": expected,
        "included_members": included,
        "excluded_members": excluded,
        "missing_members": [],
        "unknown_members": [],
    }
    accounting = put_json(
        stage,
        EVIDENCE / "source-accounting.json",
        common
        | {
            "source_sha256": SOURCE_SHA,
            "source_bytes": acquisition["source_bytes"],
            "selected_work_div": "De anulo et baculo versus",
            "source_work_div_ordinal": 29,
            "volume_work_div_count": 29,
            "source_div_c14n_sha256": "698b343662082279203e87b2e8f9b673a6136721dacc1d631c84cf9f4e9cff08",
            "unselected_sibling_work_divs": 28,
            "source_manifest_sha256": MANIFEST_SHA,
            "candidate_package_sha256": PACKAGE_SHA,
            "oracle_report_sha256": report.sha256,
        },
    )
    inputs = {
        "source_manifest": make_file_binding(stage, stage / MANIFEST),
        "package_manifest": make_file_binding(
            stage, evidence / "inputs/package/manifest.json"
        ),
        "validation": make_file_binding(stage, evidence / "inputs/validation.json"),
        "boundary": make_file_binding(stage, stage / BOUNDARY),
        "pilot": make_file_binding(stage, stage / PILOT),
    }
    descriptions = {
        "validation": "Independent oracle passes for the exact nonaccepted package and extracted source XML.",
        "accounting": "The last complete work division is selected; the other 28 sibling work divisions and enclosing volume remain in the retained source.",
        "fidelity": "Every element, attribute, text node, line break, page break, and order in the selected source work div equals the candidate; deletion and wrong-sibling mutations are rejected.",
        "reproducibility": "The pilot reproduced all seven candidate/validation files byte for byte in a second process; this stage changes only the TEI header.",
        "schema": "Original and acceptance-header TEI both pass vendored TEI P5 XSD.",
        "closure": "Extracted XML, installed acquisition, source manifest, boundary declaration, package, oracle result, and header-bound candidate have exact hashes.",
    }
    technical = {
        "producer": {"id": manifest.record["converter"]["id"]},
        "checker": {"id": manifest.record["validator"]["id"]},
        "shared_assumptions": [
            "Producer and oracle share the declared two-locator whole-work boundary; the independent source inspection checked the last work div, previous sibling, and complete element/text tree."
        ],
        "independent_corroboration": "Pilot source div oracle and focused mutations pass; a separate direct source/candidate traversal found identical tags, attributes, text, child order, and tails.",
    }
    command = "py -3 -m build.tools.stage_anulus_openmgh_acceptance --prepare"
    for name, description in descriptions.items():
        path = put_json(
            stage,
            EVIDENCE / f"{name}.json",
            common
            | {
                "status": "pass",
                "command": command,
                "exit_code": 0,
                "description": description,
                "inputs": inputs,
                "oracle_report_sha256": report.sha256,
            },
        )
        technical[name] = {
            "path": path,
            "status": "pass",
            "command": command,
            "exit_code": 0,
        }
    reviewed_at = now()
    coverage = {
        "status": "unavailable",
        "declared": SCOPE,
        "reached": ["retained XML work div", "exact nonaccepted candidate TEI"],
        "inspected": [
            "retained XML work div/boundary and adjacent sibling",
            "exact nonaccepted candidate TEI/complete source-candidate element, attribute, and text comparison",
        ],
        "unreviewed": [
            "all visual source/TEI comparison loci, including opening, middle, ending, and line/page transitions"
        ],
    }
    review = {
        "reviewer": "agent:anulus-openmgh-electronic-evidence-review",
        "reviewed_at": reviewed_at,
        "coverage": coverage,
        "source_quality_uncertainty": [
            "No independent print witness has been collated."
        ],
        "discrepancies": [],
        "unreviewed_residuals": [
            "No visual source/TEI comparison was performed; complete work fidelity was checked structurally and textually against extracted XML."
        ],
    }
    review_path = put_json(
        stage,
        EVIDENCE / "review.json",
        common
        | review
        | {
            "inputs": inputs,
            "unassessed": [
                "visual review",
                "human review",
                "print collation",
                "rights clearance",
                "publication",
            ],
        },
    )
    decision = {
        "source_local_disposition": "Agent acceptance of this complete electronic work division only.",
        "blockers": [],
        "agent_assessment": {
            "status": "accepted",
            "actor": review["reviewer"],
            "assessed_at": reviewed_at,
            "supported_scope": SCOPE,
            "unresolved_claims": [],
            "unassessed_stronger_claims": [
                "visual text review",
                "independently collated print witness",
                "human acceptance",
                "rights clearance",
                "publication",
            ],
        },
        "human_decision": {"status": "not-recorded"},
    }
    record = build_acceptance_record(
        stage,
        identity=IDENTITY,
        candidate_path=candidate,
        source_accounting_path=accounting,
        scope=scope,
        technical=technical,
        review=review | {"report_path": review_path},
        representation_revision=revision,
        decision=decision,
    )
    write_acceptance(_io_path(stage / ACCEPTANCE), record)
    validate_acceptance(_io_path(stage / ACCEPTANCE), root=_io_path(stage))
    put(stage, MASTER, derived)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(
        status="promoted",
        promoted_at=now(),
        master=make_file_binding(stage, stage / MASTER),
    )
    write_acceptance(_io_path(stage / ACCEPTANCE), record)
    state = json.loads(_io_path(stage / WORK / "state.json").read_bytes())
    target = next(x for x in state["targets"] if x["target_id"] == EDITION_ID)
    if target["stage"] != "acquired":
        raise PipelineError("Anulus edition state already advanced")
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now())
    target["evidence"].extend([MASTER.as_posix(), ACCEPTANCE.as_posix()])
    put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(stage / ACCEPTANCE), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    after = _files(stage / WORK)
    external = {
        p: h
        for p, h in _files(stage).items()
        if not p.startswith(WORK.as_posix() + "/")
    }
    for p, h in external.items():
        if digest(root / p) != h:
            raise PipelineError(f"Anulus outside dependency changed: {p}")
    result = {
        "contract": CONTRACT,
        "status": "staged-only",
        "prepared_at": now(),
        "canonical_root": root.as_posix(),
        "stage_root": stage.as_posix(),
        "work_id": WORK_ID,
        "before": before,
        "after": after,
        "external_dependencies": external,
        "changed_paths": sorted(
            p for p in set(before) | set(after) if before.get(p) != after.get(p)
        ),
        "source_path": SOURCE.as_posix(),
        "source_sha256": SOURCE_SHA,
        "category": "poetry",
        "limits": [
            "complete extracted electronic work div only",
            "visual review unperformed",
            "human, print, rights and publication separate",
        ],
    }
    _write_json_durable(receipt, result)
    return result


def preflight(receipt: Path = RECEIPT) -> tuple[dict[str, object], Path, Path]:
    record = json.loads(_io_path(receipt.resolve(strict=True)).read_bytes())
    if record.get("contract") != CONTRACT or record.get("work_id") != WORK_ID:
        raise PipelineError("Anulus stage receipt contract differs")
    root, stage = (
        Path(record["canonical_root"]).resolve(strict=True),
        Path(record["stage_root"]).resolve(strict=True),
    )
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("Anulus stage/canonical roots overlap")
    before, after = _files(root / WORK), _files(stage / WORK)
    if before != record["before"] or after != record["after"]:
        raise PipelineError("Anulus complete work generation changed")
    allowed = {
        "work.json",
        "state.json",
        ACQUISITION.relative_to(WORK).as_posix(),
        ACCEPTANCE.relative_to(WORK).as_posix(),
        MASTER.relative_to(WORK).as_posix(),
    }
    prefix = EVIDENCE.relative_to(WORK).as_posix() + "/"
    for p in set(before) | set(after):
        if (
            before.get(p) != after.get(p)
            and p not in allowed
            and not (p.startswith(prefix) and p not in before)
        ):
            raise PipelineError(f"Anulus unrelated canonical work file differs: {p}")
    old_work, new_work = (
        json.loads(_io_path(root / WORK / "work.json").read_bytes()),
        json.loads(_io_path(stage / WORK / "work.json").read_bytes()),
    )
    old_work["textual_forms"][0]["editions"][0]["category"] = "poetry"
    if old_work != new_work:
        raise PipelineError("Anulus staged work changes more than category")
    old_acquisition = json.loads(_io_path(root / ACQUISITION).read_bytes())
    new_acquisition = json.loads(_io_path(stage / ACQUISITION).read_bytes())
    if len(old_acquisition["retained_files"]) != 2 or [
        item["path"] for item in old_acquisition["retained_files"]
    ] != [PACKAGE_ARCHIVE.as_posix(), SOURCE.as_posix()]:
        raise PipelineError("Anulus acquisition member order changed")
    old_acquisition["source_scope"] = SCOPE
    old_acquisition["retained_files"][1]["scope"] = (
        "The complete extracted XML remains retained; this edition selects its complete last work division, with the other 28 divisions and volume shell outside the accepted readable text."
    )
    if new_acquisition != old_acquisition:
        raise PipelineError("Anulus staged acquisition changes more than source scope")
    old_state = json.loads(_io_path(root / WORK / "state.json").read_bytes())
    new_state = json.loads(_io_path(stage / WORK / "state.json").read_bytes())
    if (
        len(old_state["targets"]) != 2
        or old_state["targets"][0] != new_state["targets"][0]
    ):
        raise PipelineError("Anulus acquisition state changed")
    old_edition, new_edition = old_state["targets"][1], new_state["targets"][1]
    old_edition.update(stage="accepted", reason=PROMOTED_MASTER_REASON)
    old_edition["evidence"].extend([MASTER.as_posix(), ACCEPTANCE.as_posix()])
    old_edition["updated_at"] = new_edition["updated_at"]
    if old_state != new_state:
        raise PipelineError(
            "Anulus edition state changes beyond accepted-master transition"
        )
    if any(
        p in before
        for p in (
            ACCEPTANCE.relative_to(WORK).as_posix(),
            MASTER.relative_to(WORK).as_posix(),
        )
    ) or not all(
        p in after
        for p in (
            ACCEPTANCE.relative_to(WORK).as_posix(),
            MASTER.relative_to(WORK).as_posix(),
        )
    ):
        raise PipelineError("Anulus master/acceptance installation is not additive")
    external = record["external_dependencies"]
    for p, h in external.items():
        if digest(root / p) != h or digest(stage / p) != h:
            raise PipelineError(f"Anulus external evidence changed: {p}")
    accepted = validate_acceptance(_io_path(stage / ACCEPTANCE), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    if (
        accepted["promotion"]["status"] != "promoted"
        or accepted["decision"]["agent_assessment"]["status"] != "accepted"
        or accepted["decision"]["human_decision"]["status"] != "not-recorded"
        or accepted["identity"] != IDENTITY
        or accepted["scope"]["kind"] != "selection"
        or accepted["scope"]["declared"] != SCOPE
        or accepted["review"]["coverage"]["status"] != "unavailable"
    ):
        raise PipelineError("Anulus promoted acceptance claim differs")
    if (
        after[MASTER.relative_to(WORK).as_posix()]
        != after[(EVIDENCE / "candidate.tei.xml").relative_to(WORK).as_posix()]
    ):
        raise PipelineError("Anulus master differs from header-bound candidate")
    if (
        sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        != record["changed_paths"]
    ):
        raise PipelineError("Anulus changed-file inventory differs")
    return record, root, stage


def install(
    receipt: Path = RECEIPT, *, fail_at: Callable[[str], None] | None = None
) -> dict[str, object]:
    record, root, stage = preflight(receipt)
    target = root / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        preflight(receipt)
        operation = (
            root / "library/.sidecar-operations" / ("anulus-" + uuid.uuid4().hex[:16])
        )
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (
            operation / name for name in ("incoming", "previous", "failed-new")
        )
        journal = operation / "operation.json"
        state = {
            "contract": CONTRACT,
            "work_id": WORK_ID,
            "receipt": receipt.resolve().as_posix(),
            "before": record["before"],
            "after": record["after"],
            "phase": "created",
            "updated_at": now(),
        }
        _write_json_durable(journal, state)
        moved = live = False
        try:
            copy_tree(stage / WORK, incoming)
            if (
                _files(incoming) != record["after"]
                or _files(target) != record["before"]
            ):
                raise PipelineError("Anulus incoming or canonical generation changed")
            state.update(phase="prepared", updated_at=now())
            _write_json_durable(journal, state)
            if fail_at:
                fail_at("after-copy")
            os.replace(_io_path(target), _io_path(previous))
            moved = True
            state.update(phase="previous-moved", updated_at=now())
            _write_json_durable(journal, state)
            if fail_at:
                fail_at("after-old-rename")
            os.replace(_io_path(incoming), _io_path(target))
            live = True
            state.update(phase="new-live", updated_at=now())
            _write_json_durable(journal, state)
            if fail_at:
                fail_at("after-new-rename")
            if _files(target) != record["after"]:
                raise PipelineError("Anulus installed generation differs")
            validate_acceptance(
                _io_path(target / ACCEPTANCE.relative_to(WORK)), root=_io_path(root)
            )
            validate_state(_io_path(target / "state.json"), root=_io_path(root))
            if fail_at:
                fail_at("after-validation")
            state.update(phase="complete", updated_at=now())
            _write_json_durable(journal, state)
            return {
                "status": "installed-and-validated",
                "operation": operation.as_posix(),
                "before_count": len(record["before"]),
                "after_count": len(record["after"]),
            }
        except BaseException:
            try:
                if live:
                    if _files(target) != record["after"]:
                        raise PipelineError(
                            "Anulus live generation changed before rollback"
                        )
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if (
                        _io_path(target).exists()
                        or _files(previous) != record["before"]
                    ):
                        raise PipelineError(
                            "Anulus previous generation changed before rollback"
                        )
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != record["before"]:
                        raise PipelineError("Anulus rollback restored unexpected bytes")
                state.update(
                    phase="rolled-back" if moved else "failed-before-swap",
                    updated_at=now(),
                )
                _write_json_durable(journal, state)
            except BaseException as error:
                state.update(
                    phase="recovery-required",
                    rollback_error=str(error),
                    updated_at=now(),
                )
                _write_json_durable(journal, state)
                raise PipelineError(
                    f"Anulus rollback requires recovery: {operation}"
                ) from error
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidate", type=Path, default=CANDIDATE_ROOT)
    parser.add_argument("--stage", type=Path, default=STAGE)
    parser.add_argument("--receipt", type=Path, default=RECEIPT)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.prepare and args.apply:
        parser.error("--prepare and --apply are mutually exclusive")
    if args.prepare:
        result = prepare(args.root, args.candidate, args.stage, args.receipt)
    elif args.apply:
        result = install(args.receipt)
    else:
        record, _root, _stage = preflight(args.receipt)
        result = {
            "status": "ready",
            "before_count": len(record["before"]),
            "after_count": len(record["after"]),
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
