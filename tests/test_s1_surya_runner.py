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

from build.parsers import s1_surya_runner  # noqa: E402


@pytest.fixture(autouse=True)
def _skip_surya_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s1_surya_runner, "_preflight_surya", lambda: None)


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
        payload = f"surya-page-{index}".encode("utf-8")
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
    # surya_page.py writes to stdout.buffer as UTF-8 bytes; mocks must match.
    return json.dumps(
        {
            "ok": True,
            "api_used": "surya.ocr.run_recognition",
            "engine_version": "0.8.0",
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
                            "source_raw": "ΧΡΙΣΤΟΣ alpha",
                            "confidence": 0.87,
                            "bbox_native": {"x": 1, "y": 2, "w": 30, "h": 10},
                            "words": [
                                {
                                    "word_id": "w-0001-0001-0001",
                                    "source_raw": "ΧΡΙΣΤΟΣ",
                                    "confidence": 0.9,
                                    "bbox_native": {"x": 1, "y": 2, "w": 10, "h": 10},
                                }
                            ],
                        }
                    ],
                }
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _stub_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):
        _write_mock_raw(args[0])
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=_success_payload(), stderr=b"")

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", fake_run)


def _write_mock_raw(cmd: list) -> None:
    if "--raw-output" in cmd:
        raw_path = Path(cmd[cmd.index("--raw-output") + 1])
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text('{"engine_family":"surya","mock":true}', encoding="utf-8")
    if "--raw-outputs" in cmd:
        start = cmd.index("--raw-outputs") + 1
        for raw in cmd[start:]:
            raw_path = Path(raw)
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text('{"engine_family":"surya","mock":true}', encoding="utf-8")


def _read_page(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def test_surya_runner_emits_sidecar_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    summary = s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    manifest = summary.manifest
    manifest_path = output_root / "surya-py312-v1" / "vol_01" / "manifest.json"
    page_paths = sorted((manifest_path.parent / "pages").glob("*.json"))
    assert manifest_path.exists()
    assert len(page_paths) == 2
    jsonschema.validate(instance=manifest, schema=_schema("sidecar-manifest-v1"))
    for page_path in page_paths:
        jsonschema.validate(instance=_read_page(page_path), schema=_schema("sidecar-page-v1"))
    page = _read_page(page_paths[0])
    raw_ref = page["page_extras_carried"]["raw_artifact"]
    assert raw_ref["format"] == "json"
    assert (repo_root / raw_ref["path"]).exists()
    assert manifest["engine_family"] == "surya"


def test_surya_subprocess_failure_recorded_as_failure_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fake_run(*args, **kwargs):
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(returncode=1, cmd=args[0], output=b"", stderr=b"boom")
        return subprocess.CompletedProcess(args=args[0], returncode=1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", fake_run)

    summary = s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    page_ref = summary.manifest["pages"][0]
    page = _read_page(output_root / "surya-py312-v1" / "vol_01" / "pages" / "page_0001.json")
    assert page["page_extras_carried"]["failure_class"] == "subprocess_error"
    assert page_ref["status"] == "corrupt"
    assert page_ref["failure_class"] == "subprocess_error"


def test_surya_runner_resume_skips_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )
    summary = s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    assert summary.skipped_pages == 2
    assert summary.emitted_pages == 0


def test_surya_failed_pages_are_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed pages must not be recorded in emitted_pages — they are retried on the next run."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fail_run(*args, **kwargs):
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(returncode=1, cmd=args[0], output=b"", stderr=b"boom")
        return subprocess.CompletedProcess(args=args[0], returncode=1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", fail_run)

    s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )
    summary2 = s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    assert summary2.skipped_pages == 0, "failed pages must not be skipped on re-run"
    assert summary2.emitted_pages == 1, "page must be retried and re-emitted"
    assert summary2.failed_pages == 1
    page_ref = summary2.manifest["pages"][0]
    assert page_ref["status"] == "corrupt"
    assert page_ref.get("failure_class") == "subprocess_error"


def test_surya_subprocess_timeout_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("cmd", 300)

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", fake_run)

    summary = s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    page_ref = summary.manifest["pages"][0]
    page = _read_page(output_root / "surya-py312-v1" / "vol_01" / "pages" / "page_0001.json")
    assert page["page_extras_carried"]["failure_class"] == "subprocess_timeout"
    assert page_ref["failure_class"] == "subprocess_timeout"


def test_surya_throttle_minimal_passes_env_to_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    captured_kwargs: dict = {}

    def capturing_run(*args, **kwargs):
        captured_kwargs.update(kwargs)
        _write_mock_raw(args[0])
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=_success_payload(), stderr=b"")

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", capturing_run)

    s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        throttle_mode="minimal-4",
    )

    assert captured_kwargs.get("env", {}).get("OMP_NUM_THREADS") == "4"
    assert captured_kwargs.get("creationflags") == 0x00000040


