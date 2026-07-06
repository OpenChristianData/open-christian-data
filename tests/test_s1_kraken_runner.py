from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from build.parsers import s1_kraken_runner  # noqa: E402
from build.parsers.s1_kraken_runner import _preflight_kraken_models as _real_preflight_kraken_models  # noqa: E402


@pytest.fixture(autouse=True)
def _skip_kraken_model_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s1_kraken_runner, "_preflight_kraken_models", lambda: None)


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
        payload = f"kraken-page-{index}".encode("utf-8")
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
    # kraken_page.py writes to stdout.buffer as UTF-8 bytes; mocks must match.
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
    """Mock _run_batch to yield success payloads and write raw output stubs."""
    success_data = json.loads(_success_payload())

    def fake_batch(items, **kwargs):
        for _img_path, raw_path in items:
            if raw_path is not None:
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text('{"engine_family":"kraken","mock":true}', encoding="utf-8")
            yield dict(success_data), None, None

    monkeypatch.setattr(s1_kraken_runner, "_run_batch", fake_batch)


def _read_page(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def test_kraken_runner_emits_sidecar_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    summary = s1_kraken_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    manifest = summary.manifest
    manifest_path = output_root / "kraken-py312-v1" / "vol_01" / "manifest.json"
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
    assert manifest["engine_family"] == "kraken"


def test_kraken_runner_raises_if_model_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    import build.parsers.s1_kraken_runner as m

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
    # Preflight failure must not bake any pages into state
    assert not (output_root / "kraken-py312-v1").exists()


def test_kraken_subprocess_failure_recorded_as_failure_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fail_batch(items, **kwargs):
        for _ in items:
            yield None, "subprocess_error", "boom"

    monkeypatch.setattr(s1_kraken_runner, "_run_batch", fail_batch)

    summary = s1_kraken_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    page_ref = summary.manifest["pages"][0]
    page = _read_page(output_root / "kraken-py312-v1" / "vol_01" / "pages" / "page_0001.json")
    assert page["page_extras_carried"]["failure_class"] == "subprocess_error"
    assert page_ref["status"] == "corrupt"
    assert page_ref["failure_class"] == "subprocess_error"


def test_kraken_runner_resume_skips_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    s1_kraken_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )
    summary = s1_kraken_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    assert summary.skipped_pages == 2
    assert summary.emitted_pages == 0


