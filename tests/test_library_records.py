from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ocd_kernel.library.identities import validate_record
from ocd_kernel.library.record_read import RecordRead
from ocd_kernel.library.records import lookup_exit_code, lookup_library_record, render_library_record


def write(path: Path, record: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    source = root / "raw/source.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    evidence = root / "research/evidence.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("Recorded evidence.\n", encoding="utf-8")
    base = root / "library/works/alpha"
    write(base / "work.json", {
        "schema_version": "2.0", "work_id": "alpha", "title": "A work",
        "evidence": ["research/evidence.md"], "textual_forms": [
            {"textual_form_id": "en", "language": "en", "editions": [
                {"edition_id": "first", "title": "First witness", "language": "en", "category": "prose", "acquisition_ids": ["copy"]}]},
            {"textual_form_id": "fr", "language": "fr", "editions": [
                {"edition_id": "second", "title": "Second witness", "language": "fr", "category": "prose", "acquisition_ids": []}]},
        ],
    })
    write(base / "state.json", {"schema_version": "2.0", "work_id": "alpha", "targets": [
        {"target_id": identifier, "target_type": "edition", "stage": "planned", "updated_at": "2026-10-02T00:00:00Z", "evidence": ["research/evidence.md"]}
        for identifier in ("first", "second")]})
    write(base / "forms/en/editions/first/acquisitions/copy.json", {
        "schema_version": "2.0", "acquisition_id": "copy", "edition_id": "first", "provider": "Fixture source",
        "url": "https://example.org/source", "retained_files": [{"path": "raw/source.txt", "bytes": 6,
        "sha256": hashlib.sha256(b"source").hexdigest(), "media_type": "text/plain"}], "route": "born-digital"})
    return root


def core(root: Path, **selector: str) -> dict:
    return lookup_library_record(root, selector or {"kind": "work", "namespace": "ocd", "id": "alpha"}, connections=False)


def test_work_lookup_preserves_forms_sources_and_separate_inspection_bases(root: Path) -> None:
    result = core(root)
    assert lookup_exit_code(result) == 0
    validate_record("library-record", result)
    assert result["sections"]["identity"]["data"]["selected_forms"] == ["en", "fr"]
    editions = result["sections"]["holdings"]["data"]["editions"]
    assert [edition["edition_id"] for edition in editions] == ["first", "second"]
    retained = editions[0]["acquisitions"][0]["retained"][0]
    assert retained["declared"]["sha256"] == hashlib.sha256(b"source").hexdigest()
    assert retained["observed_presence"]["present"] is True
    assert retained["current_integrity"] == "not_assessed"
    assert editions[0]["historical_acceptance"]["record"] is None
    assert result["sections"]["research"]["health"] == "not_assessed"


@pytest.mark.parametrize("kind,identifier,parents", [
    ("textual_form", "fr", {"work_id": "alpha"}),
    ("edition", "first", {"work_id": "alpha", "textual_form_id": "en"}),
    ("acquisition", "copy", {"work_id": "alpha", "textual_form_id": "en", "edition_id": "first"}),
])
def test_exact_child_lookup_respects_parent_scope(root: Path, kind: str, identifier: str, parents: dict) -> None:
    result = core(root, kind=kind, namespace="ocd", id=identifier, **parents)
    assert lookup_exit_code(result) == 0
    assert len(result["sections"]["holdings"]["data"]["editions"]) == 1
    if kind == "acquisition":
        assert result["sections"]["holdings"]["data"]["editions"][0]["acquisitions"][0]["record"]["acquisition_id"] == "copy"


def test_identity_only_and_ocr_route_do_not_invent_editions(root: Path) -> None:
    write(root / "library/works/identity-only/work.json", {"schema_version": "2.0", "work_id": "identity-only",
          "title": "Provisional work", "textual_forms": [], "evidence": ["research/evidence.md"]})
    result = core(root, kind="work", namespace="ocd", id="identity-only")
    assert lookup_exit_code(result) == 0
    assert result["sections"]["holdings"]["data"]["editions"] == []
    sidecar = root / "library/works/alpha/forms/en/editions/first/acquisitions/copy.json"
    record = json.loads(sidecar.read_text())
    record["route"] = "ocr"
    write(sidecar, record)
    assert core(root)["sections"]["holdings"]["data"]["editions"][0]["acquisitions"][0]["record"]["route"] == "ocr"


@pytest.mark.parametrize("selector", [
    {"kind": "edition", "namespace": "ocd", "id": "first"},
    {"kind": "work", "namespace": "ocd", "id": "../alpha"},
    {"kind": "work", "namespace": "tfr", "id": "alpha"},
    {"kind": "title", "namespace": "ocd", "id": "A work"},
    {"kind": "work", "namespace": "ocd", "id": "alpha", "work_id": "alpha"},
])
def test_invalid_request_has_named_diagnostics_and_failure_exit(root: Path, selector: dict) -> None:
    result = lookup_library_record(root, selector, connections=False)
    assert result["resolution"] == "invalid_request"
    assert lookup_exit_code(result) == 2
    assert result["diagnostics"]
    validate_record("library-record", result)


def test_negative_lookup_is_qualified_by_bound_membership(root: Path) -> None:
    result = core(root, kind="work", namespace="ocd", id="missing")
    assert result["resolution"] == "not_found"
    assert lookup_exit_code(result) == 4
    assert result["discovery"][0]["members"] == ["alpha"]


@pytest.mark.parametrize("damage", ["json", "parent", "missing", "size"])
def test_invalid_or_missing_required_authority_never_reports_clean_absence(root: Path, damage: str) -> None:
    work = root / "library/works/alpha/work.json"
    if damage == "json":
        work.write_text("{", encoding="utf-8")
    elif damage == "parent":
        record = json.loads(work.read_text())
        record["work_id"] = "other"
        write(work, record)
    elif damage == "missing":
        work.unlink()
    else:
        (root / "raw/source.txt").write_bytes(b"x")
    result = core(root)
    assert lookup_exit_code(result) == 3
    assert result["resolution"] != "not_found"
    assert result["diagnostics"]


def test_lookup_does_not_read_text_bodies_or_unrelated_records(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    master = root / "library/works/alpha/forms/en/editions/first/master.tei.xml"
    master.write_bytes(b"This body must not be read.")
    (root / "library/works/unrelated").mkdir()
    (root / "library/works/unrelated/work.json").write_text("{broken unrelated record", encoding="utf-8")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    original = Path.open

    def guarded(path: Path, *args, **kwargs):
        normalized = str(path).replace("\\", "/")
        assert "/raw/" not in normalized and not normalized.endswith(".tei.xml")
        assert "/unrelated/" not in normalized
        return original(path, *args, **kwargs)

    with monkeypatch.context() as guard:
        guard.setattr(Path, "open", guarded)
        first = core(root)
        second = core(root)
    assert lookup_exit_code(first) == 0
    assert first["fingerprint"] == second["fingerprint"]
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    readable = render_library_record(first)
    assert first["fingerprint"] in readable and "not assessed" in readable


def test_same_size_changed_source_never_becomes_freshly_verified(root: Path) -> None:
    first = core(root)
    (root / "raw/source.txt").write_bytes(b"change")
    second = core(root)
    assert lookup_exit_code(second) == 0
    assert first["fingerprint"] == second["fingerprint"]
    retained = second["sections"]["holdings"]["data"]["editions"][0]["acquisitions"][0]["retained"][0]
    assert retained["current_integrity"] == "not_assessed"


def test_storage_availability_is_part_of_the_fingerprint(root: Path, tmp_path: Path) -> None:
    external = tmp_path / "durable"
    (external / "raw").mkdir(parents=True)
    source = external / "raw/source.txt"
    source.write_bytes(b"source")
    write(root / ".ocd-storage.json", {"library_root": str(external.resolve())})
    first = core(root)
    source.unlink()
    second = core(root)
    assert first["fingerprint"] != second["fingerprint"]
    assert lookup_exit_code(first) == 0 and lookup_exit_code(second) == 3


def test_persistently_unreadable_membership_is_unavailable_not_absent(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = Path.iterdir

    def denied(path: Path):
        if str(path).replace("\\", "/").endswith("/library/works"):
            raise PermissionError("fixture denial")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", denied)
    result = core(root)
    assert result["resolution"] is None
    assert result["collection"] == "partial"
    assert result["sections"]["identity"]["health"] == "unavailable"


@pytest.mark.parametrize("repeated", [False, True])
def test_record_changes_retry_once_then_report_instability(root: Path, monkeypatch: pytest.MonkeyPatch, repeated: bool) -> None:
    original = RecordRead.stable
    calls = 0

    def changed(read: RecordRead) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1 or repeated:
            work = root / "library/works/alpha/work.json"
            work.write_bytes(work.read_bytes() + b" ")
        return original(read)

    monkeypatch.setattr(RecordRead, "stable", changed)
    result = core(root)
    assert result["execution"]["attempts"] == 2
    assert result["collection"] == ("unstable" if repeated else "complete_declared_scope")


def test_new_matching_membership_retries_negative_lookup(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = RecordRead.stable
    added = False

    def changed(read: RecordRead) -> bool:
        nonlocal added
        if not added:
            added = True
            write(root / "library/works/missing/work.json", {"schema_version": "2.0", "work_id": "missing", "title": "New identity", "evidence": ["research/evidence.md"], "textual_forms": []})
        return original(read)

    monkeypatch.setattr(RecordRead, "stable", changed)
    result = core(root, kind="work", namespace="ocd", id="missing")
    assert result["resolution"] == "found" and result["execution"]["attempts"] == 2


def test_update_routes_are_guidance_and_closed_result_rejects_extra_keys(root: Path) -> None:
    result = core(root)
    assert all(route["prerequisites"] for route in result["update_routes"])
    assert all(route["support"] in {"supported", "owning_workflow", "unsupported"} for route in result["update_routes"])
    result["silent_authority"] = True
    with pytest.raises(ValueError, match="Additional properties"):
        validate_record("library-record", result)
