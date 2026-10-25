from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import (
    acquisition_research_report,
    load_acquisition_leads,
    manifest_research,
    validate_acquisition,
)


REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("l")


def write_json(path: Path, record: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


def research_root(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    manifest = root / "research/MANIFEST.md"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "# Corpus research\n\n## Acquisition queue\n\n### Commentary\n\n"
        "| Work | Status | Notes |\n|---|---|---|\n"
        "| Existing claim | ACQUIRED | Historical assertion, not proof |\n"
        "| Ambiguous source | BLOCKED | Needs edition identification |\n\n"
        "## Decisions pending\n\n| Decision | Options |\n|---|---|\n"
        "| Greek-only scope | Include or defer |\n",
        encoding="utf-8",
    )
    records = manifest_research(manifest, root=root)["leads"]
    write_queue(root, records)
    return root


def write_queue(root: Path, records: list[dict]) -> None:
    (root / "library").mkdir(exist_ok=True)
    (root / "library/acquisition-leads.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def test_historical_acquired_claim_remains_unresolved_and_has_no_work(tmp_path: Path) -> None:
    root = research_root(tmp_path)
    report = acquisition_research_report(root)
    assert report["counts"] == {"leads": 3, "unresolved": 3, "promoted": 0, "closed": 0}
    assert report["acquisitions"] == []
    assert not (root / "library/works").exists()
    assert "ACQUIRED" in report["leads"][0]["observed_claim"]


def test_report_is_deterministic_and_accounts_for_every_manifest_line(tmp_path: Path) -> None:
    root = research_root(tmp_path)
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    report = acquisition_research_report(root, first)
    acquisition_research_report(root, second)
    assert first.read_bytes() == second.read_bytes()
    covered = [line for group in report["line_dispositions"] for line in range(group["line_start"], group["line_end"] + 1)]
    assert covered == list(range(1, report["manifest"]["lines"] + 1))


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "claim", "intent", "work", "extra", "version"])
def test_invalid_or_unaccounted_leads_fail_closed(tmp_path: Path, mutation: str) -> None:
    root = research_root(tmp_path)
    records = load_acquisition_leads(root / "library/acquisition-leads.jsonl", root=root)
    if mutation == "missing":
        records.pop()
    elif mutation == "duplicate":
        records.append(copy.deepcopy(records[0]))
    elif mutation == "claim":
        records[0]["observed_claim"] = "Unevidenced new claim"
    elif mutation == "intent":
        records[0].pop("acquisition_intent")
    elif mutation == "work":
        records[0].update(disposition="promoted", work_id="missing", resolution="Claim")
    elif mutation == "extra":
        records[0]["isbn"] = "invented-registry-field"
    else:
        records[0]["schema_version"] = "1.0"
    write_queue(root, records)
    with pytest.raises(PipelineError):
        acquisition_research_report(root)


def test_changed_historical_manifest_does_not_silently_rebind_queue(tmp_path: Path) -> None:
    root = research_root(tmp_path)
    manifest = root / "research/MANIFEST.md"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "Changed research\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="stale"):
        acquisition_research_report(root)


def test_new_evidenced_research_can_be_added_after_manifest_migration(tmp_path: Path) -> None:
    root = research_root(tmp_path)
    records = load_acquisition_leads(root / "library/acquisition-leads.jsonl", root=root)
    note = root / "research/new-lead.md"
    note.write_text("OCD intends to assess this bounded Christian source; edition remains unresolved.\n", encoding="utf-8")
    records.append({
        "schema_version": "2.0", "lead_id": "new-research",
        "observed_claim": note.read_text(encoding="utf-8").strip(),
        "acquisition_intent": "Assess the documented source for OCD",
        "disposition": "unresolved", "context": ["New OCD source research"],
        "evidence": {"path": "research/new-lead.md", "sha256": hashlib.sha256(note.read_bytes()).hexdigest(), "line_start": 1, "line_end": 1},
    })
    write_queue(root, records)
    assert acquisition_research_report(root)["counts"]["leads"] == 4