def _success_payload_with_original_text_good() -> bytes:
    return json.dumps(
        {
            "ok": True,
            "api_used": "surya.recognition.RecognitionPredictor",
            "engine_version": "0.8.0",
            "page_width": 100,
            "page_height": 200,
            "surya_original_text_good": {"l-0001-0001": True, "l-0002-0001": False},
            "blocks": [
                {
                    "block_id": "b-0001",
                    "block_type": "text",
                    "bbox_native": {"x": 1, "y": 2, "w": 30, "h": 10},
                    "lines": [
                        {
                            "line_id": "l-0001-0001",
                            "source_raw": "Alpha",
                            "confidence": 0.9,
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
        },
        ensure_ascii=False,
    ).encode("utf-8")


def test_surya_original_text_good_in_page_extras_carried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fake_run(*args, **kwargs):
        _write_mock_raw(args[0])
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=_success_payload_with_original_text_good(),
            stderr=b"",
        )

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", fake_run)

    summary = s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    page = _read_page(output_root / "surya-py312-v1" / "vol_01" / "pages" / "page_0001.json")
    extras = page["page_extras_carried"]
    assert extras["surya_original_text_good"] == {"l-0001-0001": True, "l-0002-0001": False}
    assert summary.failed_pages == 0


def test_surya_runner_raises_if_preflight_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def always_fail() -> None:
        raise RuntimeError("Surya preflight failed: predictor initialization did not complete")

    monkeypatch.setattr(s1_surya_runner, "_preflight_surya", always_fail)
    with pytest.raises(RuntimeError, match="Surya preflight failed"):
        s1_surya_runner.normalize_volume(
            volume=1,
            input_root=input_root,
            output_root=output_root,
            repo_root=repo_root,
        )
    # Preflight failure must not bake any pages into state
    assert not (output_root / "surya-py312-v1").exists()


def test_surya_pages_subset_selects_exact_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pages=[2, 4] on a 4-image volume processes exactly those two pages."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=4)
    _stub_success(monkeypatch)

    summary = s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        pages=[2, 4],
    )

    pages_dir = output_root / "surya-py312-v1" / "vol_01" / "pages"
    assert summary.emitted_pages == 2
    assert not (pages_dir / "page_0001.json").exists()
    assert (pages_dir / "page_0002.json").exists()
    assert not (pages_dir / "page_0003.json").exists()
    assert (pages_dir / "page_0004.json").exists()
    assert {p["page_sequence"] for p in summary.manifest["pages"]} == {2, 4}


def test_surya_pages_none_whole_volume_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pages=None (default) processes all images — regression guard."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=3)
    _stub_success(monkeypatch)

    summary = s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        pages=None,
    )

    assert summary.emitted_pages == 3
    assert summary.failed_pages == 0


def test_surya_pages_empty_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pages=[] raises ValueError immediately — no silent no-op (REL-02)."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    with pytest.raises(ValueError, match="non-empty"):
        s1_surya_runner.normalize_volume(
            volume=1,
            input_root=input_root,
            output_root=output_root,
            repo_root=repo_root,
            pages=[],
        )


# ---------------------------------------------------------------------------
# Change 2: multi-page batching (batch_size parameter)
# ---------------------------------------------------------------------------


def _count_images_in_cmd(cmd: list) -> int:
    """Count image paths in a --images batch command."""
    try:
        idx = list(cmd).index("--images")
        total = 0
        for arg in cmd[idx + 1 :]:
            if str(arg).startswith("--"):
                break
            total += 1
        return total
    except ValueError:
        return 1  # --image single-image path


def _stub_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock subprocess.run for batch mode: returns N JSON lines for N images."""

    def fake_batch_run(*args, **kwargs):
        _write_mock_raw(args[0])
        n = _count_images_in_cmd(args[0])
        stdout = b"\n".join([_success_payload()] * n)
        return subprocess.CompletedProcess(args[0], returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", fake_batch_run)


def test_surya_batch_size_2_makes_2_subprocess_calls_for_4_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """4 images with batch_size=2 → 2 subprocess calls, not 4."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=4)
    call_count = [0]

    def counting_batch_run(*args, **kwargs):
        call_count[0] += 1
        _write_mock_raw(args[0])
        n = _count_images_in_cmd(args[0])
        stdout = b"\n".join([_success_payload()] * n)
        return subprocess.CompletedProcess(args[0], returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", counting_batch_run)

    s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        batch_size=2,
    )

    assert call_count[0] == 2  # 4 pages / batch_size 2 = 2 calls


def test_surya_batch_produces_same_sidecars_as_single_page_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """batch_size=3 produces byte-identical page sidecars to batch_size=1."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=3)

    # --- Single-page run (default) ---
    _stub_success(monkeypatch)
    s1_surya_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root
    )

    pages_dir = output_root / "surya-py312-v1" / "vol_01" / "pages"
    single_content = {p.name: p.read_bytes() for p in sorted(pages_dir.glob("*.json"))}

    # Reset state so batch run re-processes the same pages
    state_file = output_root / "surya-py312-v1" / "vol_01" / "manifest.state.json"
    import json as _json
    state_file.write_text(_json.dumps({"emitted_pages": []}), encoding="utf-8")

    # --- Batch run ---
    _stub_batch(monkeypatch)
    s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        batch_size=3,
    )

    batch_content = {p.name: p.read_bytes() for p in sorted(pages_dir.glob("*.json"))}

    assert set(single_content) == set(batch_content), "batch produced different page files"
    for name in single_content:
        assert single_content[name] == batch_content[name], (
            f"{name}: content differs between single-page and batch runs"
        )


# ---------------------------------------------------------------------------
# Change 3: env knobs (recognition_batch_size, detector_batch_size)
# ---------------------------------------------------------------------------


def test_surya_recognition_batch_size_injected_into_subprocess_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """recognition_batch_size=4 injects RECOGNITION_BATCH_SIZE=4 into subprocess env."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    captured: dict = {}

    def capturing_run(*args, **kwargs):
        captured.update(kwargs)
        _write_mock_raw(args[0])
        return subprocess.CompletedProcess(args[0], returncode=0, stdout=_success_payload(), stderr=b"")

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", capturing_run)

    s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        recognition_batch_size=4,
    )

    assert captured.get("env", {}).get("RECOGNITION_BATCH_SIZE") == "4"


