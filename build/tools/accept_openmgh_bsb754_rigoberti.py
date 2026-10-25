"""Stage, preflight, or guarded-install the exact bsb754 Vita Rigoberti master."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from lxml import etree

from build.tei import openmgh_bsb754_rigoberti_oracle as oracle_module
from build.tei.openmgh_bsb754_rigoberti_oracle import (
    SOURCE_SHA256,
    check_candidate,
)
from build.tools import prepare_openmgh_bsb754_rigoberti as source
from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import (
    project_accepted_prose,
    verify_accepted_prose,
)
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _commit_generation
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works") / source.WORK_ID
EDITION = WORK / "forms" / source.FORM_ID / "editions" / source.EDITION_ID
EVIDENCE = WORK / "integration" / "openmgh-bsb754-rigoberti-v1"
CONTRACT = "ocd-openmgh-bsb754-rigoberti-acceptance-stage-v1"
SOURCE_CREDIT = WORK / "publication" / "SOURCE_CREDIT.md"
TEI_NS = "http://www.tei-c.org/ns/1.0"


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _write(path: Path, data: bytes) -> Path:
    target = Path(_io_path(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return path


def _write_json(path: Path, value: object) -> Path:
    return _write(path, _json_bytes(value))


def _copy(root: Path, stage: Path, relative: Path) -> None:
    from_path = Path(_io_path(root / relative))
    to_path = Path(_io_path(stage / relative))
    to_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(from_path, to_path)


def _source_scope(oracle: dict) -> str:
    selection = oracle["selection"]
    return (
        "The complete source-native Vita Rigoberti text in section I of the "
        "retained openMGH bsb00000754 electronic witness, selecting direct "
        f"children {selection['first_child_index']} through "
        f"{selection['last_child_index_inclusive']} inclusive of the flat "
        "carrier. It includes the opening page break, section numeral I, the "
        "capitula, the Vita heading, and all following Vita lines through "
        f"{selection['last_id']} ({selection['last_source_text']}). The "
        "selection stops immediately before source marker II at "
        f"{oracle['boundary_evidence']['next_section_id']}; the separately "
        "titled 894 Translatio and following Translatio brachii remain outside "
        "this edition. The full extracted XML remains retained as the source; "
        "the ZIP is only its acquisition package."
    )


def _boundary_note(oracle: dict) -> str:
    selection = oracle["selection"]
    boundary = oracle["boundary_evidence"]
    return f"""# bsb754 Vita Rigoberti source boundary

The retained text source is `{oracle['source_path']}` (SHA-256 `{oracle['source_sha256']}`). Its single `ab` carrier is mislabeled `Vita Eucherii`; that inherited label cannot define this selection because the carrier continues across several texts.

This candidate selects the complete Vita section only: source children {selection['first_child_index']}–{selection['last_child_index_inclusive']} inclusive, beginning at `{selection['first_id']}` and ending at `{selection['last_id']}` with “{selection['last_source_text']}”. It preserves the preceding `I.` marker and capitula. The source locator `{boundary['capitula_locator_id']}` introduces the following work about Rigobert’s life and deeds, and `{boundary['vita_heading_id']}` marks the Vita itself.

The original printed contents distinguish the Vita on pp. 58–78, the *Translatio a. 894* on pp. 78–79, and the *Translatio brachii* on p. 80 ([contents scan]({boundary['printed_contents_url']})). In the retained TEI, marker `II.` at `{boundary['next_section_id']}` starts the 894 translation; marker `III.` at `{boundary['following_translation_id']}` starts the arm translation. Both adjacent sections are excluded from this Vita candidate. This documents the boundaries of this existing work record; it does not create or assert additional catalog work identities.

