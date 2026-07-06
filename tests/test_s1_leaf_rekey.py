"""R2 S1 leaf-rekey tests.

Opt-in real-engine check:
OCD_S1_ENGINE_EQUIV=1 py -3 -m pytest -p no:cacheprovider tests/test_s1_leaf_rekey.py -k engine_equiv -q
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from build.lib.edition_page_key import body_edition_key  # noqa: E402
from build.lib.engine_inventory import ENGINE_SPECS, venv_python  # noqa: E402
from build.lib.nsh_leaf_model import resolve_leaf  # noqa: E402
from build.parsers import (  # noqa: E402
    s1_kraken_greek_runner,
    s1_kraken_runner,
    s1_surya_runner,
    s1_tesseract_runner,
)

SHA = "sha256:" + "a" * 64

RUNNERS = [
    pytest.param(s1_tesseract_runner, ".tesseract.hocr", id="tesseract"),
    pytest.param(s1_kraken_runner, ".kraken.raw.json", id="kraken"),
    pytest.param(s1_surya_runner, ".surya.raw.json", id="surya"),
    pytest.param(s1_kraken_greek_runner, ".kraken-greek.raw.json", id="kraken-greek"),
]


def _payload() -> dict:
    return {
        "ok": True,
        "engine_version": "test-engine",
        "page_width": 100,
        "page_height": 200,
        "blocks": [
            {
                "block_id": "b-1",
                "block_type": "text",
                "bbox_native": {"x": 1, "y": 1, "w": 50, "h": 20},
                "lines": [
                    {
                        "line_id": "l-1-1",
                        "source_raw": "Alpha beta",
                        "confidence": 0.9,
                        "bbox_native": {"x": 1, "y": 1, "w": 40, "h": 10},
                        "words": [
                            {
                                "word_id": "w-1-1-1",
                                "source_raw": "Alpha",
                                "confidence": 0.9,
                                "bbox_native": {"x": 1, "y": 1, "w": 10, "h": 10},
                            },
                            {
                                "word_id": "w-1-1-2",
                                "source_raw": "beta",
                                "confidence": 0.8,
                                "bbox_native": {"x": 12, "y": 1, "w": 10, "h": 10},
                            },
                        ],
                    },
                    {
                        "line_id": "l-1-2",
                        "source_raw": "Gamma",
                        "confidence": 0.7,
                        "bbox_native": {"x": 1, "y": 12, "w": 40, "h": 10},
                        "words": [
                            {
                                "word_id": "w-1-2-1",
                                "source_raw": "Gamma",
                                "confidence": 0.7,
                                "bbox_native": {"x": 1, "y": 12, "w": 10, "h": 10},
                            }
                        ],
                    },
                ],
            },
            {
                "block_id": "b-2",
                "block_type": "text",
                "bbox_native": {"x": 1, "y": 30, "w": 50, "h": 20},
                "lines": [
                    {
                        "line_id": "l-2-1",
                        "source_raw": "Delta",
                        "confidence": 0.6,
                        "bbox_native": {"x": 1, "y": 30, "w": 40, "h": 10},
                        "words": [
                            {
                                "word_id": "w-2-1-1",
                                "source_raw": "Delta",
                                "confidence": 0.6,
                                "bbox_native": {"x": 1, "y": 30, "w": 10, "h": 10},
                            }
                        ],
                    }
                ],
            },
        ],
    }


def _source_manifest_for_sha(sha: str) -> dict[str, Any]:
    return {
        "schema_version": "source-manifest-v1",
        "leaves": [
            {
                "leaf_num": 54,
                "page_num": 7,
                "kind": "body",
                "image_state": "present",
                "sha256": sha,
                "source_path": "vol_01/page_0007.jpg",
            },
            {
                "leaf_num": 55,
                "page_num": 8,
                "kind": "body",
                "image_state": "present",
                "sha256": "sha256:" + "f" * 64,
                "source_path": "vol_01/page_0008.jpg",
            },
        ],
        "gaps": [],
    }


def _identity_record(runner, *, manifest_id: str, leaf: int, page_id: str, sequence: int) -> dict:
    record = runner._page_record(
        manifest_id=manifest_id,
        page_native_id=page_id,
        page_sequence=sequence,
        source_payload_sha256=SHA,
        subprocess_payload=_payload(),
        raw_artifact=None,
        canonical_leaf_id=leaf,
    )
    # edition_page_key is now schema-required on every sidecar-page-v1 record, and
    # rekey_sidecar preserves it (a page's edition identity is invariant under a
    # file rename). A fixed body key keeps stale/fresh/rekeyed byte-identical so
    # the rekey equality assertions hold.
    record["edition_page_key"] = body_edition_key(7)
    return record


@pytest.mark.parametrize("runner,_suffix", RUNNERS)
def test_observed_blocks_preserve_1_to_1_structure(runner, _suffix: str) -> None:
    payload = _payload()

    observed = runner._observed_blocks(
        payload,
        canonical_leaf_id=54,
        page_native_id="page_0050",
        page_sequence=50,
    )

    assert [len(block["lines"]) for block in observed] == [2, 1]
    assert [
        [len(line["words"]) for line in block["lines"]]
        for block in observed
    ] == [[2, 1], [1]]


@pytest.mark.parametrize("runner,_suffix", RUNNERS)
def test_observed_blocks_reseed_from_canonical_leaf_id(runner, _suffix: str) -> None:
    observed = runner._observed_blocks(
        _payload(),
        canonical_leaf_id=54,
        page_native_id="page_0050",
        page_sequence=50,
    )

    for block_index, block in enumerate(observed, start=1):
        for line_index, line in enumerate(block["lines"], start=1):
            for word_index, word in enumerate(line["words"], start=1):
                expected = runner._observation_token_id(
                    runner._word_token_seed(
                        54,
                        "page_0050",
                        50,
                        block_index,
                        line_index,
                        word_index,
                        word["source_raw"],
                        word["bbox_native"],
                    )
                )
                assert word["observation_token_id"] == expected


@pytest.mark.parametrize("runner,_suffix", RUNNERS)
def test_rekey_sidecar_matches_fresh_page_record(runner, _suffix: str) -> None:
    fresh = _identity_record(
        runner,
        manifest_id="manifest-L",
        leaf=54,
        page_id="page_0050",
        sequence=50,
    )
    stale = _identity_record(
        runner,
        manifest_id="manifest-M",
        leaf=99,
        page_id="page_0048",
        sequence=48,
    )

    rekeyed = runner.rekey_sidecar(
        stale,
        canonical_leaf_id=54,
        page_native_id="page_0050",
        page_sequence=50,
        manifest_id="manifest-L",
        raw_artifact_new_path=None,
    )

    assert rekeyed == fresh


@pytest.mark.parametrize("runner,suffix", RUNNERS)
def test_rekey_sidecar_updates_raw_artifact_path_and_extras_hash(runner, suffix: str) -> None:
    raw_artifact = {"path": f"raw/old{suffix}", "sha256": "sha256:" + "b" * 64}
    record = runner._page_record(
        manifest_id="manifest-M",
        page_native_id="page_0048",
        page_sequence=48,
        source_payload_sha256=SHA,
        subprocess_payload=_payload(),
        raw_artifact=raw_artifact,
        canonical_leaf_id=99,
    )
    record["edition_page_key"] = body_edition_key(7)

    rekeyed = runner.rekey_sidecar(
        record,
        canonical_leaf_id=54,
        page_native_id="page_0050",
        page_sequence=50,
        manifest_id="manifest-L",
        raw_artifact_new_path=f"raw/new{suffix}",
    )

    raw_ref = rekeyed["page_extras_carried"]["raw_artifact"]
    assert raw_ref["path"] == f"raw/new{suffix}"
    assert raw_ref["sha256"] == raw_artifact["sha256"]
    assert rekeyed["page_extras_jcs_sha256"] == runner._extras_hash(rekeyed["page_extras_carried"])
    assert rekeyed["page_extras_carried_keys"] == sorted(rekeyed["page_extras_carried"])


@pytest.mark.parametrize("runner,_suffix", RUNNERS)
def test_rekey_sidecar_is_pure_and_does_not_call_engine(
    runner, _suffix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _identity_record(
        runner,
        manifest_id="manifest-M",
        leaf=99,
        page_id="page_0048",
        sequence=48,
    )
    before = copy.deepcopy(record)

    # "does not call engine": OCR always runs through a subprocess. Make any
    # subprocess invocation fail loudly so a rekey that touched the engine is
    # caught here, not just asserted by the test's name.
    import subprocess as _subprocess

    def _no_subprocess(*_a, **_k):
        raise AssertionError("rekey_sidecar must not invoke an OCR subprocess")

    monkeypatch.setattr(_subprocess, "run", _no_subprocess)
    monkeypatch.setattr(_subprocess, "Popen", _no_subprocess)

    rekeyed = runner.rekey_sidecar(
        record,
        canonical_leaf_id=54,
        page_native_id="page_0050",
        page_sequence=50,
        manifest_id="manifest-L",
        raw_artifact_new_path=None,
    )

    assert record == before
    assert rekeyed is not record


@pytest.mark.parametrize("runner,_suffix", RUNNERS)
def test_sidecar_done_gate_includes_leaf_and_sha(runner, _suffix: str, tmp_path: Path) -> None:
    page_path = tmp_path / "page_0050.json"
    record = _identity_record(
        runner,
        manifest_id="manifest-L",
        leaf=54,
        page_id="page_0050",
        sequence=50,
    )
    page_path.write_text(json.dumps(record), encoding="utf-8")

    assert runner._sidecar_is_done(
        page_path,
        canonical_leaf_id=54,
        source_payload_sha256=SHA,
    )
    assert not runner._sidecar_is_done(
        page_path,
        canonical_leaf_id=55,
        source_payload_sha256=SHA,
    )


def test_nsh_runner_stamps_edition_page_key_on_record_and_page_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = s1_tesseract_runner
    input_root = tmp_path / "raw"
    output_root = tmp_path / "reports" / "s1-sidecars"
    volume_dir = input_root / "vol_01"
    volume_dir.mkdir(parents=True)
    matched = volume_dir / "page_0007.jpg"
    matched.write_bytes(b"matched image")
    matched_sha = runner._prefixed_sha256_bytes(matched.read_bytes())
    (input_root / "vol_01.manifest.json").write_text(
        json.dumps(_source_manifest_for_sha(matched_sha)),
        encoding="utf-8",
    )

    def _fake_run_batch(items, *_args, **_kwargs):
        for _image_path, raw_path in items:
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text("raw", encoding="utf-8")
            yield _payload(), None, None

    monkeypatch.setattr(runner, "_run_batch", _fake_run_batch)

    summary = runner.normalize_volume(
        volume=1,
        input_root=input_root,
        output_root=output_root,
        repo_root=tmp_path,
    )

    page_by_id = {page["page_native_id"]: page for page in summary.manifest["pages"]}
    matched_record = json.loads(
        (output_root / runner.SOURCE_LINEAGE_ID / "vol_01" / "pages" / "page_0007.json").read_text(
            encoding="utf-8"
        )
    )

    expected = {"section": "body", "anchor": 7, "ordinal": 0}
    assert matched_record["edition_page_key"] == expected
    assert page_by_id["page_0007"]["edition_page_key"] == expected

    # Required-everywhere (no exempt branch): a page whose sha resolves to no
    # manifest leaf/gap cannot be assigned the now-required edition_page_key, so
    # the run fails closed at schema validation rather than emitting a keyless
    # page (the pre-flip behavior, which the optional field used to allow).
    unmatched = volume_dir / "page_0008.jpg"
    unmatched.write_bytes(b"unmatched image")
    with pytest.raises(jsonschema.exceptions.ValidationError):
        runner.normalize_volume(
            volume=1,
            input_root=input_root,
            output_root=output_root,
            repo_root=tmp_path,
        )


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("OCD_S1_ENGINE_EQUIV") != "1", reason="set OCD_S1_ENGINE_EQUIV=1")
@pytest.mark.parametrize("runner,suffix", RUNNERS)
def test_engine_equiv_real_pages_opt_in(runner, suffix: str, tmp_path: Path) -> None:
    volume = 11
    input_root = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
    manifest_path = input_root / f"vol_{volume:02d}.manifest.json"
    volume_dir = input_root / f"vol_{volume:02d}"
    if not manifest_path.exists() or not volume_dir.exists():
        pytest.skip("real NSH images absent")
    spec_name = getattr(runner, "ENGINE_SPEC_NAME", runner.ENGINE_FAMILY)
    spec = next((candidate for candidate in ENGINE_SPECS if candidate.name == spec_name), None)
    if spec is None or not venv_python(spec).exists():
        pytest.skip(f"{spec_name} engine venv absent")
    images = sorted(volume_dir.glob("page_*.jpg"))[:3]
    if len(images) < 3:
        pytest.skip("fewer than three real page images available")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for image in images:
        sha = runner._prefixed_sha256_bytes(image.read_bytes())
        leaf_num, _page_num, _stem = resolve_leaf(manifest, sha)
        raw_path = tmp_path / f"{image.stem}{suffix}"
        if runner is s1_surya_runner:
            payload, failure_class, error = runner._run_page(
                image,
                runner.SUBPROCESS_TIMEOUT,
                raw_output_path=raw_path,
            )
        else:
            payload, failure_class, error = runner._run_page(
                image,
                runner.SUBPROCESS_TIMEOUT,
                raw_output_path=raw_path,
            )
        if failure_class:
            pytest.skip(f"engine failed on {image.name}: {failure_class} {error}")
        fresh = runner._page_record(
            manifest_id="manifest-L",
            page_native_id=image.stem,
            page_sequence=leaf_num,
            source_payload_sha256=sha,
            subprocess_payload=payload,
            raw_artifact=None,
            canonical_leaf_id=leaf_num,
        )
        stale = runner._page_record(
            manifest_id="manifest-M",
            page_native_id="page_0001",
            page_sequence=1,
            source_payload_sha256=sha,
            subprocess_payload=payload,
            raw_artifact=None,
            canonical_leaf_id=1,
        )
        assert runner.rekey_sidecar(
            stale,
            canonical_leaf_id=leaf_num,
            page_native_id=image.stem,
            page_sequence=leaf_num,
            manifest_id="manifest-L",
            raw_artifact_new_path=None,
        ) == fresh


@pytest.mark.parametrize("runner,_suffix", RUNNERS)
def test_sidecar_done_gate_none_leaf_does_not_invalidate_stamped(runner, _suffix: str, tmp_path: Path) -> None:
    """C1 / Sync-rename guard: when the current leaf cannot be resolved
    (canonical_leaf_id None -- e.g. the source manifest is transiently absent or
    renamed), the gate must NOT invalidate an already-stamped sidecar, else a
    manifest rename would re-OCR a fully migrated volume."""
    page_path = tmp_path / "page_0050.json"
    stamped = _identity_record(runner, manifest_id="manifest-L", leaf=54, page_id="page_0050", sequence=50)
    page_path.write_text(json.dumps(stamped), encoding="utf-8")

    assert runner._sidecar_is_done(page_path, canonical_leaf_id=None, source_payload_sha256=SHA)
    # sha mismatch is still not-done even with an unresolved (None) leaf
    assert not runner._sidecar_is_done(
        page_path, canonical_leaf_id=None, source_payload_sha256="sha256:" + "c" * 64
    )


@pytest.mark.parametrize("runner,_suffix", RUNNERS)
def test_sidecar_done_gate_unstamped_sidecar_with_none_leaf(runner, _suffix: str, tmp_path: Path) -> None:
    """An unstamped sidecar (no canonical_leaf_id, manifest-less volume) is 'done'
    under a None current leaf on sha match -- existing resume behavior is preserved."""
    page_path = tmp_path / "page_0050.json"
    rec = runner._page_record(
        manifest_id="m",
        page_native_id="page_0050",
        page_sequence=50,
        source_payload_sha256=SHA,
        subprocess_payload=_payload(),
        raw_artifact=None,
        canonical_leaf_id=None,
    )
    assert "canonical_leaf_id" not in rec
    page_path.write_text(json.dumps(rec), encoding="utf-8")

    assert runner._sidecar_is_done(page_path, canonical_leaf_id=None, source_payload_sha256=SHA)


@pytest.mark.parametrize("runner,_suffix", RUNNERS)
def test_sidecar_done_gate_leaf_correction_forces_reemit(runner, _suffix: str, tmp_path: Path) -> None:
    """C5: a stamped sidecar whose stored leaf disagrees with a DEFINITE current
    leaf (the manifest corrected the leaf) is NOT done -- it must re-emit."""
    page_path = tmp_path / "page_0050.json"
    stamped = _identity_record(runner, manifest_id="manifest-L", leaf=54, page_id="page_0050", sequence=50)
    page_path.write_text(json.dumps(stamped), encoding="utf-8")

    assert not runner._sidecar_is_done(page_path, canonical_leaf_id=55, source_payload_sha256=SHA)
    assert runner._sidecar_is_done(page_path, canonical_leaf_id=54, source_payload_sha256=SHA)
