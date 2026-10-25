from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

import ocd_kernel.library.identities as identities
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.acquisitions import (
    acquisition_for_edition,
    load_acquisition,
    source_sha256,
    validate_acquisition,
)
from ocd_kernel.library.identities import (
    cached_edition_lookups,
    discover_library,
    edition_by_id,
    load_editions,
    load_work,
    validate_identity_update,
)
from ocd_kernel.library.state import load_state, reconcile_state, validate_state


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "library-pipeline"
WORK_ID = "athanasius-on-the-incarnation"
FORM_ID = "athanasius-on-the-incarnation-prose"
EDITION_ID = "ccel-npnf204"
ACQUISITION_ID = "ccel-npnf204-retained-xml"


def _fixture_root(tmp_path: Path) -> Path:
    destination = tmp_path / "f"
    source = Path(f"\\\\?\\{FIXTURE_ROOT}") if os.name == "nt" else FIXTURE_ROOT
    shutil.copytree(source, destination)
    return destination


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Keep copied fixture paths short enough for Windows MAX_PATH coverage."""

    return tmp_path_factory.mktemp("p")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _work_path(root: Path) -> Path:
    return root / "library" / "works" / WORK_ID / "work.json"


def _state_path(root: Path) -> Path:
    return root / "library" / "works" / WORK_ID / "state.json"


def _acquisition_path(root: Path) -> Path:
    return (
        root
        / "library"
        / "works"
        / WORK_ID
        / "forms"
        / FORM_ID
        / "editions"
        / EDITION_ID
        / "acquisitions"
        / f"{ACQUISITION_ID}.json"
    )


def _master_path(root: Path) -> Path:
    return (
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


def _minimal_work(*, work_id: str = "work-before-source") -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "work_id": work_id,
        "title": "A work known before a source is acquired",
        "evidence": ["research/acquisition-leads.jsonl#1"],
        "textual_forms": [],
    }


def _fixture_state(root: Path) -> dict[str, object]:
    return json.loads(_state_path(root).read_text(encoding="utf-8"))


def _fixture_work(root: Path) -> dict[str, object]:
    return json.loads(_work_path(root).read_text(encoding="utf-8"))


def _fixture_acquisition(root: Path) -> dict[str, object]:
    return json.loads(_acquisition_path(root).read_text(encoding="utf-8"))


def test_promoted_fixture_uses_v2_identity_state_and_acquisition_contracts(
    tmp_path: Path,
) -> None:
    root = _fixture_root(tmp_path)

    works = discover_library(root)
    assert [work.work_id for work in works] == [WORK_ID]
    work, edition = edition_by_id(root, EDITION_ID)
    assert work.work_id == WORK_ID
    assert edition.textual_form_id == FORM_ID
    assert edition.path == _master_path(root)

    state = validate_state(_state_path(root), root=root)
    assert state["schema_version"] == "2.0"
    acquisition = validate_acquisition(_acquisition_path(root), root=root)
    assert acquisition["schema_version"] == "2.0"
    assert acquisition["edition_id"] == EDITION_ID
    assert acquisition["retained_files"]


@pytest.mark.parametrize("sibling", ["duplicate-edition", "invalid-record"])
def test_edition_lookup_snapshot_rechecks_changed_sibling_in_next_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sibling: str
) -> None:
    root = _fixture_root(tmp_path)
    original_discover = identities.discover_library
    calls = 0

    def counted_discover(path: Path) -> tuple[identities.Work, ...]:
        nonlocal calls
        calls += 1
        return original_discover(path)

    monkeypatch.setattr(identities, "discover_library", counted_discover)
    with cached_edition_lookups():
        assert edition_by_id(root, EDITION_ID)[0].work_id == WORK_ID
        assert edition_by_id(root, EDITION_ID)[0].work_id == WORK_ID
    assert calls == 1

    sibling_path = root / "library/works/sibling/work.json"
    record = _minimal_work(work_id="sibling")
    if sibling == "duplicate-edition":
        record["textual_forms"] = [{
            "textual_form_id": "sibling-form",
            "editions": [{"edition_id": EDITION_ID, "title": "Conflicting edition"}],
        }]
        expected = "edition_id is ambiguous"
    else:
        record["work_id"] = "wrong-directory"
        expected = "work sidecar identity does not match directory"
    _write_json(sibling_path, record)
    with cached_edition_lookups():
        with pytest.raises(PipelineError, match=expected):
            edition_by_id(root, EDITION_ID)
    assert calls == 2


def test_edition_lookup_snapshot_preserves_windows_root_spelling(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    extended_root = io_path(root)
    if extended_root == root:
        pytest.skip("Windows extended paths are unavailable")
    with cached_edition_lookups():
        ordinary = edition_by_id(root, EDITION_ID)[1]
        extended = edition_by_id(extended_root, EDITION_ID)[1]
    assert ordinary.path.resolve() == _master_path(root).resolve()
    assert extended.path.resolve() == io_path(_master_path(root)).resolve()


def test_work_can_be_identified_before_any_acquisition(tmp_path: Path) -> None:
    root = tmp_path / "r"
    work_path = root / "library" / "works" / "work-before-source" / "work.json"
    record = _minimal_work()
    _write_json(work_path, record)

    loaded = load_work(work_path)

    assert loaded == record
    assert "acquisitions" not in loaded
    assert "source_url" not in loaded


def test_identity_only_work_has_a_valid_empty_state(tmp_path: Path) -> None:
    root = tmp_path / "r"
    work_dir = root / "library" / "works" / "work-before-source"
    work_dir.mkdir(parents=True)
    _write_json(work_dir / "work.json", _minimal_work())
    state_path = work_dir / "state.json"
    _write_json(state_path, {
        "schema_version": "2.0",
        "work_id": "work-before-source",
        "targets": [],
    })

    assert validate_state(state_path, root=root)["targets"] == []


def test_textual_form_can_be_recorded_before_an_edition_exists(tmp_path: Path) -> None:
    root = tmp_path / "r"
    work_path = root / "library" / "works" / "form-before-edition" / "work.json"
    record = _minimal_work(work_id="form-before-edition")
    record["textual_forms"] = [
        {"textual_form_id": "known-form", "title": "Known wording", "editions": []}
    ]
    _write_json(work_path, record)

    assert load_editions(work_path) == ()


def test_multiple_forms_and_editions_are_related_by_nested_ids(tmp_path: Path) -> None:
    root = tmp_path / "r"
    work_path = root / "library" / "works" / "multi-form" / "work.json"
    record = {
        "schema_version": "2.0",
        "work_id": "multi-form",
        "title": "One intellectual work",
        "evidence": ["catalogue/item-1"],
        "textual_forms": [
            {
                "textual_form_id": "original-form",
                "title": "Original wording",
                "editions": [
                    {"edition_id": "first-edition", "title": "First edition"},
                    {"edition_id": "second-edition", "title": "Second edition"},
                ],
            },
            {
                "textual_form_id": "revised-form",
                "title": "Revised wording",
                "editions": [
                    {"edition_id": "revised-edition", "title": "Revised edition"},
                ],
            },
        ],
    }
    _write_json(work_path, record)

    editions = load_editions(work_path)

    assert [(item.textual_form_id, item.edition_id) for item in editions] == [
        ("original-form", "first-edition"),
        ("original-form", "second-edition"),
        ("revised-form", "revised-edition"),
    ]
    assert all(item.work_id == "multi-form" for item in editions)


@pytest.mark.parametrize(
    "mutation",
    ["duplicate-form", "duplicate-edition", "directory-mismatch"],
)
def test_identity_relationships_and_paths_fail_closed(
    tmp_path: Path, mutation: str
) -> None:
    root = _fixture_root(tmp_path)
    work_path = _work_path(root)
    record = _fixture_work(root)

    if mutation == "duplicate-form":
        record["textual_forms"].append(copy.deepcopy(record["textual_forms"][0]))  # type: ignore[index]
        _write_json(work_path, record)
        with pytest.raises(PipelineError):
            load_editions(work_path)
        return

    if mutation == "duplicate-edition":
        second_form = {
            "textual_form_id": "second-form",
            "title": "Another wording",
            "editions": [copy.deepcopy(record["textual_forms"][0]["editions"][0])],  # type: ignore[index]
        }
        record["textual_forms"].append(second_form)  # type: ignore[index]
        _write_json(work_path, record)
        with pytest.raises(PipelineError):
            load_editions(work_path)
        return

    mismatched = root / "library" / "works" / "different-directory" / "work.json"
    mismatched.parent.mkdir(parents=True, exist_ok=True)
    _write_json(mismatched, record)
    shutil.rmtree(root / "library" / "works" / WORK_ID)
    with pytest.raises(PipelineError):
        discover_library(root)


@pytest.mark.parametrize("mutation", ["orphan-form", "missing-declared", "wrong-owner"])
def test_discovery_rejects_orphan_or_contradictory_acquisitions(
    tmp_path: Path, mutation: str
) -> None:
    root = _fixture_root(tmp_path)
    work = _fixture_work(root)
    edition = work["textual_forms"][0]["editions"][0]
    if mutation == "orphan-form":
        work["textual_forms"][0]["textual_form_id"] = "another-form"
    elif mutation == "missing-declared":
        edition["acquisition_ids"] = ["missing-acquisition"]
    else:
        work["textual_forms"][0]["editions"].append({
            "edition_id": "another-edition",
            "title": "Another edition",
            "acquisition_ids": [ACQUISITION_ID],
        })
    _write_json(_work_path(root), work)
    with pytest.raises(PipelineError):
        discover_library(root)


@pytest.mark.parametrize("mutation", ["short-path", "wrong-work", "wrong-form"])
def test_acquisition_validates_its_full_parent_identity(
    tmp_path: Path, mutation: str
) -> None:
    root = _fixture_root(tmp_path)
    path = _acquisition_path(root)
    if mutation == "short-path":
        short_path = path.parent.parent / f"{ACQUISITION_ID}.json"
        _write_json(short_path, _fixture_acquisition(root))
        path = short_path
    else:
        work = _fixture_work(root)
        if mutation == "wrong-work":
            work["work_id"] = "another-work"
        else:
            work["textual_forms"][0]["textual_form_id"] = "another-form"
        _write_json(_work_path(root), work)
    with pytest.raises(PipelineError):
        validate_acquisition(path, root=root)


def test_state_accepts_root_relative_master_and_exact_retained_evidence(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    state = _fixture_state(root)
    state["targets"][0]["evidence"] = [_master_path(root).relative_to(root).as_posix()]
    state["targets"].append({
        "target_id": ACQUISITION_ID,
        "target_type": "acquisition",
        "stage": "acquired",
        "updated_at": "2026-09-06T00:00:00Z",
        "evidence": [_fixture_acquisition(root)["retained_files"][0]["path"]],
    })
    _write_json(_state_path(root), state)
    assert len(validate_state(_state_path(root), root=root)["targets"]) == 2


def test_state_accepts_configured_external_raw_evidence(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    state = _fixture_state(root)
    acquisition = _fixture_acquisition(root)
    retained = acquisition["retained_files"][0]
    source_path = root / retained["path"]
    external_root = tmp_path / "durable-library"
    external_source = external_root / retained["path"]
    external_source.parent.mkdir(parents=True)
    shutil.copy2(source_path, external_source)
    (root / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(external_root)}), encoding="utf-8"
    )
    state["targets"].append(
        {
            "target_id": ACQUISITION_ID,
            "target_type": "acquisition",
            "stage": "acquired",
            "updated_at": "2026-09-28T00:00:00Z",
            "evidence": [retained["path"]],
        }
    )
    _write_json(_state_path(root), state)

    validated = validate_state(_state_path(root), root=root)

    assert len(validated["targets"]) == 2


@pytest.mark.parametrize("stage", ["accepted", "review"])
def test_generated_state_exposes_contradictions_before_stage_exclusion(
    tmp_path: Path, stage: str
) -> None:
    root = _fixture_root(tmp_path)
    state = _fixture_state(root)
    state["targets"][0]["stage"] = stage
    state["targets"][0]["evidence"].append("missing-evidence.json")
    _write_json(_state_path(root), state)
    result = reconcile_state(
        root, work_id=WORK_ID, edition_id=EDITION_ID, master_path=_master_path(root)
    )
    assert result["status"] == "failed"
    assert "missing-evidence.json" in " ".join(result["reasons"])


@pytest.mark.parametrize("declaration", [[], [ACQUISITION_ID], ["missing-acquisition"]])
def test_explicit_acquisition_list_is_exact_in_discovery_and_state(
    tmp_path: Path, declaration: list[str]
) -> None:
    root = _fixture_root(tmp_path)
    work = _fixture_work(root)
    work["textual_forms"][0]["editions"][0]["acquisition_ids"] = declaration
    _write_json(_work_path(root), work)
    if declaration == [ACQUISITION_ID]:
        second = _fixture_acquisition(root)
        second["acquisition_id"] = "unlisted"
        _write_json(_acquisition_path(root).with_name("unlisted.json"), second)
    for validate in (lambda: discover_library(root), lambda: validate_state(_state_path(root), root=root)):
        with pytest.raises(PipelineError):
            validate()


def test_unknown_identity_facts_remain_absent(tmp_path: Path) -> None:
    path = tmp_path / "work.json"
    record = _minimal_work()
    _write_json(path, record)

    loaded = load_work(path)

    assert "creator" not in loaded
    assert "creators" not in loaded
    assert "publication_date" not in loaded
    assert "rights" not in loaded


def test_identity_update_allows_correcting_a_readable_title(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    previous = _fixture_work(root)
    current = copy.deepcopy(previous)
    current["title"] = "Corrected source-attested title"

    assert validate_identity_update(previous, current) is None


@pytest.mark.parametrize("identity_path", [
    ("work_id",),
    ("textual_forms", 0, "textual_form_id"),
    ("textual_forms", 0, "editions", 0, "edition_id"),
    ("textual_forms", 0, "editions", 0, "__reparent__"),
])
def test_identity_update_rejects_immutable_id_changes(
    tmp_path: Path, identity_path: tuple[object, ...]
) -> None:
    root = _fixture_root(tmp_path)
    previous = _fixture_work(root)
    current = copy.deepcopy(previous)
    if identity_path[-1] == "__reparent__":
        forms = current["textual_forms"]  # type: ignore[index]
        edition = forms[0]["editions"].pop(0)
        forms.append(
            {
                "textual_form_id": "second-form",
                "title": "Another textual form",
                "editions": [edition],
            }
        )
    else:
        target: object = current
        for part in identity_path[:-1]:
            target = target[part]  # type: ignore[index]
        target[identity_path[-1]] = "changed-id"  # type: ignore[index]

    with pytest.raises(PipelineError):
        validate_identity_update(previous, current)


@pytest.mark.parametrize(
    "stage",
    ["planned", "acquired", "reconstructing", "review", "accepted", "blocked", "abandoned"],
)
def test_state_accepts_only_the_short_stage_vocabulary(
    tmp_path: Path, stage: str
) -> None:
    root = _fixture_root(tmp_path)
    state = _fixture_state(root)
    state["targets"][0]["stage"] = stage  # type: ignore[index]
    _write_json(_state_path(root), state)

    loaded = load_state(_state_path(root))

    assert loaded["targets"][0]["stage"] == stage  # type: ignore[index]


@pytest.mark.parametrize("stage", ["draft", "published", "unknown"])
def test_state_rejects_unknown_stage(tmp_path: Path, stage: str) -> None:
    root = _fixture_root(tmp_path)
    state = _fixture_state(root)
    state["targets"][0]["stage"] = stage  # type: ignore[index]
    _write_json(_state_path(root), state)

    with pytest.raises(PipelineError):
        load_state(_state_path(root))


@pytest.mark.parametrize("mutation", ["missing", "local-time", "invalid"])
def test_state_requires_an_utc_updated_at(tmp_path: Path, mutation: str) -> None:
    root = _fixture_root(tmp_path)
    state = _fixture_state(root)
    target = state["targets"][0]  # type: ignore[index]
    if mutation == "missing":
        target.pop("updated_at")
    elif mutation == "local-time":
        target["updated_at"] = "2026-09-06T00:00:00"
    else:
        target["updated_at"] = "not-a-timestamp"
    _write_json(_state_path(root), state)

    with pytest.raises(PipelineError):
        load_state(_state_path(root))


@pytest.mark.parametrize("key", ["title", "creators", "rights"])
def test_state_does_not_repeat_stable_or_edition_metadata(
    tmp_path: Path, key: str
) -> None:
    root = _fixture_root(tmp_path)
    state = _fixture_state(root)
    state[key] = "metadata copied into the wrong authority"
    _write_json(_state_path(root), state)

    with pytest.raises(PipelineError):
        load_state(_state_path(root))


def test_validate_state_binds_the_target_to_the_fixture_master(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)

    result = validate_state(_state_path(root), root=root)

    assert result["work_id"] == WORK_ID
    assert result["targets"]
    assert result["targets"][0]["target_id"] == EDITION_ID


@pytest.mark.parametrize(
    "mutation", ["accepted-unrelated", "missing-master", "wrong-work"]
)
def test_validate_state_rejects_contradictory_physical_evidence(
    tmp_path: Path, mutation: str
) -> None:
    root = _fixture_root(tmp_path)
    state = _fixture_state(root)
    target = state["targets"][0]  # type: ignore[index]
    if mutation == "accepted-unrelated":
        target["evidence"] = [
            "retained/npnf204.vii.ii.i.thml.xml"
        ]
    elif mutation == "missing-master":
        _master_path(root).unlink()
    else:
        state["work_id"] = "different-work"
    _write_json(_state_path(root), state)

    with pytest.raises(PipelineError):
        validate_state(_state_path(root), root=root)


def test_state_can_track_an_acquisition_target_and_rejects_a_dangling_target(
    tmp_path: Path,
) -> None:
    root = _fixture_root(tmp_path)
    state = _fixture_state(root)
    acquisition_target = {
        "target_id": ACQUISITION_ID,
        "target_type": "acquisition",
        "stage": "acquired",
        "updated_at": "2026-09-06T00:00:00Z",
        "evidence": [
            "forms/athanasius-on-the-incarnation-prose/editions/ccel-npnf204/"
            "acquisitions/ccel-npnf204-retained-xml.json"
        ],
    }
    state["targets"].append(acquisition_target)  # type: ignore[index]
    _write_json(_state_path(root), state)

    loaded = validate_state(_state_path(root), root=root)

    assert any(
        target["target_id"] == ACQUISITION_ID  # type: ignore[index]
        for target in loaded["targets"]  # type: ignore[index]
    )

    state["targets"][-1]["target_id"] = "missing-acquisition"  # type: ignore[index]
    _write_json(_state_path(root), state)
    with pytest.raises(PipelineError):
        validate_state(_state_path(root), root=root)


def test_acquired_target_cannot_claim_arbitrary_existing_evidence(
    tmp_path: Path,
) -> None:
    root = _fixture_root(tmp_path)
    state = _fixture_state(root)
    state["targets"].append(  # type: ignore[index]
        {
            "target_id": ACQUISITION_ID,
            "target_type": "acquisition",
            "stage": "acquired",
            "updated_at": "2026-09-06T00:00:00Z",
            "evidence": ["work.json"],
        }
    )
    _write_json(_state_path(root), state)

    with pytest.raises(PipelineError):
        validate_state(_state_path(root), root=root)


def test_acquisition_binds_exact_retained_path_bytes_and_hash(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    record = validate_acquisition(_acquisition_path(root), root=root)
    retained = record["retained_files"][0]  # type: ignore[index]
    retained_path = root / retained["path"]  # type: ignore[index]

    assert retained_path.is_file()
    assert retained_path.stat().st_size == retained["bytes"]
    assert hashlib.sha256(retained_path.read_bytes()).hexdigest() == retained["sha256"]
    assert isinstance(record["source_scope"], str)
    assert isinstance(record["source_path"], str)
    assert isinstance(record["source_bytes"], int)
    assert isinstance(record["source_sha256"], str)


def test_multiple_retained_members_remain_valid_but_source_hash_inference_is_ambiguous(
    tmp_path: Path,
) -> None:
    root = _fixture_root(tmp_path)
    path = _acquisition_path(root)
    record = _fixture_acquisition(root)
    second_path = root / "retained" / "second-member.xml"
    second_bytes = b"second retained member\n"
    second_path.write_bytes(second_bytes)
    record["retained_files"].append(  # type: ignore[index]
        {
            "path": "retained/second-member.xml",
            "sha256": hashlib.sha256(second_bytes).hexdigest(),
            "bytes": len(second_bytes),
            "media_type": "text/plain",
        }
    )
    for key in ("source_path", "source_bytes", "source_sha256", "source_scope"):
        record.pop(key, None)
    _write_json(path, record)

    loaded = validate_acquisition(path, root=root)

    assert len(loaded["retained_files"]) == 2  # type: ignore[arg-type]
    with pytest.raises(PipelineError):
        source_sha256(loaded, context=str(path))


@pytest.mark.parametrize("mutation", ["bytes", "hash", "missing"])
def test_acquisition_rejects_changed_retained_file_evidence(
    tmp_path: Path, mutation: str
) -> None:
    root = _fixture_root(tmp_path)
    path = _acquisition_path(root)
    record = _fixture_acquisition(root)
    retained = record["retained_files"][0]  # type: ignore[index]
    retained_path = root / retained["path"]  # type: ignore[index]
    if mutation == "bytes":
        retained["bytes"] += 1  # type: ignore[operator]
    elif mutation == "hash":
        retained["sha256"] = "0" * 64  # type: ignore[index]
    else:
        retained["path"] = "retained/missing.xml"  # type: ignore[index]
    _write_json(path, record)

    with pytest.raises(PipelineError):
        validate_acquisition(path, root=root)


@pytest.mark.parametrize("extension", [".zip", ".ZIP"])
def test_acquisition_rejects_zip_as_source_path(tmp_path: Path, extension: str) -> None:
    root = _fixture_root(tmp_path)
    path = _acquisition_path(root)
    record = _fixture_acquisition(root)
    record["source_path"] = f"retained/package{extension}"
    _write_json(path, record)

    with pytest.raises(PipelineError, match="source_path cannot identify a ZIP package"):
        load_acquisition(path)


def test_acquisition_allows_zip_as_retained_package(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path = _acquisition_path(root)
    record = _fixture_acquisition(root)
    package_path = root / "retained" / "package.zip"
    package_bytes = b"retained acquisition package"
    package_path.write_bytes(package_bytes)
    record["retained_files"].append({  # type: ignore[index]
        "path": "retained/package.zip",
        "sha256": hashlib.sha256(package_bytes).hexdigest(),
        "bytes": len(package_bytes),
        "media_type": "application/zip",
        "scope": "Acquisition package; the existing source_path remains the extracted text.",
    })
    _write_json(path, record)

    loaded = validate_acquisition(path, root=root)
    assert loaded["source_path"] != "retained/package.zip"
    assert len(loaded["retained_files"]) == 2  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field,invalid_path",
    [
        ("source_path", "../outside.xml"),
        ("source_path", "C:relative.xml"),
        ("retained_files", "../outside.xml"),
        ("retained_files", "C:relative.xml"),
    ],
)
def test_acquisition_source_and_retained_paths_cannot_escape_root(
    tmp_path: Path, field: str, invalid_path: str
) -> None:
    root = _fixture_root(tmp_path)
    path = _acquisition_path(root)
    record = _fixture_acquisition(root)
    if field == "source_path":
        record[field] = invalid_path
    else:
        record["retained_files"][0]["path"] = invalid_path  # type: ignore[index]
    _write_json(path, record)

    with pytest.raises(PipelineError):
        load_acquisition(path)


@pytest.mark.parametrize("key", ["title", "creators", "edition_title"])
def test_acquisition_rejects_bibliographic_metadata_in_evidence_sidecar(
    tmp_path: Path, key: str
) -> None:
    root = _fixture_root(tmp_path)
    path = _acquisition_path(root)
    record = _fixture_acquisition(root)
    record[key] = "metadata copied into the wrong authority"
    _write_json(path, record)

    with pytest.raises(PipelineError):
        load_acquisition(path)


def test_multiple_acquisitions_require_explicit_selection(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path = _acquisition_path(root)
    first = _fixture_acquisition(root)
    second = copy.deepcopy(first)
    second["acquisition_id"] = "ccel-npnf204-retained-copy"  # type: ignore[index]
    second_path = path.with_name("ccel-npnf204-retained-copy.json")
    _write_json(second_path, second)

    first_path, first_loaded = acquisition_for_edition(
        root, WORK_ID, EDITION_ID, ACQUISITION_ID
    )
    second_path_found, second_loaded = acquisition_for_edition(
        root, WORK_ID, EDITION_ID, "ccel-npnf204-retained-copy"
    )

    assert first_path == path
    assert first_loaded["acquisition_id"] == ACQUISITION_ID
    assert second_path_found == second_path
    assert second_loaded["acquisition_id"] == "ccel-npnf204-retained-copy"
    with pytest.raises(PipelineError):
        acquisition_for_edition(root, WORK_ID, EDITION_ID)


@pytest.mark.parametrize("mutation", ["edition", "filename"])
def test_acquisition_relationships_are_checked(
    tmp_path: Path, mutation: str
) -> None:
    root = _fixture_root(tmp_path)
    path = _acquisition_path(root)
    record = _fixture_acquisition(root)
    if mutation == "edition":
        record["edition_id"] = "other-edition"
    else:
        record["acquisition_id"] = "other-acquisition"
    _write_json(path, record)

    with pytest.raises(PipelineError):
        acquisition_for_edition(root, WORK_ID, EDITION_ID, ACQUISITION_ID)


def test_unknown_access_date_is_absent_rather_than_invented(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    path = _acquisition_path(root)
    record = _fixture_acquisition(root)
    record.pop("accessed_at", None)
    _write_json(path, record)

    loaded = load_acquisition(path)

    assert "accessed_at" not in loaded


@pytest.mark.parametrize(
    "location",
    ["work", "form", "edition", "state-target", "retained-file"],
)
def test_contracts_reject_unknown_nested_properties(tmp_path: Path, location: str) -> None:
    root = _fixture_root(tmp_path)
    if location in {"work", "form", "edition"}:
        path = _work_path(root)
        record = _fixture_work(root)
        if location == "work":
            record["unmodeled_metadata"] = "reject"  # type: ignore[index]
        elif location == "form":
            record["textual_forms"][0]["unmodeled_metadata"] = "reject"  # type: ignore[index]
        else:
            record["textual_forms"][0]["editions"][0]["unmodeled_metadata"] = "reject"  # type: ignore[index]
        _write_json(path, record)
        with pytest.raises(PipelineError):
            load_work(path)
        return

    if location == "state-target":
        path = _state_path(root)
        record = _fixture_state(root)
        record["targets"][0]["unmodeled_metadata"] = "reject"  # type: ignore[index]
        _write_json(path, record)
        with pytest.raises(PipelineError):
            load_state(path)
        return

    path = _acquisition_path(root)
    record = _fixture_acquisition(root)
    record["retained_files"][0]["unmodeled_metadata"] = "reject"  # type: ignore[index]
    _write_json(path, record)
    with pytest.raises(PipelineError):
        load_acquisition(path)


@pytest.mark.parametrize(
    "record_type,field,value",
    [
        ("work", "schema_version", "1.0"),
        ("work", "title", None),
        ("state", "schema_version", "1.0"),
        ("state", "work_id", None),
        ("acquisition", "schema_version", "1.0"),
        ("acquisition", "accessed_at", "unknown"),
    ],
)
def test_contracts_reject_bad_versions_nulls_and_unknown_dates(
    tmp_path: Path, record_type: str, field: str, value: object
) -> None:
    root = _fixture_root(tmp_path)
    if record_type == "work":
        path = _work_path(root)
        record = _fixture_work(root)
        record[field] = value
        _write_json(path, record)
        with pytest.raises(PipelineError):
            load_work(path)
    elif record_type == "state":
        path = _state_path(root)
        record = _fixture_state(root)
        record[field] = value
        _write_json(path, record)
        with pytest.raises(PipelineError):
            load_state(path)
    else:
        path = _acquisition_path(root)
        record = _fixture_acquisition(root)
        record[field] = value
        _write_json(path, record)
        with pytest.raises(PipelineError):
            load_acquisition(path)
