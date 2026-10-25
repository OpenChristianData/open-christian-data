"""Focused tests for META-001.

The fixture is deliberately small: it proves accounting and classifications
without making the actual 348-lead repository count a fixture dependency.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest

from ocd_kernel.library.acquisitions import manifest_research
from ocd_kernel.library._common import PipelineError


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "library-pipeline"
WORK_ID = "athanasius-on-the-incarnation"
FORM_ID = "athanasius-on-the-incarnation-prose"
EDITION_ID = "ccel-npnf204"
ACQUISITION_ID = "ccel-npnf204-retained-xml"
RETAINED_PATH = "retained/npnf204.vii.ii.i.thml.xml"


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Keep synthetic roots short on Windows."""

    return tmp_path_factory.mktemp("meta")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _load_tool() -> ModuleType:
    path = REPO_ROOT / "build" / "tools" / "report_library_metadata.py"
    spec = importlib.util.spec_from_file_location("meta_report_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load META-001 tool: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _root(tmp_path: Path, *, acquired_only: bool = True) -> Path:
    root = tmp_path / "r"
    shutil.copytree(FIXTURE_ROOT, root)
    if acquired_only:
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
        master_path.unlink()
        state_path = root / "library" / "works" / WORK_ID / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["targets"] = [
            {
                "target_id": ACQUISITION_ID,
                "target_type": "acquisition",
                "stage": "acquired",
                "updated_at": state["targets"][0]["updated_at"],
                "evidence": [
                    f"forms/{FORM_ID}/editions/{EDITION_ID}/acquisitions/{ACQUISITION_ID}.json"
                ],
            }
        ]
        _write_json(state_path, state)
    manifest_path = root / "research" / "MANIFEST.md"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        "# Synthetic research\n\n"
        "## Acquisition queue\n\n"
        "| Work | Source |\n"
        "| --- | --- |\n"
        "| Synthetic Alpha | source-a |\n"
        "| Synthetic Beta | source-b |\n",
        encoding="utf-8",
        newline="\n",
    )
    imported = manifest_research(manifest_path, root=root)
    queue = root / "library" / "acquisition-leads.jsonl"
    queue.write_text(
        "".join(json.dumps(lead, ensure_ascii=False, sort_keys=True) + "\n" for lead in imported["leads"]),
        encoding="utf-8",
        newline="\n",
    )
    return root


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _known_library_fixture(root: Path, tmp_path: Path) -> tuple[Path, Path, dict[str, Path]]:
    """Create a small bound Ticket 37-shaped population for opt-in tests."""

    queue_rows = [
        json.loads(line)
        for line in (root / "library" / "acquisition-leads.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    lead_ids = [str(row["lead_id"]) for row in queue_rows]
    assert len(lead_ids) >= 2
    ticket_root = root / "ticket37"
    readiness_dir = ticket_root / "readiness325"
    ticket_root.mkdir(parents=True, exist_ok=True)
    readiness_dir.mkdir(parents=True, exist_ok=True)

    catalog_rows = [
        {
            "work_id": WORK_ID,
            "title": "Synthetic current title",
            "reconstruction_owner": "LIB-TEST",
            "existing_review_ticket": "37a-01",
            "sweep_ticket": "37a-01",
            "next_action": "Review the retained source.",
            "catalog_status_at_inventory": "ready-for-review",
            "assessment_status": "assessed_follow_up_required",
            "disposition": "ready-for-review",
            "assessment_evidence": {
                "new_visual_review": False,
                "new_review_admission": False,
            },
        },
        {
            "work_id": "legacy-only",
            "title": "Synthetic legacy title",
            "reconstruction_owner": "LIB-OTHER",
            "existing_review_ticket": None,
            "sweep_ticket": None,
            "next_action": "Locate retained authority.",
            "catalog_status_at_inventory": "readiness-pending",
            "assessment_status": "previously_cataloged",
            "disposition": "carried-forward",
        },
    ]
    sweep_rows = [
        {
            "work_id": row["work_id"],
            "title": row["title"],
            "status": row["catalog_status_at_inventory"],
            "reconstruction_owner": row["reconstruction_owner"],
            "existing_review_ticket": row["existing_review_ticket"],
            "next_action": row["next_action"],
        }
        for row in catalog_rows
    ]
    readiness_rows = [
        {
            "work_id": WORK_ID,
            "title": "Synthetic current title",
            "owner": "LIB-TEST",
            "investigation_disposition": "ready-for-review",
            "next_action": "Review the retained source.",
            "evidence_report": "synthetic.json",
            "evidence_selector": WORK_ID,
            "catalog_readiness_status": "ready-for-review",
            "new_visual_review": False,
            "new_review_admission": False,
        }
    ]
    gap_rows = [{"sequence": 1, "lane": "lane-1"}, {"sequence": 2, "lane": "lane-2"}]
    sweep_path = ticket_root / "sweep-index.json"
    readiness_path = readiness_dir / "work-index.json"
    gap_path = ticket_root / "acquisition-gap-report.json"
    _write_json(sweep_path, {"catalog_rows": sweep_rows})
    _write_json(readiness_path, {"work_count": 1, "rows": readiness_rows})
    _write_json(gap_path, {"rows": gap_rows})

    legacy_rows = [
        {
            "work_id": WORK_ID,
            "title": "Synthetic legacy title",
            "category": "structured-text",
            "schema_types": ["structured_text"],
            "file_count": 1,
            "source_paths": ["structured-text/synthetic.json"],
            "metadata_fields": {
                "title": ["Synthetic legacy title"],
                "author": ["Legacy Author"],
                "contributors": ["Legacy Editor"],
                "provenance.translator": ["Legacy Translator"],
                "language": ["en"],
                "provenance.source_edition": ["Synthetic edition"],
                "provenance.source_url": ["https://example.invalid/source"],
                "provenance.source_hash": ["sha256:legacy"],
                "provenance.download_date": ["2026-09-08"],
                "provenance.processing_date": ["2026-09-08"],
                "original_publication_year": ["1900"],
            },
            "publication_date": "1900",
        },
        {
            "work_id": "legacy-only",
            "title": "Synthetic legacy title 2",
            "category": "hymns",
            "schema_types": ["hymn_collection"],
            "file_count": 1,
            "source_paths": ["hymns/synthetic.json"],
            "metadata_fields": {"title": ["Synthetic legacy title 2"], "language": ["mul"]},
            "publication_date": None,
        },
    ]
    legacy_path = root / "reports" / "publish" / "work_catalog.json"
    _write_json(legacy_path, {"works": legacy_rows})

    def _lane(sequence: int, lead_id: str, *, existing: bool) -> dict[str, object]:
        return {
            "sequence": sequence,
            "lane": f"lane-{sequence}",
            "title": f"Lane title {sequence}",
            "grouping_key": (f"existing:{WORK_ID}" if existing else f"proposed:lane-{sequence}"),
            "relationship": "source-upgrade" if existing else "distinct-title-candidate",
            "classification": "source_upgrade_existing_work" if existing else "new_work_candidate",
            "scope_status": "frozen_reviewed",
            "identity_evidence": {
                "file": "identity-first.json",
                "path": "research/MANIFEST.md",
                "locator": f"lane-{sequence}",
            },
            "research_evidence": {"lead_id": lead_id},
            "catalog_relation": (
                {
                    "current_view": "existing",
                    "exact": True,
                    "relation": "source_upgrade_to_existing_work",
                    "work_id": WORK_ID,
                    "related_work_ids": [WORK_ID],
                }
                if existing
                else {
                    "current_view": "none",
                    "exact": False,
                    "relation": "no_exact_current_catalog_row",
                    "related_work_ids": [],
                }
            ),
            "execution_ticket": f"37b-{sequence:02d}",
            "execution_route": {
                "route_key": f"proposed:lane-{sequence}",
                "path": f"issues/37b-{sequence:02d}-lane.md",
                "status": "readiness-pending",
            },
            "unresolved": ["edition boundary"],
            "next_action": f"Resolve lane {sequence}.",
        }

    known_path = ticket_root / "library-status.json"
    known = {
        "catalog_rows": catalog_rows,
        "acquisition_lanes": [
            _lane(1, lead_ids[0], existing=False),
            _lane(2, lead_ids[1], existing=True),
        ],
        "input_identities": [
            {"path": "sweep-index.json", "bytes": sweep_path.stat().st_size, "sha256": _hash(sweep_path)},
            {
                "path": "readiness325/work-index.json",
                "bytes": readiness_path.stat().st_size,
                "sha256": _hash(readiness_path),
            },
            {
                "path": "acquisition-gap-report.json",
                "bytes": gap_path.stat().st_size,
                "sha256": _hash(gap_path),
            },
        ],
    }
    _write_json(known_path, known)
    receipt_path = ticket_root / "library-status-verification.json"
    _write_json(
        receipt_path,
        {
            "decision": "PASS",
            "checks": ["synthetic exact catalog and readiness binding"],
            "outputs": [
                {"path": "library-status.json", "bytes": known_path.stat().st_size, "sha256": _hash(known_path)}
            ],
        },
    )
    return known_path, legacy_path, {
        "sweep": sweep_path,
        "readiness": readiness_path,
        "gap": gap_path,
        "receipt": receipt_path,
    }


def _refresh_known_receipt(known_path: Path) -> None:
    receipt_path = known_path.with_name("library-status-verification.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["outputs"] = [
        {"path": known_path.name, "bytes": known_path.stat().st_size, "sha256": _hash(known_path)}
    ]
    _write_json(receipt_path, receipt)


def _pipe004_helpers() -> ModuleType:
    """Load only the settled PIPE-004 fixture builders, when needed."""

    path = REPO_ROOT / "tests" / "test_tei_acceptance.py"
    spec = importlib.util.spec_from_file_location("pipe004_fixture_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load PIPE-004 fixture helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _promote_acceptance(root: Path) -> None:
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
    state["targets"][0]["evidence"].extend(
        [
            f"library/works/{WORK_ID}/forms/{FORM_ID}/editions/{EDITION_ID}/acceptance.json",
            f"library/works/{WORK_ID}/forms/{FORM_ID}/editions/{EDITION_ID}/master.tei.xml",
        ]
    )
    _write_json(state_path, state)


def test_declared_boundary_keeps_library_and_leads_separate(tmp_path: Path) -> None:
    report = _load_tool().build_report(_root(tmp_path))

    assert report["scope"]["declared_coverage"] == "complete"
    assert report["scope"]["historical_coverage"] == "unassessed"
    assert len(report["research_leads"]) == 2
    assert report["counts"]["resolved_research_leads"] == 0
    assert report["counts"]["unresolved_research_leads"] == 2
    assert report["accounting"]["research_leads"]["all_accounted"] is True
    assert {row["entity_type"] for row in report["entities"]} >= {
        "work",
        "textual_form",
        "edition",
        "acquisition",
        "state",
        "state_target",
        "master",
        "acceptance",
        "research_lead",
    }
    assert report["pipeline_availability"][0]["pipeline_status"] == "acquired_no_master"
    assert all(row["stable_work_id"] is None for row in report["research_leads"])
    assert all(
        {"identity", "entity_id", "authority_kind", "field_path", "classification", "evidence", "authority_route"}
        <= set(row)
        for row in report["findings"]
    )


def test_absent_optional_fields_are_not_called_unknown(tmp_path: Path) -> None:
    report = _load_tool().build_report(_root(tmp_path))
    fields = {"accessed_at", "rights", "source"}
    findings = [item for item in report["findings"] if item["field_path"] in fields]

    assert findings
    assert all(item["classification"] == "useful_optional_missing" for item in findings)
    assert not any(
        item["classification"] == "unknown" and item["field_path"] in fields
        for item in report["findings"]
    )


def test_preacquisition_edition_remains_an_inventory_entity(tmp_path: Path) -> None:
    root = _root(tmp_path)
    work_path = root / "library" / "works" / WORK_ID / "work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    work["textual_forms"].append(
        {
            "textual_form_id": "unacquired-form",
            "editions": [{"edition_id": "unacquired-edition", "title": "Unacquired edition"}],
        }
    )
    _write_json(work_path, work)

    report = _load_tool().build_report(root)
    row = next(item for item in report["pipeline_availability"] if item["edition_id"] == "unacquired-edition")

    assert any(item.get("edition_id") == "unacquired-edition" for item in report["entities"])
    assert row["pipeline_status"] == "source_unavailable"
    assert row["source_availability"] == "unacquired"


def test_malformed_authority_is_invalid_unknown_and_blocks_coverage(tmp_path: Path) -> None:
    root = _root(tmp_path)
    work_path = root / "library" / "works" / WORK_ID / "work.json"
    work_path.write_text("{not-json", encoding="utf-8", newline="\n")

    report = _load_tool().build_report(root)
    work_findings = [item for item in report["findings"] if item["entity_type"] == "work"]

    assert any(item["classification"] == "unknown" and item["availability"] == "invalid" for item in work_findings)
    assert not any(item["classification"] == "required_missing" for item in work_findings)
    assert report["scope"]["declared_coverage"] == "incomplete"


def test_partial_source_group_names_each_conditional_requirement_once(tmp_path: Path) -> None:
    root = _root(tmp_path)
    path = (
        root / "library" / "works" / WORK_ID / "forms" / FORM_ID
        / "editions" / EDITION_ID / "acquisitions" / f"{ACQUISITION_ID}.json"
    )
    acquisition = json.loads(path.read_text(encoding="utf-8"))
    missing = {"source_bytes", "source_sha256", "source_scope"}
    for field in missing:
        acquisition.pop(field)
    _write_json(path, acquisition)

    report = _load_tool().build_report(root)
    findings = [
        item for item in report["findings"]
        if item["entity_type"] == "acquisition"
        and item["classification"] == "required_missing"
    ]

    assert {item["field_path"] for item in findings} == missing
    assert len(findings) == len(missing)
    assert len({item["finding_id"] for item in findings}) == len(missing)
    assert all(item["authority_route"] == "acquisition" for item in findings)
    assert report["scope"]["declared_coverage"] == "incomplete"


def test_duplicate_and_malformed_leads_fail_accounting_without_minting_ids(tmp_path: Path) -> None:
    root = _root(tmp_path)
    queue = root / "library" / "acquisition-leads.jsonl"
    lines = queue.read_text(encoding="utf-8").splitlines()
    queue.write_text(
        "\n".join(lines + [lines[0], "{not-json", ""]),
        encoding="utf-8",
        newline="\n",
    )

    report = _load_tool().build_report(root)
    accounting = report["accounting"]["research_leads"]
    codes = {item["code"] for item in report["issues"]}

    assert accounting["expected"] == 2
    assert accounting["reported"] == 3
    assert accounting["unique"] == 2
    assert accounting["all_accounted"] is False
    assert accounting["duplicate_ids"]
    assert {"duplicate-lead-id", "invalid-lead-json", "invalid-research-leads"} <= codes
    assert not any(row.get("stable_work_id") for row in report["research_leads"])


def test_equivalent_roots_have_identical_portable_reports(tmp_path: Path) -> None:
    first = _root(tmp_path / "one")
    second = _root(tmp_path / "two")
    first_report = _load_tool().build_report(first)
    second_report = _load_tool().build_report(second)

    assert first_report == second_report
    serialized = json.dumps(first_report, sort_keys=True)
    assert str(first) not in serialized
    assert str(second) not in serialized


def test_two_bound_records_can_be_contradictory(tmp_path: Path) -> None:
    tool = _load_tool()
    root = _root(tmp_path)
    manifest = {
        "works": [
            {"work_id": "w", "title": "A", "work_path": "library/works/w/work.json"},
            {"work_id": "w", "title": "B", "work_path": "library/works/w/work.json"},
        ]
    }

    findings = tool._bound_conflict_rows(root, manifest)

    assert len(findings) == 1
    assert findings[0]["classification"] == "contradictory"
    assert findings[0]["field_path"] == "title"
    assert len(findings[0]["evidence"]) == 2


def test_legacy_non_authority_config_does_not_create_contradiction(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _write_json(root / "legacy-config.json", {"title": "Unbound spelling variant"})
    report = _load_tool().build_report(root)

    assert not any(item["classification"] == "contradictory" for item in report["findings"])


def test_promoted_acceptance_is_required_for_accepted_pipeline_status(tmp_path: Path) -> None:
    root = _root(tmp_path, acquired_only=False)
    _promote_acceptance(root)
    report = _load_tool().build_report(root)
    item = report["pipeline_availability"][0]

    assert item["pipeline_status"] == "accepted"
    assert item["master_status"] == "accepted"
    assert item["acceptance_status"] == "promoted"
    assert item["edition_stage"] == "accepted"
    assert report["accepted_tei_observations"][0]["status"] == "observed"
    assert report["accepted_tei_observations"][0]["availability"]["teiHeader.title"] == "present"


def test_retained_source_hash_is_unchanged_by_read_only_report(tmp_path: Path) -> None:
    root = _root(tmp_path)
    source = root / RETAINED_PATH
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    _load_tool().build_report(root)
    after = hashlib.sha256(source.read_bytes()).hexdigest()

    assert before == after


def test_report_output_cannot_target_an_authority(tmp_path: Path) -> None:
    root = _root(tmp_path)
    tool = _load_tool()

    with pytest.raises(PipelineError, match="refusing to write"):
        tool.write_report(root, root / "library" / "works" / WORK_ID / "work.json")
    with pytest.raises(PipelineError, match="refusing to write"):
        tool.write_report(root, root / "raw" / "would-be-authority.json")

    output = tmp_path / "fresh-report.json"
    tool.write_report(root, output)
    assert output.is_file()


def test_cli_returns_nonzero_for_incomplete_lead_accounting(tmp_path: Path) -> None:
    root = _root(tmp_path)
    queue = root / "library" / "acquisition-leads.jsonl"
    queue.write_text(queue.read_text(encoding="utf-8") + "{not-json\n", encoding="utf-8", newline="\n")

    assert _load_tool().main(["--root", str(root), "--output", str(tmp_path / "incomplete.json")]) == 2


def test_known_library_accounts_without_promoting_claims(tmp_path: Path) -> None:
    root = _root(tmp_path)
    known, legacy, _ = _known_library_fixture(root, tmp_path)
    report = _load_tool().build_report(root, known, legacy)
    coverage = report["known_library"]
    assert coverage["catalog"]["row_count"] == 2
    assert coverage["catalog"]["readiness_actual_row_count"] == 1
    assert coverage["catalog"]["prior_disposition_row_count"] == 1
    assert coverage["catalog"]["registration_status"]["registered"] == 1
    current = next(row for row in coverage["catalog_rows"] if row["work_id"] == WORK_ID)
    assert current["current_authority"]["declared_textual_forms"][0]["textual_form_id"] == FORM_ID
    assert current["observed_legacy_metadata"]["authoritative"] is False
    assert coverage["acquisition_lanes"][0]["grouping_key"] == "proposed:lane-1"
    assert coverage["lane_accounting"]["combined_work_count"] is None
    assert coverage["factual_verification"] == "incomplete"
    assert report["counts"]["required_missing"] == 0
    assert _load_tool().build_report(root, known, legacy) == report


@pytest.mark.parametrize("mutation, message", [
    ("duplicate_catalog", "duplicate"),
    ("missing_catalog", "versus sweep"),
    ("duplicate_lead", "duplicate research lead"),
    ("missing_lane", "lane identities differ"),
    ("unknown_relation", "unknown existing catalog ID"),
])
def test_known_library_rejects_incoherent_join_even_with_current_receipt(
    tmp_path: Path, mutation: str, message: str,
) -> None:
    root = _root(tmp_path)
    known, legacy, _ = _known_library_fixture(root, tmp_path)
    data = json.loads(known.read_text(encoding="utf-8"))
    if mutation == "duplicate_catalog":
        data["catalog_rows"].append(data["catalog_rows"][0])
    elif mutation == "missing_catalog":
        data["catalog_rows"].pop()
    elif mutation == "duplicate_lead":
        data["acquisition_lanes"][1]["research_evidence"] = data["acquisition_lanes"][0]["research_evidence"]
    elif mutation == "missing_lane":
        data["acquisition_lanes"].pop()
    else:
        data["acquisition_lanes"][0]["catalog_relation"]["related_work_ids"] = ["nonexistent"]
    _write_json(known, data)
    _refresh_known_receipt(known)
    with pytest.raises(PipelineError, match=message):
        _load_tool().build_report(root, known, legacy)


@pytest.mark.parametrize("target", ["catalog", "readiness", "receipt_missing"])
def test_known_library_rejects_missing_or_changed_evidence(tmp_path: Path, target: str) -> None:
    root = _root(tmp_path)
    known, legacy, paths = _known_library_fixture(root, tmp_path)
    if target == "receipt_missing":
        paths["receipt"].unlink()
    else:
        path = known if target == "catalog" else paths["readiness"]
        path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(PipelineError, match="missing|drift"):
        _load_tool().build_report(root, known, legacy)


def test_known_library_rejects_missing_readiness_row_after_rebinding(tmp_path: Path) -> None:
    root = _root(tmp_path)
    known, legacy, paths = _known_library_fixture(root, tmp_path)
    _write_json(paths["readiness"], {"work_count": 0, "rows": []})
    data = json.loads(known.read_text(encoding="utf-8"))
    for identity in data["input_identities"]:
        if identity["path"] == "readiness325/work-index.json":
            identity.update(bytes=paths["readiness"].stat().st_size, sha256=_hash(paths["readiness"]))
    _write_json(known, data)
    _refresh_known_receipt(known)
    with pytest.raises(PipelineError, match="readiness325 versus assessed"):
        _load_tool().build_report(root, known, legacy)


def test_readiness_actions_may_advance_past_sweep(tmp_path: Path) -> None:
    root = _root(tmp_path)
    known, legacy, paths = _known_library_fixture(root, tmp_path)
    sweep = json.loads(paths["sweep"].read_text(encoding="utf-8"))
    sweep["catalog_rows"][0]["next_action"] = "Earlier investigation action."
    _write_json(paths["sweep"], sweep)
    data = json.loads(known.read_text(encoding="utf-8"))
    data["input_identities"][0].update(bytes=paths["sweep"].stat().st_size, sha256=_hash(paths["sweep"]))
    _write_json(known, data)
    _refresh_known_receipt(known)
    assert _load_tool().build_report(root, known, legacy)["known_library"]["catalog_accounting"] == "complete"