The extracted XML is the text authority. The retained ZIP is checked for byte equality with that XML and is treated as the package only. Source publication and license statements and the print bibliography are copied unchanged into the candidate header. The source header assigns CC BY 4.0 to MGH/BSB digital annotations, says the underlying text is believed public domain, and requests source credit to both institutions.
"""


def _source_statements(source_bytes: bytes) -> tuple[str, str]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    document = etree.fromstring(source_bytes, parser)
    namespace = {"t": TEI_NS}
    licenses = document.xpath(
        "/t:TEI/t:teiHeader/t:fileDesc/t:publicationStmt//t:licence",
        namespaces=namespace,
    )
    bibliographies = document.xpath(
        "/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc/t:biblFull",
        namespaces=namespace,
    )
    if len(licenses) != 1 or len(bibliographies) != 1:
        raise PipelineError("retained source license or print bibliography is ambiguous")
    license_text = " ".join("".join(licenses[0].itertext()).split())
    bibliography_text = " ".join("".join(bibliographies[0].itertext()).split())
    if not license_text or not bibliography_text:
        raise PipelineError("retained source license or print bibliography is empty")
    return license_text, bibliography_text


def _source_credit(master_sha256: str, license_text: str, bibliography_text: str) -> str:
    return f"""# Vita sancti Rigoberti source credit and rights evidence

Authority: retained openMGH TEI header, not an inferred whole-dataset license.

Retained text source: `{source.SOURCE.as_posix()}` (SHA-256 `{SOURCE_SHA256}`). The retained ZIP is only the acquisition package; the extracted XML is the text source.

Accepted technical master: `{(EDITION / 'master.tei.xml').as_posix()}` (SHA-256 `{master_sha256}`). It represents the complete section-I Vita, children 279–1150 of the source carrier. The 894 translation and the arm translation are adjacent, separately enumerated texts and are excluded.

Printed bibliography as identified in the retained source header:

{bibliography_text}

Retained license statement (normalized whitespace; wording preserved):

{license_text}