def test_surya_detector_batch_size_injected_into_subprocess_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """detector_batch_size=1 injects DETECTOR_BATCH_SIZE=1 into subprocess env."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    captured: dict = {}

    def capturing_run(*args, **kwargs):
        captured.update(kwargs)
        _write_mock_raw(args[0])
        return subprocess.CompletedProcess(args[0], returncode=0, stdout=_success_payload(), stderr=b"")

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", capturing_run)

    s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        detector_batch_size=1,
    )

    assert captured.get("env", {}).get("DETECTOR_BATCH_SIZE") == "1"


# ---------------------------------------------------------------------------
# Change 4: max_width downsampling parameter
# ---------------------------------------------------------------------------


def _captured_cmd(monkeypatch: pytest.MonkeyPatch) -> list:
    """Capture the subprocess cmd list from the next normalize_volume call."""
    captured_cmd: list = []

    def capturing_run(*args, **kwargs):
        captured_cmd.extend(args[0])
        _write_mock_raw(args[0])
        return subprocess.CompletedProcess(args[0], returncode=0, stdout=_success_payload(), stderr=b"")

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", capturing_run)
    return captured_cmd


def test_surya_max_width_passes_to_single_page_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """max_width=2500 adds --max-width 2500 to the single-page subprocess command."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    cmd = _captured_cmd(monkeypatch)

    s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        max_width=2500,
    )

    assert "--max-width" in cmd
    assert cmd[cmd.index("--max-width") + 1] == "2500"


