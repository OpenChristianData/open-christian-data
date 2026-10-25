from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from build.tools.build_library_views import main as build_views_main
import ocd_kernel.library.identities as identities_module
import ocd_kernel.library.views as views_module
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.identities import discover_library
from ocd_kernel.library.views import build_library_views, check_library_views
from ocd_kernel.tei.acceptance import _validate_acceptance_for_views


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "library-pipeline"
WORK_ID = "athanasius-on-the-incarnation"
FORM_ID = "athanasius-on-the-incarnation-prose"
EDITION_ID = "ccel-npnf204"
ACQUISITION_ID = "ccel-npnf204-retained-xml"
RETAINED = "retained/npnf204.vii.ii.i.thml.xml"


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Keep copied acceptance fixtures below Windows path limits."""

    return tmp_path_factory.mktemp("lv")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "f"
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE_ROOT, root)
    return root


def _build(root: Path, tmp_path: Path) -> dict[str, object]:
    return build_library_views(root, tmp_path / "views")


def _artifact(root: Path, name: str, content: bytes, *, kind: str = "source") -> dict[str, str]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "artifact_id": name.replace("/", "-").replace(".", "-"),
        "kind": kind,
        "path": name,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _assessment(root: Path) -> dict[str, object]:
    source = _artifact(root, "assessment-source.txt", b"source\n")
    return {
        "schema_version": "2.0",
        "assessment_id": "fixture-agent-assessment",
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "assessed_at": "2026-09-06T00:00:00Z",
        "agent": {"name": "fixture-agent"},
        "scope": {
            "kind": "edition",
            "reference": EDITION_ID,
            "description": "the fixture edition",
        },
        "artifacts": [source],
        "citations": [],
        "coverage": {"completeness": "complete", "inspected": ["all"], "omitted": []},
        "outcome": "supports",
        "summary": "The fixture evidence supports the bounded assessment.",
        "uncertainties": [],
        "issues": [],
    }


def _review(root: Path) -> dict[str, object]:
    source = _artifact(root, "review-source.txt", b"review source\n")
    return {
        "schema_version": "2.0",
        "review_id": "fixture-human-review",
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "reviewer": "synthetic reviewer",
        "reviewed_at": "2026-09-06T01:00:00Z",
        "record_origin": "synthetic-test",
        "synthetic": True,
        "decision_area": ["fidelity"],
        "scope": {
            "kind": "edition",
            "reference": EDITION_ID,
            "description": "the fixture edition",
        },
        "artifacts": [source],
        "citations": [],
        "coverage": {"completeness": "complete", "inspected": ["all"], "omitted": []},
        "result": "confirmed",
        "summary": "The fixture evidence was inspected.",
        "uncertainties": [],
        "issues": [],
    }


def _pipe004_helpers() -> ModuleType:
    """Load settled PIPE-004 fixture builders only for this synthetic test."""

    path = REPO_ROOT / "tests" / "test_tei_acceptance.py"
    spec = importlib.util.spec_from_file_location("_pipe004_fixture_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load PIPE-004 fixture helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _add_second_acquisition(root: Path, acquisition_id: str) -> None:
    edition = (
        root
        / "library"
        / "works"
        / WORK_ID
        / "forms"
        / FORM_ID
        / "editions"
        / EDITION_ID
    )
    work_path = root / "library" / "works" / WORK_ID / "work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    raw_edition = work["textual_forms"][0]["editions"][0]
    raw_edition["acquisition_ids"] = [ACQUISITION_ID, acquisition_id]
    _write_json(work_path, work)
    original_path = edition / "acquisitions" / f"{ACQUISITION_ID}.json"
    second_path = edition / "acquisitions" / f"{acquisition_id}.json"
    second = json.loads(original_path.read_text(encoding="utf-8"))
    second["acquisition_id"] = acquisition_id
    _write_json(second_path, second)


def _write_promoted_acceptance(root: Path) -> None:
    helpers = _pipe004_helpers()
    acceptance_path, record = helpers._write_valid_acceptance(root)
    candidate_path = root / "acceptance" / "candidate.tei.xml"
    master_path = (
        root
        / "library"
        / "works"
        / WORK_ID
        / "forms"
        / FORM_ID
        / "editions"
        / EDITION_ID
        / "master.tei.xml"
    )
    master_path.write_bytes(candidate_path.read_bytes())
    record["promotion"]["status"] = "promoted"
    record["promotion"]["promoted_at"] = "2026-09-06T12:00:00Z"
    record["promotion"]["master"] = helpers.make_file_binding(root, master_path) | {
        "path": f"library/works/{WORK_ID}/forms/{FORM_ID}/editions/{EDITION_ID}/master.tei.xml"
    }
    _write_json(acceptance_path, record)
    state_path = root / "library" / "works" / WORK_ID / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"][0]["evidence"].append(
        f"library/works/{WORK_ID}/forms/{FORM_ID}/editions/{EDITION_ID}/acceptance.json"
    )
    state["targets"][0]["evidence"].append(
        f"library/works/{WORK_ID}/forms/{FORM_ID}/editions/{EDITION_ID}/master.tei.xml"
    )
    _write_json(state_path, state)


def test_inventory_keeps_legacy_routing_provisional_without_acceptance(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    result = _build(root, tmp_path)
    manifest = result["manifest"]
    item = result["status"]["items"][0]

    assert manifest["scope"]["status"] == "declared-library-tree-plus-research-leads"
    assert manifest["counts"]["works"] == 1
    assert manifest["counts"]["textual_forms"] == 1
    assert manifest["counts"]["editions"] == 1
    assert manifest["counts"]["acquisitions"] == 1
    assert item["status"] == "included"
    assert item["release_status"] == "provisional"
    assert item["acceptance_status"] == "not-recorded"
    assert item["master_status"] == "present-unbound"
    assert item["provisional"] is True
    assert result["manifest"]["acceptances"][0]["status"] == "not-recorded"


def test_acquisition_target_and_preacquisition_entities_are_distinct(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    work_path = root / "library" / "works" / WORK_ID / "work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["textual_forms"].append(
        {
            "textual_form_id": "unacquired-form",
            "editions": [{"edition_id": "unacquired-edition", "title": "Unacquired edition"}],
        }
    )
    _write_json(work_path, work)
    state_path = root / "library" / "works" / WORK_ID / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"] = [
        {
            "target_id": ACQUISITION_ID,
            "target_type": "acquisition",
            "stage": "acquired",
            "updated_at": "2026-09-06T08:57:28.078565Z",
            "evidence": [
                f"forms/{FORM_ID}/editions/{EDITION_ID}/acquisitions/{ACQUISITION_ID}.json"
            ],
        }
    ]
    _write_json(state_path, state)

    result = _build(root, tmp_path)
    items = {item["edition_id"]: item for item in result["status"]["items"]}
    acquired = items[EDITION_ID]
    unacquired = items["unacquired-edition"]

    assert acquired["status"] == "excluded"
    assert acquired["state_status"] == "untracked"
    assert acquired["acquisition_stage"] == "acquired"
    assert unacquired["master_status"] == "absent"
    assert unacquired["dimensions"]["source_availability"] == "unacquired"
    assert unacquired["acceptance_status"] == "not-recorded"
    assert result["manifest"]["counts"]["master_targets"] == 2
    assert result["manifest"]["counts"]["masters"] == 1
    assert result["manifest"]["counts"]["accepted_masters"] == 0
    assert any(target["target_id"] == ACQUISITION_ID for target in result["manifest"]["state_targets"])
    assert result["queue"]["acquisitions"][0]["acquisition_id"] == ACQUISITION_ID


def test_freshness_check_detects_authority_change(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    output = tmp_path / "views"
    build_library_views(root, output)
    assert check_library_views(root, output)["fresh"] is True

    work_path = root / "library" / "works" / WORK_ID / "work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["title"] = "Changed title for freshness test"
    _write_json(work_path, work)
    checked = check_library_views(root, output)
    assert checked["fresh"] is False
    assert any("stale" in reason for reason in checked["reasons"])


def test_orphan_acquisition_is_reported_without_repair(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    source = root / "library" / "works" / WORK_ID / "forms" / FORM_ID / "editions" / EDITION_ID / "acquisitions" / f"{ACQUISITION_ID}.json"
    orphan = root / "library" / "works" / WORK_ID / "forms" / "orphan-form" / "editions" / "orphan-edition" / "acquisitions" / f"{ACQUISITION_ID}.json"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan_record = json.loads(source.read_text(encoding="utf-8"))
    orphan_record["edition_id"] = "orphan-edition"
    _write_json(orphan, orphan_record)

    result = _build(root, tmp_path)
    orphan_rows = [item for item in result["manifest"]["acquisitions"] if item["acquisition_path"] == orphan.relative_to(root).as_posix()]
    assert orphan_rows[0]["identity_status"] == "orphan"
    assert orphan_rows[0]["collision_status"] == "collision"
    assert any(issue["code"] == "orphan-acquisition" for issue in result["manifest"]["issues"])


def test_invalid_acceptance_cannot_make_master_accepted(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    acceptance_path = root / "library" / "works" / WORK_ID / "forms" / FORM_ID / "editions" / EDITION_ID / "acceptance.json"
    _write_json(acceptance_path, {"schema_version": "2.0"})

    result = _build(root, tmp_path)
    item = result["status"]["items"][0]
    assert item["acceptance_status"] == "invalid"
    assert item["master_status"] == "present-unbound"
    assert item["status"] == "failed"
    assert any(issue["code"] == "invalid-acceptance" for issue in result["manifest"]["issues"])


def test_promoted_acceptance_selects_its_valid_acquisition_and_exposes_dimensions(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    _add_second_acquisition(root, "ccel-npnf204-alternate")
    _write_promoted_acceptance(root)

    result = _build(root, tmp_path)
    item = result["status"]["items"][0]

    assert item["status"] == "included"
    assert item["release_status"] == "accepted"
    assert item["acceptance_status"] == "promoted"
    assert item["master_status"] == "accepted"
    assert item["acquisition_id"] == ACQUISITION_ID
    assert item["dimensions"]["technical_closure"]["status"] == "pass"
    assert item["dimensions"]["visual_coverage"] == "partial"
    assert item["dimensions"]["agent_assessment"] == "accepted"
    assert item["dimensions"]["human_acceptance"] == "not-recorded"
    assert len(result["manifest"]["acquisitions"]) == 2


def test_view_reuses_one_validated_discovery_and_still_rejects_stale_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture_root(tmp_path)
    _write_promoted_acceptance(root)
    acceptance_path = (
        root / "library" / "works" / WORK_ID / "forms" / FORM_ID
        / "editions" / EDITION_ID / "acceptance.json"
    )
    view_discoveries = 0
    fallback_discoveries = 0
    original_discover = views_module.discover_library

    def counted_view_discovery(path: Path) -> object:
        nonlocal view_discoveries
        view_discoveries += 1
        return original_discover(path)

    def forbidden_fallback_discovery(path: Path) -> object:
        nonlocal fallback_discoveries
        fallback_discoveries += 1
        return original_discover(path)

    monkeypatch.setattr(views_module, "discover_library", counted_view_discovery)
    monkeypatch.setattr(identities_module, "discover_library", forbidden_fallback_discovery)
    valid = _build(root, tmp_path)
    assert valid["status"]["items"][0]["acceptance_status"] == "promoted"
    assert valid["status"]["items"][0]["master_status"] == "accepted"
    assert (view_discoveries, fallback_discoveries) == (1, 0)

    record = json.loads(acceptance_path.read_text(encoding="utf-8"))
    record["source"]["source_sha256"] = "0" * 64
    _write_json(acceptance_path, record)
    invalid = build_library_views(root, tmp_path / "views-invalid")
    assert invalid["status"]["items"][0]["acceptance_status"] == "invalid"
    assert any(
        "source_sha256 does not bind acquisition" in reason
        for reason in invalid["manifest"]["acceptances"][0]["reasons"]
    )
    assert (view_discoveries, fallback_discoveries) == (2, 0)


def test_view_acceptance_discovery_must_bind_exact_root_and_work(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    _write_promoted_acceptance(root)
    acceptance_path = (
        root / "library" / "works" / WORK_ID / "forms" / FORM_ID
        / "editions" / EDITION_ID / "acceptance.json"
    )
    works = discover_library(root)
    wrong_work = replace(works[0], path=root / "other" / "work.json")
    with pytest.raises(PipelineError, match="does not bind the selected library root"):
        _validate_acceptance_for_views(
            acceptance_path, root=root, discovered_works=(wrong_work,)
        )

    other_root = _fixture_root(tmp_path / "other")
    with pytest.raises(PipelineError, match="does not bind the selected library root"):
        _validate_acceptance_for_views(
            acceptance_path, root=other_root, discovered_works=works
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows long-path regression")
def test_long_path_acceptance_validates_bound_source_and_rejects_stale_source(tmp_path: Path) -> None:
    staged_root = _fixture_root(tmp_path)
    _write_promoted_acceptance(staged_root)
    acceptance_suffix = (
        Path("library") / "works" / WORK_ID / "forms" / FORM_ID
        / "editions" / EDITION_ID / "acceptance.json"
    )
    padding = max(1, 270 - len(str(tmp_path / "deep-" / acceptance_suffix)))
    root = tmp_path / ("deep-" + "x" * padding)
    shutil.copytree(io_path(staged_root), io_path(root))
    acceptance_path = root / acceptance_suffix
    assert len(str(acceptance_path)) > 260

    result = _build(root, tmp_path)
    assert result["status"]["items"][0]["acceptance_status"] == "promoted"
    assert result["status"]["items"][0]["master_status"] == "accepted"

    record = json.loads(io_path(acceptance_path).read_text(encoding="utf-8"))
    record["source"]["source_sha256"] = "0" * 64
    _write_json(io_path(acceptance_path), record)
    invalid = build_library_views(root, tmp_path / "views-invalid")
    assert invalid["status"]["items"][0]["acceptance_status"] == "invalid"
    assert any(
        "source_sha256 does not bind acquisition" in reason
        for reason in invalid["manifest"]["acceptances"][0]["reasons"]
    )


def test_multiple_acquisitions_without_bound_acceptance_are_not_guessed(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    _add_second_acquisition(root, "ccel-npnf204-alternate")

    result = _build(root, tmp_path)
    item = result["status"]["items"][0]

    assert item["status"] == "failed"
    assert item["release_status"] == "not-eligible"
    assert item["acquisition_id"] is None
    assert "multiple acquisition sidecars" in " ".join(item["reasons"])
    assert len(result["queue"]["acquisitions"]) == 2


def test_orphan_acceptance_sidecar_is_retained_as_orphan(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    orphan = root / "library" / "works" / WORK_ID / "forms" / "orphan-form" / "editions" / "orphan-edition" / "acceptance.json"
    _write_json(orphan, {"schema_version": "2.0"})

    result = _build(root, tmp_path)
    rows = [
        row
        for row in result["manifest"]["acceptances"]
        if row["acceptance_path"] == orphan.relative_to(root).as_posix()
    ]
    assert len(rows) == 1
    assert rows[0]["identity_status"] == "orphan"
    assert rows[0]["status"] == "orphan"
    assert any(issue["code"] == "orphan-acceptance" for issue in result["manifest"]["issues"])
    assert any(
        item["path"] == orphan.relative_to(root).as_posix()
        and item["role"] == "acceptance-sidecar"
        for item in result["manifest"]["freshness"]["inputs"]
    )


def test_orphan_pipe016_record_is_not_grouped_as_edition_evidence(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    assessment = _assessment(root)
    assessment["work_id"] = "undeclared-work"
    assessment["edition_id"] = "undeclared-edition"
    _write_json(root / "assessments" / "orphan-agent-assessment.json", assessment)

    result = _build(root, tmp_path)
    rows = [
        row
        for row in result["manifest"]["assessments"]
        if row["record_path"].endswith("orphan-agent-assessment.json")
    ]
    assert len(rows) == 1
    assert rows[0]["status"] == "orphan"
    assert rows[0]["identity_status"] == "orphan"
    assert result["status"]["items"][0]["agent_assessment"]["status"] == "not-recorded"
    assert any(issue["code"] == "orphan-assessment" for issue in result["manifest"]["issues"])


def test_diagnostics_are_root_independent_for_equivalent_malformed_fixtures(tmp_path: Path) -> None:
    first = _fixture_root(tmp_path / "one")
    second = _fixture_root(tmp_path / "two")
    for root in (first, second):
        state_path = root / "library" / "works" / WORK_ID / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["targets"][0].pop("updated_at")
        _write_json(state_path, state)

    first_result = _build(first, tmp_path / "first-views")
    second_result = _build(second, tmp_path / "second-views")
    for section in ("manifest", "status", "queue"):
        assert first_result[section] == second_result[section]
    serialized = json.dumps(first_result["manifest"], sort_keys=True)
    assert str(first) not in serialized
    assert str(second) not in serialized


def test_agent_assessment_and_human_review_remain_separate(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    _write_json(root / "assessments" / "agent.json", _assessment(root))
    _write_json(root / "reviews" / "review.json", _review(root))

    result = _build(root, tmp_path)
    item = result["status"]["items"][0]
    assert item["agent_assessment"]["status"] == "recorded"
    assert item["human_review"]["status"] == "recorded"
    assert item["agent_assessment"]["records"][0]["result"] == "supports"
    assert item["human_review"]["records"][0]["result"] == "confirmed"


def test_cli_check_is_read_only_and_returns_freshness_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _fixture_root(tmp_path)
    output = tmp_path / "views"
    assert build_views_main(["--root", str(root), "--output", str(output)]) == 0
    assert build_views_main(["--root", str(root), "--output", str(output), "--check"]) == 0
    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert payload["fresh"] is True


def test_explicit_in_place_mode_routes_only_named_outputs(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    result = build_library_views(root, root, in_place=True)
    assert result["paths"]["manifest"].endswith("library/corpus-manifest.json")
    assert (root / "library" / "corpus-manifest.md").is_file()
    assert (root / "reports" / "library" / "project-status.json").is_file()
    assert check_library_views(root, root)["fresh"] is True