def test_kraken_failed_pages_are_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed pages must not be recorded in emitted_pages — they are retried on the next run."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fail_batch(items, **kwargs):
        for _ in items:
            yield None, "subprocess_error", "boom"

    monkeypatch.setattr(s1_kraken_runner, "_run_batch", fail_batch)

    s1_kraken_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )
    # Second run: page still failed on first run, so it must be retried (not skipped).
    summary2 = s1_kraken_runner.normalize_volume(
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


def test_kraken_subprocess_timeout_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def timeout_batch(items, **kwargs):
        for _ in items:
            yield None, "subprocess_timeout", "TimeoutExpired: cmd timeout"

    monkeypatch.setattr(s1_kraken_runner, "_run_batch", timeout_batch)

    summary = s1_kraken_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    page_ref = summary.manifest["pages"][0]
    page = _read_page(output_root / "kraken-py312-v1" / "vol_01" / "pages" / "page_0001.json")
    assert page["page_extras_carried"]["failure_class"] == "subprocess_timeout"
    assert page_ref["failure_class"] == "subprocess_timeout"


def test_run_batch_per_page_timeout_kills_hung_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_run_batch enforces per-page timeout: hung subprocess is killed, error written to state.

    Verifies the thread-based timeout mechanism in _run_batch itself (not just the
    higher-level normalize_volume timeout handling). Uses a real pipe whose write end
    is never written to, so the reader thread blocks until kill() closes it.
    """
    img = tmp_path / "page_0001.jpg"
    img.write_bytes(b"")

    r_fd, w_fd = os.pipe()

    class _HangProc:
        stdout = os.fdopen(r_fd, "rb", 0)  # blocks until write end closed
        stderr = io.BytesIO(b"")
        returncode = -1

        def wait(self, timeout: float | None = None) -> int:
            if timeout is not None:
                raise subprocess.TimeoutExpired("cmd", timeout)
            return self.returncode

        def kill(self) -> None:
            try:
                os.close(w_fd)  # EOF on read end -> reader thread exits
            except OSError:
                pass

        def poll(self) -> int | None:
            return None  # still running

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: _HangProc())

    t0 = time.monotonic()
    results = list(s1_kraken_runner._run_batch([(img, None)], timeout_per_page=1))
    elapsed = time.monotonic() - t0

    assert elapsed < 5.0, f"timeout did not fire promptly ({elapsed:.1f}s)"
    assert len(results) == 1
    payload, failure_class, error = results[0]
    assert payload is None
    assert failure_class == "subprocess_timeout_batch"
    assert error is not None and "killed" in error


def test_run_batch_shutdown_kills_hung_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A graceful pipeline stop must kill the active Kraken worker promptly."""
    img = tmp_path / "page_0001.jpg"
    img.write_bytes(b"")

    r_fd, w_fd = os.pipe()
    killed = False

    class _HangProc:
        stdout = os.fdopen(r_fd, "rb", 0)
        stderr = io.BytesIO(b"")
        returncode = -1

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode

        def kill(self) -> None:
            nonlocal killed
            killed = True
            try:
                os.close(w_fd)
            except OSError:
                pass

        def poll(self) -> int | None:
            return None

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: _HangProc())
    shutdown_event = threading.Event()
    shutdown_event.set()

    t0 = time.monotonic()
    with pytest.raises(s1_kraken_runner._ShutdownRequested):
        list(s1_kraken_runner._run_batch(
            [(img, None)],
            timeout_per_page=600,
            shutdown_event=shutdown_event,
        ))
    elapsed = time.monotonic() - t0

    assert elapsed < 5.0, f"shutdown did not fire promptly ({elapsed:.1f}s)"
    assert killed


