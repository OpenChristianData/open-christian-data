"""Tests for build/tools/verify_nsh_page_accounting.verify.

The verifier guards the three-representations invariant (disk page_*.jpg /
manifest / page_order.json) that the 2026-06 phantom-page incident violated.
These tests build a synthetic single-volume corpus in a tmp dir, then assert the
verifier (a) PASSES a consistent volume and (b) FAILS — naming the right check —
when each representation is corrupted. A final slow test runs the real corpus as
a regression tripwire.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from build.lib.ocr_store_paths import s1_sidecars_root

_MOD_PATH = Path(__file__).resolve().parents[1] / "build" / "tools" / "verify_nsh_page_accounting.py"
_spec = importlib.util.spec_from_file_location("verify_nsh_page_accounting", _MOD_PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _write_volume(
    base: Path,
    vol: int,
    *,
    manifest_pages,
    disk_page_nums,
    page_count,
    gaps=None,
    po_entries=None,
):
    """Materialize one synthetic volume's three representations under ``base``."""
    vol_id = f"vol_{vol:02d}"
    vdir = base / vol_id
    vdir.mkdir(parents=True, exist_ok=True)
    for pn in disk_page_nums:
        # Minimal JPEG SOI marker — the verifier only globs/counts, never decodes.
        (vdir / f"page_{pn:04d}.jpg").write_bytes(b"\xff\xd8\xff")
    manifest = {"page_count": page_count, "pages": manifest_pages, "gaps": gaps or []}
    (base / f"{vol_id}.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if po_entries is None:
        po_entries = [{"corpus_role": "body", "scan_status": "present"} for _ in range(page_count)]
    (vdir / "page_order.json").write_text(json.dumps({"pages": po_entries}), encoding="utf-8")


def _clean_pages(n):
    return [
        {"page_num": i, "ia_leaf_id": str(20 + i), "local_path": f"vol/page_{i:04d}.jpg"}
        for i in range(1, n + 1)
    ]


def _run(base, vol):
    """Run verify on one volume; return (all_pass, captured_lines)."""
    lines = []
    ok = mod.verify(base=base, volumes=[vol], out=lines.append)
    return ok, lines


def _body_key(page_num: int) -> dict:
    return {"section": "body", "anchor": page_num, "ordinal": 0}


def _write_completeness_volume(
    repo_root: Path,
    *,
    vol: int = 1,
    page_count: int = 2,
    disk_pages=None,
    gaps=None,
    extra_leaves=None,
    lineages=None,
):
    """Materialize the minimal source + S1 store shape for completeness tests."""
    disk_pages = list(range(1, page_count + 1)) if disk_pages is None else disk_pages
    if lineages is None:
        lineages = {
            "tesseract-py314-v1": list(range(1, page_count + 1)),
            "ia-abbyy-dli-v1": list(range(1, page_count + 1)),
        }
    vol_id = f"vol_{vol:02d}"
    base = repo_root / "raw" / "internet-archive" / "schaff-herzog-pages"
    vdir = base / vol_id
    vdir.mkdir(parents=True, exist_ok=True)
    for page_num in disk_pages:
        (vdir / f"page_{page_num:04d}.jpg").write_bytes(b"\xff\xd8\xff")

    body_leaves = [
        {"leaf_num": 100 + i, "page_num": i, "kind": "body", "image_state": "present",
         "ia_leaf_id": str(100 + i), "local_path": f"{vol_id}/page_{i:04d}.jpg",
         "sha256": f"sha256:{i:064x}"}
        for i in range(1, page_count + 1)
        if i in set(disk_pages)
    ]
    manifest = {
        "volume": vol,
        "page_count": page_count,
        "leaves": body_leaves + list(extra_leaves or []),
        "gaps": gaps or [],
    }
    (base / f"{vol_id}.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    root = s1_sidecars_root(repo_root)
    for lineage, pages in lineages.items():
        cell = root / lineage / vol_id
        pages_dir = cell / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        refs = []
        for item in pages:
            if isinstance(item, int):
                page_num = item
                edition_key = _body_key(page_num)
                canonical_leaf_id = 100 + page_num
            else:
                page_num = item["page_num"]
                edition_key = item.get("edition_page_key", _body_key(page_num))
                canonical_leaf_id = item.get("canonical_leaf_id", 100 + page_num)
            native_id = f"page_{page_num:04d}"
            record = {
                "schema_version": "sidecar-page-v1",
                "page_native_id": native_id,
                "source_payload_sha256": f"sha256:{page_num:064x}",
                "canonical_leaf_id": canonical_leaf_id,
            }
            if edition_key is not None:
                record["edition_page_key"] = dict(edition_key)
            refs.append(dict(record))
            (pages_dir / f"{native_id}.json").write_text(json.dumps(record), encoding="utf-8")
        (cell / "manifest.json").write_text(json.dumps({"pages": refs}), encoding="utf-8")


def _write_leaf_sidecar(repo_root: Path, lineage: str, vol: int, leaf_num: int, edition_key=None):
    cell = s1_sidecars_root(repo_root) / lineage / f"vol_{vol:02d}"
    pages_dir = cell / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    native_id = f"leaf_{leaf_num:04d}"
    record = {
        "schema_version": "sidecar-page-v1",
        "page_native_id": native_id,
        "source_payload_sha256": f"sha256:leaf{leaf_num}",
        "clid_exempt": True,
    }
    if edition_key is not None:
        record["edition_page_key"] = dict(edition_key)
    (pages_dir / f"{native_id}.json").write_text(json.dumps(record), encoding="utf-8")
    manifest_path = cell / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("pages", []).append(dict(record))
    else:
        manifest = {"pages": [dict(record)]}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _run_completeness(repo_root: Path, *, vol: int = 1, header_reader=None, content_sample_pages=None):
    lines = []
    reader = header_reader or (lambda path: {"header_num": int(path.stem.split("_")[1]), "side": "recto", "raw": ""})
    result = mod.verify_completeness(
        repo_root=repo_root,
        volumes=[vol],
        header_reader=reader,
        content_sample_pages=content_sample_pages if content_sample_pages is not None else [],
        out=lines.append,
    )
    return result, lines


def test_clean_volume_passes(tmp_path):
    _write_volume(tmp_path, 1, manifest_pages=_clean_pages(3), disk_page_nums=[1, 2, 3], page_count=3)

    ok, lines = _run(tmp_path, 1)

    assert ok is True
    assert not any("**FAIL**" in line for line in lines)


def test_duplicate_page_num_fails(tmp_path):
    pages = _clean_pages(3)
    pages.append({"page_num": 2, "ia_leaf_id": "99", "local_path": "vol/page_0002.jpg"})
    _write_volume(tmp_path, 1, manifest_pages=pages, disk_page_nums=[1, 2, 3], page_count=3)

    ok, lines = _run(tmp_path, 1)

    assert ok is False
    assert any("**FAIL**" in line and "duplicate page_num" in line for line in lines)


def test_orphan_disk_file_fails(tmp_path):
    # Disk carries page_0004 that no manifest entry references.
    _write_volume(tmp_path, 1, manifest_pages=_clean_pages(3), disk_page_nums=[1, 2, 3, 4], page_count=3)

    ok, lines = _run(tmp_path, 1)

    assert ok is False
    assert any("**FAIL**" in line and "orphan disk" in line for line in lines)


def test_manifest_page_without_disk_file_fails(tmp_path):
    # Manifest claims 3 pages; disk only has 2.
    _write_volume(tmp_path, 1, manifest_pages=_clean_pages(3), disk_page_nums=[1, 2], page_count=3)

    ok, lines = _run(tmp_path, 1)

    assert ok is False
    assert any("**FAIL**" in line and "every manifest page has a disk file" in line for line in lines)


def test_body_missing_gap_tiles_cleanly(tmp_path):
    # page 2 is a real hole (permanently_missing); disk has 1 and 3 only.
    pages = [
        {"page_num": 1, "ia_leaf_id": "21", "local_path": "vol/page_0001.jpg"},
        {"page_num": 3, "ia_leaf_id": "23", "local_path": "vol/page_0003.jpg"},
    ]
    gaps = [{"page_num": 2, "status": "permanently_missing"}]
    po = [
        {"corpus_role": "body", "scan_status": "present"},
        {"corpus_role": "body", "scan_status": "unresolved"},
        {"corpus_role": "body", "scan_status": "present"},
    ]
    _write_volume(tmp_path, 1, manifest_pages=pages, disk_page_nums=[1, 3], page_count=3, gaps=gaps, po_entries=po)

    ok, lines = _run(tmp_path, 1)

    assert ok is True, [line for line in lines if "**FAIL**" in line]


def test_completeness_fails_unkeyed_covered_body_page(tmp_path):
    _write_completeness_volume(
        tmp_path,
        page_count=1,
        lineages={
            "tesseract-py314-v1": [{"page_num": 1, "canonical_leaf_id": None, "edition_page_key": None}],
            "ia-abbyy-dli-v1": [1],
        },
    )

    result, lines = _run_completeness(tmp_path)

    assert result["ok"] is False
    assert result["coverage"]["unkeyed_body_pages"] == [{"volume": 1, "page_num": 1, "lineage": "tesseract-py314-v1"}]
    assert any("unkeyed covered body page" in line for line in lines)


def test_completeness_passes_keyed_class1_page(tmp_path):
    _write_completeness_volume(
        tmp_path,
        page_count=1,
        lineages={
            "tesseract-py314-v1": [{"page_num": 1, "canonical_leaf_id": None, "edition_page_key": _body_key(1)}],
            "ia-abbyy-dli-v1": [1],
        },
    )

    result, lines = _run_completeness(tmp_path)

    assert result["ok"] is True, lines
    assert result["coverage"]["unkeyed_body_pages"] == []


def test_completeness_fails_stale_gap_record_from_reconciler(tmp_path):
    gaps = [{"page_num": 1, "status": "resolved"}]
    _write_completeness_volume(tmp_path, page_count=1, gaps=gaps, lineages={"tesseract-py314-v1": [1]})

    classes = mod.classify_volume(mod.load_manifest(tmp_path, 1), tmp_path)
    result, _lines = _run_completeness(tmp_path)

    assert classes["stale_gap_record"] == [1]
    assert result["ok"] is False
    assert result["coverage"]["hard_failures"][0]["class"] == "stale_gap_record"


def test_completeness_fails_image_present_without_ocr(tmp_path):
    gaps = [{"page_num": 1, "status": "unresolved"}]
    _write_completeness_volume(tmp_path, page_count=1, gaps=gaps, lineages={})

    result, _lines = _run_completeness(tmp_path)

    assert result["ok"] is False
    assert result["coverage"]["hard_failures"][0]["class"] == "image_not_ocrd"


def test_completeness_records_depth_per_edition_page(tmp_path):
    # page 1 is covered by one copy-family, page 2 by two; the gate records the
    # depth per edition page and the distribution -- no value judgement attached.
    _write_completeness_volume(
        tmp_path,
        page_count=2,
        lineages={
            "tesseract-py314-v1": [1, 2],
            "ia-abbyy-dli-v1": [2],
        },
    )

    result, _lines = _run_completeness(tmp_path)

    by_vol = result["depth"]["by_volume"][1]
    assert by_vol["distribution"] == {1: 1, 2: 1}
    assert by_vol["body_depths"][("body", 1, 0)] == 1
    assert by_vol["body_depths"][("body", 2, 0)] == 2


def test_completeness_content_read_flags_mismatch_and_passes_match(tmp_path):
    _write_completeness_volume(tmp_path, page_count=1)

    mismatch, _ = _run_completeness(
        tmp_path,
        header_reader=lambda path: {"header_num": 9, "side": "recto", "raw": "9"},
        content_sample_pages=[1],
    )
    match, _ = _run_completeness(
        tmp_path,
        header_reader=lambda path: {"header_num": 1, "side": "recto", "raw": "1"},
        content_sample_pages=[1],
    )

    assert mismatch["content"]["mismatches"] == [{"volume": 1, "page_num": 1, "expected": 1, "actual": 9, "delta": 8}]
    assert match["content"]["mismatches"] == []


def test_completeness_true_hole_reasoned_passes_unreasoned_fails(tmp_path):
    _write_completeness_volume(
        tmp_path / "reasoned",
        page_count=1,
        disk_pages=[],
        gaps=[{"page_num": 1, "status": "permanently_missing"}],
        lineages={},
    )
    _write_completeness_volume(
        tmp_path / "unreasoned",
        page_count=1,
        disk_pages=[],
        gaps=[{"page_num": 1, "status": "unresolved"}],
        lineages={},
    )

    reasoned, _ = _run_completeness(tmp_path / "reasoned")
    unreasoned, _ = _run_completeness(tmp_path / "unreasoned")

    assert reasoned["ok"] is True
    assert unreasoned["ok"] is False
    assert unreasoned["coverage"]["hard_failures"][0]["class"] == "true_hole"


def test_completeness_clean_volume_passes_with_no_fail_lines(tmp_path):
    _write_completeness_volume(tmp_path, page_count=2)

    result, lines = _run_completeness(tmp_path, content_sample_pages=[1, 2])

    assert result["ok"] is True
    assert result["content"]["mismatches"] == []
    assert not any("FAIL" in line for line in lines)


def test_completeness_frontback_keyed_sidecar_is_covered(tmp_path):
    _write_completeness_volume(
        tmp_path,
        page_count=1,
        extra_leaves=[
            {"leaf_num": 2, "page_num": None, "kind": "front_matter", "image_state": "present",
             "blank": False, "local_path": "vol_01/leaf_0002.jpg", "sha256": "sha256:front"}
        ],
        lineages={"tesseract-py314-v1": [1]},
    )
    _write_leaf_sidecar(
        tmp_path,
        "tesseract-py314-v1",
        1,
        2,
        edition_key={"section": "front_matter", "anchor": 1, "ordinal": 0},
    )

    result, lines = _run_completeness(tmp_path)

    assert result["ok"] is True, lines
    assert result["frontback"]["by_volume"][1]["covered"] == 1
    assert result["frontback"]["by_volume"][1]["awaiting_ocr"] == 0


def test_completeness_frontback_discarded_leaf_with_sidecar_is_orphan_failure(tmp_path):
    _write_completeness_volume(
        tmp_path,
        page_count=1,
        extra_leaves=[
            {"leaf_num": 2, "page_num": None, "kind": "discarded", "image_state": "discarded",
             "local_path": "vol_01/leaf_0002.jpg", "sha256": "sha256:discarded"}
        ],
        lineages={"tesseract-py314-v1": [1]},
    )
    _write_leaf_sidecar(tmp_path, "tesseract-py314-v1", 1, 2)

    result, lines = _run_completeness(tmp_path)

    assert result["ok"] is False
    assert result["frontback"]["orphans"] == [{"volume": 1, "leaf_num": 2, "lineage": "tesseract-py314-v1"}]
    assert any("front/back orphan" in line for line in lines)


def test_completeness_frontback_discarded_leaf_without_sidecar_passes(tmp_path):
    _write_completeness_volume(
        tmp_path,
        page_count=1,
        extra_leaves=[
            {"leaf_num": 2, "page_num": None, "kind": "discarded", "image_state": "discarded",
             "local_path": "vol_01/leaf_0002.jpg", "sha256": "sha256:discarded"}
        ],
        lineages={"tesseract-py314-v1": [1]},
    )

    result, lines = _run_completeness(tmp_path)

    assert result["ok"] is True, lines
    assert result["frontback"]["orphans"] == []


def test_completeness_skips_wellformed_nonbody_sidecar(tmp_path):
    # A page_NNNN.json sidecar legitimately keyed to front_matter must NOT be
    # flagged as an unkeyed BODY page (non-body != malformed). Regression for the
    # review's Bug A.
    _write_completeness_volume(
        tmp_path,
        page_count=1,
        lineages={
            "tesseract-py314-v1": [
                1,
                {"page_num": 2, "edition_page_key": {"section": "front_matter", "anchor": 2, "ordinal": 0},
                 "canonical_leaf_id": 102},
            ],
            "ia-abbyy-dli-v1": [1],
        },
    )

    result, _lines = _run_completeness(tmp_path)

    assert result["ok"] is True, result["coverage"]
    assert all(item["page_num"] != 2 for item in result["coverage"]["unkeyed_body_pages"])


def test_completeness_survives_malformed_s1_manifest(tmp_path):
    # A malformed S1 cell manifest is recorded and skipped, never aborts the gate
    # (REL-08, unattended-safe). Regression for the review's finding 1.
    _write_completeness_volume(tmp_path, page_count=1)
    bad = mod.s1_sidecars_root(tmp_path) / "ia-abbyy-dli-v1" / "vol_01" / "manifest.json"
    bad.write_text("{ not valid json", encoding="utf-8")

    result, _lines = _run_completeness(tmp_path)

    assert any(
        item["lineage"] == "ia-abbyy-dli-v1" for item in result["depth"]["missing_manifests"]
    )


def test_completeness_survives_corrupt_sidecar(tmp_path):
    # A corrupted page sidecar in a non-primary lineage is logged and skipped by
    # the unkeyed-body scan, never aborts it. Regression for the review's finding 2.
    _write_completeness_volume(tmp_path, page_count=1)
    bad = mod.s1_sidecars_root(tmp_path) / "ia-abbyy-dli-v1" / "vol_01" / "pages" / "page_0001.json"
    bad.write_text("{ corrupt", encoding="utf-8")

    result, lines = _run_completeness(tmp_path)

    assert result["ok"] is True, lines
    assert any("unreadable sidecar" in line for line in lines)


def test_completeness_records_plate_as_distinct_edition_key(tmp_path):
    # An interleaved plate (ordinal >= 1) is recorded as its own edition key with
    # its own depth, distinct from the numbered page sharing the anchor -- the two
    # are never conflated.
    _write_completeness_volume(
        tmp_path,
        page_count=1,
        lineages={
            "tesseract-py314-v1": [
                1,
                {"page_num": 2, "edition_page_key": {"section": "body", "anchor": 1, "ordinal": 1},
                 "canonical_leaf_id": 102},
            ],
            "ia-abbyy-dli-v1": [1],
        },
    )

    result, _lines = _run_completeness(tmp_path)

    body_depths = result["depth"]["by_volume"][1]["body_depths"]
    assert body_depths[("body", 1, 0)] == 2   # numbered page: primary + dli
    assert body_depths[("body", 1, 1)] == 1   # plate: primary only, distinct key


@pytest.mark.slow
def test_real_corpus_passes():
    """Regression tripwire: the live corpus must satisfy every accounting invariant."""
    if not any(mod.BASE.rglob("page_*.jpg")):
        pytest.skip("raw/internet-archive/schaff-herzog-pages images not present (gitignored)")
    assert mod.verify(out=lambda *_: None) is True
