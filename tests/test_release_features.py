from __future__ import annotations

import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.features import configuration_features
from ocd_kernel.release.public_allowlist import render_dataset_card


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("hf")


def test_complete_schema_preserves_late_nested_fields_in_batched_reader(tmp_path: Path, monkeypatch):
    datasets = pytest.importorskip("datasets")
    monkeypatch.setenv("HF_DATASETS_OFFLINE", "1")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    rows = [
        {"locator": {"unit": 1}, "structure": [{"kind": "text", "text": "early"}]},
        {"locator": {"unit": 1, "document": 2}, "structure": [
            {"kind": "paragraph", "children": [{"kind": "text", "text": "later"}]}]},
    ]
    path = tmp_path / "public/data/prose/train.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    features = configuration_features(rows)
    assert features == configuration_features(reversed(rows))
    (tmp_path / "public/README.md").write_text(render_dataset_card([
        {"category": "prose", "path": "public/data/prose/train.jsonl", "row_count": 2,
         "features": features}]), encoding="utf-8")
    loaded = datasets.load_dataset(str(tmp_path / "public"), name="prose", split="train",
                                   chunksize=64, cache_dir=str(tmp_path / "cache"))
    assert loaded[0]["locator"] == {"document": None, "unit": 1}
    assert loaded[1]["locator"] == rows[1]["locator"]
    assert loaded[0]["structure"][0]["text"] == "early"
    assert loaded[1]["structure"][0]["children"][0]["text"] == "later"


def test_incompatible_types_fail_without_coercion():
    with pytest.raises(PipelineError, match="incompatible"):
        configuration_features([{"value": 12}, {"value": "12"}])


def test_typed_directory_reader_preserves_dates_empty_elements_and_late_fields(tmp_path, monkeypatch):
    import hashlib
    import datasets
    from ocd_kernel.release.typed_rows import encode_rows, compare_rows

    monkeypatch.setenv("HF_DATASETS_OFFLINE", "1")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    rows = [
        {"text": "2019-08-26T21:08:27Z", "structure": [{"attributes": {}, "content": []}]},
        {"text": "2019-08-26", "structure": [{"attributes": {}, "content": [
            {"when": "2019-08-26T21:08:27Z", "number": "001"}]}], "document": 2},
    ]
    features = configuration_features(rows)
    public = tmp_path / "public"
    path = public / "data/poetry/train.arrow"
    path.parent.mkdir(parents=True)
    content = encode_rows(rows, features)
    path.write_bytes(content)
    config = {"category": "poetry", "path": "public/data/poetry/train.jsonl",
              "row_count": len(rows), "features": features,
              "typed_companion": {"path": "public/data/poetry/train.arrow",
                                  "sha256": hashlib.sha256(content).hexdigest()}}
    (path.with_suffix(".jsonl")).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    (public / "README.md").write_text(render_dataset_card([config]), encoding="utf-8")
    for streaming in (False, True):
        loaded = datasets.load_dataset(str(public), name="poetry", split="train",
                                       streaming=streaming, cache_dir=str(tmp_path / "cache"))
        compare_rows(rows, list(loaded))


@pytest.mark.parametrize("mutation", ["date", "omission", "reorder", "invented", "metadata", "trailing"])
def test_typed_companion_rejects_value_changes_and_hidden_payloads(mutation):
    import pyarrow as pa
    from ocd_kernel.release.typed_rows import encode_rows, check_rows, arrow_schema

    rows = [{"text": "2019-08-26T21:08:27Z"}, {"text": "second"}]
    features = configuration_features(rows)
    changed = [dict(row) for row in rows]
    if mutation == "date":
        changed[0]["text"] = "2019-08-26 21:08:27"
    elif mutation == "omission":
        changed.pop()
    elif mutation == "reorder":
        changed.reverse()
    elif mutation == "invented":
        changed[0]["extra"] = "invented"
    if mutation == "metadata":
        schema = arrow_schema(features).with_metadata({b"private": b"hidden"})
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, schema) as writer:
            writer.write_table(pa.Table.from_pylist(rows, schema=schema))
        content = sink.getvalue().to_pybytes()
    else:
        content = encode_rows(changed, configuration_features(changed))
    if mutation == "trailing":
        content += b"hidden payload"
    with pytest.raises(PipelineError):
        check_rows(content, rows, features)


def test_changed_features_rejected_even_with_matching_card(tmp_path: Path):
    from tests.test_release_assembly_v2 import _build_single, _read_json, _write_json
    from ocd_kernel.release.public_allowlist import check_public_boundary

    _root, release, _selection, _acceptance = _build_single(tmp_path)
    report = _read_json(release / "internal/release-report.json")
    report["configurations"][0]["features"] = [{"name": "invented", "dtype": "string"}]
    _write_json(release / "internal/release-report.json", report)
    (release / "public/README.md").write_text(render_dataset_card(report["configurations"]), encoding="utf-8", newline="\n")
    assert "public configuration features differ from complete row schema" in check_public_boundary(release, report)


def test_complete_reader_verification_uses_actual_standard_loader(tmp_path):
    from tests.test_release_assembly_v2 import _build_single
    from build.tools.check_release_reader import check_reader

    root, release, selection, _acceptance = _build_single(tmp_path)
    result = check_reader(root, release, selection)
    assert result["status"] == "pass"
    assert result["configurations"][0]["normal_and_streaming"] == "pass"
    assert result["publication_performed"] is False


def test_rebound_typed_digest_does_not_hide_changed_source_values(tmp_path):
    import hashlib
    from tests.test_release_assembly_v2 import _build_single, _read_json
    from ocd_kernel.release.public_allowlist import check_public_boundary
    from ocd_kernel.release.typed_rows import encode_rows

    _root, release, _selection, _acceptance = _build_single(tmp_path)
    report = _read_json(release / "internal/release-report.json")
    config = report["configurations"][0]
    rows = [json.loads(line) for line in (release / config["path"]).read_text(encoding="utf-8").splitlines()]
    rows[0]["text"] += " invented"
    content = encode_rows(rows, config["features"])
    (release / config["typed_companion"]["path"]).write_bytes(content)
    config["typed_companion"]["sha256"] = hashlib.sha256(content).hexdigest()
    errors = check_public_boundary(release, report)
    assert any("changed value" in error for error in errors)
