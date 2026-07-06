from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from build.parsers import s1_kraken_greek_runner  # noqa: E402
from build.parsers.s1_kraken_greek_runner import _preflight_kraken_models as _real_preflight_kraken_models  # noqa: E402


@pytest.fixture(autouse=True)
def _skip_kraken_model_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s1_kraken_greek_runner, "_preflight_kraken_models", lambda: None)


def _schema(name: str) -> dict:
    with (REPO_ROOT / "schemas" / "v1" / f"{name}.schema.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def _prepare_pages(tmp_path: Path, count: int = 2) -> tuple[Path, Path, Path]:
    repo_root = tmp_path / "repo"
    input_root = repo_root / "raw" / "internet-archive" / "schaff-herzog-pages"
    volume_dir = input_root / "vol_01"
    output_root = repo_root / "reports" / "s1-sidecars"
    volume_dir.mkdir(parents=True)
    # Distinct bytes per page so each image has a unique sha; a minimal v4
    # source manifest maps those shas to body leaves so the emitter can resolve
    # canonical_leaf_id + the (now required) edition_page_key (production always
    # has this manifest -- the test previously relied on the removed exempt path).
    leaves = []
    for index in range(1, count + 1):
        payload = f"kraken-greek-page-{index}".encode("utf-8")
        (volume_dir / f"page_{index:04d}.jpg").write_bytes(payload)
        leaves.append(
            {
                "leaf_num": index,
                "page_num": index,
                "kind": "body",
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
            }
        )
    (input_root / "vol_01.manifest.json").write_text(
        json.dumps({"leaves": leaves}), encoding="utf-8"
    )
    return repo_root, input_root, output_root


def _success_payload() -> bytes:
    return json.dumps(
        {
            "ok": True,
            "engine_version": "1.4.2",
            "page_width": 100,
            "page_height": 200,
            "blocks": [
                {
                    "block_id": "b-0001",
                    "block_type": "text",
                    "bbox_native": {"x": 1, "y": 2, "w": 30, "h": 10},
                    "lines": [
                        {
                            "line_id": "l-0001-0001",
                            "source_raw": "Alpha beta",
                            "confidence": 0.87,
                            "bbox_native": {"x": 1, "y": 2, "w": 30, "h": 10},
                            "words": [
                                {
                                    "word_id": "w-0001-0001-0001",
                                    "source_raw": "Alpha",
                                    "confidence": 0.9,
                                    "bbox_native": {"x": 1, "y": 2, "w": 10, "h": 10},
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ).encode("utf-8")


def _stub_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):
        _write_mock_raw(args[0])
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=_success_payload(), stderr=b"")

    monkeypatch.setattr(s1_kraken_greek_runner.subprocess, "run", fake_run)


def _write_mock_raw(cmd: list) -> None:
    if "--raw-output" not in cmd:
        return
    raw_path = Path(cmd[cmd.index("--raw-output") + 1])
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text('{"engine_family":"kraken","engine_variant":"greek","mock":true}', encoding="utf-8")


def _read_page(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def test_kraken_greek_runner_emits_sidecar_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    summary = s1_kraken_greek_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    manifest = summary.manifest
    manifest_path = output_root / "kraken-greek-py312-v1" / "vol_01" / "manifest.json"
    page_paths = sorted((manifest_path.parent / "pages").glob("*.json"))
    assert manifest_path.exists()
    assert len(page_paths) == 2
    jsonschema.validate(instance=manifest, schema=_schema("sidecar-manifest-v1"))
    for page_path in page_paths:
        jsonschema.validate(instance=_read_page(page_path), schema=_schema("sidecar-page-v1"))
    page = _read_page(page_paths[0])
    raw_ref = page["page_extras_carried"]["raw_artifact"]
    assert raw_ref["engine"] == "kraken-greek"
    assert (repo_root / raw_ref["path"]).exists()
    # ENGINE_FAMILY is "kraken" (not "kraken-greek") — sidecar collapses both lanes.
    assert manifest["engine_family"] == "kraken"
    assert manifest["source_lineage_id"] == "kraken-greek-py312-v1"


def test_kraken_greek_rendering_id_distinct_from_base_kraken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Greek lane must produce a different RENDERING_ID than the standard Kraken lane."""
    from build.parsers import s1_kraken_runner

    assert s1_kraken_greek_runner.RENDERING_ID != s1_kraken_runner.RENDERING_ID
    assert "kraken-greek" in s1_kraken_greek_runner.RENDERING_ID


def test_kraken_greek_runner_raises_if_model_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    import build.parsers.s1_kraken_greek_runner as m

    def always_fail():
        raise RuntimeError("No Kraken models found")

    monkeypatch.setattr(m, "_preflight_kraken_models", always_fail)
    with pytest.raises(RuntimeError, match="No Kraken models found"):
        m.normalize_volume(
            volume=1,
            input_root=input_root,
            output_root=output_root,
            repo_root=repo_root,
        )
    assert not (output_root / "kraken-greek-py312-v1").exists()


def test_kraken_greek_subprocess_failure_recorded_as_failure_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fake_run(*args, **kwargs):
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(returncode=1, cmd=args[0], output=b"", stderr=b"boom")
        return subprocess.CompletedProcess(args=args[0], returncode=1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(s1_kraken_greek_runner.subprocess, "run", fake_run)

    summary = s1_kraken_greek_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    page_ref = summary.manifest["pages"][0]
    page = _read_page(output_root / "kraken-greek-py312-v1" / "vol_01" / "pages" / "page_0001.json")
    assert page["page_extras_carried"]["failure_class"] == "subprocess_error"
    assert page_ref["status"] == "corrupt"


def test_kraken_greek_runner_resume_skips_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    s1_kraken_greek_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )
    summary = s1_kraken_greek_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.skipped_pages == 2
    assert summary.emitted_pages == 0


def _success_payload_with_greek_side_channel() -> bytes:
    return json.dumps(
        {
            "ok": True,
            "engine_version": "1.4.2",
            "model_id": "ciaconna-greek-latin.mlmodel",
            "page_width": 100,
            "page_height": 200,
            "kraken_greek_char_confidences": {"l-0001-0001": [0.9, 0.8, 0.95]},
            "kraken_greek_line_polygons": {
                "l-0001-0001": [[0.0, 0.0], [100.0, 0.0], [100.0, 20.0], [0.0, 20.0]]
            },
            "blocks": [
                {
                    "block_id": "b-0001",
                    "block_type": "text",
                    "bbox_native": {"x": 1, "y": 2, "w": 30, "h": 10},
                    "lines": [
                        {
                            "line_id": "l-0001-0001",
                            "source_raw": "Alpha beta",
                            "confidence": 0.87,
                            "bbox_native": {"x": 1, "y": 2, "w": 30, "h": 10},
                            "words": [
                                {
                                    "word_id": "w-0001-0001-0001",
                                    "source_raw": "Alpha",
                                    "confidence": 0.9,
                                    "bbox_native": {"x": 1, "y": 2, "w": 10, "h": 10},
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ).encode("utf-8")


def test_kraken_greek_side_channel_uses_greek_prefixed_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Greek lane side-channel keys use kraken_greek_ prefix, not kraken_."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fake_run(*args, **kwargs):
        _write_mock_raw(args[0])
        return subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout=_success_payload_with_greek_side_channel(), stderr=b""
        )

    monkeypatch.setattr(s1_kraken_greek_runner.subprocess, "run", fake_run)

    summary = s1_kraken_greek_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    page = _read_page(output_root / "kraken-greek-py312-v1" / "vol_01" / "pages" / "page_0001.json")
    extras = page["page_extras_carried"]
    assert "kraken_greek_char_confidences" in extras
    assert "kraken_greek_line_polygons" in extras
    assert "kraken_char_confidences" not in extras
    assert "kraken_line_polygons" not in extras
    assert extras["kraken_greek_char_confidences"] == {"l-0001-0001": [0.9, 0.8, 0.95]}
    assert summary.failed_pages == 0


def test_kraken_greek_preflight_accepts_nonempty_model(tmp_path: Path) -> None:
    model_dir = tmp_path / "kraken-models"
    model_dir.mkdir()
    (model_dir / "ciaconna-greek-latin.mlmodel").write_bytes(b"data")

    _real_preflight_kraken_models(_model_dir=model_dir)  # must not raise


def test_kraken_greek_preflight_rejects_zero_byte_model(tmp_path: Path) -> None:
    model_dir = tmp_path / "kraken-models"
    model_dir.mkdir()
    (model_dir / "ciaconna-greek-latin.mlmodel").write_bytes(b"")

    with pytest.raises(RuntimeError, match="zero bytes"):
        _real_preflight_kraken_models(_model_dir=model_dir)


# ---------------------------------------------------------------------------
# R2: skip predicate keyed on sidecar existence, not state file
# ---------------------------------------------------------------------------


def _write_minimal_sidecar(page_path: Path, *, failure_class: str | None = None) -> None:
    page_path.parent.mkdir(parents=True, exist_ok=True)
    extras: dict = {}
    if failure_class is not None:
        extras["failure_class"] = failure_class
    page_path.write_text(json.dumps({"page_extras_carried": extras}), encoding="utf-8")


def _write_state_claiming_done(state_path: Path, page_ids: list) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({
            "manifest_id": "test",
            "emitted_pages": page_ids,
            "updated_at": "2026-01-01T00:00:00Z",
        }),
        encoding="utf-8",
    )


def test_kraken_greek_skip_keyed_on_sidecar_not_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skip must fire from a valid on-disk sidecar even when the state file is absent."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    s1_kraken_greek_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )
    state_path = output_root / "kraken-greek-py312-v1" / "vol_01" / "manifest.state.json"
    state_path.unlink()

    summary = s1_kraken_greek_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.skipped_pages == 2, "valid sidecars must cause skip even without state file"
    assert summary.emitted_pages == 0


def test_kraken_greek_stale_success_sidecar_is_reprocessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    s1_kraken_greek_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )
    page_path = output_root / "kraken-greek-py312-v1" / "vol_01" / "pages" / "page_0001.json"
    page = _read_page(page_path)
    page["page_extras_carried"].pop("runner_cache_version")
    page["page_extras_carried_keys"].remove("runner_cache_version")
    page_path.write_text(json.dumps(page), encoding="utf-8")

    summary = s1_kraken_greek_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.skipped_pages == 1
    assert summary.emitted_pages == 1
    assert (
        _read_page(page_path)["page_extras_carried"]["runner_cache_version"]
        == s1_kraken_greek_runner.S1_SIDECAR_CACHE_VERSION
    )


def test_kraken_greek_failed_sidecar_not_skipped_when_state_claims_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sidecar with failure_class must be retried even if the state file lists it as done."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    _stub_success(monkeypatch)

    pages_dir = output_root / "kraken-greek-py312-v1" / "vol_01" / "pages"
    _write_minimal_sidecar(pages_dir / "page_0001.json", failure_class="subprocess_error")
    state_path = output_root / "kraken-greek-py312-v1" / "vol_01" / "manifest.state.json"
    _write_state_claiming_done(state_path, ["page_0001"])

    summary = s1_kraken_greek_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.skipped_pages == 0, "failed sidecar must not be skipped even if state claims done"
    assert summary.emitted_pages == 1, "failed sidecar must be retried and re-emitted"


def test_kraken_greek_corrupt_sidecar_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt (unparseable) sidecar must be treated as not-done and retried."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    _stub_success(monkeypatch)

    pages_dir = output_root / "kraken-greek-py312-v1" / "vol_01" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "page_0001.json").write_text("not valid json{{", encoding="utf-8")
    state_path = output_root / "kraken-greek-py312-v1" / "vol_01" / "manifest.state.json"
    _write_state_claiming_done(state_path, ["page_0001"])

    summary = s1_kraken_greek_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.emitted_pages == 1, "corrupt sidecar must be retried, not skipped"
    assert summary.skipped_pages == 0
