"""Focused tests for the read-only source-metadata benchmark CLI."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from build.lib import source_metadata as sm
from build.lib import source_metadata_evidence
from build.tools import benchmark_source_metadata as benchmark_tool


_AUTHORITY_ROOTS = (
    ".git",
    "raw",
    "sources",
    "metadata",
    "data",
    "ir",
    "library",
    "schemas",
    "reports",
    "exports",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    packet = _canonical({"title": "Synthetic title"})
    packet_path = tmp_path / "evidence.json"
    packet_path.write_bytes(packet)

    xml = b'<root><p id="title">Synthetic title</p></root>'
    xml_path = tmp_path / "source.xml"
    xml_path.write_bytes(xml)

    dimensions = {
        dimension: {
            "items": [
                {
                    "item_id": "work:title",
                    "field": "title",
                    "source_packet": packet_path.name,
                    "input_pointer": "/title",
                    "input_value": "Synthetic title",
                    "input_sha256": _sha(packet),
                    "requirement": "useful_optional",
                    "repair_required": False,
                }
            ]
            if dimension == "work"
            else [],
        }
        for dimension in sm.dimension_names()
    }
    worklist = {
        "schema_version": "source-metadata-worklist-v1",
        "writer": sm.WRITER_ID,
        "batch_id": "benchmark-test",
        "subjects": [{"subject": {"kind": "catalog", "id": "synthetic-work"}, "dimensions": dimensions}],
    }
    binding = {
        "path": xml_path.name,
        "sha256": _sha(xml),
        "bytes": len(xml),
        "role": "primary",
        "locator": {"kind": "xml_id", "value": "title", "expected": "Synthetic title"},
    }
    claim = {
        "worklist_item_id": "work:title",
        "claim_id": "synthetic-title",
        "scope": {"member": "source.xml", "entity": "work", "predicate": "title", "event_role": "none"},
        "evidence": {"classification": "supported", "value": "Synthetic title", "bindings": [binding, copy.deepcopy(binding)]},
        "requirement": {"classification": "useful_optional", "reason": "benchmark test"},
        "adoption": {"classification": "adopted", "destination": "source_evidence_only"},
        "inspection": {"classification": "inspected", "owner": "benchmark-test", "evidence": "source.xml#title"},
    }
    decision = {
        "schema_version": "source-metadata-decisions-v1",
        "writer": sm.WRITER_ID,
        "batch_id": "benchmark-test",
        "decisions": [
            {
                "subject": {"kind": "catalog", "id": "synthetic-work"},
                "dimensions": {"work": {"status": "inspected", "owner": "benchmark-test", "fields": [claim]}},
            }
        ],
    }
    worklist_path = tmp_path / "worklist.json"
    decisions_path = tmp_path / "decisions.json"
    worklist_path.write_bytes(_canonical(worklist))
    decisions_path.write_bytes(_canonical(decision))
    return worklist_path, decisions_path, xml_path


def _args(root: Path, worklist: Path, decisions: Path, output: Path | None = None) -> list[str]:
    args = ["--root", str(root), "--worklist", str(worklist), "--decisions", str(decisions)]
    if output is not None:
        args.extend(["--output", str(output)])
    return args


class _StrictCp1252:
    encoding = "cp1252"

    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, value: str) -> int:
        value.encode("cp1252")
        self.parts.append(value)
        return len(value)

    def flush(self) -> None:
        return None


def test_cli_records_explicit_inputs_runtime_identity_and_parse_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    worklist, decisions, source = _fixture(tmp_path)
    source_before = source.read_bytes()
    output = tmp_path / "benchmark.json"

    assert benchmark_tool.main(_args(tmp_path, worklist, decisions, output)) == 0
    printed = json.loads(capsys.readouterr().out)
    saved = json.loads(output.read_text(encoding="utf-8"))

    assert printed == saved
    assert printed["format"] == "source-metadata-benchmark-v1"
    assert "startup" not in printed["measurement_scope"].lower() or "excludes startup" in printed["measurement_scope"]
    assert printed["runtime"]["data_root"] == str(tmp_path.resolve())
    assert Path(printed["loaded_engine"]["path"]).name == "source_metadata.py"
    assert Path(printed["loaded_schema"]["path"]).name == "source-metadata.schema.json"
    assert printed["inputs"]["worklist"]["sha256"] == _sha(worklist.read_bytes())
    assert printed["inputs"]["decisions"]["sha256"] == _sha(decisions.read_bytes())
    assert printed["input_byte_hashes"][str(source.resolve())] == _sha(source_before)
    assert printed["xml_parse_calls"] == 1
    assert printed["timing"]["load_validation_seconds"] >= 0
    assert printed["timing"]["evidence_verification_seconds"] >= 0
    assert printed["timing"]["total_measured_seconds"] >= printed["timing"]["evidence_verification_seconds"]
    assert printed["issues"] == []
    assert source.read_bytes() == source_before


def test_benchmark_restores_xml_instrumentation_and_returns_nonzero_for_bad_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    worklist, decisions, source = _fixture(tmp_path)
    original = source_metadata_evidence.ET.fromstring
    source.write_bytes(b'<root><p id="title">Changed title</p></root>')
    source_before = source.read_bytes()

    assert benchmark_tool.main(_args(tmp_path, worklist, decisions)) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed"
    assert report["issues"]
    assert any("byte count mismatch" in item["message"] for item in report["issues"])
    assert source_metadata_evidence.ET.fromstring is original
    assert source.read_bytes() == source_before


def test_input_drift_invalidates_measurement_and_output_refuses_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    worklist, decisions, source = _fixture(tmp_path)
    real_verify = sm.verify_evidence
    original = source_metadata_evidence.ET.fromstring

    def mutate_during_verify(*args: object, **kwargs: object) -> list[dict[str, str]]:
        source.write_bytes(source.read_bytes() + b" ")
        return real_verify(*args, **kwargs)

    monkeypatch.setattr(sm, "verify_evidence", mutate_during_verify)
    report = benchmark_tool.benchmark(tmp_path, worklist_path=worklist, decisions_path=decisions)
    assert report["status"] == "invalid_input_identity"
    assert any(item["kind"] == "input_identity" for item in report["issues"])
    assert source_metadata_evidence.ET.fromstring is original

    output = tmp_path / "existing.json"
    output.write_bytes(b"sentinel")
    assert benchmark_tool.main(_args(tmp_path, worklist, decisions, output)) == 2
    capsys.readouterr()
    assert output.read_bytes() == b"sentinel"


@pytest.mark.parametrize("authority_name", _AUTHORITY_ROOTS)
def test_prepare_output_rejects_direct_authority_roots(
    tmp_path: Path, authority_name: str
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    authority = root / authority_name
    authority.mkdir()
    worklist = root / "worklist.json"
    decisions = root / "decisions.json"
    worklist.write_bytes(b"{}")
    decisions.write_bytes(b"{}")
    output = authority / "benchmark.json"

    with pytest.raises(sm.MetadataError, match="authority directory"):
        benchmark_tool._prepare_output(root, output, (worklist, decisions))
    assert not output.exists()


def test_console_output_is_ascii_escaped_but_report_file_is_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worklist, decisions, _source = _fixture(tmp_path)
    output = tmp_path / "report.json"
    stdout = _StrictCp1252()
    monkeypatch.setattr(benchmark_tool.sys, "stdout", stdout)
    monkeypatch.setattr(benchmark_tool.sys, "executable", "C:\\python-雪.exe")

    assert benchmark_tool.main(_args(tmp_path, worklist, decisions, output)) == 0
    rendered = "".join(stdout.parts)
    assert "\\u96ea" in rendered
    saved = output.read_bytes()
    assert "雪".encode("utf-8") in saved


def test_console_error_is_ascii_escaped_for_strict_cp1252(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worklist, _decisions, _source = _fixture(tmp_path)
    missing = tmp_path / "missing-雪.json"
    stderr = _StrictCp1252()
    monkeypatch.setattr(benchmark_tool.sys, "stderr", stderr)

    assert benchmark_tool.main(_args(tmp_path, worklist, missing)) == 2
    rendered = "".join(stderr.parts)
    assert "source metadata benchmark error" in rendered
    assert "\\u96ea" in rendered


def test_seed_identity_must_match_full_preverification_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worklist, decisions, _source = _fixture(tmp_path)
    real_referenced_paths = benchmark_tool._referenced_paths

    def mutate_after_load(
        root: Path, loaded_worklist: dict[str, object], loaded_decisions: list[dict[str, object]]
    ) -> list[Path]:
        paths = real_referenced_paths(root, loaded_worklist, loaded_decisions)
        decisions.write_bytes(decisions.read_bytes() + b" ")
        return paths

    monkeypatch.setattr(benchmark_tool, "_referenced_paths", mutate_after_load)
    with pytest.raises(sm.MetadataError, match="changed before verification"):
        benchmark_tool.benchmark(tmp_path, worklist_path=worklist, decisions_path=decisions)


def test_malformed_explicit_decisions_fail_without_creating_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    worklist, decisions, _source = _fixture(tmp_path)
    decisions.write_bytes(b"not json")
    output = tmp_path / "report.json"

    assert benchmark_tool.main(_args(tmp_path, worklist, decisions, output)) == 2
    captured = capsys.readouterr()
    assert "source metadata benchmark error" in captured.err
    assert not output.exists()

@pytest.mark.parametrize("module_name", ["source_metadata_evidence", "source_metadata_contract"])
def test_benchmark_binds_and_checks_moved_implementation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module_name: str,
) -> None:
    worklist, decisions, _ = _fixture(tmp_path)
    module = getattr(benchmark_tool, module_name)
    original_identity = benchmark_tool._file_identity
    calls = 0

    def identity(path: Path):
        nonlocal calls
        result = original_identity(path)
        if Path(path).resolve() == Path(module.__file__).resolve():
            calls += 1
            if calls == 2:
                result = {**result, "sha256": "0" * 64}
        return result

    monkeypatch.setattr(benchmark_tool, "_file_identity", identity)
    report = benchmark_tool.benchmark(tmp_path, worklist_path=worklist, decisions_path=decisions)
    assert Path(report["loaded_implementations"][module_name]["path"]) == Path(module.__file__).resolve()
    assert report["status"] == "failed"
    assert any(issue.get("artifact") == module_name for issue in report["issues"])
