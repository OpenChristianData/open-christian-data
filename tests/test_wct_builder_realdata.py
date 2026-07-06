"""Real-data-derived tests for the vol_01 page_0010 WCT (bug 2 + two-column body).

Bug 2: a line-level engine (Surya, Kraken) carries word TEXT but no per-word
bbox. The builder dropped every null-bbox word before alignment, so the WCT
degenerated to the geometry-bearing engines only. The fix lets geometry-less
engines contribute their text tokens to the body track, aligned by the
confusion-network text alignment; geometry-bearing engines (Tesseract, ABBYY)
anchor the positions.

The unit test derives a geometry-less Surya from the committed synthetic fixture
by nulling its word bboxes (its blocks keep bbox_canonical, so it still serves as
the layout authority). The integration test runs the real page_0010 renderings
when present -- skipif in CI, since reports/ is gitignored (TEST-13, OCD raw-read
convention).
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

from build.lib.edition_page_key import body_edition_key  # noqa: E402
from build.lib.wct_builder import build_wct_page  # noqa: E402
from build.lib.wct_semantic_validator import validate_page  # noqa: E402

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "wct_builder"
REAL_DIR = REPO_ROOT / "reports" / "_thinslice" / "rendering_single"
SOURCE_IMAGE = {
    "path": "raw/internet-archive/schaff-herzog-pages/vol_01/page_0010.jpg",
    "sha256": "b8f4d2476ea47dba58d920aa7af510c56433d5858447f7e0017b41c13210a1bb",
}


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"rendering_{name}.json").read_text(encoding="utf-8"))


def _strip_word_geometry(rendering: dict) -> dict:
    """Return a copy whose words carry no bbox -- a line-level (geometry-less)
    engine. Block bbox_canonical is kept so it can still be the layout authority."""
    out = copy.deepcopy(rendering)
    for block in out["pages"][0]["blocks"]:
        for line in block["lines"]:
            line["bbox_native"] = None
            for word in line["words"]:
                word["bbox_native"] = None
    return out


def _span_records_for_family(position: dict, family: str) -> list[dict]:
    return [sr for sr in position["span_records"] if sr["family"] == family]


# --------------------------------------------------------------------------- #
# Unit: a geometry-less Surya still contributes its text tokens to the body.
# --------------------------------------------------------------------------- #


def test_geometry_less_surya_contributes_text_tokens() -> None:
    surya = _strip_word_geometry(_fixture("surya"))   # layout authority, no word boxes
    tesseract = _fixture("tesseract")                  # geometry engine, anchors positions
    page = build_wct_page(
        [surya, tesseract],
        work_id="schaff-herzog", volume_id="vol_01", page_id="page_0010",
        source_image=SOURCE_IMAGE,
        edition_page_key=body_edition_key(10),
    )
    # Output is still well-formed.
    jsonschema.validate(instance=page, schema=_schema("word-confusion-table-v1"))
    assert validate_page(page) == []

    # Find the shared 'the' slot. Surya must attest it despite having no word box.
    target = None
    for position in page["positions"]:
        if any(c["candidate_key"] == "the" for c in position["candidate_set"]):
            target = position
            break
    assert target is not None, "no position carries the shared candidate 'the'"

    surya_records = [sr for sr in _span_records_for_family(target, "surya") if sr["token_span_type"] != "skip"]
    assert surya_records, "geometry-less surya dropped from the 'the' slot (bug 2)"
    surya_sr = surya_records[0]
    # A geometry-less attestation: real candidate text, but empty source_spans
    # (the schema's source_span requires a bbox; surya reports none).
    assert surya_sr["normalized_text"] == "the"
    assert surya_sr["source_spans"] == [], "geometry-less engine must not fabricate a bbox"
    # Tesseract anchors the same position with real geometry.
    tess_records = [sr for sr in _span_records_for_family(target, "tesseract") if sr["token_span_type"] != "skip"]
    assert tess_records and tess_records[0]["source_spans"], "tesseract geometry missing"


# --------------------------------------------------------------------------- #
# Integration: the real page_0010 WCT has positions fed by >1 engine, two body
# columns, and left-column reading order before right.
# --------------------------------------------------------------------------- #

_REAL_ENGINES = ("surya-py312-v1", "tesseract-py314-v1", "ia-abbyy-v1")
_real_present = all((REAL_DIR / f"{e}.rendering-v1.json").exists() for e in _REAL_ENGINES)


@pytest.mark.slow
@pytest.mark.skipif(not _real_present, reason="real page_0010 single-page renderings not on disk")
def test_real_page10_wct_is_multi_engine_two_column() -> None:
    renderings = [
        json.loads((REAL_DIR / f"{e}.rendering-v1.json").read_text(encoding="utf-8"))
        for e in _REAL_ENGINES
    ]
    page = build_wct_page(
        renderings,
        work_id="schaff-herzog", volume_id="vol_01", page_id="page_0010",
        source_image=SOURCE_IMAGE,
        edition_page_key=body_edition_key(10),
    )
    jsonschema.validate(instance=page, schema=_schema("word-confusion-table-v1"))
    assert validate_page(page) == []

    body_zones = [z for z in page["zones"] if z["zone_type"] == "body"]
    assert len(body_zones) == 2, f"expected two body columns, got {len(body_zones)}"

    # At least one position is attested by both a geometry engine (tesseract) and a
    # text-only engine (surya) -- the WCT no longer degenerates to one engine.
    multi = 0
    for position in page["positions"]:
        fams = {sr["family"] for sr in position["span_records"] if sr["token_span_type"] != "skip"}
        if "tesseract" in fams and "surya" in fams:
            multi += 1
    assert multi > 0, "no position fed by both tesseract and surya (bug 2 not fixed)"
    assert page["reading_order"], "empty reading order"