def test_run_batch_respects_max_pages_chunking(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """_run_batch restarts the subprocess after max_pages items, not just on timeout.

    With max_pages=3 and 7 items, we expect _run_chunk to be called at least twice —
    once for the first 3 items and at least once for the remainder. Each call to
    _run_chunk represents one subprocess lifetime.
    """
    chunk_sizes: list[int] = []

    real_run_chunk = s1_kraken_runner._run_chunk

    def tracking_run_chunk(items, *args, **kwargs):
        chunk_sizes.append(len(items))
        for _ in items:
            yield {"ok": True, "blocks": [], "page_width": 100, "page_height": 100}, None, None

    monkeypatch.setattr(s1_kraken_runner, "_run_chunk", tracking_run_chunk)

    imgs = [tmp_path / f"page_{i:04d}.jpg" for i in range(7)]
    for img in imgs:
        img.write_bytes(b"")

    results = list(s1_kraken_runner._run_batch(
        [(img, None) for img in imgs],
        timeout_per_page=300,
        max_pages=3,
    ))

    assert len(results) == 7, f"expected 7 results, got {len(results)}"
    assert all(r[1] is None for r in results), "unexpected failures"
    # 7 items with max_pages=3 → chunks of 3, 3, 1
    assert chunk_sizes == [3, 3, 1], f"unexpected chunk sizes: {chunk_sizes}"


def test_run_batch_max_pages_timeout_continues_correctly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """After a timeout within a chunk, remaining items get a new subprocess (not abandoned).

    5 items, max_pages=3: first chunk is [0,1,2]. Item 1 times out.
    _run_batch should restart with [2] + [3,4] = items 2,3,4 in the next chunk.
    Total results = 5: item 0 (ok), item 1 (timeout), items 2-4 (ok).
    """
    call_log: list[list[int]] = []
    imgs = [tmp_path / f"page_{i:04d}.jpg" for i in range(5)]
    for img in imgs:
        img.write_bytes(b"")
    img_indices = {img: i for i, img in enumerate(imgs)}

    def controlled_run_chunk(items, *args, **kwargs):
        indices = [img_indices[img] for img, _ in items]
        call_log.append(indices)
        for img, _ in items:
            idx = img_indices[img]
            if idx == 1:
                yield None, "subprocess_timeout_batch", "hung"
                return  # _run_chunk stops after the timeout
            yield {"ok": True, "blocks": [], "page_width": 100, "page_height": 100}, None, None

    monkeypatch.setattr(s1_kraken_runner, "_run_chunk", controlled_run_chunk)

    results = list(s1_kraken_runner._run_batch(
        [(img, None) for img in imgs],
        timeout_per_page=300,
        max_pages=3,
    ))

    assert len(results) == 5
    assert results[0][1] is None       # item 0: ok
    assert results[1][1] == "subprocess_timeout_batch"  # item 1: timeout
    assert results[2][1] is None       # item 2: ok (new subprocess)
    assert results[3][1] is None       # item 3: ok
    assert results[4][1] is None       # item 4: ok
    # First chunk: [0,1,2], timeout at 1 → restart with [2,3,4] (fits in max_pages=3)
    assert call_log[0] == [0, 1, 2]
    assert call_log[1] == [2, 3, 4]


def test_kraken_throttle_minimal_passes_env_to_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """minimal-4 throttle env vars and creationflags reach Popen."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    captured_kwargs: dict = {}
    success_data = json.loads(_success_payload())

    class FakeProc:
        stdout = iter([json.dumps(success_data).encode("utf-8") + b"\n"])
        stderr = iter([])
        returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            pass

        def poll(self):
            return self.returncode

    def capturing_popen(cmd, *args, **kwargs):
        captured_kwargs.update(kwargs)
        # Write raw stubs so _raw_artifact_ref can hash them.
        manifest_path = Path(cmd[cmd.index("--batch-manifest-file") + 1])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest:
            if entry.get("raw_output"):
                raw_p = Path(entry["raw_output"])
                raw_p.parent.mkdir(parents=True, exist_ok=True)
                raw_p.write_text('{"engine_family":"kraken","mock":true}', encoding="utf-8")
        return FakeProc()

    monkeypatch.setattr(s1_kraken_runner.subprocess, "Popen", capturing_popen)

    s1_kraken_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        throttle_mode="minimal-4",
    )

    assert captured_kwargs.get("env", {}).get("OMP_NUM_THREADS") == "4"
    assert captured_kwargs.get("creationflags") == 0x00000040


def _success_payload_with_side_channel() -> bytes:
    return json.dumps(
        {
            "ok": True,
            "engine_version": "1.4.2",
            "model_id": "test-model",
            "page_width": 100,
            "page_height": 200,
            "kraken_char_confidences": {"l-0001-0001": [0.9, 0.8, 0.95]},
            "kraken_line_polygons": {
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


def test_kraken_side_channel_in_page_extras_carried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    sc_data = json.loads(_success_payload_with_side_channel())

    def sc_batch(items, **kwargs):
        for _img_path, raw_path in items:
            if raw_path is not None:
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text('{"engine_family":"kraken","mock":true}', encoding="utf-8")
            yield dict(sc_data), None, None

    monkeypatch.setattr(s1_kraken_runner, "_run_batch", sc_batch)

    summary = s1_kraken_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    page = _read_page(output_root / "kraken-py312-v1" / "vol_01" / "pages" / "page_0001.json")
    extras = page["page_extras_carried"]
    assert extras["kraken_char_confidences"] == {"l-0001-0001": [0.9, 0.8, 0.95]}
    assert "l-0001-0001" in extras["kraken_line_polygons"]
    assert len(extras["kraken_line_polygons"]["l-0001-0001"]) == 4
    assert summary.failed_pages == 0


def test_kraken_preflight_rejects_zero_byte_model(tmp_path: Path) -> None:
    model_dir = tmp_path / "kraken-models"
    model_dir.mkdir()
    (model_dir / "model.mlmodel").write_bytes(b"")

    with pytest.raises(RuntimeError, match="zero bytes"):
        _real_preflight_kraken_models(_model_dir=model_dir)


def test_kraken_preflight_accepts_nonempty_model(tmp_path: Path) -> None:
    model_dir = tmp_path / "kraken-models"
    model_dir.mkdir()
    (model_dir / "model.mlmodel").write_bytes(b"data")

    _real_preflight_kraken_models(_model_dir=model_dir)  # must not raise


def test_kraken_pages_subset_selects_exact_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pages=[1, 3] on a 4-image volume processes exactly those two pages."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=4)
    _stub_success(monkeypatch)

    summary = s1_kraken_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        pages=[1, 3],
    )

    pages_dir = output_root / "kraken-py312-v1" / "vol_01" / "pages"
    assert summary.emitted_pages == 2
    assert (pages_dir / "page_0001.json").exists()
    assert not (pages_dir / "page_0002.json").exists()
    assert (pages_dir / "page_0003.json").exists()
    assert not (pages_dir / "page_0004.json").exists()
    assert {p["page_sequence"] for p in summary.manifest["pages"]} == {1, 3}


def test_kraken_pages_none_whole_volume_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pages=None (default) processes all images — regression guard."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=3)
    _stub_success(monkeypatch)

    summary = s1_kraken_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        pages=None,
    )

    assert summary.emitted_pages == 3
    assert summary.failed_pages == 0


def test_kraken_pages_empty_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pages=[] raises ValueError immediately — no silent no-op (REL-02)."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    with pytest.raises(ValueError, match="non-empty"):
        s1_kraken_runner.normalize_volume(
            volume=1,
            input_root=input_root,
            output_root=output_root,
            repo_root=repo_root,
            pages=[],
        )


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


def test_kraken_skip_keyed_on_sidecar_not_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skip must fire from a valid on-disk sidecar even when the state file is absent."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    s1_kraken_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )
    state_path = output_root / "kraken-py312-v1" / "vol_01" / "manifest.state.json"
    state_path.unlink()

    summary = s1_kraken_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.skipped_pages == 2, "valid sidecars must cause skip even without state file"
    assert summary.emitted_pages == 0


def test_kraken_stale_success_sidecar_is_reprocessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    s1_kraken_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )
    page_path = output_root / "kraken-py312-v1" / "vol_01" / "pages" / "page_0001.json"
    page = _read_page(page_path)
    page["page_extras_carried"].pop("runner_cache_version")
    page["page_extras_carried_keys"].remove("runner_cache_version")
    page_path.write_text(json.dumps(page), encoding="utf-8")

    summary = s1_kraken_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.skipped_pages == 1
    assert summary.emitted_pages == 1
    assert (
        _read_page(page_path)["page_extras_carried"]["runner_cache_version"]
        == s1_kraken_runner.S1_SIDECAR_CACHE_VERSION
    )


def test_kraken_failed_sidecar_not_skipped_when_state_claims_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sidecar with failure_class must be retried even if the state file lists it as done."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    _stub_success(monkeypatch)

    pages_dir = output_root / "kraken-py312-v1" / "vol_01" / "pages"
    _write_minimal_sidecar(pages_dir / "page_0001.json", failure_class="subprocess_error")
    state_path = output_root / "kraken-py312-v1" / "vol_01" / "manifest.state.json"
    _write_state_claiming_done(state_path, ["page_0001"])

    summary = s1_kraken_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.skipped_pages == 0, "failed sidecar must not be skipped even if state claims done"
    assert summary.emitted_pages == 1, "failed sidecar must be retried and re-emitted"


def test_kraken_corrupt_sidecar_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt (unparseable) sidecar must be treated as not-done and retried."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    _stub_success(monkeypatch)

    pages_dir = output_root / "kraken-py312-v1" / "vol_01" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "page_0001.json").write_text("not valid json{{", encoding="utf-8")
    state_path = output_root / "kraken-py312-v1" / "vol_01" / "manifest.state.json"
    _write_state_claiming_done(state_path, ["page_0001"])

    summary = s1_kraken_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.emitted_pages == 1, "corrupt sidecar must be retried, not skipped"
    assert summary.skipped_pages == 0
