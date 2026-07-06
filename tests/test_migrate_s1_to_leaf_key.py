from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from build.lib.edition_page_key import body_edition_key  # noqa: E402
from build.parsers import (  # noqa: E402
    s1_kraken_greek_runner,
    s1_kraken_runner,
    s1_surya_runner,
    s1_tesseract_runner,
)
from build.tools.ocr_pipeline.migrate_s1_to_leaf_key import (  # noqa: E402
    CellResult,
    _print_table,
    _volumes_found,
    apply_cell,
    classify_cell,
    dry_run,
)

RUNNERS = [
    pytest.param("tesseract", s1_tesseract_runner, ".tesseract.hocr", id="tesseract"),
    pytest.param("kraken", s1_kraken_runner, ".kraken.raw.json", id="kraken"),
    pytest.param("surya", s1_surya_runner, ".surya.raw.json", id="surya"),
    pytest.param("kraken-greek", s1_kraken_greek_runner, ".kraken-greek.raw.json", id="kraken-greek"),
]

PRIMARY_RUNNER = s1_tesseract_runner
PRIMARY_SUFFIX = ".tesseract.hocr"


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
                    }
                ],
            }
        ],
    }


def _volume_label(volume: int) -> str:
    return f"vol_{volume:02d}"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _raw_text_for(suffix: str, image_path: Path) -> str:
    if suffix == ".tesseract.hocr":
        return f'<div class="ocr_page" title=\'image "{image_path}"\'>Alpha</div>\n'
    return json.dumps({"image_path": str(image_path), "records": ["Alpha"]}, indent=2, sort_keys=True) + "\n"


def _write_raw(path: Path, suffix: str, image_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_raw_text_for(suffix, image_path), encoding="utf-8", newline="\n")


def _fixture(
    tmp_path: Path,
    runner=PRIMARY_RUNNER,
    suffix: str = PRIMARY_SUFFIX,
    *,
    leaves: list[dict] | None = None,
    gaps: list[dict] | None = None,
) -> dict:
    volume = 7
    repo_root = tmp_path
    input_root = repo_root / "raw" / "internet-archive" / "schaff-herzog-pages"
    output_root = repo_root / "reports" / "s1-sidecars"
    vol_dir = input_root / _volume_label(volume)
    pages_dir = output_root / runner.SOURCE_LINEAGE_ID / _volume_label(volume) / "pages"
    vol_dir.mkdir(parents=True)
    pages_dir.mkdir(parents=True)

    image_bytes = {
        "page_0001": b"image one",
        "page_0002": b"image two",
        "page_0003": b"image three",
        "leaf_0005": b"front matter",
    }
    shas = {}
    for stem, payload in image_bytes.items():
        path = vol_dir / f"{stem}.jpg"
        path.write_bytes(payload)
        shas[stem] = runner._prefixed_sha256_bytes(payload)

    manifest = {
        "schema_version": "source-manifest-v4",
        "volume": volume,
        "leaves": leaves
        or [
            {"leaf_num": 10, "page_num": 1, "kind": "body", "image_state": "present", "sha256": shas["page_0001"]},
            {"leaf_num": 11, "page_num": 2, "kind": "body", "image_state": "present", "sha256": shas["page_0002"]},
            {"leaf_num": 12, "page_num": 3, "kind": "body", "image_state": "present", "sha256": shas["page_0003"]},
            {
                "leaf_num": 5,
                "page_num": None,
                "kind": "front_matter",
                "image_state": "present",
                "local_path": str(vol_dir / "leaf_0005.jpg"),
                "sha256": shas["leaf_0005"],
            },
        ],
    }
    if gaps is not None:
        manifest["gaps"] = gaps
    _write_json(input_root / f"{_volume_label(volume)}.manifest.json", manifest)
    images = runner._image_paths(input_root, volume)
    source_files, source_file_sha256 = runner._source_files(images, repo_root)
    manifest_id = runner._build_manifest_id(volume, source_file_sha256)
    return {
        "repo_root": repo_root,
        "input_root": input_root,
        "output_root": output_root,
        "volume": volume,
        "vol_dir": vol_dir,
        "pages_dir": pages_dir,
        "manifest": manifest,
        "manifest_id": manifest_id,
        "source_files": source_files,
        "shas": shas,
        "suffix": suffix,
        "runner": runner,
    }


