"""TDD tests for R4b: WCT + reconciliation + gold alignment leaf-rekey.

R4b makes ``canonical_leaf_id`` (int) the first-class cross-engine / cross-stage
page-level JOIN KEY for the primary chain:

* ``build_wct_page`` emits ``canonical_leaf_id`` as a first-class field.
* ``build_from_files`` derives the leaf from the per-engine renderings and
  fail-closes when two engines disagree on it (the silent mis-alignment the
  filename-stem join could not catch -- an engine OCR'd before vs after a
  rename). Renderings that carry no ``canonical_leaf_id`` (the ABBYY geometry
  lane, still filename-keyed until R7; and non-NSH sources such as JE) are
  exempt from the agreement check by design.
* CCEL page-gold proposals carry ``canonical_leaf_id`` and the WCT<->CCEL page
  join keys on it (falling back to ``page_native_id`` only when the leaf is
  absent on either side).

``page_id`` / ``page_native_id`` stay display/provenance (design SS2 -- filename
demoted to display, never a key); the int leaf is the key.

Run failing-first:
    py -3 -m pytest -p no:cacheprovider -q tests/test_r4b_wct_recon_leaf_rekey.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "wct_builder"
SOURCE_IMAGE = {
    "path": "raw/internet-archive/schaff-herzog-pages/vol_01/page_0010.jpg",
    "sha256": "3b1f9c2e7a4d6058e1c9b2f0a7d34e58f6b1029c3d4e5f60718293a4b5c6d7e8",
}


def _rendering(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"rendering_{name}.json").read_text(encoding="utf-8"))


def _write_renderings(
    root: Path,
    leaf_by_engine: dict[str, int | None],
    edition_key_by_engine: dict[str, dict | None] | None = None,
) -> list[Path]:
    """Write the four wct_builder fixtures to ``root`` with a stamped (or absent)
    ``canonical_leaf_id`` per engine, returning the rendering file paths."""
    paths: list[Path] = []
    for name in ("surya", "azure", "tesseract", "abbyy"):
        rendering = _rendering(name)
        leaf = leaf_by_engine.get(name, "__missing__")
        if leaf == "__missing__":
            # Not mentioned -> mirror the default (carries no leaf, like JE/ABBYY).
            rendering["pages"][0].pop("canonical_leaf_id", None)
        elif leaf is None:
            rendering["pages"][0].pop("canonical_leaf_id", None)
        else:
            rendering["pages"][0]["canonical_leaf_id"] = leaf
        if edition_key_by_engine is not None:
            key = edition_key_by_engine.get(name, "__missing__")
            if key == "__missing__" or key is None:
                rendering["pages"][0].pop("edition_page_key", None)
            else:
                rendering["pages"][0]["edition_page_key"] = dict(key)
        out = root / f"rendering_{name}.json"
        out.write_text(json.dumps(rendering, ensure_ascii=False), encoding="utf-8")
        paths.append(out)
    return paths


# --------------------------------------------------------------------------- #
# build_wct_page -- first-class canonical_leaf_id field
# --------------------------------------------------------------------------- #


def test_build_wct_page_emits_canonical_leaf_id() -> None:
    from build.lib.wct_builder import build_wct_page

    renderings = [_rendering(n) for n in ("surya", "azure", "tesseract", "abbyy")]
    page = build_wct_page(
        renderings,
        work_id="schaff-herzog",
        volume_id="vol_01",
        page_id="page_0010",
        canonical_leaf_id=37,
        source_image=SOURCE_IMAGE,
    )
    assert page["canonical_leaf_id"] == 37


def test_build_wct_page_omits_canonical_leaf_id_when_none() -> None:
    """Backward compatible: a caller that supplies no leaf (JE, Track-C,
    reviewer, s3_reconciler) gets a page with no canonical_leaf_id key."""
    from build.lib.wct_builder import build_wct_page

    renderings = [_rendering(n) for n in ("surya", "azure", "tesseract", "abbyy")]
    page = build_wct_page(
        renderings,
        work_id="schaff-herzog",
        volume_id="vol_01",
        page_id="page_0010",
        source_image=SOURCE_IMAGE,
    )
    assert "canonical_leaf_id" not in page


def test_build_wct_page_stamps_edition_key_and_clid_exempt_when_keyless() -> None:
    from build.lib.wct_builder import build_wct_page

    edition_key = {"section": "body", "anchor": 96, "ordinal": 0}
    renderings = [_rendering(n) for n in ("surya", "azure", "tesseract", "abbyy")]
    page = build_wct_page(
        renderings,
        work_id="schaff-herzog",
        volume_id="vol_01",
        page_id="page_0096",
        canonical_leaf_id=None,
        edition_page_key=edition_key,
        source_image=SOURCE_IMAGE,
    )
    assert page["edition_page_key"] == edition_key
    assert page["clid_exempt"] is True
    assert "canonical_leaf_id" not in page


# --------------------------------------------------------------------------- #
# build_from_files -- derive + cross-engine join validation on the leaf
# --------------------------------------------------------------------------- #


def test_build_from_files_derives_canonical_leaf_id(tmp_path: Path) -> None:
    from build.tools.ocr_pipeline.build_wct import build_from_files

    paths = _write_renderings(tmp_path, {"surya": 37, "azure": 37, "tesseract": 37, "abbyy": 37})
    page = build_from_files(paths, source_image=SOURCE_IMAGE)
    assert page["canonical_leaf_id"] == 37


def test_build_from_files_raises_on_cross_engine_leaf_disagreement(tmp_path: Path) -> None:
    """Two engines whose renderings claim different leaves for the same join must
    fail closed -- this is the silent mis-alignment the stem join could not see."""
    from build.tools.ocr_pipeline.build_wct import build_from_files

    paths = _write_renderings(tmp_path, {"surya": 37, "azure": 37, "tesseract": 38, "abbyy": 37})
    with pytest.raises(ValueError, match="canonical_leaf_id"):
        build_from_files(paths, source_image=SOURCE_IMAGE)


def test_build_from_files_tolerates_rendering_without_leaf(tmp_path: Path) -> None:
    """The ABBYY geometry lane is still filename-keyed (rekeyed in R7); a
    rendering carrying no canonical_leaf_id must not block the join -- the leaf
    is taken from the engines that do carry it."""
    from build.tools.ocr_pipeline.build_wct import build_from_files

    paths = _write_renderings(tmp_path, {"surya": 37, "azure": 37, "tesseract": 37, "abbyy": None})
    page = build_from_files(paths, source_image=SOURCE_IMAGE)
    assert page["canonical_leaf_id"] == 37


def test_derive_canonical_leaf_id_agreeing_renderings() -> None:
    """The clid derivation is a standalone function so the WCT clid-stamp tool
    (rebuild_wct_clid) reuses the SAME cross-engine fail-closed logic build_from_files
    uses -- one source of truth, no drift."""
    from build.tools.ocr_pipeline.build_wct import derive_canonical_leaf_id

    renderings = [{"pages": [{"canonical_leaf_id": 47}]}, {"pages": [{"canonical_leaf_id": 47}]}]
    assert derive_canonical_leaf_id(renderings) == 47


def test_derive_canonical_leaf_id_disagreement_raises() -> None:
    from build.tools.ocr_pipeline.build_wct import derive_canonical_leaf_id

    renderings = [{"pages": [{"canonical_leaf_id": 47}]}, {"pages": [{"canonical_leaf_id": 48}]}]
    with pytest.raises(ValueError, match="canonical_leaf_id"):
        derive_canonical_leaf_id(renderings)


def test_derive_canonical_leaf_id_none_when_absent() -> None:
    from build.tools.ocr_pipeline.build_wct import derive_canonical_leaf_id

    assert derive_canonical_leaf_id([{"pages": [{}]}, {"pages": [{}]}]) is None


def test_derive_edition_page_key_agreeing_renderings() -> None:
    from build.tools.ocr_pipeline.build_wct import derive_edition_page_key

    key = {"section": "body", "anchor": 96, "ordinal": 0}
    renderings = [{"pages": [{"edition_page_key": key}]}, {"pages": [{"edition_page_key": dict(key)}]}]
    assert derive_edition_page_key(renderings) == key


def test_derive_edition_page_key_disagreement_raises() -> None:
    from build.tools.ocr_pipeline.build_wct import derive_edition_page_key

    renderings = [
        {"pages": [{"edition_page_key": {"section": "body", "anchor": 96, "ordinal": 0}}]},
        {"pages": [{"edition_page_key": {"section": "body", "anchor": 97, "ordinal": 0}}]},
    ]
    with pytest.raises(ValueError, match="edition_page_key"):
        derive_edition_page_key(renderings)


def test_derive_edition_page_key_none_when_absent() -> None:
    from build.tools.ocr_pipeline.build_wct import derive_edition_page_key

    assert derive_edition_page_key([{"pages": [{}]}, {"pages": [{}]}]) is None


def test_build_from_files_no_leaf_when_none_present(tmp_path: Path) -> None:
    """All renderings filename-keyed (JE) -> no leaf emitted; page_id falls back
    to the page_native_id stem (backward compatible)."""
    from build.tools.ocr_pipeline.build_wct import build_from_files

    paths = _write_renderings(
        tmp_path, {"surya": None, "azure": None, "tesseract": None, "abbyy": None}
    )
    page = build_from_files(paths, source_image=SOURCE_IMAGE)
    assert "canonical_leaf_id" not in page
    assert page["page_id"] == "leaf_0010"  # the fixtures' page_native_id stem


def test_build_from_files_derives_edition_page_key_for_keyless_page(tmp_path: Path) -> None:
    from build.tools.ocr_pipeline.build_wct import build_from_files

    key = {"section": "body", "anchor": 96, "ordinal": 0}
    paths = _write_renderings(
        tmp_path,
        {"surya": None, "azure": None, "tesseract": None, "abbyy": None},
        {"surya": key, "azure": key, "tesseract": key, "abbyy": key},
    )
    page = build_from_files(paths, source_image=SOURCE_IMAGE)
    assert page["edition_page_key"] == key
    assert page["clid_exempt"] is True


# --------------------------------------------------------------------------- #
# CCEL gold alignment + proposal -- join on canonical_leaf_id
# --------------------------------------------------------------------------- #


def _wct_page(readings: list[str], *, page_id: str, canonical_leaf_id: int | None) -> dict:
    positions = []
    reading_order = []
    for i, reading in enumerate(readings):
        pid = f"vol_01:{page_id}:body:c1:l000:p{i:03d}"
        positions.append(
            {
                "position_id": pid,
                "zone": {"zone_type": "body"},
                "candidate_set": [
                    {"candidate_id": "cand_001", "raw_reading": reading, "attesting_engines": ["e1"]}
                ],
                "reference_bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
            }
        )
        reading_order.append(pid)
    page = {
        "work_id": "schaff-herzog",
        "volume_id": "vol_01",
        "page_id": page_id,
        "positions": positions,
        "reading_order": reading_order,
    }
    if canonical_leaf_id is not None:
        page["canonical_leaf_id"] = canonical_leaf_id
    return page


def test_align_joins_ccel_page_by_canonical_leaf_id() -> None:
    """The WCT<->CCEL page join keys on canonical_leaf_id: a CCEL page whose
    page_native_id differs from the WCT page_id still aligns when the leaves
    match (the filename stem is no longer the join key)."""
    from build.tools.ocr_pipeline.align_ccel_to_wct import align_page

    wct = _wct_page(["merit"], page_id="page_0012", canonical_leaf_id=37)
    ccel = {
        "volume": 1,
        "source": {"source_basis": "ccel:test"},
        "pages": [
            {
                "page_native_id": "page_0010",  # deliberately different stem
                "canonical_leaf_id": 37,
                "scan_path": "raw/x/page_0010.jpg",
                "ccel_page_text": "merit",
            }
        ],
    }
    artifact = align_page(wct, ccel)
    assert artifact["coverage"]["gold_candidates"] == 1


def test_align_joins_keyless_ccel_page_by_edition_page_key() -> None:
    from build.tools.ocr_pipeline.align_ccel_to_wct import align_page

    key = {"section": "body", "anchor": 96, "ordinal": 0}
    wct = _wct_page(["merit"], page_id="page_0096", canonical_leaf_id=None)
    wct["edition_page_key"] = key
    ccel = {
        "volume": 1,
        "source": {"source_basis": "ccel:test"},
        "pages": [
            {
                "page_native_id": "different_scan_stem",
                "edition_page_key": dict(key),
                "scan_path": "raw/x/page_0096.jpg",
                "ccel_page_text": "merit",
            }
        ],
    }
    artifact = align_page(wct, ccel)
    assert artifact["coverage"]["gold_candidates"] == 1
    assert artifact["edition_page_key"] == key


def test_extract_ccel_proposal_pages_carry_canonical_leaf_id(tmp_path: Path) -> None:
    from build.tools.ocr_pipeline.extract_ccel_page_gold import build_proposal

    xml = tmp_path / "encyc99.xml"
    xml.write_text(
        '<ThML><body><p><pb n="1"/>Alpha beta gamma.<pb n="2"/>Delta.</p></body></ThML>',
        encoding="utf-8",
    )
    scan = tmp_path / "vol_99" / "page_0001.jpg"
    scan.parent.mkdir(parents=True, exist_ok=True)
    scan.write_bytes(b"\xff\xd8\xff\xd9")
    manifest = tmp_path / "vol_99.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "pages": [
                    {"page_num": 1, "ia_leaf_id": "37", "local_path": "vol_99/page_0001.jpg"}
                ]
            }
        ),
        encoding="utf-8",
    )
    proposal = build_proposal(volume=99, xml_path=xml, manifest_path=manifest)
    page = proposal["pages"][0]
    assert page["canonical_leaf_id"] == 37
    assert page["edition_page_key"] == {"section": "body", "anchor": 1, "ordinal": 0}
