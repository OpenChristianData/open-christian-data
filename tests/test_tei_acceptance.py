from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Keep copied source/edition paths within the Windows path limit."""
    return tmp_path_factory.mktemp("a")

import ocd_kernel.tei.acceptance as acceptance_module
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    _tei_facts,
    build_acceptance_record,
    make_file_binding,
    promote_accepted_master,
    validate_acceptance,
    write_acceptance,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "library-pipeline"
WORK_ID = "athanasius-on-the-incarnation"
FORM_ID = "athanasius-on-the-incarnation-prose"
EDITION_ID = "ccel-npnf204"
ACQUISITION_ID = "ccel-npnf204-retained-xml"
RETAINED_PATH = "retained/npnf204.vii.ii.i.thml.xml"
RETAINED_SHA256 = "d16a6d825621cde9b93c5ed54489521895b9b9e44098b38bd61c437b927faafa"
DECLARED_SCOPE = "div1[@id='vii']/div2[@id='vii.ii']/div3[@id='vii.ii.i']"
SOURCE_SCOPE = "div1[@id='vii']"
SOURCE_SHA256 = "bd625a0fa4f5ddd4b2fa13fcee753de8832ea4b316625e0e06454beb81cfa652"
SOURCE_BYTES = 5809854
REVIEWER = "agent:pipe-004-fixture-review"
REVIEWED_AT = "2026-09-06T09:00:00Z"


def _fixture_root(tmp_path: Path) -> Path:
    destination = tmp_path / "f"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE_ROOT, destination)
    return destination


def _edition_root(root: Path) -> Path:
    return (
        root
        / "library"
        / "works"
        / WORK_ID
        / "forms"
        / FORM_ID
        / "editions"
        / EDITION_ID
    )


def _master_path(root: Path) -> Path:
    return _edition_root(root) / "master.tei.xml"


def _acceptance_path(root: Path) -> Path:
    return _edition_root(root) / "acceptance.json"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _candidate(root: Path, *, revision_id: str = "pipe-004-fixture-v1", historical: bool = False) -> Path:
    path = root / "acceptance" / "candidate.tei.xml"
    content = _master_path(root).read_text(encoding="utf-8")
    content = content.replace("pipe-001-fixture-v1", revision_id, 1)
    changes = (
        '<change xml:id="pipe-003-fixture-v1" when="2026-09-05">Prior fixture revision.</change>'
        if historical
        else ""
    )
    revision = (
        "  <revisionDesc>\n"
        f"{changes}\n"
        f"    <change xml:id=\"{revision_id}\" when=\"2026-09-06\">Bound fixture candidate for PIPE-004.</change>\n"
        "  </revisionDesc>\n"
    )
    content = content.replace("</teiHeader>", revision + "</teiHeader>", 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _identity() -> dict[str, str]:
    return {
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
    }


def _scope() -> dict[str, object]:
    return {
        "kind": "member",
        "declared": DECLARED_SCOPE,
        "expected_members": [{"path": RETAINED_PATH, "position": 1}],
        "included_members": [
            {
                "path": RETAINED_PATH,
                "position": 1,
                "bytes": 4174,
                "sha256": RETAINED_SHA256,
                "scope": DECLARED_SCOPE,
            }
        ],
        "excluded_members": [],
    }


def _source_facts() -> dict[str, object]:
    return {
        "source_path": "raw/ccel/npnf2/npnf204.xml",
        "source_sha256": SOURCE_SHA256,
        "source_bytes": SOURCE_BYTES,
        "source_scope": SOURCE_SCOPE,
    }


def _coverage(declared: str = DECLARED_SCOPE) -> dict[str, object]:
    return {
        "status": "partial",
        "declared": declared,
        "reached": ["div3[@id='vii.ii.i']"],
        "inspected": ["div3[@id='vii.ii.i']/head"],
        "unreviewed": ["div3[@id='vii.ii.i']/body"],
    }


def _decision(*, blockers: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "source_local_disposition": "supported for the declared member scope",
        "blockers": blockers or [],
        "agent_assessment": {
            "status": "accepted",
            "actor": "agent:pipe-004-fixture",
            "assessed_at": "2026-09-06T09:10:00Z",
            "supported_scope": DECLARED_SCOPE,
            "unassessed_stronger_claims": ["whole source volume"],
            "unresolved_claims": [],
        },
        "human_decision": {"status": "not-recorded"},
    }


def _prepare_evidence(
    root: Path,
    candidate: Path,
    *,
    scope: dict[str, object] | None = None,
    source_facts: dict[str, object] | None = None,
    missing_members: list[str] | None = None,
    unknown_members: list[str] | None = None,
) -> tuple[Path, dict[str, object], dict[str, object]]:
    identity = _identity()
    scope = copy.deepcopy(scope or _scope())
    missing_members = list(missing_members or [])
    unknown_members = list(unknown_members or [])
    candidate_binding = make_file_binding(root, candidate)
    source = copy.deepcopy(source_facts or _source_facts())
    source_accounting = root / "acceptance" / "source-accounting.json"
    source_document = {
        "contract": "ocd-source-accounting-v1",
        "identity": identity,
        "source": source,
        "source_sha256": source["source_sha256"],
        "source_bytes": source["source_bytes"],
        "scope": source["source_scope"],
        "accepted_scope": {
            "kind": scope["kind"],
            "declared": scope["declared"],
        },
        "expected_members": scope["expected_members"],
        "included_members": scope["included_members"],
        "excluded_members": scope["excluded_members"],
        "missing_members": missing_members,
        "unknown_members": unknown_members,
    }
    _write_json(source_accounting, source_document)
    technical: dict[str, object] = {
        "producer": {"id": "producer:pipe-004-fixture"},
        "checker": {"id": "checker:pipe-004-fixture"},
        "shared_assumptions": ["fixture source/member path is canonical"],
        "independent_corroboration": "source-native member traversal",
    }
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = root / "acceptance" / f"{name}.json"
        document: dict[str, object] = {
            "contract": f"ocd-tei-{name}-v1",
            "identity": identity,
            "source": source,
            "candidate": candidate_binding,
            "scope": scope["declared"],
            "status": "pass",
            "command": f"fixture-{name}",
            "exit_code": 0,
            "expected_members": scope["expected_members"],
            "included_members": scope["included_members"],
            "excluded_members": scope["excluded_members"],
            "missing_members": missing_members,
            "unknown_members": unknown_members,
        }
        if name == "accounting":
            document["accepted_scope"] = {
                "kind": scope["kind"],
                "declared": scope["declared"],
            }
        _write_json(path, document)
        technical[name] = {"path": path, "status": "pass", "command": f"fixture-{name}", "exit_code": 0}

    review_path = root / "acceptance" / "review.json"
    review_document = {
        "contract": "ocd-tei-review-v1",
        "identity": identity,
        "source": source,
        "candidate": candidate_binding,
        "scope": scope["declared"],
        "reviewer": REVIEWER,
        "reviewed_at": REVIEWED_AT,
        "coverage": _coverage(str(scope["declared"])),
        "source_quality_uncertainty": ["source quality outside selected member is unassessed"],
        "discrepancies": [],
        "unreviewed_residuals": ["body paragraphs were not visually compared in this fixture"],
    }
    _write_json(review_path, review_document)
    review = {
        "report_path": review_path,
        "reviewer": REVIEWER,
        "reviewed_at": REVIEWED_AT,
        "coverage": _coverage(str(scope["declared"])),
        "source_quality_uncertainty": ["source quality outside selected member is unassessed"],
        "discrepancies": [],
        "unreviewed_residuals": ["body paragraphs were not visually compared in this fixture"],
    }
    return source_accounting, technical, review


def _write_valid_acceptance(
    root: Path,
    *,
    historical: bool = False,
    scope: dict[str, object] | None = None,
    missing_members: list[str] | None = None,
    unknown_members: list[str] | None = None,
) -> tuple[Path, dict[str, object]]:
    candidate = _candidate(root, historical=historical)
    selected_scope = copy.deepcopy(scope or _scope())
    source_accounting, technical, review = _prepare_evidence(
        root,
        candidate,
        scope=selected_scope,
        missing_members=missing_members,
        unknown_members=unknown_members,
    )
    record = build_acceptance_record(
        root,
        identity=_identity(),
        candidate_path=candidate,
        source_accounting_path=source_accounting,
        scope=selected_scope,
        technical=technical,  # type: ignore[arg-type]
        review=review,
        representation_revision={
            "id": "pipe-004-fixture-v1",
            "date": "2026-09-06",
            "note": "Bound fixture candidate for PIPE-004.",
        },
        decision=_decision(),
        missing_members=missing_members or [],
        unknown_members=unknown_members or [],
    )
    path = _acceptance_path(root)
    write_acceptance(path, record)
    return path, record


def test_acceptance_binds_exact_evidence_and_keeps_partial_review_separate(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path, _record = _write_valid_acceptance(root)

    validated = validate_acceptance(path, root=root)

    assert validated["decision"]["agent_assessment"]["status"] == "accepted"
    assert validated["decision"]["human_decision"]["status"] == "not-recorded"
    assert validated["review"]["coverage"]["status"] == "partial"
    assert validated["promotion"]["status"] == "pending"


def test_historical_revision_entries_are_allowed_but_current_revision_is_bound(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path, _record = _write_valid_acceptance(root, historical=True)

    assert validate_acceptance(path, root=root)["representation_revision"]["id"] == "pipe-004-fixture-v1"

    record = json.loads(path.read_text(encoding="utf-8"))
    record["representation_revision"]["note"] = "Detached note."
    _write_json(path, record)
    with pytest.raises(PipelineError, match="revision history"):
        validate_acceptance(path, root=root)


@pytest.mark.parametrize(
    ("needle", "addition", "message"),
    [
        (
            '<ptr target="https://www.ccel.org/ccel/schaff/npnf204.xml"/>',
            '<ptr target="https://example.invalid/conflicting-source.xml"/>',
            "sourceDesc pointers",
        ),
        (
            '<note type="source-scope">div1[@id=\'vii\']/div2[@id=\'vii.ii\']/div3[@id=\'vii.ii.i\']</note>',
            '<note type="source-scope">div1[@id=\'conflict\']</note>',
            "source-scope",
        ),
    ],
)
def test_conflicting_tei_header_source_claims_are_rejected(
    tmp_path: Path, needle: str, addition: str, message: str
) -> None:
    root = _fixture_root(tmp_path)
    candidate = _candidate(root)
    content = candidate.read_text(encoding="utf-8")
    if "ptr target" in needle:
        content = content.replace(needle, needle + addition, 1)
    else:
        content = content.replace(needle, needle + addition, 1)
    candidate.write_text(content, encoding="utf-8", newline="\n")

    with pytest.raises(PipelineError, match=message):
        _tei_facts(candidate)


@pytest.mark.parametrize("binding", ["technical.candidate", "source.source_manifest", "source.accounting", "review.report"])
def test_stale_file_bindings_are_rejected(tmp_path: Path, binding: str) -> None:
    root = _fixture_root(tmp_path)
    path, record = _write_valid_acceptance(root)
    if binding == "technical.candidate":
        target = root / record["technical"]["candidate"]["path"]
    elif binding == "source.source_manifest":
        target = root / record["source"]["source_manifest"]["path"]
    elif binding == "source.accounting":
        target = root / record["source"]["accounting"]["path"]
    else:
        target = root / record["review"]["report"]["path"]
    target.write_bytes(target.read_bytes() + (b" \n" if binding == "source.source_manifest" else b"\nchanged"))

    with pytest.raises(PipelineError, match="(sha256|byte) mismatch"):
        validate_acceptance(path, root=root)


def test_scope_expansion_to_an_unretained_member_is_rejected(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path, record = _write_valid_acceptance(root)
    expanded = {
        "path": "retained/not-retained.xml",
        "position": 2,
        "bytes": 1,
        "sha256": hashlib.sha256(b"x").hexdigest(),
        "scope": DECLARED_SCOPE,
    }
    record["scope"]["expected_members"].append({"path": expanded["path"], "position": 2})
    record["scope"]["included_members"].append(expanded)
    _write_json(path, record)

    with pytest.raises(PipelineError, match="absent from the retained acquisition"):
        validate_acceptance(path, root=root)


def test_selected_scope_can_account_for_an_explicitly_missing_excluded_member(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    missing = "retained/not-present-in-this-acquisition.xml"
    scope = _scope()
    scope["expected_members"].append({"path": missing, "position": 2})
    scope["excluded_members"] = [
        {"path": missing, "position": 2, "reason": "not retained by selected acquisition"}
    ]
    path, _record = _write_valid_acceptance(
        root,
        scope=scope,
        missing_members=[missing],
    )

    assert validate_acceptance(path, root=root)["scope"]["included_members"]


def test_scope_missing_or_unknown_members_must_be_expected_and_excluded(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path, record = _write_valid_acceptance(root)
    record["source"]["missing_members"] = ["retained/not-expected.xml"]
    _write_json(path, record)

    with pytest.raises(PipelineError, match="expected envelope"):
        validate_acceptance(path, root=root)

    root = _fixture_root(tmp_path / "second")
    path, record = _write_valid_acceptance(root)
    record["source"]["missing_members"] = [RETAINED_PATH]
    _write_json(path, record)

    with pytest.raises(PipelineError, match="explicitly excluded"):
        validate_acceptance(path, root=root)


def test_broader_scope_kind_is_bound_by_accounting_evidence(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path, record = _write_valid_acceptance(root)
    record["scope"]["kind"] = "work"
    _write_json(path, record)

    with pytest.raises(PipelineError, match="accepted_scope"):
        validate_acceptance(path, root=root)


def test_scope_contraction_cannot_hide_a_retained_member(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    acquisition_path = (
        _edition_root(root)
        / "acquisitions"
        / f"{ACQUISITION_ID}.json"
    )
    acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
    second_path = "retained/npnf204.vii.ii.ii.thml.xml"
    source_path = root / RETAINED_PATH
    destination_path = root / second_path
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, destination_path)
    second_item = copy.deepcopy(acquisition["retained_files"][0])
    second_item["path"] = second_path
    acquisition["retained_files"].append(second_item)
    _write_json(acquisition_path, acquisition)

    scope = _scope()
    scope["expected_members"].append({"path": second_path, "position": 2})
    scope["excluded_members"] = [
        {"path": second_path, "position": 2, "reason": "outside selected fixture member"}
    ]
    for unavailable_field in ("missing_members", "unknown_members"):
        invalid_path, _ = _write_valid_acceptance(
            root, scope=scope, **{unavailable_field: [second_path]}
        )
        with pytest.raises(PipelineError, match="retained member cannot be missing or unknown"):
            validate_acceptance(invalid_path, root=root)
    path, record = _write_valid_acceptance(root, scope=scope)
    record["scope"]["expected_members"] = [record["scope"]["expected_members"][0]]
    record["scope"]["excluded_members"] = []
    _write_json(path, record)

    with pytest.raises(PipelineError, match="contracts an acquisition envelope"):
        validate_acceptance(path, root=root)


def test_missing_required_accounting_and_review_fields_are_rejected(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path, record = _write_valid_acceptance(root)
    source_accounting = root / record["source"]["accounting"]["path"]
    source_document = json.loads(source_accounting.read_text(encoding="utf-8"))
    del source_document["expected_members"]
    _write_json(source_accounting, source_document)
    record["source"]["accounting"] = make_file_binding(root, source_accounting, fixture_only=False)
    _write_json(path, record)
    with pytest.raises(PipelineError, match="source.accounting expected_members"):
        validate_acceptance(path, root=root)

    second_base = tmp_path / "second"
    second_base.mkdir()
    root = _fixture_root(second_base)
    path, record = _write_valid_acceptance(root)
    technical_accounting = root / record["technical"]["accounting"]["path"]
    technical_document = json.loads(technical_accounting.read_text(encoding="utf-8"))
    del technical_document["expected_members"]
    _write_json(technical_accounting, technical_document)
    technical_binding = make_file_binding(root, technical_accounting, fixture_only=False)
    record["technical"]["accounting"] = technical_binding | {
        "status": "pass",
        "command": "fixture-accounting",
        "exit_code": 0,
    }
    _write_json(path, record)
    with pytest.raises(PipelineError, match="technical accounting expected_members"):
        validate_acceptance(path, root=root)

    third_base = tmp_path / "third"
    third_base.mkdir()
    root = _fixture_root(third_base)
    path, record = _write_valid_acceptance(root)
    review_path = root / record["review"]["report"]["path"]
    review_document = json.loads(review_path.read_text(encoding="utf-8"))
    del review_document["reviewer"]
    _write_json(review_path, review_document)
    record["review"]["report"] = make_file_binding(root, review_path, fixture_only=False)
    _write_json(path, record)
    with pytest.raises(PipelineError, match="review report reviewer"):
        validate_acceptance(path, root=root)


def test_inner_candidate_binding_requires_bytes_as_well_as_digest(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path, record = _write_valid_acceptance(root)
    proof_path = root / record["technical"]["validation"]["path"]
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["candidate"]["bytes"] += 1
    _write_json(proof_path, proof)
    record["technical"]["validation"] = make_file_binding(root, proof_path, fixture_only=False) | {
        "status": "pass",
        "command": "fixture-validation",
        "exit_code": 0,
    }
    _write_json(path, record)

    with pytest.raises(PipelineError, match="candidate binding is stale"):
        validate_acceptance(path, root=root)


def test_review_report_binds_uncertainty_and_coverage_invariants(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path, record = _write_valid_acceptance(root)
    review_path = root / record["review"]["report"]["path"]
    review_document = json.loads(review_path.read_text(encoding="utf-8"))
    review_document["discrepancies"] = ["synthetic discrepancy"]
    _write_json(review_path, review_document)
    record["review"]["report"] = make_file_binding(root, review_path, fixture_only=False)
    _write_json(path, record)

    with pytest.raises(PipelineError, match="discrepancies binding"):
        validate_acceptance(path, root=root)

    root = _fixture_root(tmp_path / "coverage")
    path, record = _write_valid_acceptance(root)
    review_path = root / record["review"]["report"]["path"]
    review_document = json.loads(review_path.read_text(encoding="utf-8"))
    invalid_coverage = copy.deepcopy(review_document["coverage"])
    invalid_coverage["inspected"] = ["div3[@id='vii.ii.i']/body"]
    review_document["coverage"] = invalid_coverage
    _write_json(review_path, review_document)
    record["review"]["coverage"] = invalid_coverage
    record["review"]["report"] = make_file_binding(root, review_path, fixture_only=False)
    _write_json(path, record)

    with pytest.raises(PipelineError, match="inspected loci"):
        validate_acceptance(path, root=root)


def test_recorded_blocker_prevents_agent_acceptance_and_promotion(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    candidate = _candidate(root)
    source_accounting, technical, review = _prepare_evidence(root, candidate)
    blocker_evidence = make_file_binding(root, source_accounting)
    record = build_acceptance_record(
        root,
        identity=_identity(),
        candidate_path=candidate,
        source_accounting_path=source_accounting,
        scope=_scope(),
        technical=technical,  # type: ignore[arg-type]
        review=review,
        representation_revision={"id": "pipe-004-fixture-v1", "date": "2026-09-06", "note": "Bound fixture candidate for PIPE-004."},
        decision=_decision(
            blockers=[
                {"id": "source-quality", "reason": "fixture blocker", "evidence": [blocker_evidence]}
            ]
        ),
    )
    path = _acceptance_path(root)
    write_acceptance(path, record)
    with pytest.raises(PipelineError, match="blockers"):
        validate_acceptance(path, root=root)


def test_decision_scope_and_recorded_human_fields_are_bound(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path, record = _write_valid_acceptance(root)
    record["decision"]["agent_assessment"]["supported_scope"] = SOURCE_SCOPE
    _write_json(path, record)

    with pytest.raises(PipelineError, match="supported_scope"):
        validate_acceptance(path, root=root)

    root = _fixture_root(tmp_path / "human")
    path, record = _write_valid_acceptance(root)
    record["decision"]["human_decision"] = {
        "status": "accepted",
        "actor": "human:synthetic-fixture",
        "decided_at": "2026-09-06T09:30:00Z",
        "scope": SOURCE_SCOPE,
        "note": "Synthetic out-of-scope decision for rejection testing.",
    }
    write_acceptance(path, record)

    with pytest.raises(PipelineError, match="human decision scope"):
        validate_acceptance(path, root=root)

    root = _fixture_root(tmp_path / "missing-human-fields")
    path, record = _write_valid_acceptance(root)
    record["decision"]["human_decision"] = {"status": "accepted"}
    with pytest.raises(PipelineError):
        write_acceptance(path, record)

    root = _fixture_root(tmp_path / "conflicting-human")
    path, record = _write_valid_acceptance(root)
    record["decision"]["human_decision"] = {
        "status": "rejected",
        "actor": "human:synthetic-fixture",
        "decided_at": "2026-09-06T09:30:00Z",
        "scope": DECLARED_SCOPE,
        "note": "Synthetic conflicting rejection for boundary testing.",
    }
    write_acceptance(path, record)

    with pytest.raises(PipelineError, match="conflicts"):
        validate_acceptance(path, root=root)


@pytest.mark.parametrize("mutation", ["status", "command", "exit_code"])
def test_proof_document_outcome_is_authoritative(tmp_path: Path, mutation: str) -> None:
    root = _fixture_root(tmp_path)
    path, record = _write_valid_acceptance(root)
    proof_path = root / record["technical"]["validation"]["path"]
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    if mutation == "status":
        del proof["status"]
    elif mutation == "command":
        proof["command"] = "different-command"
    else:
        proof["exit_code"] = 1
    _write_json(proof_path, proof)
    binding = make_file_binding(root, proof_path, fixture_only=False)
    record["technical"]["validation"] = binding | {
        "status": "pass",
        "command": "fixture-validation",
        "exit_code": 0,
    }
    _write_json(path, record)

    with pytest.raises(PipelineError, match="technical validation document"):
        validate_acceptance(path, root=root)


def test_builder_requires_caller_supplied_acceptance_and_actor_evidence(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    candidate = _candidate(root)
    source_accounting, technical, review = _prepare_evidence(root, candidate)
    incomplete = copy.deepcopy(technical)
    del incomplete["checker"]
    with pytest.raises(PipelineError, match="checker"):
        build_acceptance_record(
            root,
            identity=_identity(),
            candidate_path=candidate,
            source_accounting_path=source_accounting,
            scope=_scope(),
            technical=incomplete,  # type: ignore[arg-type]
            review=review,
            representation_revision={"id": "pipe-004-fixture-v1", "date": "2026-09-06", "note": "Bound fixture candidate for PIPE-004."},
            decision=_decision(),
        )


def test_partial_human_review_can_record_a_narrower_scope(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path, record = _write_valid_acceptance(root)
    record["decision"]["human_decision"] = {
        "status": "partial",
        "actor": "human:synthetic-fixture",
        "decided_at": "2026-09-06T09:30:00Z",
        "scope": DECLARED_SCOPE + "/head",
        "note": "Synthetic partial heading review; no whole-member human acceptance.",
    }
    write_acceptance(path, record)
    validated = validate_acceptance(path, root=root)
    assert validated["decision"]["human_decision"]["status"] == "partial"
    assert validated["decision"]["agent_assessment"]["status"] == "accepted"


def test_single_retained_member_can_supply_source_binding_without_original_group(
    tmp_path: Path,
) -> None:
    root = _fixture_root(tmp_path)
    acquisition_path = (
        _edition_root(root)
        / "acquisitions"
        / f"{ACQUISITION_ID}.json"
    )
    acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
    for key in ("source_path", "source_sha256", "source_bytes", "source_scope"):
        del acquisition[key]
    _write_json(acquisition_path, acquisition)

    candidate = _candidate(root)
    candidate_content = candidate.read_text(encoding="utf-8")
    candidate_content = candidate_content.replace(SOURCE_SHA256, RETAINED_SHA256, 1)
    candidate_content = candidate_content.replace(str(SOURCE_BYTES), "4174", 1)
    candidate_content = candidate_content.replace(
        "raw/ccel/npnf2/npnf204.xml", RETAINED_PATH, 1
    )
    candidate.write_text(candidate_content, encoding="utf-8", newline="\n")
    source = {
        "source_path": RETAINED_PATH,
        "source_sha256": RETAINED_SHA256,
        "source_bytes": 4174,
        "source_scope": DECLARED_SCOPE,
    }
    source_accounting, technical, review = _prepare_evidence(
        root,
        candidate,
        source_facts=source,
    )
    record = build_acceptance_record(
        root,
        identity=_identity(),
        candidate_path=candidate,
        source_accounting_path=source_accounting,
        scope=_scope(),
        technical=technical,  # type: ignore[arg-type]
        review=review,
        representation_revision={
            "id": "pipe-004-fixture-v1",
            "date": "2026-09-06",
            "note": "Bound fixture candidate for PIPE-004.",
        },
        decision=_decision(),
    )
    path = _acceptance_path(root)
    write_acceptance(path, record)

    assert validate_acceptance(path, root=root)["source"]["source_path"] == RETAINED_PATH


def test_promotion_is_atomic_in_a_fresh_destination_and_does_not_mutate_input(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path, record = _write_valid_acceptance(root)
    original_master = _master_path(root).read_bytes()
    original_state = (root / "library" / "works" / WORK_ID / "state.json").read_bytes()
    destination = tmp_path / "promoted"

    result = promote_accepted_master(root, acceptance_path=path, destination=destination)

    assert result.destination_root == destination.resolve()
    assert result.master_path == _master_path(destination)
    assert result.master_path.read_bytes() == (root / record["technical"]["candidate"]["path"]).read_bytes()
    assert result.acceptance_path.is_file()
    assert result.state_path.is_file()
    assert _master_path(root).read_bytes() == original_master
    assert (root / "library" / "works" / WORK_ID / "state.json").read_bytes() == original_state
    promoted = validate_acceptance(result.acceptance_path, root=destination)
    assert promoted["promotion"]["status"] == "promoted"
    state = json.loads(result.state_path.read_text(encoding="utf-8"))
    target = state["targets"][0]
    assert target["stage"] == "accepted"
    assert target["reason"] == PROMOTED_MASTER_REASON
    assert promoted["promotion"]["master"]["path"] in target["evidence"]
    assert promoted["promotion"]["state_path"] == "library/works/athanasius-on-the-incarnation/state.json"


def test_promotion_rejects_external_data_plane_configuration(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path, _record = _write_valid_acceptance(root)
    (root / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(tmp_path / "durable-library")}),
        encoding="utf-8",
    )
    destination = tmp_path / "external-root-rejected"

    with pytest.raises(PipelineError, match="external data-plane"):
        promote_accepted_master(root, acceptance_path=path, destination=destination)

    assert not destination.exists()


def test_failed_promotion_leaves_no_partial_destination(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path, record = _write_valid_acceptance(root)
    candidate = root / record["technical"]["candidate"]["path"]
    candidate.write_bytes(candidate.read_bytes() + b"broken")
    destination = tmp_path / "failed-promotion"

    with pytest.raises(PipelineError, match="(?:byte|sha256) mismatch"):
        promote_accepted_master(root, acceptance_path=path, destination=destination)

    assert not destination.exists()


def test_mid_staging_failure_rolls_back_owned_stage_and_preserves_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture_root(tmp_path)
    path, _record = _write_valid_acceptance(root)
    original_master = _master_path(root).read_bytes()
    original_state_path = root / "library" / "works" / WORK_ID / "state.json"
    original_state = original_state_path.read_bytes()
    original_acceptance = path.read_bytes()
    destination = tmp_path / "mid-failure"
    real_write_json = acceptance_module.write_json

    def fail_state_write(target: Path, value: object) -> None:
        if Path(target).name == "state.json":
            raise OSError("synthetic state-write failure")
        real_write_json(target, value)

    monkeypatch.setattr(acceptance_module, "write_json", fail_state_write)
    with pytest.raises(OSError, match="synthetic state-write failure"):
        promote_accepted_master(root, acceptance_path=path, destination=destination)

    assert not destination.exists()
    assert not any(item.name.startswith(".mid-failure.p004-") for item in tmp_path.iterdir())
    assert _master_path(root).read_bytes() == original_master
    assert original_state_path.read_bytes() == original_state
    assert path.read_bytes() == original_acceptance
