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

from build.parsers import s1_tesseract_runner  # noqa: E402
from build.tools.ocr_runners.tesseract_page import _blocks_from_hocr  # noqa: E402


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
        payload = f"tesseract-page-{index}".encode("utf-8")
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
    # tesseract_page.py writes to stdout.buffer as UTF-8 bytes; mocks must match.
    return json.dumps(
        {
            "ok": True,
            "engine_version": "5.5.0",
            "page_width": 100,
            "page_height": 200,
            "blocks": [
                {
                    "block_id": "b-0001",
                    "block_type": "text",
                    "bbox_native": {"x": 1, "y": 2, "w": 42, "h": 12},
                    "lines": [
                        {
                            "line_id": "l-0001-0001",
                            "source_raw": "Alpha beta",
                            "confidence": 0.87,
                            "bbox_native": {"x": 1, "y": 2, "w": 42, "h": 12},
                            "words": [
                                {
                                    "word_id": "w-0001-0001-0001",
                                    "source_raw": "Alpha",
                                    "confidence": 0.9,
                                    "bbox_native": {"x": 1, "y": 2, "w": 20, "h": 10},
                                },
                                {
                                    "word_id": "w-0001-0001-0002",
                                    "source_raw": "beta",
                                    "confidence": 0.84,
                                    "bbox_native": {"x": 23, "y": 2, "w": 20, "h": 10},
                                },
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
                raw_path.write_bytes(b"<html><body>mock hocr</body></html>")
            yield dict(success_data), None, None

    monkeypatch.setattr(s1_tesseract_runner, "_run_batch", fake_batch)


def _read_page(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def test_tesseract_runner_emits_sidecar_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    summary = s1_tesseract_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    manifest = summary.manifest
    manifest_path = output_root / "tesseract-py314-v1" / "vol_01" / "manifest.json"
    page_paths = sorted((manifest_path.parent / "pages").glob("*.json"))
    assert manifest_path.exists()
    assert len(page_paths) == 2
    jsonschema.validate(instance=manifest, schema=_schema("sidecar-manifest-v1"))
    for page_path in page_paths:
        jsonschema.validate(instance=_read_page(page_path), schema=_schema("sidecar-page-v1"))
    page = _read_page(page_paths[0])
    raw_ref = page["page_extras_carried"]["raw_artifact"]
    assert raw_ref["format"] == "hocr"
    assert (repo_root / raw_ref["path"]).exists()
    assert manifest["engine_family"] == "tesseract"


def test_tesseract_subprocess_failure_recorded_as_failure_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fail_batch(items, **kwargs):
        for _ in items:
            yield None, "subprocess_error", "boom"

    monkeypatch.setattr(s1_tesseract_runner, "_run_batch", fail_batch)

    summary = s1_tesseract_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    page_ref = summary.manifest["pages"][0]
    page = _read_page(output_root / "tesseract-py314-v1" / "vol_01" / "pages" / "page_0001.json")
    assert page["page_extras_carried"]["failure_class"] == "subprocess_error"
    assert page_ref["status"] == "corrupt"
    assert page_ref["failure_class"] == "subprocess_error"


def test_tesseract_runner_resume_skips_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    s1_tesseract_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )
    summary = s1_tesseract_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    assert summary.skipped_pages == 2
    assert summary.emitted_pages == 0


def test_tesseract_distinguishes_leaf_and_printed_page_with_same_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=0)
    volume_dir = input_root / "vol_01"
    front_payload = b"tesseract-leaf-0011"
    body_payload = b"tesseract-page-0011"
    (volume_dir / "leaf_0011.jpg").write_bytes(front_payload)
    (volume_dir / "page_0011.jpg").write_bytes(body_payload)
    # Source manifest: a front-matter leaf (leaf_0011) and a body leaf printed as
    # page 11 (page_0011) so the emitter resolves a required edition_page_key for
    # each -- front matter via the all-section resolver, body via page_num.
    (input_root / "vol_01.manifest.json").write_text(
        json.dumps(
            {
                "leaves": [
                    {
                        "leaf_num": 11,
                        "page_num": None,
                        "kind": "front_matter",
                        "sha256": "sha256:" + hashlib.sha256(front_payload).hexdigest(),
                    },
                    {
                        "leaf_num": 12,
                        "page_num": 11,
                        "kind": "body",
                        "sha256": "sha256:" + hashlib.sha256(body_payload).hexdigest(),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    # Since the P0.5 OCR-gateway fix (R-ocr-glob), volume_image_paths selects OCR
    # input by kind: the bare-dir fallback is body-only (page_*.jpg), so a
    # front-matter leaf is OCR'd only when explicitly opted in via page_order.json.
    # This test exercises that opt-in path to verify the runner still names the
    # leaf_0011 and page_0011 sidecars distinctly (no "0011" collision).
    (volume_dir / "page_order.json").write_text(
        json.dumps(
            {
                "schema": "page-order-v1",
                "pages": [
                    {"seq": 1, "file": "leaf_0011.jpg", "book_page": None,
                     "corpus_role": "front-matter", "scan_status": "present"},
                    {"seq": 2, "file": "page_0011.jpg", "book_page": "11",
                     "corpus_role": "body", "scan_status": "present"},
                ],
            }
        ),
        encoding="utf-8",
    )
    _stub_success(monkeypatch)

    summary = s1_tesseract_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        pages=[11],
    )

    page_refs = summary.manifest["pages"]
    assert {ref["page_native_id"] for ref in page_refs} == {"leaf_0011", "page_0011"}
    assert len({ref["sidecar_page_path"] for ref in page_refs}) == 2
    pages_dir = output_root / "tesseract-py314-v1" / "vol_01" / "pages"
    assert (pages_dir / "leaf_0011.json").exists()
    assert (pages_dir / "page_0011.json").exists()

    token_ids = []
    for page_path in sorted(pages_dir.glob("*.json")):
        page = _read_page(page_path)
        for block in page["blocks"]:
            for line in block["lines"]:
                token_ids.extend(word["observation_token_id"] for word in line["words"])
    assert len(token_ids) == len(set(token_ids))


def test_tesseract_failed_pages_are_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed pages must not be recorded in emitted_pages — they are retried on the next run."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def fail_batch(items, **kwargs):
        for _ in items:
            yield None, "subprocess_error", "boom"

    monkeypatch.setattr(s1_tesseract_runner, "_run_batch", fail_batch)

    s1_tesseract_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )
    summary2 = s1_tesseract_runner.normalize_volume(
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


def test_tesseract_subprocess_timeout_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)

    def timeout_batch(items, **kwargs):
        for _ in items:
            yield None, "subprocess_timeout", "TimeoutExpired: cmd timeout"

    monkeypatch.setattr(s1_tesseract_runner, "_run_batch", timeout_batch)

    summary = s1_tesseract_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    page_ref = summary.manifest["pages"][0]
    page = _read_page(output_root / "tesseract-py314-v1" / "vol_01" / "pages" / "page_0001.json")
    assert page["page_extras_carried"]["failure_class"] == "subprocess_timeout"
    assert page_ref["failure_class"] == "subprocess_timeout"


def test_tesseract_throttle_minimal_passes_env_to_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Overnight throttle env vars and creationflags reach Popen."""
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
                raw_p.write_bytes(b"<html><body>mock hocr</body></html>")
        return FakeProc()

    monkeypatch.setattr(s1_tesseract_runner.subprocess, "Popen", capturing_popen)

    s1_tesseract_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        throttle_mode="minimal-4",
    )

    assert captured_kwargs.get("env", {}).get("OMP_NUM_THREADS") == "4"
    assert captured_kwargs.get("creationflags") == 0x00000040


def test_throttle_canonical_names_and_legacy_aliases() -> None:
    """GUI-style names map to the documented priority classes, and the legacy
    names (overnight/test/none) remain valid aliases of the canonical ones."""
    kw = s1_tesseract_runner._subprocess_kwargs_for_throttle
    # canonical names -> documented priority classes
    assert kw("minimal-4")["creationflags"] == 0x00000040  # IDLE
    assert kw("background-8")["creationflags"] == 0x00004000  # BELOW_NORMAL
    assert kw("background-8")["env"]["OMP_NUM_THREADS"] == "8"
    assert kw("minimal-4")["env"]["OMP_NUM_THREADS"] == "4"
    # full-speed returns no env/priority overrides
    assert kw("full-speed") == {}


_MINIMAL_HOCR = b"""<?xml version="1.0" encoding="UTF-8"?>
<html>
<body>
 <div class='ocr_page'>
  <div class='ocr_carea' id='block_1_1' title='bbox 10 10 500 400'>
   <p class='ocr_par' dir='ltr' title='bbox 10 10 500 60'>
    <span class='ocr_line' id='line_1_1' title='bbox 10 10 500 60; x_size 40; x_descenders 6; x_ascenders 8; baseline 0.001 -5'>
     <span class='ocrx_word' id='word_1_1_1' title='bbox 10 10 120 58; x_wconf 95'>Alpha</span>
     <span class='ocrx_word' id='word_1_1_2' title='bbox 130 10 260 58; x_wconf 89'>beta</span>
    </span>
   </p>
  </div>
 </div>
</body>
</html>"""


def test_blocks_from_hocr_parses_words_and_line_attrs() -> None:
    side_channel: dict = {}
    blocks = _blocks_from_hocr(_MINIMAL_HOCR, _side_channel=side_channel)

    assert len(blocks) == 1
    assert len(blocks[0]["lines"]) == 1
    line = blocks[0]["lines"][0]
    assert line["source_raw"] == "Alpha beta"
    assert len(line["words"]) == 2
    assert line["words"][0]["source_raw"] == "Alpha"
    assert abs(line["words"][0]["confidence"] - 0.95) < 1e-9

    attrs = side_channel.get("tesseract_line_attrs", {})
    assert "l-0001-0001" in attrs
    la = attrs["l-0001-0001"]
    assert la["x_size"] == 40.0
    assert la["baseline"] == [0.001, -5.0]
    assert la["x_descenders"] == 6.0
    assert la["x_ascenders"] == 8.0


def test_blocks_from_hocr_no_side_channel_is_safe() -> None:
    blocks = _blocks_from_hocr(_MINIMAL_HOCR)
    assert len(blocks) == 1


def _success_payload_with_line_attrs() -> bytes:
    return json.dumps(
        {
            "ok": True,
            "engine_version": "5.5.0",
            "page_width": 100,
            "page_height": 200,
            "tesseract_line_attrs": {
                "l-0001-0001": {
                    "x_size": 40.0,
                    "baseline": [0.001, -5.0],
                    "x_descenders": 6.0,
                    "x_ascenders": 8.0,
                }
            },
            "blocks": [
                {
                    "block_id": "b-0001",
                    "block_type": "text",
                    "bbox_native": {"x": 1, "y": 2, "w": 42, "h": 12},
                    "lines": [
                        {
                            "line_id": "l-0001-0001",
                            "source_raw": "Alpha beta",
                            "confidence": 0.87,
                            "bbox_native": {"x": 1, "y": 2, "w": 42, "h": 12},
                            "words": [
                                {
                                    "word_id": "w-0001-0001-0001",
                                    "source_raw": "Alpha",
                                    "confidence": 0.9,
                                    "bbox_native": {"x": 1, "y": 2, "w": 20, "h": 10},
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ).encode("utf-8")


def test_tesseract_line_attrs_in_page_extras_carried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    la_data = json.loads(_success_payload_with_line_attrs())

    def la_batch(items, **kwargs):
        for _img_path, raw_path in items:
            if raw_path is not None:
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(b"<html><body>mock hocr</body></html>")
            yield dict(la_data), None, None

    monkeypatch.setattr(s1_tesseract_runner, "_run_batch", la_batch)

    summary = s1_tesseract_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
    )

    page = _read_page(output_root / "tesseract-py314-v1" / "vol_01" / "pages" / "page_0001.json")
    extras = page["page_extras_carried"]
    assert "tesseract_line_attrs" in extras
    la = extras["tesseract_line_attrs"]["l-0001-0001"]
    assert la["x_size"] == 40.0
    assert la["baseline"] == [0.001, -5.0]
    assert summary.failed_pages == 0


def test_tesseract_pages_subset_selects_exact_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pages=[1, 3] on a 4-image volume processes exactly those two pages."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=4)
    _stub_success(monkeypatch)

    summary = s1_tesseract_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        pages=[1, 3],
    )

    pages_dir = output_root / "tesseract-py314-v1" / "vol_01" / "pages"
    assert summary.emitted_pages == 2
    assert (pages_dir / "page_0001.json").exists()
    assert not (pages_dir / "page_0002.json").exists()
    assert (pages_dir / "page_0003.json").exists()
    assert not (pages_dir / "page_0004.json").exists()
    assert len(summary.manifest["pages"]) == 2
    assert {p["page_sequence"] for p in summary.manifest["pages"]} == {1, 3}


def test_tesseract_pages_none_whole_volume_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pages=None (default) processes all images — regression guard."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=3)
    _stub_success(monkeypatch)

    summary = s1_tesseract_runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=repo_root,
        pages=None,
    )

    assert summary.emitted_pages == 3
    assert summary.failed_pages == 0


def test_tesseract_pages_empty_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pages=[] raises ValueError immediately — no silent no-op (REL-02)."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    with pytest.raises(ValueError, match="non-empty"):
        s1_tesseract_runner.normalize_volume(
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


def test_tesseract_skip_keyed_on_sidecar_not_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skip must fire from a valid on-disk sidecar even when the state file is absent."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    s1_tesseract_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )
    state_path = output_root / "tesseract-py314-v1" / "vol_01" / "manifest.state.json"
    state_path.unlink()

    summary = s1_tesseract_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.skipped_pages == 2, "valid sidecars must cause skip even without state file"
    assert summary.emitted_pages == 0


def test_tesseract_stale_success_sidecar_is_reprocessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, input_root, output_root = _prepare_pages(tmp_path)
    _stub_success(monkeypatch)

    s1_tesseract_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )
    page_path = output_root / "tesseract-py314-v1" / "vol_01" / "pages" / "page_0001.json"
    page = _read_page(page_path)
    page["page_extras_carried"].pop("runner_cache_version")
    page["page_extras_carried_keys"].remove("runner_cache_version")
    page_path.write_text(json.dumps(page), encoding="utf-8")

    summary = s1_tesseract_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.skipped_pages == 1
    assert summary.emitted_pages == 1
    assert (
        _read_page(page_path)["page_extras_carried"]["runner_cache_version"]
        == s1_tesseract_runner.S1_SIDECAR_CACHE_VERSION
    )


def test_tesseract_failed_sidecar_not_skipped_when_state_claims_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sidecar with failure_class must be retried even if the state file lists it as done."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    _stub_success(monkeypatch)

    pages_dir = output_root / "tesseract-py314-v1" / "vol_01" / "pages"
    _write_minimal_sidecar(pages_dir / "page_0001.json", failure_class="subprocess_error")
    state_path = output_root / "tesseract-py314-v1" / "vol_01" / "manifest.state.json"
    _write_state_claiming_done(state_path, ["page_0001"])

    summary = s1_tesseract_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.skipped_pages == 0, "failed sidecar must not be skipped even if state claims done"
    assert summary.emitted_pages == 1, "failed sidecar must be retried and re-emitted"


def test_tesseract_corrupt_sidecar_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt (unparseable) sidecar must be treated as not-done and retried."""
    repo_root, input_root, output_root = _prepare_pages(tmp_path, count=1)
    _stub_success(monkeypatch)

    pages_dir = output_root / "tesseract-py314-v1" / "vol_01" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "page_0001.json").write_text("not valid json{{", encoding="utf-8")
    state_path = output_root / "tesseract-py314-v1" / "vol_01" / "manifest.state.json"
    _write_state_claiming_done(state_path, ["page_0001"])

    summary = s1_tesseract_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    assert summary.emitted_pages == 1, "corrupt sidecar must be retried, not skipped"
    assert summary.skipped_pages == 0


def test_recovered_gap_page_is_silent_and_edition_keyed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A recovered-gap page (sha in gaps[], not a body leaf) must OCR cleanly:
    no 'leaf unresolved'/'NEITHER' warning in the log, and its sidecar carries
    an edition_page_key while being clid-exempt (no canonical_leaf_id). This is
    the vol_01 page-96 case the old unconditional warning made look broken."""
    repo_root = tmp_path / "repo"
    input_root = repo_root / "raw" / "internet-archive" / "schaff-herzog-pages"
    volume_dir = input_root / "vol_01"
    output_root = repo_root / "reports" / "s1-sidecars"
    volume_dir.mkdir(parents=True)

    body_bytes = b"tesseract-body-1"
    gap_bytes = b"tesseract-gap-96"
    (volume_dir / "page_0001.jpg").write_bytes(body_bytes)
    (volume_dir / "page_0096.jpg").write_bytes(gap_bytes)
    body_sha = "sha256:" + hashlib.sha256(body_bytes).hexdigest()
    gap_sha = "sha256:" + hashlib.sha256(gap_bytes).hexdigest()

    (input_root / "vol_01.manifest.json").write_text(
        json.dumps(
            {
                "leaves": [
                    {"leaf_num": 1, "page_num": 1, "kind": "body", "sha256": body_sha}
                ],
                "gaps": [{"page_num": 96, "sha256": gap_sha, "status": "resolved"}],
            }
        ),
        encoding="utf-8",
    )

    # Feed both the body page and the recovered-gap page to OCR (production does
    # this via volume_image_paths + page_order.json; bypass that plumbing here).
    monkeypatch.setattr(
        s1_tesseract_runner,
        "_image_paths",
        lambda input_root, volume: [
            volume_dir / "page_0001.jpg",
            volume_dir / "page_0096.jpg",
        ],
    )
    _stub_success(monkeypatch)

    s1_tesseract_runner.normalize_volume(
        volume=1, input_root=input_root, output_root=output_root, repo_root=repo_root,
    )

    out = capsys.readouterr().out
    assert "leaf unresolved" not in out, "old scary wording must be gone"
    assert "NEITHER" not in out, "a properly edition-keyed gap page must not warn"

    pages_dir = output_root / "tesseract-py314-v1" / "vol_01" / "pages"
    gap_sidecar = _read_page(pages_dir / "page_0096.json")
    assert gap_sidecar["edition_page_key"] == {
        "section": "body",
        "anchor": 96,
        "ordinal": 0,
    }
    assert "canonical_leaf_id" not in gap_sidecar
    assert gap_sidecar.get("clid_exempt") is True