def _add_sidecar(cell: dict, *, old_stem: str, sha_stem: str, leaf: int | None, page_id: str | None = None) -> dict:
    runner = cell["runner"]
    suffix = cell["suffix"]
    pages_dir = cell["pages_dir"]
    page_id = page_id or old_stem
    source_payload_sha256 = cell["shas"][sha_stem]
    raw_path = runner._raw_artifact_path(pages_dir, old_stem, suffix)
    _write_raw(raw_path, suffix, cell["vol_dir"] / f"{old_stem}.jpg")
    raw_ref = {"path": runner._relative_path(raw_path, cell["repo_root"]), "sha256": runner._prefixed_sha256_bytes(raw_path.read_bytes())}
    record = runner._page_record(
        manifest_id="old-manifest",
        page_native_id=page_id,
        page_sequence=runner._page_sequence(1, Path(f"{page_id}.jpg")),
        canonical_leaf_id=leaf,
        source_payload_sha256=source_payload_sha256,
        subprocess_payload=_payload(),
        raw_artifact=raw_ref,
    )
    # edition_page_key is now schema-required on every emitted sidecar-page-v1
    # record; a post-A2a producer always stamps it, and rekey_sidecar preserves
    # it through the migration. Mirror that here so the apply path validates.
    record["edition_page_key"] = body_edition_key(7)
    _write_json(pages_dir / f"{old_stem}.json", record)
    return record


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_classify_recovered(tmp_path: Path) -> None:
    cell = _fixture(tmp_path)
    _add_sidecar(cell, old_stem="page_0001", sha_stem="page_0001", leaf=10)

    result = classify_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"])

    assert result.counts["recovered"] == 1
    assert result.counts["relocated"] == 0


def test_classify_relocated(tmp_path: Path) -> None:
    cell = _fixture(tmp_path)
    _add_sidecar(cell, old_stem="page_0099", sha_stem="page_0002", leaf=99)

    result = classify_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"])

    assert result.counts["relocated"] == 1
    assert result.rekeys[0].old_stem == "page_0099"
    assert result.rekeys[0].new_stem == "page_0002"


def test_classify_need_first_ocr(tmp_path: Path) -> None:
    cell = _fixture(tmp_path)

    result = classify_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"])

    assert result.counts["need-first-OCR"] == 3


def test_classify_orphan(tmp_path: Path) -> None:
    cell = _fixture(tmp_path)
    _add_sidecar(cell, old_stem="page_0099", sha_stem="page_0001", leaf=99)
    path = cell["pages_dir"] / "page_0099.json"
    record = _read_json(path)
    record["source_payload_sha256"] = "sha256:" + "f" * 64
    _write_json(path, record)

    result = classify_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"])

    assert result.counts["orphan"] == 1


def test_classify_preserve_non_body(tmp_path: Path) -> None:
    cell = _fixture(tmp_path)
    _add_sidecar(cell, old_stem="leaf_0005", sha_stem="leaf_0005", leaf=5)

    result = classify_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"])

    assert result.counts["preserved-non-body"] == 1
    assert result.counts["orphan"] == 0


