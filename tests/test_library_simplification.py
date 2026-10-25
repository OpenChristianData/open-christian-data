"""Observable SIMP-001/003 contracts at the existing small-library seams."""
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import inspection_read_phase, read_input_bytes
from ocd_kernel.library.records import lookup_library_record, render_library_record
from tests.test_library_records import root, core, write


def test_compact_completed_lookup_retains_stage_scope_and_authorities(tmp_path):
    from tests.test_library_views import _fixture_root, _write_promoted_acceptance, WORK_ID
    fixture = _fixture_root(tmp_path)
    _write_promoted_acceptance(fixture)
    state_path = fixture / f"library/works/{WORK_ID}/state.json"
    state = json.loads(state_path.read_text())
    state["targets"][0]["stage"] = "accepted"
    write(state_path, state)
    result = lookup_library_record(fixture, {"kind": "work", "namespace": "ocd", "id": WORK_ID}, connections=False)
    readable = render_library_record(result)
    assert len(readable.encode("utf-8")) < 4096
    for text in (WORK_ID, "accepted", "Extent:", "Acceptance:", "Master:", "Source:", "not assessed", "--json"):
        assert text in readable
    assert "route_sha256" not in readable and "members\":" not in readable


def test_incomplete_lookup_preserves_alternatives_and_hold_reason(root):
    path = root / "library/works/alpha/state.json"
    state = json.loads(path.read_text())
    state["targets"][0].update(stage="blocked", reason="Missing source supplement")
    write(path, state)
    readable = render_library_record(core(root))
    assert "Alternatives:" in readable and "first" in readable and "second" in readable
    assert "blocked; Missing source supplement" in readable


def test_lookup_reads_config_once_per_phase_and_refreshes_next_query(root, tmp_path, monkeypatch):
    config = root / ".ocd-storage.json"
    external = tmp_path / "library"
    (external / "raw").mkdir(parents=True)
    (external / "raw/source.txt").write_bytes(b"source")
    write(config, {"library_root": str(external.resolve())})
    original = Path.open
    opens = []

    def opened(path, *args, **kwargs):
        if str(path).endswith(".ocd-storage.json"):
            opens.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    first = core(root)
    # One routing config read plus its bound bytes in each of two read phases.
    assert len(opens) == 4
    (external / "raw/source.txt").unlink()
    second = core(root)
    assert first["fingerprint"] != second["fingerprint"]
    assert second["sections"]["holdings"]["health"] == "unavailable"


def test_failed_small_input_is_not_cached_and_standalone_reads_are_fresh(tmp_path):
    path = tmp_path / "input.json"
    with inspection_read_phase():
        with pytest.raises(FileNotFoundError):
            read_input_bytes(path)
        path.write_bytes(b"first")
        assert read_input_bytes(path) == b"first"
        path.write_bytes(b"second")
        assert read_input_bytes(path) == b"first"
    assert read_input_bytes(path) == b"second"


def test_metadata_report_builds_its_inventory_once(tmp_path, monkeypatch):
    from tests.test_library_metadata_report import _root, _load_tool
    tool = _load_tool()
    original = tool._build_snapshot
    snapshots = []

    def built(path):
        snapshot = original(path)
        snapshots.append(snapshot)
        return snapshot

    monkeypatch.setattr(tool, "_build_snapshot", built)
    original_check = tool.check_library_views

    def checked(root, output, *, snapshot=None):
        assert snapshot is snapshots[0]
        return original_check(root, output, snapshot=snapshot)

    monkeypatch.setattr(tool, "check_library_views", checked)
    assert tool.build_report(_root(tmp_path))["scope"]["declared_coverage"] == "complete"
    assert len(snapshots) == 1


def test_browse_uses_current_records_without_reading_text_or_saved_views(root, monkeypatch):
    from ocd_kernel.library.views import library_browse_snapshot
    original = Path.open

    def opened(path, *args, **kwargs):
        name = str(path).replace("\\", "/")
        assert not name.endswith(".xml") and "/raw/" not in name
        assert "corpus-manifest" not in name
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    before = library_browse_snapshot(root)
    assert before["counts"]["works"] == 1 and before["counts"]["editions"] == 2
    assert before["scope"]["text_integrity"] == "not_assessed"
    path = root / "library/works/alpha/work.json"
    work = json.loads(path.read_text())
    work.update(title="Changed title", creators=[{"name": "Émile Example"}])
    write(path, work)
    after = library_browse_snapshot(root, search="emile changed", creator="example", category="prose", stage="planned", limit=1)
    assert after["works"][0]["title"] == "Changed title"
    assert "--id alpha" in after["works"][0]["lookup"]
    assert library_browse_snapshot(root, creator="unknown")["works"] == []


def test_browse_observes_real_master_and_missing_accepted_authority_without_body_reads(tmp_path, monkeypatch):
    from tests.test_library_views import _fixture_root
    from ocd_kernel.library.views import library_browse_snapshot
    fixture = _fixture_root(tmp_path)
    original = Path.open

    def opened(path, *args, **kwargs):
        assert not str(path).endswith(".xml")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    report = library_browse_snapshot(fixture)
    edition = report["works"][0]["editions"][0]
    assert edition["observed_master_presence"] is True
    assert edition["observed_acceptance_presence"] is False
    assert report["counts"]["observed_master_files"] == 1
    assert report["counts"]["failed"] == 1
    assert any(issue["path"].endswith("acceptance.json") for issue in report["issues"])
    next((fixture / "library/works").rglob("master.tei.xml")).unlink()
    changed = library_browse_snapshot(fixture)
    assert changed["counts"]["observed_master_files"] == 0
    assert any(issue["path"].endswith("master.tei.xml") for issue in changed["issues"])


def test_browse_filters_same_edition_and_pages_distinct_identities(root):
    from ocd_kernel.library.views import library_browse_snapshot
    path = root / "library/works/alpha/work.json"
    work = json.loads(path.read_text())
    work["textual_forms"][1]["editions"][0]["category"] = "bible-text"
    write(path, work)
    state_path = root / "library/works/alpha/state.json"
    state = json.loads(state_path.read_text())
    state["targets"][1].update(stage="blocked", reason="Fixture hold")
    write(state_path, state)
    write(root / "library/works/beta/work.json", {"schema_version": "2.0", "work_id": "beta",
          "title": "A work", "textual_forms": [], "evidence": ["research/evidence.md"]})
    first = library_browse_snapshot(root, search="A work", limit=1)
    assert first["page"] == {"offset": 0, "returned": 1, "total": 2, "next_offset": 1}
    assert library_browse_snapshot(root, search="A work", offset=1, limit=1)["works"][0]["work_id"] == "beta"
    assert library_browse_snapshot(root, category="prose", stage="blocked")["works"] == []
    assert library_browse_snapshot(root, category="bible-text", stage="blocked")["works"][0]["work_id"] == "alpha"
    with pytest.raises(ValueError, match="stage"):
        library_browse_snapshot(root, stage="invented")
