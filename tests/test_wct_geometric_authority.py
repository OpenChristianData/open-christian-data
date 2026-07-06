"""TDD contract: consensus-geometry layout authority for the WCT (Phase A).

Surya (~21h compute) is replaced as the WCT layout authority by consensus word-box
geometry. The new authority derives body column zones from the pooled word boxes of
the geometry-bearing engines (azure, tesseract, abbyy) and ESCALATES any page it
cannot resolve confidently; Surya then runs ONLY on the escalated pages as a
fallback. This file pins:

  * column_zones() in build.lib.consensus_layout: real-page-grounded body column
    extents + assign_x, and the escalation flag (the load-bearing safety property).
  * build_wct_page(..., layout_authority=...): geometric is the DEFAULT and emits
    layout_authority.tool == "geometric"; the Surya path is still reachable behind
    the interface (reversible); an escalated page with no Surya rendering raises
    LayoutEscalation so the driver can run Surya on it.

Grounding is REAL page word-boxes on disk (raw azure/abbyy + tesseract S1), NOT
synthetic point-column fixtures -- the prior round's bug was synthetic fixtures
that passed but broke on real column spread. Raw-read tests skipif-guard on the
gitignored raw/ + reports/ trees (OCD raw-read convention).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.consensus_layout import column_zones  # noqa: E402
from build.lib.edition_page_key import body_edition_key  # noqa: E402
import build.lib.wct_builder as wct_builder  # noqa: E402
from build.lib.wct_builder import (  # noqa: E402
    LayoutEscalation,
    _zones_from_annotation,
    build_wct_page,
)
from build.lib.wct_semantic_validator import validate_page  # noqa: E402

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "wct_builder"
THINSLICE_DIR = REPO_ROOT / "reports" / "_thinslice" / "rendering_single"
RAW_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_01"
TESSERACT_S1 = REPO_ROOT / "reports" / "s1-sidecars" / "tesseract-py314-v1" / "vol_01" / "pages"

SOURCE_IMAGE = {
    "path": "raw/internet-archive/schaff-herzog-pages/vol_01/page_0010.jpg",
    "sha256": "b8f4d2476ea47dba58d920aa7af510c56433d5858447f7e0017b41c13210a1bb",
}


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"rendering_{name}.json").read_text(encoding="utf-8"))


def _thinslice(engine: str) -> dict:
    return json.loads((THINSLICE_DIR / f"{engine}.rendering-v1.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Real-page word-box loaders (mirror ablate_layout_authority.py exactly).
# --------------------------------------------------------------------------- #


def _valid_box(box: object) -> bool:
    return isinstance(box, dict) and all(k in box for k in ("x", "y", "w", "h"))


def _rect(box: dict) -> dict:
    return {"x": float(box["x"]), "y": float(box["y"]), "w": float(box["w"]), "h": float(box["h"])}


def _boxes_from_blocks(blocks, bbox_key: str) -> list[dict]:
    out: list[dict] = []
    for block in blocks:
        for line in block.get("lines", []):
            for word in line.get("words", []):
                bbox = word.get(bbox_key)
                if _valid_box(bbox):
                    out.append(_rect(bbox))
    return out


def _azure_boxes(page: int) -> tuple[list[dict], tuple[int, int] | None]:
    p = RAW_DIR / f"page_{page:04d}.azure.json"
    if not p.exists():
        return [], None
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("partial") is True:
        return [], None
    size = d.get("image_size")
    dims = (int(size[0]), int(size[1])) if isinstance(size, list) and len(size) == 2 else None
    return _boxes_from_blocks(d.get("blocks", []), "bbox"), dims


def _abbyy_boxes(page: int) -> list[dict]:
    p = RAW_DIR / f"page_{page:04d}.ia-abbyy.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    return _boxes_from_blocks(d.get("blocks", []), "bbox")


def _tesseract_boxes(page: int) -> list[dict]:
    p = TESSERACT_S1 / f"page_{page:04d}.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    return _boxes_from_blocks(d.get("blocks", []), "bbox_native")


_RAW_PAGE10 = (RAW_DIR / "page_0010.azure.json").exists()
_RAW_PAGE381 = (RAW_DIR / "page_0381.azure.json").exists()


# --------------------------------------------------------------------------- #
# column_zones() -- real-data grounding (the no-false-positive case is page_0010,
# a clean two-column body that MUST NOT escalate).
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not _RAW_PAGE10, reason="raw/ page_0010 not downloaded")
def test_column_zones_real_page10_two_columns_no_escalation() -> None:
    azure, dims = _azure_boxes(10)
    tess = _tesseract_boxes(10)
    abbyy = _abbyy_boxes(10)
    engine_boxes = {k: v for k, v in {"azure": azure, "tesseract": tess, "abbyy": abbyy}.items() if v}
    assert dims is not None
    width, height = dims

    result, columns = column_zones(engine_boxes, width, height)

    # Clean body page -> two columns, no escalation (the load-bearing safety property).
    assert result.n_columns == 2
    assert result.escalate is False
    assert len(columns) == 2

    # Columns are left-to-right with a mid-page gutter (~0.5*W; ablation: gutter 2797.5).
    left, right = columns[0], columns[1]
    assert left["column"] == 1 and right["column"] == 2
    assert left["assign_x"] < right["assign_x"]
    assert 0.45 * width <= result.gutter_x <= 0.58 * width

    # Each column carries a real native rect (a band, not a point) spanning real height.
    for col in columns:
        nat = col["native"]
        assert nat["w"] > 0 and nat["h"] > 0.3 * height


@pytest.mark.skipif(not _RAW_PAGE381, reason="raw/ page_0381 not downloaded")
def test_column_zones_real_page381_table_escalates() -> None:
    # The sideways statistical table: engines disagree / a token spans the gutter.
    azure, dims = _azure_boxes(381)
    abbyy = _abbyy_boxes(381)
    engine_boxes = {k: v for k, v in {"azure": azure, "abbyy": abbyy}.items() if v}
    assert dims is not None
    result, _columns = column_zones(engine_boxes, dims[0], dims[1])
    assert result.escalate is True


def test_column_zones_zero_geometry_escalates() -> None:
    # Defensive: no provider boxes -> escalate (driver must route to a fallback).
    result, columns = column_zones({}, 5034, 6959)
    assert result.escalate is True
    assert columns == []


# --------------------------------------------------------------------------- #
# build_wct_page() -- geometric is the DEFAULT authority.
# --------------------------------------------------------------------------- #

_THIN_GEOM = ("tesseract-py314-v1", "ia-abbyy-v1")
_thin_present = all((THINSLICE_DIR / f"{e}.rendering-v1.json").exists() for e in _THIN_GEOM)


@pytest.mark.slow
@pytest.mark.skipif(not _thin_present, reason="thinslice geometry renderings not on disk")
def test_build_wct_geometric_mode_no_surya() -> None:
    # The whole point: a valid two-column WCT with NO Surya rendering present.
    renderings = [_thinslice(e) for e in _THIN_GEOM]
    page = build_wct_page(
        renderings,
        work_id="schaff-herzog", volume_id="vol_01", page_id="page_0010",
        source_image=SOURCE_IMAGE,
        edition_page_key=body_edition_key(10),
    )
    jsonschema.validate(instance=page, schema=_schema("word-confusion-table-v1"))
    assert validate_page(page) == []
    assert page["layout_authority"]["tool"] == "geometric"
    body_zones = [z for z in page["zones"] if z["zone_type"] == "body"]
    assert len(body_zones) == 2, f"expected two body columns, got {len(body_zones)}"
    assert all(z["source"] == "geometric" for z in body_zones)
    assert page["reading_order"], "empty reading order"


def test_zones_from_annotation_splits_two_columns() -> None:
    zones = _zones_from_annotation({
        "zones": [
            {
                "role": "body",
                "column_count": 2,
                "bbox_native": {"x": 100, "y": 200, "w": 600, "h": 800},
            },
            {
                "role": "header",
                "column_count": 1,
                "bbox_native": {"x": 0, "y": 0, "w": 800, "h": 100},
            },
        ],
    })

    assert len(zones) == 2
    left, right = zones
    assert left["zone_id"] == "z_body_1"
    assert right["zone_id"] == "z_body_2"
    assert left["column"] == 1
    assert right["column"] == 2
    assert left["_native"] == {"x": 100.0, "y": 200, "w": 300.0, "h": 800}
    assert right["_native"] == {"x": 400.0, "y": 200, "w": 300.0, "h": 800}
    assert left["_assign_x"] == 250.0
    assert right["_assign_x"] == 550.0
    assert {z["source"] for z in zones} == {"manual-annotation"}


def _write_annotation(root: Path, volume_id: str, page_id: str, zones: list[dict]) -> None:
    ann_path = root / "reports" / "layout-annotations" / volume_id / f"{page_id}.json"
    ann_path.parent.mkdir(parents=True, exist_ok=True)
    ann_path.write_text(json.dumps({
        "page_id": f"{volume_id}/{page_id}",
        "vol": volume_id,
        "page_num": page_id,
        "source": "manual",
        "image_native_w": 5034,
        "image_native_h": 6959,
        "zones": zones,
    }), encoding="utf-8")


def test_build_wct_manual_annotation_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(wct_builder, "REPO_ROOT", tmp_path)
    _write_annotation(tmp_path, "vol_01", "page_0010", [
        {
            "zone_id": "z1",
            "role": "body",
            "column_count": 2,
            "reading_order": 0,
            "bbox_native": {"x": 0, "y": 0, "w": 5034, "h": 6959},
        },
    ])

    page = build_wct_page(
        [_fixture("tesseract"), _fixture("abbyy")],
        work_id="schaff-herzog", volume_id="vol_01", page_id="page_0010",
        source_image=SOURCE_IMAGE,
    )

    assert page["layout_authority"] == {
        "tool": "manual-annotation",
        "model_version": "reviewer-v1",
        "status": "annotation-override",
    }
    body_zones = [z for z in page["zones"] if z["zone_type"] == "body"]
    assert len(body_zones) == 2
    assert all(z["source"] == "manual-annotation" for z in body_zones)


def test_manual_annotation_with_no_body_zones_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(wct_builder, "REPO_ROOT", tmp_path)
    _write_annotation(tmp_path, "vol_01", "page_0010", [
        {
            "zone_id": "z1",
            "role": "header",
            "column_count": 1,
            "reading_order": 0,
            "bbox_native": {"x": 0, "y": 0, "w": 5034, "h": 200},
        },
    ])

    with pytest.raises(LayoutEscalation) as exc_info:
        build_wct_page(
            [_fixture("tesseract"), _fixture("abbyy")],
            work_id="schaff-herzog", volume_id="vol_01", page_id="page_0010",
            source_image=SOURCE_IMAGE,
        )

    assert exc_info.value.flags == ["annotation-no-body-zones"]


def test_missing_manual_annotation_falls_back_to_geometric(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(wct_builder, "REPO_ROOT", tmp_path)

    page = build_wct_page(
        [_fixture("tesseract"), _fixture("abbyy")],
        work_id="schaff-herzog", volume_id="vol_01", page_id="page_0010",
        source_image=SOURCE_IMAGE,
    )

    assert page["layout_authority"]["tool"] == "geometric"


def test_build_wct_surya_mode_still_works() -> None:
    # Reversibility: the Surya-fed path remains reachable behind the interface.
    surya = _fixture("surya")
    tesseract = _fixture("tesseract")
    page = build_wct_page(
        [surya, tesseract],
        work_id="schaff-herzog", volume_id="vol_01", page_id="page_0010",
        source_image=SOURCE_IMAGE,
        layout_authority="surya",
        edition_page_key=body_edition_key(10),
    )
    jsonschema.validate(instance=page, schema=_schema("word-confusion-table-v1"))
    assert validate_page(page) == []
    assert page["layout_authority"]["tool"] == "surya"


def test_geometric_escalation_without_surya_raises() -> None:
    # An escalated page with no Surya fallback must raise LayoutEscalation so the
    # driver can run Surya on it -- never silently emit a wrong column layout.
    # Strip word geometry from both engines -> zero geometry -> escalate.
    def _strip(rendering: dict) -> dict:
        out = copy.deepcopy(rendering)
        for block in out["pages"][0]["blocks"]:
            for line in block["lines"]:
                line["bbox_native"] = None
                for word in line["words"]:
                    word["bbox_native"] = None
        return out

    renderings = [_strip(_fixture("tesseract")), _strip(_fixture("abbyy"))]
    with pytest.raises(LayoutEscalation):
        build_wct_page(
            renderings,
            work_id="schaff-herzog", volume_id="vol_01", page_id="page_0010",
            source_image=SOURCE_IMAGE,
        )