def test_classify_recovered_gap(tmp_path: Path) -> None:
    # page_0003's content is a printed body page the primary scan skipped, recovered
    # into gaps[] (no spine leaf). resolve_leaf can't see it; the migration must
    # recognize it as a recovered-gap page (not an anomaly) and migrate it like a
    # fresh emit -- keyed on its current stem, canonical_leaf_id absent (gaps have
    # no leaf_num).
    sha1 = PRIMARY_RUNNER._prefixed_sha256_bytes(b"image one")
    sha2 = PRIMARY_RUNNER._prefixed_sha256_bytes(b"image two")
    sha3 = PRIMARY_RUNNER._prefixed_sha256_bytes(b"image three")
    cell = _fixture(
        tmp_path,
        leaves=[
            {"leaf_num": 10, "page_num": 1, "kind": "body", "image_state": "present", "sha256": sha1},
            {"leaf_num": 11, "page_num": 2, "kind": "body", "image_state": "present", "sha256": sha2},
        ],
        gaps=[{"page_num": 3, "status": "resolved", "sha256": sha3}],
    )
    # Real data keeps the recovered-gap page in page_order.json (so it stays an OCR
    # input); the manifest-only fallback would exclude it. Mirror that here.
    _write_json(
        cell["vol_dir"] / "page_order.json",
        {"pages": [{"file": "page_0001.jpg", "corpus_role": "body"},
                   {"file": "page_0002.jpg", "corpus_role": "body"},
                   {"file": "page_0003.jpg", "corpus_role": "body"}]},
    )
    _add_sidecar(cell, old_stem="page_0003", sha_stem="page_0003", leaf=None)

    result = classify_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"])

    assert result.counts["recovered-gap"] == 1
    assert result.counts["anomaly"] == 0
    gap_plans = [p for p in result.rekeys if p.leaf_num is None]
    assert len(gap_plans) == 1
    assert gap_plans[0].new_stem == "page_0003"
    assert gap_plans[0].page_num == 3


def test_dup_sha_fanout(tmp_path: Path) -> None:
    dup_sha = PRIMARY_RUNNER._prefixed_sha256_bytes(b"image one")
    leaves = [
        {"leaf_num": 10, "page_num": 1, "kind": "body", "image_state": "present", "sha256": dup_sha},
        {"leaf_num": 11, "page_num": 2, "kind": "body", "image_state": "present", "sha256": dup_sha},
    ]
    cell = _fixture(tmp_path, leaves=leaves)
    _add_sidecar(cell, old_stem="page_0099", sha_stem="page_0001", leaf=99)

    result = classify_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"])

    assert result.counts["dup-sha-fanout"] == 2
    assert [plan.new_stem for plan in result.rekeys] == ["page_0001", "page_0002"]
    assert [plan.leaf_num for plan in result.rekeys] == [10, 11]


def test_classify_needs_alternate(tmp_path: Path) -> None:
    # An all-black/blank body scan shares its sha with a non-body leaf (a blank
    # front-matter leaf). resolve_leaf can't disambiguate (>1 leaves, not a body
    # dup); the body page needs an alternate-source image, so it is HELD (no rekey
    # plan) and surfaced as needs-alternate rather than a tool anomaly.
    black = PRIMARY_RUNNER._prefixed_sha256_bytes(b"image one")
    leaves = [
        {"leaf_num": 10, "page_num": 1, "kind": "body", "image_state": "present", "sha256": black},
        {"leaf_num": 5, "page_num": None, "kind": "front_matter", "image_state": "present",
         "local_path": "raw/x/leaf_0005.jpg", "sha256": black},
    ]
    cell = _fixture(tmp_path, leaves=leaves)
    _add_sidecar(cell, old_stem="page_0001", sha_stem="page_0001", leaf=10)

    result = classify_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"])

    assert result.counts["needs-alternate"] == 1
    assert result.counts["anomaly"] == 0
    assert result.rekeys == []
    assert result.needs_alternate and black in result.needs_alternate[0]