This source statement assigns CC BY 4.0 to digital annotations added by MGH and BSB, separately says they make no rights claim to the underlying text believed to be public domain, and requests credit to both institutions. It is reproduced as source evidence; it does not establish independent rights clearance, human acceptance, print collation, or publication authorization. No visual source review is claimed.
"""


def prepare(
    root: Path,
    direct_receipt: Path,
    stage: Path,
    receipt: Path,
) -> dict:
    root = root.resolve(strict=True)
    direct_receipt = direct_receipt.resolve(strict=True)
    stage = stage.absolute()
    receipt = receipt.absolute()
    if (
        root == stage
        or root in stage.parents
        or stage in root.parents
        or Path(_io_path(stage)).exists()
        or Path(_io_path(receipt)).exists()
        or not Path(_io_path(stage.parent)).is_dir()
        or not Path(_io_path(receipt.parent)).is_dir()
        or stage.parent.resolve(strict=True) != receipt.parent.resolve(strict=True)
    ):
        raise PipelineError("fresh sibling stage and receipt paths outside the canonical root are required")
    direct = _read(direct_receipt)
    if (
        direct.get("contract") != "ocd-openmgh-bsb754-rigoberti-direct-v1"
        or direct.get("status") != "nonaccepted"
        or direct.get("work_id") != source.WORK_ID
        or direct.get("edition_id") != source.EDITION_ID
        or direct.get("source_sha256") != SOURCE_SHA256
        or direct.get("tei_p5") != "pass"
        or direct.get("native_prose_rows") != 1
        or direct.get("native_prose_verification") != "pass"
    ):
        raise PipelineError("direct source candidate receipt differs")
    candidate_path = Path(direct["candidate_path"]).resolve(strict=True)
    candidate_bytes = Path(_io_path(candidate_path)).read_bytes()
    if _sha(candidate_path) != direct["candidate_sha256"]:
        raise PipelineError("direct candidate hash differs")
    source_bytes = Path(_io_path(root / source.SOURCE)).read_bytes()
    license_text, bibliography_text = _source_statements(source_bytes)
    oracle = check_candidate(source_bytes, candidate_bytes)
    if oracle != direct["source_oracle"]:
        raise PipelineError("direct source oracle report differs")
    if (
        _sha(root / WORK / "work.json") != direct["work_sha256"]
        or _sha(root / WORK / "state.json") != direct["state_sha256"]
        or _sha(root / WORK / "forms" / source.FORM_ID / "editions"
                / source.EDITION_ID / "acquisitions" / f"{source.ACQUISITION_ID}.json")
        != direct["acquisition_sha256"]
    ):
        raise PipelineError("direct candidate was prepared from a different work preimage")

    with TemporaryDirectory(prefix="rigoberti-clean-repro-") as temporary:
        reproduced = Path(temporary) / "direct"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "build.tools.prepare_openmgh_bsb754_rigoberti",
                "--destination",
                str(reproduced),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        reproduced_candidate = reproduced / source.WORK_ID / "candidate.tei.xml"
        if (
            not result.stdout.strip()
            or _sha(reproduced_candidate) != direct["candidate_sha256"]
        ):
            raise PipelineError("fresh-process candidate reproduction differs")

    before = _files(root / WORK)
    shutil.copytree(_io_path(root / WORK), _io_path(stage / WORK))
    if _files(stage / WORK) != before:
        raise PipelineError("complete work preimage copy differs")
    for relative in (source.SOURCE, source.PACKAGE, source.ACQUISITION_RECEIPT):
        _copy(root, stage, relative)

    current_work = _read(root / WORK / "work.json")
    staged_work = _read(stage / WORK / "work.json")
    editions = staged_work["textual_forms"][0]["editions"]
    if len(editions) != 1 or editions[0].get("edition_id") != source.EDITION_ID:
        raise PipelineError("single canonical Rigoberti edition changed")
    edition = editions[0]
    if edition.get("category") or edition.get("language"):
        raise PipelineError("edition category/language preimage changed")
    edition.update(category="prose", language="la")
    validate_identity_update(current_work, staged_work)
    _write_json(stage / WORK / "work.json", staged_work)
    load_work(Path(_io_path(stage / WORK / "work.json")))

    revision = {
        "id": source.REVISION_ID,
        "date": source.REVISION_DATE,
        "note": source.REVISION_NOTE,
    }
    identity = {
        "work_id": source.WORK_ID,
        "textual_form_id": source.FORM_ID,
        "edition_id": source.EDITION_ID,
        "acquisition_id": source.ACQUISITION_ID,
    }
    acquisition = _read(
        stage / WORK / "forms" / source.FORM_ID / "editions"
        / source.EDITION_ID / "acquisitions" / f"{source.ACQUISITION_ID}.json"
    )
    scope_text = _source_scope(oracle)
    source_binding = {
        "source_path": source.SOURCE.as_posix(),
        "source_sha256": SOURCE_SHA256,
        "source_bytes": len(source_bytes),
        "source_scope": scope_text,
    }
    bound_candidate_bytes = bind_reviewed_header(
        candidate_bytes,
        expected_sha256=direct["candidate_sha256"],
        identity=identity,
        source=source_binding,
        source_url=acquisition["url"],
        declared_scope=scope_text,
        revision=revision,
    )
    if (
        bound_candidate_bytes.split(b"</teiHeader>", 1)[1]
        != candidate_bytes.split(b"</teiHeader>", 1)[1]
    ):
        raise PipelineError("candidate binding changed the source body")
    bound_oracle = check_candidate(source_bytes, bound_candidate_bytes)
    candidate_rel = EVIDENCE / "candidate.tei.xml"
    candidate_in_stage = _write(stage / candidate_rel, bound_candidate_bytes)
    direct_candidate_rel = EVIDENCE / "direct-candidate.tei.xml"
    _write(stage / direct_candidate_rel, candidate_bytes)
    direct_receipt_rel = EVIDENCE / "direct-receipt.json"
    _write(stage / direct_receipt_rel, Path(_io_path(direct_receipt)).read_bytes())
    if errors := validate_file(Path(_io_path(candidate_in_stage))):
        raise PipelineError(f"bound source candidate P5 validation failed: {errors[:3]}")
    boundary_rel = EVIDENCE / "source-boundary.md"
    boundary_path = _write(
        stage / boundary_rel, _boundary_note(oracle).encode("utf-8")
    )
    source_accounting_rel = EVIDENCE / "source-accounting.json"
    expected = [
        {"path": source.PACKAGE.as_posix(), "position": 1},
        {"path": source.SOURCE.as_posix(), "position": 2},
    ]
    included = [
        {
            "path": source.SOURCE.as_posix(),
            "position": 2,
            "bytes": len(source_bytes),
            "sha256": SOURCE_SHA256,
            "scope": scope_text,
        }
    ]
    excluded = [
        {
            "path": source.PACKAGE.as_posix(),
            "position": 1,
            "reason": "The ZIP is the acquisition package; its extracted TEI XML is the text source.",
        }
    ]
    scope = {
        "kind": "selection",
        "declared": scope_text,
        "expected_members": expected,
        "included_members": included,
        "excluded_members": excluded,
    }
    common = {
        "identity": identity,
        "source": {
            "source_path": source.SOURCE.as_posix(),
            "source_sha256": SOURCE_SHA256,
            "source_bytes": len(source_bytes),
            "source_scope": acquisition["source_scope"],
        },
        "candidate": make_file_binding(stage, candidate_in_stage),
        "scope": scope_text,
        "accepted_scope": {"kind": "selection", "declared": scope_text},
        "expected_members": expected,
        "included_members": included,
        "excluded_members": excluded,
        "missing_members": [],
        "unknown_members": [],
    }
    accounting_path = _write_json(
        stage / source_accounting_rel,
        common
        | {
            "scope": acquisition["source_scope"],
            "source_sha256": SOURCE_SHA256,
            "source_bytes": len(source_bytes),
            "source_carrier": oracle["source_carrier"],
            "source_child_count": oracle["source_child_count"],
            "selected_source_children": oracle["selection"],
            "boundary_evidence": oracle["boundary_evidence"],
            "structure": oracle["structure"],
            "source_oracle": bound_oracle,
            "candidate_sha256": _sha(candidate_in_stage),
            "direct_candidate_path": direct_candidate_rel.as_posix(),
            "direct_candidate_sha256": direct["candidate_sha256"],
            "direct_receipt_path": direct_receipt_rel.as_posix(),
            "direct_receipt_sha256": _sha(direct_receipt),
            "clean_process_reproduction": "pass",
            "mutation_challenges": direct["mutation_challenges"],
            "projection_profile": None,
        },
    )
    command = "py -3 -m build.tools.accept_openmgh_bsb754_rigoberti prepare"
    technical: dict[str, dict[str, object]] = {
        "producer": {"id": "ocd-openmgh-bsb754-rigoberti-direct-v1"},
        "checker": {"id": "ocd-openmgh-bsb754-rigoberti-source-oracle-v1"},
        "shared_assumptions": [
            "Producer and oracle both read the retained flat carrier; independent boundary pins come from the source IDs, explicit Vita ending before II, and the original MGH contents scan."
        ],
        "independent_corroboration": (
            "The independently selected 872-node section-I span, exact node signatures, "
            "printed contents, capitula locator, Vita heading, and following II/III "
            "translation boundaries agree."
        ),
    }
    proof = {
        **common,
        "status": "pass",
        "command": command,
        "exit_code": 0,
        "source_oracle": bound_oracle,
        "direct_receipt_sha256": _sha(direct_receipt),
        "fresh_process_candidate_sha256": direct["candidate_sha256"],
        "mutation_challenges": direct["mutation_challenges"],
        "tei_p5": "pass",
        "native_prose": "one row; independent verification passed",
    }
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof_path = _write_json(stage / EVIDENCE / f"{name}.json", proof | {"claim": name})
        technical[name] = {
            "path": proof_path,
            "status": "pass",
            "command": command,
            "exit_code": 0,
        }

    reviewed_at = _now()
    review = {
        "reviewer": "agent:rigobertus_boundary_review",
        "reviewed_at": reviewed_at,
        "coverage": {
            "status": "partial",
            "declared": scope_text,
            "reached": [
                "retained XML children 279-1150 (complete section-I span)",
                "retained XML children 1151-1222 (adjacent II/III boundaries)",
                "original printed contents scan (three separate text entries)",
            ],
            "inspected": [
                "retained XML children 279-1150 (complete section-I span)",
                "retained XML children 1151-1222 (adjacent II/III boundaries)",
                "original printed contents scan (three separate text entries)",
            ],
            "unreviewed": ["visual source-to-TEI comparison"],
        },
        "source_quality_uncertainty": [
            "The candidate represents the retained MGH/BSB electronic witness; it was not collated against an independent print copy."
        ],
        "discrepancies": [],
        "unreviewed_residuals": [
            "Visual proofreading, human acceptance, print collation, rights clearance, and publication are not recorded."
        ],
    }
    review_path = _write_json(
        stage / EVIDENCE / "review.json",
        common | review | {"source_boundary_path": boundary_rel.as_posix()},
    )
    decision = {
        "source_local_disposition": "Accept only the source-native section-I Vita span; do not include the separately enumerated 894 or arm translation sections.",
        "blockers": [],
        "agent_assessment": {
            "status": "accepted",
            "actor": review["reviewer"],
            "assessed_at": reviewed_at,
            "supported_scope": scope_text,
            "unresolved_claims": [],
            "unassessed_stronger_claims": [
                "visual source review",
                "human acceptance",
                "print collation",
                "rights clearance",
                "publication",
            ],
        },
        "human_decision": {"status": "not-recorded"},
    }

    edition_root = WORK / "forms" / source.FORM_ID / "editions" / source.EDITION_ID
    acceptance_path = stage / edition_root / "acceptance.json"
    master_path = stage / edition_root / "master.tei.xml"
    _write(master_path, bound_candidate_bytes)
    if errors := validate_file(Path(_io_path(master_path))):
        raise PipelineError(f"accepted TEI P5 validation failed: {errors[:3]}")

    acceptance = build_acceptance_record(
        stage,
        identity=identity,
        candidate_path=candidate_in_stage,
        source_accounting_path=accounting_path,
        scope=scope,
        technical=technical,
        review=review | {"report_path": review_path},
        representation_revision=revision,
        decision=decision,
    )
    acceptance["promotion"].update(
        status="promoted",
        promoted_at=reviewed_at,
        master=make_file_binding(stage, master_path),
    )
    write_acceptance(acceptance_path, acceptance)
    credit_path = _write(
        stage / SOURCE_CREDIT,
        _source_credit(_sha(master_path), license_text, bibliography_text).encode("utf-8"),
    )

    state = _read(stage / WORK / "state.json")
    edition_targets = [
        item
        for item in state["targets"]
        if item.get("target_type") == "edition"
        and item.get("target_id") == source.EDITION_ID
    ]
    if len(edition_targets) != 1 or edition_targets[0].get("stage") != "acquired":
        raise PipelineError("one acquired edition state target is required")
    edition_targets[0].update(
        stage="accepted",
        reason=PROMOTED_MASTER_REASON,
        updated_at=reviewed_at,
    )
    for path in (
        (edition_root / "master.tei.xml").as_posix(),
        (edition_root / "acceptance.json").as_posix(),
        candidate_rel.as_posix(),
        SOURCE_CREDIT.as_posix(),
    ):
        if path not in edition_targets[0]["evidence"]:
            edition_targets[0]["evidence"].append(path)
    _write_json(stage / WORK / "state.json", state)
    validate_state(Path(_io_path(stage / WORK / "state.json")), root=Path(_io_path(stage)))
    validate_acceptance(acceptance_path, root=stage)

    projection = project_accepted_prose(stage, acceptance_path=acceptance_path)
    errors = verify_accepted_prose(
        stage,
        acceptance_path=acceptance_path,
        rows=projection["rows"],
        receipt=projection["receipt"],
    )
    if errors or len(projection["rows"]) != 1:
        raise PipelineError(f"actual accepted-master projection failed: {errors[:3]}")
    before = _files(root / WORK)
    after = _files(stage / WORK)
    record = {
        "contract": CONTRACT,
        "status": "staged-only",
        "work_id": source.WORK_ID,
        "edition_id": source.EDITION_ID,
        "canonical_root": root.as_posix(),
        "stage_root": stage.resolve().as_posix(),
        "direct_receipt": direct_receipt.as_posix(),
        "direct_receipt_sha256": _sha(direct_receipt),
        "source_sha256": SOURCE_SHA256,
        "package_sha256": source.PACKAGE_SHA256,
        "acquisition_receipt_sha256": source.ACQUISITION_RECEIPT_SHA256,
        "generator_sha256": _sha(Path(source.__file__)),
        "oracle_sha256": _sha(Path(oracle_module.__file__)),
        "acceptance_tool_sha256": _sha(Path(__file__)),
        "before": before,
        "after": after,
        "master_sha256": _sha(master_path),
        "acceptance_sha256": _sha(acceptance_path),
        "candidate_sha256": _sha(candidate_in_stage),
        "source_credit_sha256": _sha(credit_path),
        "projection_rows": len(projection["rows"]),
        "projection_errors": [],
        "human_review": "not-recorded",
        "rights_clearance": "not-recorded",
        "installation": "not-performed",
    }
    _write_json(receipt, record)
    return record


def preflight(receipt: Path) -> dict:
    receipt = receipt.resolve(strict=True)
    record = _read(receipt)
    if record.get("contract") != CONTRACT or record.get("status") != "staged-only":
        raise PipelineError("Rigoberti stage receipt contract differs")
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    if root != ROOT.resolve(strict=True) or root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("canonical and staged roots differ or overlap")
    direct_receipt = Path(record["direct_receipt"]).resolve(strict=True)
    direct = _read(direct_receipt)
    source_bytes = Path(_io_path(root / source.SOURCE)).read_bytes()
    license_text, bibliography_text = _source_statements(source_bytes)
    staged_candidate = Path(_io_path(stage / EVIDENCE / "candidate.tei.xml")).read_bytes()
    staged_direct_candidate = Path(
        _io_path(stage / EVIDENCE / "direct-candidate.tei.xml")
    ).read_bytes()
    direct_oracle = check_candidate(source_bytes, staged_direct_candidate)
    fresh_oracle = check_candidate(source_bytes, staged_candidate)
    direct_candidate = Path(direct["candidate_path"]).resolve(strict=True)
    direct_oracle_without_hash = {
        key: value for key, value in direct.get("source_oracle", {}).items()
        if key != "candidate_sha256"
    }
    bound_oracle_without_hash = {
        key: value for key, value in fresh_oracle.items()
        if key != "candidate_sha256"
    }
    if (
        _sha(direct_receipt) != record["direct_receipt_sha256"]
        or _sha(stage / EVIDENCE / "direct-receipt.json")
        != record["direct_receipt_sha256"]
        or direct.get("contract") != "ocd-openmgh-bsb754-rigoberti-direct-v1"
        or direct.get("status") != "nonaccepted"
        or direct.get("source_sha256") != SOURCE_SHA256
        or _sha(direct_candidate) != direct.get("candidate_sha256")
        or staged_direct_candidate != Path(_io_path(direct_candidate)).read_bytes()
        or direct_oracle != direct.get("source_oracle")
        or direct_oracle_without_hash != bound_oracle_without_hash
        or fresh_oracle["candidate_sha256"] != record["candidate_sha256"]
        or direct.get("work_sha256") != _sha(root / WORK / "work.json")
        or direct.get("state_sha256") != _sha(root / WORK / "state.json")
    ):
        raise PipelineError("source/candidate/direct receipt bindings differ")
    for relative, expected in (
        (source.SOURCE, SOURCE_SHA256),
        (source.PACKAGE, source.PACKAGE_SHA256),
        (source.ACQUISITION_RECEIPT, source.ACQUISITION_RECEIPT_SHA256),
    ):
        if _sha(root / relative) != expected or _sha(stage / relative) != expected:
            raise PipelineError(f"retained source dependency changed: {relative}")
    for relative, expected in (
        (Path(source.__file__), record["generator_sha256"]),
        (Path(oracle_module.__file__), record["oracle_sha256"]),
        (Path(__file__), record["acceptance_tool_sha256"]),
    ):
        if _sha(root / relative.relative_to(root)) != expected:
            raise PipelineError(f"source-to-TEI implementation changed: {relative}")

    before, after = _files(root / WORK), _files(stage / WORK)
    if before != record["before"] or after != record["after"]:
        raise PipelineError("canonical or staged work generation changed")
    if _files(root / WORK / "forms" / source.FORM_ID / "editions" / source.EDITION_ID):
        if (root / EDITION / "acceptance.json").exists() or (root / EDITION / "master.tei.xml").exists():
            raise PipelineError("accepted master appeared before initial install")
    permitted = {"work.json", "state.json"}
    permitted.update(
        path.relative_to(WORK).as_posix()
        for path in (EDITION / "acceptance.json", EDITION / "master.tei.xml", SOURCE_CREDIT)
    )
    evidence_prefix = EVIDENCE.relative_to(WORK).as_posix() + "/"
    for path in set(before) | set(after):
        changed = before.get(path) != after.get(path)
        if changed and path not in permitted and not path.startswith(evidence_prefix):
            raise PipelineError(f"unrelated canonical work file differs: {path}")

    current_work, staged_work = _read(root / WORK / "work.json"), _read(stage / WORK / "work.json")
    expected_work = json.loads(json.dumps(current_work))
    expected_edition = expected_work["textual_forms"][0]["editions"][0]
    expected_edition.update(category="prose", language="la")
    if staged_work != expected_work:
        raise PipelineError("edition metadata changed beyond prose/la classification")
    validate_identity_update(current_work, staged_work)
    load_work(Path(_io_path(stage / WORK / "work.json")))

    acceptance_path = stage / EDITION / "acceptance.json"
    acceptance = validate_acceptance(acceptance_path, root=stage)
    validate_state(Path(_io_path(stage / WORK / "state.json")), root=Path(_io_path(stage)))
    master = stage / EDITION / "master.tei.xml"
    candidate = stage / EVIDENCE / "candidate.tei.xml"
    if (
        _sha(master) != record["master_sha256"]
        or _sha(acceptance_path) != record["acceptance_sha256"]
        or _sha(stage / SOURCE_CREDIT) != record["source_credit_sha256"]
        or Path(_io_path(stage / SOURCE_CREDIT)).read_text(encoding="utf-8")
        != _source_credit(record["master_sha256"], license_text, bibliography_text)
        or acceptance["promotion"]["status"] != "promoted"
        or acceptance["promotion"]["master"]["sha256"] != record["master_sha256"]
        or Path(_io_path(master)).read_bytes().split(b"</teiHeader>", 1)[1]
        != Path(_io_path(candidate)).read_bytes().split(b"</teiHeader>", 1)[1]
    ):
        raise PipelineError("staged accepted master differs from candidate body")
    if errors := validate_file(Path(_io_path(master))):
        raise PipelineError(f"staged accepted TEI P5 validation failed: {errors[:3]}")
    projection = project_accepted_prose(stage, acceptance_path=acceptance_path)
    errors = verify_accepted_prose(
        stage,
        acceptance_path=acceptance_path,
        rows=projection["rows"],
        receipt=projection["receipt"],
    )
    if errors or len(projection["rows"]) != record["projection_rows"]:
        raise PipelineError(f"staged actual-master projection differs: {errors[:3]}")
    return {
        "status": "ready-to-install",
        "work_id": source.WORK_ID,
        "master_sha256": record["master_sha256"],
        "acceptance_sha256": record["acceptance_sha256"],
        "files_before": len(before),
        "files_after": len(after),
        "projection_rows": len(projection["rows"]),
        "rights_clearance": "not-recorded",
        "human_review": "not-recorded",
    }


def install(receipt: Path) -> dict:
    record = _read(receipt.resolve(strict=True))
    ready = preflight(receipt)
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    target, promoted = root / WORK, stage / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        ready = preflight(receipt)

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                validate_acceptance(root / EDITION / "acceptance.json", root=root)
                validate_state(Path(_io_path(root / WORK / "state.json")), root=Path(_io_path(root)))
                projection = project_accepted_prose(
                    root, acceptance_path=root / EDITION / "acceptance.json"
                )
                errors = verify_accepted_prose(
                    root,
                    acceptance_path=root / EDITION / "acceptance.json",
                    rows=projection["rows"],
                    receipt=projection["receipt"],
                )
                if errors or len(projection["rows"]) != record["projection_rows"]:
                    raise PipelineError(f"installed actual-master projection differs: {errors[:3]}")

        result = _commit_generation(
            root,
            target,
            promoted,
            work_id=source.WORK_ID,
            before=record["before"],
            after=record["after"],
            existed=True,
            replacement=False,
            operation_kind="openmgh-bsb754-rigoberti-acceptance",
            result_status="installed-and-validated",
            accepted_editions=1,
            fail_at=checkpoint,
        )
    return ready | result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "preflight", "apply"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--direct-receipt", type=Path)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        if args.direct_receipt is None or args.stage is None:
            parser.error("prepare requires --direct-receipt and --stage")
        result = prepare(args.root, args.direct_receipt, args.stage, args.receipt)
    elif args.action == "preflight":
        result = preflight(args.receipt)
    else:
        result = install(args.receipt)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