def test_surya_max_width_none_omits_flag_from_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """max_width=None (default) must not add --max-width to the subprocess command."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    cmd = _captured_cmd(monkeypatch)

    s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        max_width=None,
    )

    assert "--max-width" not in cmd


def test_surya_max_width_passes_to_batch_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """max_width=2500 with batch_size=2 adds --max-width 2500 to the batch subprocess command."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=2)

    captured_cmd: list = []

    def capturing_batch_run(*args, **kwargs):
        captured_cmd.extend(args[0])
        _write_mock_raw(args[0])
        n = _count_images_in_cmd(args[0])
        stdout = b"\n".join([_success_payload()] * n)
        return subprocess.CompletedProcess(args[0], returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", capturing_batch_run)

    s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        batch_size=2,
        max_width=2500,
    )

    assert "--max-width" in captured_cmd
    assert captured_cmd[captured_cmd.index("--max-width") + 1] == "2500"


# ---------------------------------------------------------------------------
# Change 5: max_width recorded in manifest bundle_extras and page sidecar
# ---------------------------------------------------------------------------


def _success_payload_with_inference_width() -> bytes:
    """Payload as surya_page.py would emit when max_width was applied."""
    return json.dumps(
        {
            "ok": True,
            "api_used": "surya.recognition.RecognitionPredictor",
            "engine_version": "0.17.1",
            "page_width": 5034,
            "page_height": 6959,
            "surya_inference_width": 2500,
            "surya_scale_to_native": 2.0136,
            "blocks": [
                {
                    "block_id": "b-0001",
                    "block_type": "text",
                    "bbox_native": {"x": 1, "y": 2, "w": 30, "h": 10},
                    "lines": [
                        {
                            "line_id": "l-0001-0001",
                            "source_raw": "Hello",
                            "confidence": 0.9,
                            "bbox_native": {"x": 1, "y": 2, "w": 30, "h": 10},
                            "words": [
                                {
                                    "word_id": "w-0001-0001-0001",
                                    "source_raw": "Hello",
                                    "confidence": 0.9,
                                    "bbox_native": {"x": 1, "y": 2, "w": 10, "h": 10},
                                }
                            ],
                        }
                    ],
                }
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")


def test_surya_max_width_recorded_in_manifest_bundle_extras(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """max_width=2500 is recorded in manifest bundle_extras_carried."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fake_run(*args, **kwargs):
        _write_mock_raw(args[0])
        return subprocess.CompletedProcess(
            args[0], returncode=0, stdout=_success_payload_with_inference_width(), stderr=b""
        )

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", fake_run)

    summary = s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        max_width=2500,
    )

    manifest = summary.manifest
    assert manifest["bundle_extras_carried"] == {"surya_max_width": 2500}
    assert manifest["bundle_extras_carried_keys"] == ["surya_max_width"]
    assert manifest["bundle_extras_jcs_sha256"] != s1_surya_runner.EMPTY_EXTRAS_SHA256


def test_surya_max_width_none_leaves_bundle_extras_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """max_width=None (default) leaves bundle_extras_carried empty."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    _stub_success(monkeypatch)

    summary = s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        max_width=None,
    )

    assert summary.manifest["bundle_extras_carried"] == {}
    assert summary.manifest["bundle_extras_carried_keys"] == []
    assert summary.manifest["bundle_extras_jcs_sha256"] == s1_surya_runner.EMPTY_EXTRAS_SHA256


def test_surya_inference_width_carried_in_page_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """surya_inference_width/scale_to_native emitted by surya_page.py appear in page_extras_carried."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fake_run(*args, **kwargs):
        _write_mock_raw(args[0])
        return subprocess.CompletedProcess(
            args[0], returncode=0, stdout=_success_payload_with_inference_width(), stderr=b""
        )

    monkeypatch.setattr(s1_surya_runner.subprocess, "run", fake_run)

    s1_surya_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        max_width=2500,
    )

    page_path = output_root / "surya-py312-v1" / "vol_01" / "pages" / "page_0001.json"
    page = _read_page(page_path)
    extras = page["page_extras_carried"]
    assert extras.get("surya_inference_width") == 2500
    assert extras.get("surya_scale_to_native") == 2.0136


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


def test_surya_skip_keyed_on_sidecar_not_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skip must fire from a valid on-disk sidecar even when the state file is absent."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    s1_surya_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )
    state_path = output_root / "surya-py312-v1" / "vol_01" / "manifest.state.json"
    state_path.unlink()

    summary = s1_surya_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.skipped_pages == 2, "valid sidecars must cause skip even without state file"
    assert summary.emitted_pages == 0


def test_surya_stale_success_sidecar_is_reprocessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    s1_surya_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )
    page_path = output_root / "surya-py312-v1" / "vol_01" / "pages" / "page_0001.json"
    page = _read_page(page_path)
    page["page_extras_carried"].pop("runner_cache_version")
    page["page_extras_carried_keys"].remove("runner_cache_version")
    page_path.write_text(json.dumps(page), encoding="utf-8")

    summary = s1_surya_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.skipped_pages == 1
    assert summary.emitted_pages == 1
    assert (
        _read_page(page_path)["page_extras_carried"]["runner_cache_version"]
        == s1_surya_runner.S1_SIDECAR_CACHE_VERSION
    )


def test_surya_failed_sidecar_not_skipped_when_state_claims_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sidecar with failure_class must be retried even if the state file lists it as done."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    _stub_success(monkeypatch)

    pages_dir = output_root / "surya-py312-v1" / "vol_01" / "pages"
    _write_minimal_sidecar(pages_dir / "page_0001.json", failure_class="subprocess_error")
    state_path = output_root / "surya-py312-v1" / "vol_01" / "manifest.state.json"
    _write_state_claiming_done(state_path, ["page_0001"])

    summary = s1_surya_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.skipped_pages == 0, "failed sidecar must not be skipped even if state claims done"
    assert summary.emitted_pages == 1, "failed sidecar must be retried and re-emitted"


def test_surya_corrupt_sidecar_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt (unparseable) sidecar must be treated as not-done and retried."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    _stub_success(monkeypatch)

    pages_dir = output_root / "surya-py312-v1" / "vol_01" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "page_0001.json").write_text("not valid json{{", encoding="utf-8")
    state_path = output_root / "surya-py312-v1" / "vol_01" / "manifest.state.json"
    _write_state_claiming_done(state_path, ["page_0001"])

    summary = s1_surya_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.emitted_pages == 1, "corrupt sidecar must be retried, not skipped"
    assert summary.skipped_pages == 0


def test_surya_batch_path_skip_keyed_on_sidecar_not_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Batch path must skip via sidecar alone — same predicate as the single-page path."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=2)
    _stub_batch(monkeypatch)

    s1_surya_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
        batch_size=2,
    )
    state_path = output_root / "surya-py312-v1" / "vol_01" / "manifest.state.json"
    state_path.unlink()

    summary = s1_surya_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
        batch_size=2,
    )

    assert summary.skipped_pages == 2, "batch path must skip via sidecar without state file"
    assert summary.emitted_pages == 0


def test_surya_batch_path_reprocesses_stale_success_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=2)
    _stub_batch(monkeypatch)

    s1_surya_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
        batch_size=2,
    )
    page_path = output_root / "surya-py312-v1" / "vol_01" / "pages" / "page_0001.json"
    page = _read_page(page_path)
    page["page_extras_carried"].pop("runner_cache_version")
    page["page_extras_carried_keys"].remove("runner_cache_version")
    page_path.write_text(json.dumps(page), encoding="utf-8")

    summary = s1_surya_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
        batch_size=2,
    )

    assert summary.skipped_pages == 1
    assert summary.emitted_pages == 1
    assert (
        _read_page(page_path)["page_extras_carried"]["runner_cache_version"]
        == s1_surya_runner.S1_SIDECAR_CACHE_VERSION
    )
