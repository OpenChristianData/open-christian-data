"""Focused SIMP-006/007 current curation checks."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from build.lib import source_metadata
from build.tools.maintain_research_lead import main as lead_main
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import load_acquisition_leads
from ocd_kernel.library.research_leads import (
    apply_lead_repair,
    apply_lead_upkeep,
    plan_lead_repair,
    plan_lead_upkeep,
)
from ocd_kernel.library.record_connections import _metadata
from ocd_kernel.library.record_read import RecordRead
from ocd_kernel.release.work_metadata import compose_work_metadata
from tests.test_library_connections import change_manifest, fixture as lead_fixture
from tests.test_library_records import write
from tests.test_source_metadata_semantics import _fixture as metadata_fixture


def test_current_lead_upkeep_preserves_import_history_and_holds(tmp_path: Path, capsys) -> None:
    root, previous = lead_fixture(tmp_path)
    change_manifest(root)
    migration = plan_lead_repair(root)
    apply_lead_repair(root, migration)
    migration_path = root / f"research/lead-history/{migration['migration']['migration_id']}/migration.json"
    history_before = {path: path.read_bytes() for path in migration_path.parent.iterdir()}
    queue = root / "library/acquisition-leads.jsonl"
    before = {row["lead_id"]: row for row in load_acquisition_leads(queue, root=root)}

    write(root / "library/works/alpha/work.json", {
        "schema_version": "2.0", "work_id": "alpha", "title": "Supported identity",
        "evidence": ["research/resolution.md"], "textual_forms": [],
    })
    (root / "research/resolution.md").write_text(
        "Primary source identifies this lead with work alpha.\nNew primary-source lead.\n",
        encoding="utf-8",
    )
    promoted = plan_lead_upkeep(
        root, lead_id=previous[0]["lead_id"], evidence_path="research/resolution.md",
        line_start=1, line_end=1, disposition="promoted", work_id="alpha",
    )
    apply_lead_upkeep(root, promoted)
    added = plan_lead_upkeep(
        root, lead_id="primary-source-follow-up", evidence_path="research/resolution.md",
        line_start=2, line_end=2, acquisition_intent="Review retained source",
        context=["Current primary-source review"],
    )
    apply_lead_upkeep(root, added)

    after = {row["lead_id"]: row for row in load_acquisition_leads(queue, root=root)}
    assert after[previous[0]["lead_id"]]["work_id"] == "alpha"
    assert after[previous[0]["lead_id"]]["observed_claim"] == before[previous[0]["lead_id"]]["observed_claim"]
    assert after["primary-source-follow-up"]["disposition"] == "unresolved"
    from ocd_kernel.library.records import lookup_library_record
    found = lookup_library_record(root, {'kind':'research_lead','namespace':'research','id':'primary-source-follow-up'})
    assert found['sections']['research']['data']['leads'][0]['schema_version'] == '2.2'
    held = previous[1]["lead_id"]
    assert after[held] == before[held]
    assert history_before == {path: path.read_bytes() for path in migration_path.parent.iterdir()}
    with pytest.raises(PipelineError, match="ambiguous"):
        plan_lead_upkeep(
            root, lead_id="duplicate-follow-up", evidence_path="research/resolution.md",
            line_start=2, line_end=2, acquisition_intent="Duplicate", context=["Test"],
        )
    with pytest.raises(PipelineError, match="held lead"):
        plan_lead_upkeep(
            root, lead_id=held, evidence_path="research/resolution.md", line_start=1,
            line_end=1, disposition="closed",
        )
    (root / "research/cli.md").write_text("CLI evidence.\n", encoding="utf-8")
    assert lead_main([
        "--root", str(root), "--lead-id", "cli-follow-up",
        "--evidence-path", "research/cli.md", "--line-start", "1", "--line-end", "1",
        "add", "--intent", "Review CLI evidence", "--context", "Focused test",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["written"] is False


def test_retired_queue_cannot_override_the_library_queue(tmp_path: Path) -> None:
    root, _ = lead_fixture(tmp_path)
    library_queue = root / 'library/acquisition-leads.jsonl'
    old_queue = root / 'research/acquisition-leads.jsonl'
    old_queue.write_text('invalid stale queue', encoding='utf-8')
    note = root / 'library/follow-up.md'
    note.write_text('An evidenced new library lead.\n', encoding='utf-8')
    plan = plan_lead_upkeep(root, lead_id='library-follow-up', evidence_path='library/follow-up.md',
                            line_start=1, line_end=1, acquisition_intent='Assess source', context=['Test'])
    apply_lead_upkeep(root, plan)
    assert old_queue.read_text(encoding='utf-8') == 'invalid stale queue'
    assert any(row['lead_id'] == 'library-follow-up' for row in load_acquisition_leads(library_queue, root=root))
    library_queue.unlink()
    with pytest.raises(OSError):
        plan_lead_upkeep(root, lead_id='another', evidence_path='library/follow-up.md',
                         line_start=1, line_end=1, acquisition_intent='Assess source', context=['Test'])


def test_current_metadata_owner_flows_to_lookup_and_selected_rows(tmp_path: Path) -> None:
    descriptor = {"kind": "work_kind", "predicate": "work_kind", "role": "work_classification", "scope": "work"}
    worklist, decision, claim, worklist_path, _ = metadata_fixture(
        tmp_path, descriptor=descriptor, packet_value="treatise",
    )
    work_path = tmp_path / "library/works/synthetic-work/work.json"
    work = {
        "schema_version": "2.0", "work_id": "synthetic-work", "title": "Fixture work",
        "evidence": ["evidence.json"],
        "work_kind": {"value": "treatise", "source_metadata_subject": {"kind": "catalog", "id": "synthetic-work"}},
        "textual_forms": [{"textual_form_id": "en", "language": "en", "editions": [{
            "edition_id": "fixture-edition", "title": "Fixture edition", "language": "en",
            "category": "prose", "acquisition_ids": [],
        }]}],
    }
    write(work_path, work)
    work_bytes = work_path.read_bytes()
    claim["adoption"] = {
        "classification": "adopted", "destination": "v2",
        "target": {"path": work_path.relative_to(tmp_path).as_posix(), "selector": "/work_kind/value",
                   "expected_value": "treatise", "value_check": True,
                   "current_raw_sha256": hashlib.sha256(work_bytes).hexdigest()},
    }
    current = tmp_path / source_metadata.DEFAULT_DECISIONS / "synthetic-work.json"
    current.parent.mkdir(parents=True)
    current.write_bytes(source_metadata.canonical_bytes(decision))

    source_metadata.write_outputs(tmp_path, worklist_path=worklist_path)
    assert source_metadata.decision_owner(tmp_path, "catalog", "synthetic-work") == "metadata/decisions/synthetic-work.json"
    assert source_metadata.lookup_work_kind(tmp_path, work_path)["evidence"]["value"] == "treatise"
    sections = {"metadata": {"data": {"source_observations": []}}}
    _metadata(RecordRead(tmp_path), sections, "synthetic-work", [])
    assert sections["metadata"]["data"]["source_observations"][0]["authored_owner"] == "metadata/decisions/synthetic-work.json"
    rows = [{"work_id": "synthetic-work", "textual_form_id": "en", "edition_id": "fixture-edition",
             "provenance": {}}]
    selected, receipt = compose_work_metadata(tmp_path, rows, {})
    assert selected[0]["provenance"]["work_kind"] == "treatise"
    assert receipt["work_metadata"]["values"] == {"work_kind": "treatise"}

    stale = copy.deepcopy(decision)
    stale["decisions"][0]["dimensions"]["work"]["owner"] = "different reviewer"
    current.write_bytes(source_metadata.canonical_bytes(stale))
    with pytest.raises(source_metadata.MetadataError, match="projection differs"):
        source_metadata.decision_owner(
            tmp_path, "catalog", "synthetic-work",
            sidecar=source_metadata.lookup_sidecar(tmp_path, "catalog", "synthetic-work"),
        )
    current.write_bytes(source_metadata.canonical_bytes(decision))
    (tmp_path / "evidence.json").write_bytes(source_metadata.canonical_bytes({"value": "sermon"}))
    with pytest.raises(source_metadata.EvidenceError):
        source_metadata.lookup_work_kind(tmp_path, work_path)


def test_legacy_metadata_decision_remains_resolvable(tmp_path: Path) -> None:
    _, decision, _, _, _ = metadata_fixture(tmp_path)
    legacy = tmp_path / source_metadata.LEGACY_DECISIONS / "historical.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(source_metadata.canonical_bytes(decision))
    assert source_metadata.decision_owner(tmp_path, "catalog", "synthetic-work") == legacy.relative_to(tmp_path).as_posix()

    current = tmp_path / source_metadata.DEFAULT_DECISIONS / "duplicate.json"
    current.parent.mkdir(parents=True)
    current.write_bytes(source_metadata.canonical_bytes(copy.deepcopy(decision)))
    with pytest.raises(source_metadata.MetadataError, match="unique"):
        source_metadata.decision_owner(tmp_path, "catalog", "synthetic-work")


def test_family_decision_resolves_through_aggregate_projection_batch(tmp_path: Path) -> None:
    _, decision, _, worklist_path, _ = metadata_fixture(tmp_path)
    decision['batch_id'] = 'historical-family-packet'
    legacy = tmp_path / source_metadata.LEGACY_DECISIONS / 'family.json'
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(source_metadata.canonical_bytes(decision))
    source_metadata.write_outputs(tmp_path, worklist_path=worklist_path, decisions_path=legacy)
    sidecar = source_metadata.lookup_sidecar(tmp_path, 'catalog', 'synthetic-work')
    assert sidecar['batch_id'] != decision['batch_id']
    assert source_metadata.decision_owner(tmp_path, 'catalog', 'synthetic-work', sidecar=sidecar) == legacy.relative_to(tmp_path).as_posix()
    wrong_batch = {**sidecar, 'batch_id': decision['batch_id']}
    with pytest.raises(source_metadata.MetadataError, match='projection differs'):
        source_metadata.decision_owner(tmp_path, 'catalog', 'synthetic-work', sidecar=wrong_batch)
