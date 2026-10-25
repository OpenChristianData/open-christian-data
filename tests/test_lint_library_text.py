"""Corpus coverage must not hide failed, orphaned, or moving accepted inputs."""
import json
from types import SimpleNamespace

import pytest

from build.tools import lint_library_text as tool


def library(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    work = root / "library/works/example/work.json"
    work.parent.mkdir(parents=True)
    work.write_text("{}")
    master = work.parent / "forms/english/editions/retained/master.tei.xml"
    master.parent.mkdir(parents=True)
    master.write_text('<TEI><text><body><p>\ufffd</p></body></text></TEI>', encoding="utf-8")
    acceptance_path = master.with_name("acceptance.json")
    acceptance = {"identity": {"work_id": "example", "textual_form_id": "english", "edition_id": "retained"},
                  "promotion": {"status": "promoted", "master": {
                      "path": master.relative_to(root).as_posix(), "bytes": master.stat().st_size,
                      "sha256": tool.digest(master)}}}
    acceptance_path.write_text(json.dumps(acceptance))
    edition = SimpleNamespace(work_id="example", textual_form_id="english", edition_id="retained", path=master)
    monkeypatch.setattr(tool, "load_editions", lambda path: (edition,))
    monkeypatch.setattr(tool, "load_acceptance", lambda path: json.loads(path.read_text()))
    return root, master, acceptance_path


def test_complete_scan_is_advisory_and_preserves_bytes(tmp_path, monkeypatch):
    root, master, acceptance = library(tmp_path, monkeypatch)
    before = master.read_bytes(), acceptance.read_bytes()
    output = tmp_path / "report"
    result = tool.scan_library(root, output)
    assert result["status"] == "complete"
    assert result["statuses"] == {"scanned": 1}
    assert result["text_correctness"] == "not_assessed"
    finding, = [json.loads(line) for line in (output / "observations.jsonl").read_text().splitlines()]
    assert finding["rule"] == "replacement_character_present"
    assert finding["master_sha256"] == tool.digest(master)
    assert finding["edition_id"] == "retained"
    assert result["editions"][0]["groups_by_region"] == [
        {"region": "body", "reading": None, "rule": "replacement_character_present", "count": 1}]
    assert before == (master.read_bytes(), acceptance.read_bytes())


@pytest.mark.parametrize("change", ["bytes", "identity", "path", "status"])
def test_unbound_or_unpromoted_master_never_scans(tmp_path, monkeypatch, change):
    root, master, acceptance = library(tmp_path, monkeypatch)
    data = json.loads(acceptance.read_text())
    if change == "bytes":
        master.write_text("<TEI/>")
    elif change == "identity":
        data["identity"]["edition_id"] = "other"
    elif change == "path":
        data["promotion"]["master"]["path"] = "elsewhere.xml"
    else:
        data["promotion"]["status"] = "pending"
    acceptance.write_text(json.dumps(data))
    result = tool.scan_library(root, tmp_path / "report")
    assert result["status"] == "incomplete"
    assert result["statuses"] == {"scan_failed": 1}


def test_unaccepted_editions_and_orphans_are_accounted(tmp_path, monkeypatch):
    root, master, acceptance = library(tmp_path, monkeypatch)
    orphan = acceptance.parent.parent / "orphan/acceptance.json"
    orphan.parent.mkdir()
    acceptance.rename(orphan)
    result = tool.scan_library(root, tmp_path / "report")
    assert result["statuses"] == {"no_acceptance": 1, "orphan_acceptance": 1}
    assert result["status"] == "incomplete"


def test_changes_after_scanning_are_detected(tmp_path, monkeypatch):
    root, master, acceptance = library(tmp_path, monkeypatch)
    original = tool.lint_xml_file

    def moving_scan(path):
        report = original(path)
        acceptance.write_text(acceptance.read_text() + "\n")
        master.write_text("<TEI/>")
        return report

    monkeypatch.setattr(tool, "lint_xml_file", moving_scan)
    result = tool.scan_library(root, tmp_path / "report")
    assert result["status"] == "incomplete"
    assert set(result["changed_during_scan"]) == {
        acceptance.relative_to(root).as_posix(), master.relative_to(root).as_posix()}


def test_invalid_work_and_unsafe_xml_are_coverage_failures(tmp_path, monkeypatch):
    root, master, acceptance = library(tmp_path, monkeypatch)
    master.write_text('<!DOCTYPE TEI [<!ENTITY e SYSTEM "file:///missing">]><TEI>&e;</TEI>')
    data = json.loads(acceptance.read_text())
    data["promotion"]["master"].update(bytes=master.stat().st_size, sha256=tool.digest(master))
    acceptance.write_text(json.dumps(data))
    result = tool.scan_library(root, tmp_path / "unsafe")
    assert result["status"] == "incomplete"
    assert "external text entities" in result["editions"][0]["error"]
    monkeypatch.setattr(tool, "load_editions", lambda path: (_ for _ in ()).throw(ValueError("invalid identity")))
    result = tool.scan_library(root, tmp_path / "invalid")
    assert result["statuses"] == {"invalid_work": 1, "orphan_acceptance": 1}
