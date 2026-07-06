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

from build.parsers import s1_calamari_runner  # noqa: E402


@pytest.fixture(autouse=True)
def _fake_calamari_model_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_dir = tmp_path / "calamari-model"
    model_dir.mkdir()
    (model_dir / "model.ckpt.json").write_text("mock", encoding="utf-8")
    monkeypatch.setattr(s1_calamari_runner, "DEFAULT_CALAMARI_MODEL_DIR", model_dir)


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
        payload = f"calamari-page-{index}".encode("utf-8")
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
    # calamari_page.py writes UTF-8 bytes to stdout.buffer; mocks must match.
    return json.dumps(
        {
            "ok": True,
            "engine_version": "2.2.0",
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
                            "confidence": 0.92,
                            "bbox_native": {"x": 1, "y": 2, "w": 30, "h": 10},
                            "words": [
                                {
                                    "word_id": "w-0001-0001-0001",
                                    "source_raw": "Alpha",
                                    "confidence": 0.93,
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
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=_success_payload(), stderr=b"")

    monkeypatch.setattr(s1_calamari_runner.subprocess, "run", fake_run)


def _read_page(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def test_calamari_runner_emits_sidecar_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    summary = s1_calamari_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    manifest = summary.manifest
    manifest_path = output_root / "calamari-py311-v1" / "vol_01" / "manifest.json"
    page_paths = sorted((manifest_path.parent / "pages").glob("*.json"))
    assert manifest_path.exists()
    assert len(page_paths) == 2
    jsonschema.validate(instance=manifest, schema=_schema("sidecar-manifest-v1"))
    for page_path in page_paths:
        jsonschema.validate(instance=_read_page(page_path), schema=_schema("sidecar-page-v1"))
    assert manifest["engine_family"] == "calamari"


def test_calamari_build_blocks_bbox_has_numeric_width() -> None:
    from build.tools.ocr_runners.calamari_page import _build_blocks_from_predictions

    predictions = [((10, 50), "hello world", 0.9)]
    blocks = _build_blocks_from_predictions(predictions, page_width=1000)
    assert blocks[0]["bbox_native"]["w"] == 1000.0
    assert blocks[0]["bbox_native"]["y"] == 10.0
    assert blocks[0]["bbox_native"]["h"] == 40.0


def test_calamari_runner_raises_if_model_absent(tmp_path: Path) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    import build.parsers.s1_calamari_runner as m

    orig = m.DEFAULT_CALAMARI_MODEL_DIR
    m.DEFAULT_CALAMARI_MODEL_DIR = tmp_path / "no_such_dir"
    try:
        with pytest.raises(RuntimeError, match="Calamari model directory"):
            m.normalize_volume(
                volume=1,
                input_root=input_root,
                output_root=output_root,
                repo_root=repo_root,
            )
    finally:
        m.DEFAULT_CALAMARI_MODEL_DIR = orig


def test_calamari_subprocess_failure_recorded_as_failure_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fake_run(*args, **kwargs):
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(returncode=1, cmd=args[0], output=b"", stderr=b"boom")
        return subprocess.CompletedProcess(args=args[0], returncode=1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(s1_calamari_runner.subprocess, "run", fake_run)

    summary = s1_calamari_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    page_ref = summary.manifest["pages"][0]
    page = _read_page(output_root / "calamari-py311-v1" / "vol_01" / "pages" / "page_0001.json")
    assert page["page_extras_carried"]["failure_class"] == "subprocess_error"
    assert page_ref["status"] == "corrupt"
    assert page_ref["failure_class"] == "subprocess_error"


def test_calamari_runner_resume_skips_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    s1_calamari_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )
    summary = s1_calamari_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    assert summary.skipped_pages == 2
    assert summary.emitted_pages == 0


def test_calamari_resume_preserves_failure_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fail_run(*args, **kwargs):
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(returncode=1, cmd=args[0], output=b"", stderr=b"boom")
        return subprocess.CompletedProcess(args=args[0], returncode=1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(s1_calamari_runner.subprocess, "run", fail_run)

    s1_calamari_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )
    summary2 = s1_calamari_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    assert summary2.skipped_pages == 1
    assert summary2.failed_pages == 1
    page_ref = summary2.manifest["pages"][0]
    assert page_ref["status"] == "corrupt"
    assert page_ref.get("failure_class") == "subprocess_error"


def test_calamari_subprocess_timeout_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("cmd", 300)

    monkeypatch.setattr(s1_calamari_runner.subprocess, "run", fake_run)

    summary = s1_calamari_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    page_ref = summary.manifest["pages"][0]
    page = _read_page(output_root / "calamari-py311-v1" / "vol_01" / "pages" / "page_0001.json")
    assert page["page_extras_carried"]["failure_class"] == "subprocess_timeout"
    assert page_ref["failure_class"] == "subprocess_timeout"


def test_calamari_throttle_minimal_passes_env_to_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    captured_kwargs: dict = {}

    def capturing_run(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=_success_payload(), stderr=b"")

    monkeypatch.setattr(s1_calamari_runner.subprocess, "run", capturing_run)

    s1_calamari_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        throttle_mode="minimal-4",
    )

    assert captured_kwargs.get("env", {}).get("OMP_NUM_THREADS") == "4"
    assert captured_kwargs.get("creationflags") == 0x00000040

