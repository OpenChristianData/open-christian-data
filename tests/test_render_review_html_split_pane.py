import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.render_review_html import render_resource_html  # noqa: E402


def _block(**overrides: object) -> dict:
    block = {
        "block_id": "slot8-bbox-block",
        "block_id_history": [],
        "block_type": "paragraph",
        "language": "en",
        "language_confidence": 0.99,
        "language_alternates": [],
        "language_segments": [],
        "original_text": "A block with scan coordinates.",
        "modern_text": "",
        "annotations": {},
        "source_pages": [],
        "attested_by": ["ia/r"],
        "disagreements": [],
        "structural_disagreements": [],
        "modernisations": [],
    }
    block.update(overrides)
    return block


def _record(block: dict) -> dict:
    return {
        "meta": {
            "id": "sample-work-edition",
            "title": "Sample Work",
            "author_slug": "sample-author",
            "author_display_name": "Sample Author",
            "author_birth_year": None,
            "author_death_year": None,
            "original_publication_year": 1900,
            "language": "en",
            "tradition": ["reformed"],
            "license": "public-domain",
            "schema_type": "reconciled_record",
            "schema_version": "3.0.0",
            "resource_type": "encyclopedia",
            "edition": "1900",
            "pd_anchor": "ia/r",
            "modernisation_ruleset_version": None,
            "attestation_summary": {
                "block_count": 1,
                "fully_attested_blocks": 1,
                "blocks_with_disagreements": 0,
                "blocks_with_structural_disagreements": 0,
            },
        },
        "blocks": [block],
        "match_explanations": [],
        "data": [
            {
                "entry_id": block["block_id"],
                "term": "Sample",
                "alt_terms": [],
                "definition_blocks": [{"type": block["block_type"], "text": block["original_text"]}],
                "related_terms": [],
            }
        ],
    }


def test_bbox_highlight_fires_on_hocr_block():
    bbox = {"x": 10, "y": 20, "w": 300, "h": 40}
    block = _block(source_pages=[{"rendering_id": "ia/r", "page_number": 2, "bbox": bbox}])

    html = render_resource_html(_record(block))

    assert 'data-bbox="' in html
    assert json.dumps(bbox, separators=(",", ":"), sort_keys=True) in html

    no_bbox = _block(source_pages=[{"rendering_id": "ia/r", "page_number": 2, "bbox": None}])
    no_bbox_html = render_resource_html(_record(no_bbox))
    assert "data-bbox" not in no_bbox_html


def test_bbox_highlight_falls_back_when_bbox_absent():
    block = _block(source_pages=[{"rendering_id": "ia/r", "page_number": 2, "bbox": None}])

    html = render_resource_html(_record(block))

    assert 'class="split-pane"' in html
    assert "A block with scan coordinates." in html
    assert "data-bbox" not in html
