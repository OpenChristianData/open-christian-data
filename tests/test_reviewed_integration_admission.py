"""Closed reviewed integrations reject changed authority before staging."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from build.tools import integrate_reviewed_equiano as equiano
from build.tools import integrate_reviewed_standard_ebooks as ebooks
from build.tools import integrate_reviewed_tcp as tcp
from build.tools import integrate_reviewed_wesley as wesley
from ocd_kernel.library._common import PipelineError


BASE = "plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-004"


def write_json(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_standard_ebooks_rejects_unreviewed_package_before_staging(tmp_path, monkeypatch):
    write_json(tmp_path, BASE + "/28-standard-ebooks-manifest-drift.json", [
        {"work_id": "paradise-lost", "candidate_root": "unused"},
    ])
    monkeypatch.setattr(ebooks.CandidatePackage, "load", lambda *a, **k: SimpleNamespace(sha256="0" * 64))
    stage = tmp_path / "stage"
    with pytest.raises(PipelineError, match="Reviewed package identity changed"):
        ebooks.prepare(tmp_path, stage, "paradise-lost")
    assert not stage.exists()


def test_equiano_rejects_changed_volume_before_staging(tmp_path, monkeypatch):
    write_json(tmp_path, BASE + "/12-additional-integration-readiness.json", {
        "items": [{}, {"candidate_roots": ["unused-volume", "unused-volume-two"]}],
    })
    monkeypatch.setattr(equiano.SourceManifest, "load", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(equiano.CandidatePackage, "load", lambda *a, **k: SimpleNamespace(sha256="0" * 64))
    stage = tmp_path / "stage"
    with pytest.raises(PipelineError, match="reviewed Equiano package changed"):
        equiano.prepare(tmp_path, stage)
    assert not stage.exists()


def test_equiano_rejects_missing_continuation_before_staging(tmp_path):
    write_json(tmp_path, BASE + "/12-additional-integration-readiness.json", {
        "items": [{}, {"candidate_roots": ["volume-one"]}],
    })
    with pytest.raises(PipelineError, match="continuation"):
        equiano.prepare(tmp_path, tmp_path / "stage")
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize(
    ("roots", "package_hashes"),
    [
        (["volume-two", "volume-one"], equiano.PACKAGES[::-1]),
        (["other-edition", "volume-two"], ("f" * 64, equiano.PACKAGES[1])),
    ],
    ids=["swapped-witness", "mixed-edition-witness"],
)
def test_equiano_rejects_swapped_or_mixed_edition_witness_before_staging(
    tmp_path, monkeypatch, roots, package_hashes
):
    write_json(tmp_path, BASE + "/12-additional-integration-readiness.json", {
        "items": [{}, {"candidate_roots": roots}],
    })
    monkeypatch.setattr(equiano.SourceManifest, "load", lambda *a, **k: SimpleNamespace())
    hashes = iter(package_hashes)
    monkeypatch.setattr(
        equiano.CandidatePackage,
        "load",
        lambda *a, **k: SimpleNamespace(sha256=next(hashes)),
    )
    stage = tmp_path / "stage"
    with pytest.raises(PipelineError, match="reviewed Equiano package changed"):
        equiano.prepare(tmp_path, stage)
    assert not stage.exists()


def test_equiano_binding_only_replay_preserves_all_payload_members():
    payloads = {
        "README.source.md": b"source",
        "content.tei.xml": b"tei",
        "provenance.json": b"provenance",
        "source-accountability.json": b"accountability",
        "unresolved.jsonl": b"unresolved",
    }
    historical = SimpleNamespace(
        member_names=tuple(sorted((*payloads, "manifest.json"))),
        member_bytes=lambda name: payloads[name],
    )
    current = SimpleNamespace(
        member_names=historical.member_names,
        member_bytes=lambda name: payloads[name],
    )

    equiano._assert_replay_payloads_match(historical, current, 1)


def test_equiano_binding_only_replay_rejects_payload_change():
    historical_payloads = {
        "README.source.md": b"source",
        "content.tei.xml": b"tei",
        "provenance.json": b"provenance",
        "source-accountability.json": b"accountability",
        "unresolved.jsonl": b"unresolved",
    }
    current_payloads = {**historical_payloads, "content.tei.xml": b"changed"}
    historical = SimpleNamespace(
        member_names=tuple(sorted((*historical_payloads, "manifest.json"))),
        member_bytes=lambda name: historical_payloads[name],
    )
    current = SimpleNamespace(
        member_names=historical.member_names,
        member_bytes=lambda name: current_payloads[name],
    )

    with pytest.raises(PipelineError, match="replay payload changed"):
        equiano._assert_replay_payloads_match(historical, current, 1)


def test_wesley_rejects_changed_package_even_with_self_consistent_replay(tmp_path, monkeypatch):
    write_json(tmp_path, BASE + "/12-additional-integration-readiness.json", {
        "items": [{"package_path": "unused"}],
    })
    write_json(tmp_path, BASE + "/17-wesley-header-integration-probe.json", {})
    result = {"status": "pass", "candidate_sha256": "0" * 64}
    raw = (json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()
    result["result_sha256"] = hashlib.sha256(raw).hexdigest()
    write_json(tmp_path, BASE + "/16-wesley-current-checker-replay.json", {
        "oracle_result": result, "replay_input_bindings": [],
    })
    monkeypatch.setattr(wesley.CandidatePackage, "load", lambda *a, **k: SimpleNamespace(sha256="0" * 64))
    stage = tmp_path / "stage"
    with pytest.raises(PipelineError, match="reviewed Wesley package changed"):
        wesley.prepare(tmp_path, stage)
    assert not stage.exists()


def test_tcp_rejects_changed_retained_source_before_staging(tmp_path, monkeypatch):
    work = "occom-moses-paul-execution-sermon"
    source = tmp_path / "changed.xml"
    source.write_bytes(b"changed retained source")
    write_json(tmp_path, f"sources/structured-text/{work}/{work}.source-manifest.json", {
        "authorities": [{"role": "primary-source", "path": "changed.xml",
                         "sha256": tcp.CASES[work]["sha"], "bytes": source.stat().st_size}],
    })
    monkeypatch.setattr(tcp, "resolve_repo_path", lambda *a, **k: source)
    stage = tmp_path / "stage"
    with pytest.raises(PipelineError, match="retained source no longer matches"):
        tcp.prepare(tmp_path, work, stage)
    assert not stage.exists()
