"""Streaming release serialization preserves canonical bytes and trust checks."""

import hashlib

import pyarrow as pa
import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.release.features import configuration_features
from ocd_kernel.release.streaming import file_sha256, iter_jsonl
from ocd_kernel.release.typed_rows import (
    BOUNDED_ENCODING, LEGACY_ENCODING, check_rows_file, encode_rows, write_rows,
)


def test_legacy_streaming_matches_historical_full_table_bytes(tmp_path):
    rows = [{"text": f"2019-08-26T21:08:27Z {index}", "nested": [{"x": index}]}
            for index in range(2201)]
    rows[-1]["late"] = "last"
    features = configuration_features(rows)
    path = tmp_path / "rows.arrow"
    write_rows(path, iter(rows), features, encoding=LEGACY_ENCODING)
    assert path.read_bytes() == encode_rows(rows, features)
    check_rows_file(path, iter(rows), features)


def test_bounded_batches_preserve_values_and_exact_canonical_check(tmp_path, monkeypatch):
    from ocd_kernel.release import typed_rows

    monkeypatch.setattr(typed_rows, "_BATCH_BYTES", 40)
    rows = [{"text": "0123456789", "nested": {"n": index}} for index in range(4)]
    features = configuration_features(rows)
    path = tmp_path / "rows.arrow"
    write_rows(path, iter(rows), features)
    with path.open("rb") as source:
        with pa.ipc.open_stream(source) as reader:
            batches = list(reader)
    assert len(batches) == 4
    assert [row for batch in batches for row in batch.to_pylist()] == rows
    check_rows_file(path, iter(rows), features, encoding=BOUNDED_ENCODING)
    with pytest.raises(PipelineError, match="changed value"):
        check_rows_file(path, iter(reversed(rows)), features, encoding=BOUNDED_ENCODING)
    path.write_bytes(path.read_bytes() + b"private payload")
    with pytest.raises(PipelineError, match="not canonical"):
        check_rows_file(path, iter(rows), features, encoding=BOUNDED_ENCODING)


def test_bounded_rows_reject_oversize_and_unknown_encoder(tmp_path, monkeypatch):
    from ocd_kernel.release import typed_rows

    monkeypatch.setattr(typed_rows, "_MAX_ROW_BYTES", 32)
    rows = [{"text": "x" * 33}]
    features = configuration_features(rows)
    with pytest.raises(PipelineError, match="typed row exceeds"):
        write_rows(tmp_path / "large.arrow", iter(rows), features)
    with pytest.raises(PipelineError, match="unsupported typed encoding"):
        write_rows(tmp_path / "invalid.arrow", iter(rows), features, encoding="unknown")


@pytest.mark.parametrize("content, message", [
    (b'{"x":1}', "not canonical JSONL"),
    (b'{"x":1}\r\n', "not canonical JSONL"),
    (b'{"x":1,"x":2}\n', "duplicate public row key"),
    (b'[]\n', "object rows"),
    (b'{ "x": 1 }\n', "not canonical JSONL"),
    (b'\n', "Expecting value"),
])
def test_jsonl_rejects_invalid_framing_keys_and_values(tmp_path, content, message):
    path = tmp_path / "rows.jsonl"
    path.write_bytes(content)
    with pytest.raises((PipelineError, ValueError), match=message):
        list(iter_jsonl(path, canonical=True))


def test_jsonl_literal_separators_remain_one_record_and_hashes_are_chunked(tmp_path, monkeypatch):
    from pathlib import Path

    rows = [{"text": "NEL\u0085line\u2028paragraph\u2029"}, {"text": "last"}]
    content = b"".join(canonical_bytes(row) for row in rows)
    path = tmp_path / "rows.jsonl"
    path.write_bytes(content)
    monkeypatch.setattr(Path, "read_bytes", lambda _path: pytest.fail("whole file read"))
    assert list(iter_jsonl(path, canonical=True)) == rows
    assert file_sha256(path) == hashlib.sha256(content).hexdigest()


def test_jsonl_rejects_oversized_line_before_parsing(tmp_path, monkeypatch):
    from ocd_kernel.release import streaming

    monkeypatch.setattr(streaming, "MAX_JSONL_ROW_BYTES", 32)
    path = tmp_path / "oversized.jsonl"
    path.write_bytes(canonical_bytes({"text": "x" * 33}))
    with pytest.raises(PipelineError, match="JSONL row exceeds"):
        list(iter_jsonl(path, canonical=True))


def test_preview_requires_ready_evidence_for_manifest_build(tmp_path, monkeypatch):
    from ocd_kernel.release import build_state, public_allowlist, verify

    manifest = tmp_path / build_state.MANIFEST
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b"{}\n")
    monkeypatch.setattr(verify, "verify_release_v2", lambda *args, **kwargs: {"status": "pass", "errors": []})
    calls = []

    def reject_unready(directory):
        calls.append(directory)
        raise PipelineError("candidate is not ready")

    monkeypatch.setattr(build_state, "check_ready", reject_unready)
    result = public_allowlist.preview_release(tmp_path, tmp_path, selection={})
    assert result["status"] == "fail" and "candidate is not ready" in result["errors"][0]
    assert calls == [tmp_path]