def test_stable_identity_before_acquisition_is_not_reported_as_acquired(tmp_path: Path) -> None:
    root = research_root(tmp_path)
    write_json(root / "library/works/known-work/work.json", {
        "schema_version": "2.0", "work_id": "known-work", "title": "Evidenced work",
        "evidence": ["research/MANIFEST.md#L9"], "textual_forms": [],
    })
    records = load_acquisition_leads(root / "library/acquisition-leads.jsonl", root=root)
    records[0].update(disposition="promoted", work_id="known-work", resolution="Identity established; no retained acquisition evidence yet.")
    write_queue(root, records)
    report = acquisition_research_report(root)
    assert report["counts"]["promoted"] == 1
    assert report["acquisitions"] == []


def test_unscoped_book_inventory_is_not_automatically_imported(tmp_path: Path) -> None:
    manifest = tmp_path / "books.md"
    manifest.write_text("# ISBN inventory\n| Work | ISBN |\n|---|---|\n| Irrelevant | 123 |\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="explicit acquisition queue"):
        manifest_research(manifest, root=tmp_path)


def test_malformed_legacy_table_is_preserved_with_visible_warning(tmp_path: Path) -> None:
    root = research_root(tmp_path)
    manifest = root / "research/MANIFEST.md"
    content = manifest.read_text(encoding="utf-8").replace(
        "| Existing claim | ACQUIRED | Historical assertion, not proof |",
        "| Existing claim | extra old column | ACQUIRED | Historical assertion, not proof |",
    )
    manifest.write_text(content, encoding="utf-8")
    imported = manifest_research(manifest, root=root)
    assert "extra old column" in imported["leads"][0]["observed_claim"]
    assert imported["warnings"][0]["line"] == 9


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    root = research_root(tmp_path)
    queue = root / "library/acquisition-leads.jsonl"
    content = queue.read_text(encoding="utf-8").replace('"disposition": "unresolved"', '"disposition": "closed", "disposition": "unresolved"', 1)
    queue.write_text(content, encoding="utf-8")
    with pytest.raises(PipelineError, match="duplicate JSON key"):
        load_acquisition_leads(queue, root=root)


def test_acquisition_uses_configured_storage_route_without_copying_source(tmp_path: Path) -> None:
    root = tmp_path / "f"
    shutil.copytree(REPO / "tests/fixtures/library-pipeline", root)
    external = tmp_path / "durable"
    source = external / "raw/source.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"retained evidence\n")
    write_json(root / ".ocd-storage.json", {"library_root": str(external.resolve())})
    path = next((root / "library/works").glob("*/forms/*/editions/*/acquisitions/*.json"))
    record = json.loads(path.read_text(encoding="utf-8"))
    record["retained_files"] = [{"path": "raw/source.txt", "bytes": source.stat().st_size, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "media_type": "text/plain"}]
    write_json(path, record)
    assert validate_acquisition(path, root=root)["retained_files"][0]["path"] == "raw/source.txt"
    assert not (root / "raw/source.txt").exists()
    source.write_bytes(b"changed")
    with pytest.raises(PipelineError, match="mismatch"):
        validate_acquisition(path, root=root)


def test_live_manifest_migration_has_exact_line_coverage_and_preserves_snapshot() -> None:
    artifact = REPO / "plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-019"
    snapshot = json.loads((artifact / "00-input-snapshot.json").read_text(encoding="utf-8"))
    historical = next(item["sha256"] for item in snapshot["files"] if item["path"] == "research/MANIFEST.md")
    current = hashlib.sha256((REPO / "research/MANIFEST.md").read_bytes()).hexdigest()
    # The live manifest gained the publication-boundary note after this
    # historical PIPE-019 snapshot. Preserve both identities instead of
    # pretending that the current file is still the old input.
    assert historical == "871a3227a51ef514018def0184f9c57e32d0af585c804d2c0225e66508e5a685"
    assert current == "c99fc84653519380e01b84f3c3aa8cb719a3924754b1b3b7c8ce4fcd09979899"
    assert current != historical
    imported = manifest_research(REPO / "research/MANIFEST.md", root=REPO)
    assert len(imported["leads"]) == 357
    assert {lead["lead_id"] for lead in imported["leads"] if lead["lead_id"].startswith("TFR-")} == {f"TFR-20261001-{i:02d}" for i in range(1, 10)}
    assert any(lead["evidence"]["line_start"] == 282 and "Baxter" in lead["observed_claim"] for lead in imported["leads"])
