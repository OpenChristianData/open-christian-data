"""The scoped reader command must not claim independent release verification."""

from __future__ import annotations

import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from build.tools import check_release_reader as reader
from ocd_kernel.library._common import PipelineError


@pytest.fixture
def package(tmp_path, monkeypatch):
    release = tmp_path / "release"
    public = release / "public"
    source = public / "data/prose/train.jsonl"
    source.parent.mkdir(parents=True)
    content = b'{"text":"hello"}\n'
    source.write_bytes(content)
    typed = source.with_suffix(".arrow")
    typed.write_bytes(b"typed fixture")
    (public / "README.md").write_text("fixture card\n", encoding="utf-8")
    report = {"configurations": [{
        "category": "prose", "path": "public/data/prose/train.jsonl",
        "row_count": 1, "sha256": hashlib.sha256(content).hexdigest(),
        "features": [], "typed_companion": {
            "path": "public/data/prose/train.arrow",
            "sha256": hashlib.sha256(typed.read_bytes()).hexdigest(),
        },
    }]}
    report_path = release / "internal/release-report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setitem(sys.modules, "datasets", SimpleNamespace(
        __version__="fixture", load_dataset=lambda *args, **kwargs: [{"text": "hello"}]))
    monkeypatch.setitem(sys.modules, "pyarrow", SimpleNamespace(__version__="fixture"))
    return tmp_path, release, report, report_path, source, typed


def test_reader_only_is_scoped_and_default_still_verifies(package, monkeypatch):
    root, release, _report, _report_path, _source, _typed = package
    calls = []

    def full_verification(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "pass", "errors": []}

    monkeypatch.setattr(reader, "verify_release_v2", full_verification)
    scoped = reader.check_reader(root, release, {}, reader_only=True)
    assert scoped["status"] == "reader-only-pass"
    assert scoped["scope"] == "reader-values-only"
    assert scoped["verification"]["status"] == "not-run"
    assert scoped["configurations"] == [{"category": "prose", "rows": 1,
        "normal_and_streaming": "pass", "all_original_values_and_order_preserved": True}]
    assert not calls

    full = reader.check_reader(root, release, {})
    assert full["status"] == "pass" and full["verification"] == {"status": "pass", "errors": []}
    assert len(calls) == 1
    monkeypatch.setattr(reader, "verify_release_v2", lambda *args, **kwargs: {
        "status": "fail", "errors": ["full verification rejected package"]})
    with pytest.raises(PipelineError, match="full verification rejected package"):
        reader.check_reader(root, release, {})


def test_reader_only_rejects_report_paths_counts_hashes_and_public_extras(package):
    root, release, report, report_path, source, typed = package
    for key, changed in (("path", "../private.jsonl"), ("row_count", 2),
                         ("sha256", "0" * 64)):
        old = report["configurations"][0][key]
        report["configurations"][0][key] = changed
        report_path.write_text(json.dumps(report), encoding="utf-8")
        with pytest.raises(PipelineError):
            reader.check_reader(root, release, {}, reader_only=True)
        report["configurations"][0][key] = old
    report_path.write_text(json.dumps(report), encoding="utf-8")
    typed.write_bytes(b"changed")
    with pytest.raises(PipelineError, match="typed companion changed"):
        reader.check_reader(root, release, {}, reader_only=True)
    typed.write_bytes(b"typed fixture")
    extra = release / "public/unlisted.txt"
    extra.write_text("extra", encoding="utf-8")
    with pytest.raises(PipelineError, match="public file set differs"):
        reader.check_reader(root, release, {}, reader_only=True)
    extra.unlink()
    source.write_bytes(b'{"text":"changed"}\n')
    with pytest.raises(PipelineError, match="public JSONL changed"):
        reader.check_reader(root, release, {}, reader_only=True)


def test_reader_only_cli_reports_scoped_pass(package, monkeypatch, tmp_path):
    root, release, _report, _report_path, _source, _typed = package
    monkeypatch.setattr(reader, "load_release_selection", lambda _path: {})
    monkeypatch.setattr(reader, "verify_release_v2", lambda *args, **kwargs: (
        pytest.fail("reader-only CLI invoked full verification")))
    output = tmp_path / "reader-only-proof.json"
    assert reader.main(["--root", str(root), "--release", str(release),
                        "--selection", str(tmp_path / "selection.json"),
                        "--output", str(output), "--reader-only"]) == 0
    proof = json.loads(output.read_bytes())
    assert proof["status"] == "reader-only-pass"
    assert proof["scope"] == "reader-values-only"
    assert proof["verification"]["status"] == "not-run"


def test_reader_caches_are_category_scoped_and_payload_reads_are_streamed(package, monkeypatch):
    from pathlib import Path

    root, release, report, report_path, source, typed = package
    second = release / "public/data/poetry/train.jsonl"
    second.parent.mkdir(parents=True)
    second.write_bytes(source.read_bytes())
    second.with_suffix(".arrow").write_bytes(typed.read_bytes())
    config = dict(report["configurations"][0], category="poetry", path="public/data/poetry/train.jsonl")
    config["typed_companion"] = dict(config["typed_companion"], path="public/data/poetry/train.arrow")
    report["configurations"].append(config)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    temp_root = root / "reader-temp"
    caches = {}

    def load_dataset(*args, **kwargs):
        category, cache = kwargs["name"], Path(kwargs["cache_dir"])
        assert cache.parent == temp_root and cache.is_dir()
        if category not in caches:
            assert all(not prior.exists() for prior in caches.values())
            caches[category] = cache
        assert caches[category] == cache
        (cache / "cached-payload").write_text("fixture", encoding="utf-8")
        return [{"text": "hello"}]

    monkeypatch.setattr(sys.modules["datasets"], "load_dataset", load_dataset)
    original_read_bytes = Path.read_bytes

    def bounded_reads(path):
        assert path.suffix not in {".jsonl", ".arrow"}, "whole payload read"
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", bounded_reads)
    proof = reader.check_reader(root, release, {}, reader_only=True, temp_root=temp_root)
    assert proof["status"] == "reader-only-pass"
    assert len(caches) == 2 and all(not cache.exists() for cache in caches.values())