@pytest.mark.parametrize("engine_name,runner,suffix", RUNNERS)
def test_apply_rekey_byte_equals_fresh_page_record(engine_name: str, runner, suffix: str, tmp_path: Path) -> None:
    cell = _fixture(tmp_path, runner=runner, suffix=suffix)
    stale = _add_sidecar(cell, old_stem="page_0099", sha_stem="page_0002", leaf=99)
    result = apply_cell(runner, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"], repo_root=cell["repo_root"])
    migrated = _read_json(cell["pages_dir"] / "page_0002.json")
    raw_path = runner._raw_artifact_path(cell["pages_dir"], "page_0002", suffix)
    fresh = runner._page_record(
        manifest_id=result.manifest_id,
        page_native_id="page_0002",
        page_sequence=2,
        canonical_leaf_id=11,
        source_payload_sha256=stale["source_payload_sha256"],
        subprocess_payload=_payload(),
        raw_artifact={"path": runner._relative_path(raw_path, cell["repo_root"]), "sha256": runner._prefixed_sha256_bytes(raw_path.read_bytes())},
    )
    # rekey preserves the stale record's edition_page_key (set in _add_sidecar);
    # the fresh comparison record must carry the same key for byte-equality.
    fresh["edition_page_key"] = body_edition_key(7)

    assert migrated == fresh


@pytest.mark.parametrize("engine_name,runner,suffix", RUNNERS)
def test_apply_recovered_gap_byte_equals_fresh_emit(engine_name: str, runner, suffix: str, tmp_path: Path) -> None:
    # A recovered-gap page migrates exactly like a fresh emit: keyed on its current
    # stem, canonical_leaf_id absent (gaps have no leaf_num). This is the zero-re-OCR
    # invariant for gap pages -- a migrated gap sidecar byte-equals re-running the
    # engine on it.
    sha1 = runner._prefixed_sha256_bytes(b"image one")
    sha2 = runner._prefixed_sha256_bytes(b"image two")
    sha3 = runner._prefixed_sha256_bytes(b"image three")
    cell = _fixture(
        tmp_path,
        runner=runner,
        suffix=suffix,
        leaves=[
            {"leaf_num": 10, "page_num": 1, "kind": "body", "image_state": "present", "sha256": sha1},
            {"leaf_num": 11, "page_num": 2, "kind": "body", "image_state": "present", "sha256": sha2},
        ],
        gaps=[{"page_num": 3, "status": "resolved", "sha256": sha3}],
    )
    _write_json(
        cell["vol_dir"] / "page_order.json",
        {"pages": [{"file": "page_0001.jpg", "corpus_role": "body"},
                   {"file": "page_0002.jpg", "corpus_role": "body"},
                   {"file": "page_0003.jpg", "corpus_role": "body"}]},
    )
    stale = _add_sidecar(cell, old_stem="page_0003", sha_stem="page_0003", leaf=None)

    result = apply_cell(runner, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"], repo_root=cell["repo_root"])

    migrated = _read_json(cell["pages_dir"] / "page_0003.json")
    raw_path = runner._raw_artifact_path(cell["pages_dir"], "page_0003", suffix)
    fresh = runner._page_record(
        manifest_id=result.manifest_id,
        page_native_id="page_0003",
        page_sequence=3,
        canonical_leaf_id=None,
        source_payload_sha256=stale["source_payload_sha256"],
        subprocess_payload=_payload(),
        raw_artifact={"path": runner._relative_path(raw_path, cell["repo_root"]), "sha256": runner._prefixed_sha256_bytes(raw_path.read_bytes())},
    )
    # rekey preserves the stale record's edition_page_key (set in _add_sidecar);
    # the fresh comparison record must carry the same key for byte-equality.
    fresh["edition_page_key"] = body_edition_key(7)

    assert "canonical_leaf_id" not in migrated
    assert migrated == fresh


@pytest.mark.parametrize("engine_name,runner,suffix", RUNNERS)
def test_apply_relocates_and_rewrites_raw_artifact(engine_name: str, runner, suffix: str, tmp_path: Path) -> None:
    cell = _fixture(tmp_path, runner=runner, suffix=suffix)
    _add_sidecar(cell, old_stem="page_0099", sha_stem="page_0002", leaf=99)
    old_raw = runner._raw_artifact_path(cell["pages_dir"], "page_0099", suffix)
    old_text = old_raw.read_text(encoding="utf-8")

    apply_cell(runner, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"], repo_root=cell["repo_root"])

    new_raw = runner._raw_artifact_path(cell["pages_dir"], "page_0002", suffix)
    migrated = _read_json(cell["pages_dir"] / "page_0002.json")
    raw_ref = migrated["page_extras_carried"]["raw_artifact"]
    assert not old_raw.exists()
    assert new_raw.exists()
    if suffix == ".tesseract.hocr":
        assert str(cell["vol_dir"] / "page_0099.jpg") in old_text
        assert str(cell["vol_dir"] / "page_0002.jpg") in new_raw.read_text(encoding="utf-8")
    else:
        assert json.loads(old_text)["image_path"] == str(cell["vol_dir"] / "page_0099.jpg")
        assert _read_json(new_raw)["image_path"] == str(cell["vol_dir"] / "page_0002.jpg")
    assert raw_ref["path"] == runner._relative_path(new_raw, cell["repo_root"])
    assert raw_ref["sha256"] == runner._prefixed_sha256_bytes(new_raw.read_bytes())
    assert migrated["page_extras_jcs_sha256"] == runner._extras_hash(migrated["page_extras_carried"])


@pytest.mark.parametrize("engine_name,runner,suffix", RUNNERS)
def test_apply_upshift_chain_does_not_clobber_unread_source(engine_name: str, runner, suffix: str, tmp_path: Path) -> None:
    # A contiguous up-shift relocation chain: each sidecar's content belongs one
    # page HIGHER than its current stem (page_0001's content -> page_0002,
    # page_0002 -> page_0003, page_0003 -> page_0004). apply processes plans in
    # ascending stem order; the pre-fix transaction re-reads each source from disk
    # at apply time, so the write that lands page_0002.json runs BEFORE the
    # page_0002 -> page_0003 plan reads page_0002.json as its source -- destroying
    # the higher page's OCR. Each migrated stem must carry the sha of the image NOW
    # at that stem, not content shifted up from a lower stem.
    volume = 7
    repo_root = tmp_path
    input_root = repo_root / "raw" / "internet-archive" / "schaff-herzog-pages"
    output_root = repo_root / "reports" / "s1-sidecars"
    vol_dir = input_root / _volume_label(volume)
    pages_dir = output_root / runner.SOURCE_LINEAGE_ID / _volume_label(volume) / "pages"
    vol_dir.mkdir(parents=True)
    pages_dir.mkdir(parents=True)

    # Post-shift (correct) image arrangement on disk: distinct content per stem.
    image_bytes = {
        "page_0002": b"up-shift content one",
        "page_0003": b"up-shift content two",
        "page_0004": b"up-shift content three",
    }
    shas = {}
    for stem, payload in image_bytes.items():
        (vol_dir / f"{stem}.jpg").write_bytes(payload)
        shas[stem] = runner._prefixed_sha256_bytes(payload)

    manifest = {
        "schema_version": "source-manifest-v4",
        "volume": volume,
        "leaves": [
            {"leaf_num": 12, "page_num": 2, "kind": "body", "image_state": "present", "sha256": shas["page_0002"]},
            {"leaf_num": 13, "page_num": 3, "kind": "body", "image_state": "present", "sha256": shas["page_0003"]},
            {"leaf_num": 14, "page_num": 4, "kind": "body", "image_state": "present", "sha256": shas["page_0004"]},
        ],
    }
    _write_json(input_root / f"{_volume_label(volume)}.manifest.json", manifest)

    # Stale (pre-shift) sidecars: content sits one stem too low. Each sidecar's
    # source_payload_sha256 is the content that belongs one page higher.
    cell = {"runner": runner, "suffix": suffix, "pages_dir": pages_dir,
            "vol_dir": vol_dir, "shas": shas, "repo_root": repo_root}
    _add_sidecar(cell, old_stem="page_0001", sha_stem="page_0002", leaf=11)
    _add_sidecar(cell, old_stem="page_0002", sha_stem="page_0003", leaf=12)
    _add_sidecar(cell, old_stem="page_0003", sha_stem="page_0004", leaf=13)

    result = apply_cell(runner, volume=volume, input_root=input_root, output_root=output_root, repo_root=repo_root)

    assert result.counts["relocated"] == 3
    assert result.counts["anomaly"] == 0
    for stem in ("page_0002", "page_0003", "page_0004"):
        migrated = _read_json(pages_dir / f"{stem}.json")
        assert migrated["source_payload_sha256"] == shas[stem], (
            f"{stem}: migrated sidecar carries {migrated['source_payload_sha256']}, "
            f"expected {shas[stem]} (the image now at {stem}) -- an up-shift source was "
            f"clobbered before it was read"
        )
        new_raw = runner._raw_artifact_path(pages_dir, stem, suffix)
        raw_ref = migrated["page_extras_carried"]["raw_artifact"]
        assert raw_ref["path"] == runner._relative_path(new_raw, repo_root)
        if suffix == ".tesseract.hocr":
            assert str(vol_dir / f"{stem}.jpg") in new_raw.read_text(encoding="utf-8")
        else:
            assert _read_json(new_raw)["image_path"] == str(vol_dir / f"{stem}.jpg")


def test_apply_orphan_at_relocation_target_keeps_migrated_sidecar(tmp_path: Path) -> None:
    # A stale "orphan" sidecar sits at a stem that is ALSO a relocation target (the
    # systematic shape at an up-shift volume's top boundary: the vacated stem holds
    # stale content AND receives relocated content). The rekey loop writes the correct
    # migrated sidecar to that stem; the orphan-quarantine step must NOT then move it
    # away. After apply the canonical stem must carry the migrated content, and the
    # ORIGINAL orphan content must be preserved in quarantine.
    cell = _fixture(tmp_path)
    # Relocation source: page_0099 carries page_0002's content -> relocates to page_0002.
    _add_sidecar(cell, old_stem="page_0099", sha_stem="page_0002", leaf=99)
    # Orphan sitting AT the relocation target stem (page_0002), with stale content whose
    # sha matches no current image.
    orphan_sha = "sha256:" + "a" * 64
    _add_sidecar(cell, old_stem="page_0002", sha_stem="page_0001", leaf=1)
    orphan_path = cell["pages_dir"] / "page_0002.json"
    orphan_record = _read_json(orphan_path)
    orphan_record["source_payload_sha256"] = orphan_sha
    _write_json(orphan_path, orphan_record)

    result = apply_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"], repo_root=cell["repo_root"])

    assert result.counts["relocated"] == 1
    assert result.counts["orphan"] == 1
    migrated = _read_json(cell["pages_dir"] / "page_0002.json")
    assert migrated["source_payload_sha256"] == cell["shas"]["page_0002"], (
        "canonical stem must carry the migrated content, not be clobbered by orphan quarantine"
    )
    q_orphans = cell["pages_dir"].parent / "quarantine" / "migrate_s1_to_leaf_key" / "orphans"
    quarantined_shas = {_read_json(p)["source_payload_sha256"] for p in q_orphans.glob("*.json")}
    assert orphan_sha in quarantined_shas, "the original orphan content must be preserved in quarantine"


def test_apply_refuses_to_clobber_leftover_snapshot(tmp_path: Path) -> None:
    # A leftover .migrate-snapshot means a prior apply crashed mid-run and the dir
    # holds the only copy of un-recovered source OCR (re-OCR is forbidden). Phase A
    # must NOT blindly delete it -- it must fail fast so the staged sources can be
    # recovered by hand.
    cell = _fixture(tmp_path)
    _add_sidecar(cell, old_stem="page_0099", sha_stem="page_0002", leaf=99)
    leftover = cell["pages_dir"] / ".migrate-snapshot" / "pages"
    leftover.mkdir(parents=True)
    sentinel = leftover / "page_0042.json"
    sentinel.write_text("{}", encoding="utf-8")

    with pytest.raises((RuntimeError, FileExistsError)):
        apply_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"], repo_root=cell["repo_root"])

    assert sentinel.exists(), "leftover snapshot source must not be destroyed"


def test_print_table_header_matches_row_columns(capsys) -> None:
    # The header must name every count column; a hardcoded header drifts from
    # COUNT_KEYS when a class is added (recovered-gap / needs-alternate).
    _print_table([CellResult(engine="tesseract", source_lineage_id="x", volume=1)])
    lines = capsys.readouterr().out.splitlines()
    assert len(lines[0].split()) == len(lines[1].split())


def test_dry_run_mutates_nothing(tmp_path: Path) -> None:
    cell = _fixture(tmp_path)
    _add_sidecar(cell, old_stem="page_0099", sha_stem="page_0002", leaf=99)
    before = _snapshot(tmp_path)

    dry_run(engine="tesseract", volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"])

    assert _snapshot(tmp_path) == before


def test_volumes_found_ignores_non_canonical_manifests(tmp_path: Path) -> None:
    """Only vol_NN.manifest.json drives a cell -- stale/backup variants such as
    vol_11_rebuild.stale_scandata.manifest.json must not produce a duplicate
    (and stale) volume entry."""
    root = tmp_path
    for name in (
        "vol_10.manifest.json",
        "vol_11.manifest.json",
        "vol_11_rebuild.stale_scandata.manifest.json",
        "vol_11.manifest.preswap_20260611T092150Z.json",
    ):
        (root / name).write_text("{}", encoding="utf-8")

    assert _volumes_found(root) == [10, 11]


def test_apply_is_reversible_via_journal(tmp_path: Path) -> None:
    cell = _fixture(tmp_path)
    original = _add_sidecar(cell, old_stem="page_0099", sha_stem="page_0002", leaf=99)

    apply_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"], repo_root=cell["repo_root"])

    run_dir = cell["pages_dir"].parent
    journal = run_dir / "migrate_s1_to_leaf_key.journal.jsonl"
    quarantine = run_dir / "quarantine" / "migrate_s1_to_leaf_key"
    assert journal.exists()
    entries = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert any(entry["op"] == "move_raw" for entry in entries)
    assert any(entry["op"] == "quarantine_sidecar" for entry in entries)
    assert _read_json(quarantine / "pages" / "page_0099.json") == original


def test_apply_dup_sha_fanout_writes_both_dests(tmp_path: Path) -> None:
    # One source sidecar fans out to two leaf-keyed dests (one sha -> 2 body
    # leaves). The apply path must write BOTH dest sidecars (deep-copied) and
    # copy the staged raw to each -- losing one would silently drop a page.
    dup_sha = PRIMARY_RUNNER._prefixed_sha256_bytes(b"image one")
    leaves = [
        {"leaf_num": 10, "page_num": 1, "kind": "body", "image_state": "present", "sha256": dup_sha},
        {"leaf_num": 11, "page_num": 2, "kind": "body", "image_state": "present", "sha256": dup_sha},
    ]
    cell = _fixture(tmp_path, leaves=leaves)
    _add_sidecar(cell, old_stem="page_0099", sha_stem="page_0001", leaf=99)

    result = apply_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"], repo_root=cell["repo_root"])

    pages_dir = cell["pages_dir"]
    assert result.counts["dup-sha-fanout"] == 2
    for stem, leaf in (("page_0001", 10), ("page_0002", 11)):
        sidecar = _read_json(pages_dir / f"{stem}.json")
        assert sidecar["canonical_leaf_id"] == leaf
        assert PRIMARY_RUNNER._raw_artifact_path(pages_dir, stem, cell["suffix"]).exists()


def test_apply_empty_cell_does_not_clobber_existing_manifest(tmp_path: Path) -> None:
    # Every page is need-first-OCR (no sidecars on disk) -> 0 rekeys, 0 orphans.
    # apply must NOT rebuild the manifest to an empty pages[] and clobber a
    # pre-existing index (pure re-indexing is reindex_manifest's job).
    cell = _fixture(tmp_path)
    manifest_path, _state, _pages = PRIMARY_RUNNER._normal_manifest_paths(
        cell["output_root"], PRIMARY_RUNNER.SOURCE_LINEAGE_ID, cell["volume"]
    )
    sentinel = {"schema_version": "sidecar-manifest-v1",
                "pages": [{"page_native_id": "page_0001"}], "_sentinel": True}
    _write_json(manifest_path, sentinel)

    result = apply_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"], repo_root=cell["repo_root"])

    assert not result.rekeys and not result.orphans
    assert _read_json(manifest_path) == sentinel  # untouched


def test_apply_journal_records_snapshot_source(tmp_path: Path) -> None:
    # The Phase-A source staging must be journalled so a crash mid-write-loop is
    # recoverable by journal replay, not only by knowing the dir convention.
    cell = _fixture(tmp_path)
    _add_sidecar(cell, old_stem="page_0099", sha_stem="page_0002", leaf=99)

    apply_cell(PRIMARY_RUNNER, volume=cell["volume"], input_root=cell["input_root"], output_root=cell["output_root"], repo_root=cell["repo_root"])

    journal = cell["pages_dir"].parent / "migrate_s1_to_leaf_key.journal.jsonl"
    entries = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    snaps = [entry for entry in entries if entry["op"] == "snapshot_source"]
    assert snaps and snaps[0]["stem"] == "page_0099" and snaps[0]["staged_sidecar"]
